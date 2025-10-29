# udp_to_mqtt_bridge_opt.py
import os
import sys
import socket
import signal
import threading
import queue
import time
from datetime import datetime
import paho.mqtt.client as mqtt

# ======================
# 配置（可用环境变量覆盖）
# ======================
UDP_LISTEN_PORT = int(os.getenv("UDP_LISTEN_PORT", "13251"))
UDP_COPY_LOCAL  = os.getenv("UDP_COPY_LOCAL", "0") == "1"   # 是否继续复制到本机UDP 53000
LOCAL_FWD_IP    = os.getenv("LOCAL_FWD_IP", "127.0.0.1")
LOCAL_FWD_PORT  = int(os.getenv("LOCAL_FWD_PORT", "53000"))

BROKER_HOST     = os.getenv("MQTT_BROKER_HOST", "127.0.0.1")
BROKER_PORT     = int(os.getenv("MQTT_BROKER_PORT", "1883"))
DEVICE_ID       = os.getenv("DEVICE_ID", "R25")
CLIENT_ID       = os.getenv("CLIENT_ID", f"udp-bridge-{DEVICE_ID}")
TOPIC_RAW       = os.getenv("MQTT_TOPIC_RAW", f"etx/v1/raw/{DEVICE_ID}")
MQTT_QOS        = int(os.getenv("MQTT_QOS", "1"))

# 队列与批量参数
Q_MAXSIZE       = int(os.getenv("BRIDGE_QUEUE_SIZE", "2000"))   # 有界队列，防止内存增长
DROP_POLICY     = os.getenv("DROP_POLICY", "drop_oldest")       # drop_oldest / drop_new
BATCH_MAX_ITEMS = int(os.getenv("BATCH_MAX_ITEMS", "50"))       # 每个MQTT消息最多聚合多少UDP包
BATCH_MAX_MS    = int(os.getenv("BATCH_MAX_MS", "40"))          # 聚合的最长时间窗(ms)
BATCH_SEPARATOR = os.getenv("BATCH_SEPARATOR", "NONE")          # NONE / NL （聚合时在包间插入分隔符）
PRINT_EVERY_MS  = int(os.getenv("PRINT_EVERY_MS", "2000"))      # 状态打印周期

# UDP接收参数
UDP_BUF_BYTES   = int(os.getenv("UDP_BUF_BYTES", "8192"))       # 每次接收的最大字节
SO_RCVBUF_BYTES = int(os.getenv("SO_RCVBUF_BYTES", "4_194_304".replace('_','')))  # 4MB接收缓冲

running = True
pkt_in = 0
pkt_pub = 0
pkt_drop = 0

q: "queue.Queue[bytes]" = queue.Queue(maxsize=Q_MAXSIZE)

def install_signals():
    def _handler(sig, frame):
        global running
        running = False
    signal.signal(signal.SIGINT, _handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handler)

def make_udp_sock():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # 调大接收缓冲，降低内核丢包
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, SO_RCVBUF_BYTES)
    except Exception:
        pass
    # 监听所有地址
    sock.bind(("", UDP_LISTEN_PORT))
    return sock

def make_local_fwd_sock():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((LOCAL_FWD_IP, LOCAL_FWD_PORT))
    return s

def udp_receiver():
    """生产者：从UDP收包→有界队列。使用 recvfrom_into 降低分配开销。"""
    global pkt_in, pkt_drop
    sock = make_udp_sock()
    fwd = make_local_fwd_sock() if UDP_COPY_LOCAL else None

    # 预分配缓冲
    buf = bytearray(UDP_BUF_BYTES)
    view = memoryview(buf)

    print(f"[BRIDGE/UDP] listen=:{UDP_LISTEN_PORT}, rcvbuf={SO_RCVBUF_BYTES}, copy_local={UDP_COPY_LOCAL}")
    while running:
        try:
            n, addr = sock.recvfrom_into(view, UDP_BUF_BYTES)
        except OSError:
            break
        if n <= 0:
            continue

        # 可选：继续转发到本机53000（兼容旧工具）
        if fwd:
            try:
                fwd.send(view[:n])
            except Exception:
                pass

        pkt_in += 1

        # 将当前数据“快照”为bytes后入队（避免后续缓冲被复用覆盖）
        data_bytes = bytes(view[:n])

        # 有界入队：队满时按策略丢弃
        try:
            q.put_nowait(data_bytes)
        except queue.Full:
            if DROP_POLICY == "drop_oldest":
                try:
                    q.get_nowait()  # 丢掉最旧
                except Exception:
                    pass
                try:
                    q.put_nowait(data_bytes)
                except Exception:
                    pkt_drop += 1
            else:  # drop_new
                pkt_drop += 1

    sock.close()
    if fwd:
        fwd.close()
    print("[BRIDGE/UDP] receiver stopped.")

def mqtt_publisher():
    """消费者：从队列取数据→聚合→发布到MQTT。"""
    global pkt_pub
    client = mqtt.Client(client_id=CLIENT_ID, clean_session=True)
    client.connect(BROKER_HOST, BROKER_PORT, keepalive=30)
    client.loop_start()

    print(f"[BRIDGE/MQTT] broker={BROKER_HOST}:{BROKER_PORT}, topic={TOPIC_RAW}, qos={MQTT_QOS}")
    sep = b"\n" if BATCH_SEPARATOR == "NL" else b""

    while running:
        try:
            # 阻塞等待第一条
            item = q.get(timeout=0.1)
        except queue.Empty:
            continue

        batch = [item]
        t0 = time.time()
        # 尝试在时间窗内尽量多聚合（减小协议头开销）
        while len(batch) < BATCH_MAX_ITEMS:
            elapsed_ms = (time.time() - t0) * 1000.0
            if elapsed_ms >= BATCH_MAX_MS:
                break
            try:
                nxt = q.get_nowait()
                batch.append(nxt)
            except queue.Empty:
                # 没有新数据了，稍微等一下；也可以直接break
                time.sleep(0.001)
                if q.empty():
                    break

        if len(batch) == 1 and not sep:
            payload = batch[0]
        else:
            payload = sep.join(batch)

        # 同步发布（返回后表明入队MQTT客户端缓冲成功），默认QOS1
        info = client.publish(TOPIC_RAW, payload=payload, qos=MQTT_QOS)
        # 你也可以选择等待 mid 完成（减少乱序），这里调试阶段不强制
        # info.wait_for_publish()

        pkt_pub += len(batch)

    client.loop_stop()
    client.disconnect()
    print("[BRIDGE/MQTT] publisher stopped.")

def stats_printer():
    last = time.time()
    last_in, last_pub, last_drop = 0, 0, 0
    while running:
        time.sleep(PRINT_EVERY_MS / 1000.0)
        now = time.time()
        dt = max(now - last, 1e-6)
        in_rate = (pkt_in - last_in) / dt
        pub_rate = (pkt_pub - last_pub) / dt
        drop_rate = (pkt_drop - last_drop) / dt
        qsize = q.qsize()
        print(f"[STATS] in={pkt_in} ({in_rate:.1f}/s)  pub={pkt_pub} ({pub_rate:.1f}/s)  drop={pkt_drop} ({drop_rate:.1f}/s)  q={qsize}")
        last, last_in, last_pub, last_drop = now, pkt_in, pkt_pub, pkt_drop

def main():
    install_signals()
    t_recv = threading.Thread(target=udp_receiver, daemon=True)
    t_pub  = threading.Thread(target=mqtt_publisher, daemon=True)
    t_stat = threading.Thread(target=stats_printer, daemon=True)

    t_recv.start()
    t_pub.start()
    t_stat.start()

    # 等待信号
    try:
        while running:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass

    # 优雅退出：留一点时间清空队列（也可直接退出）
    time.sleep(0.3)
    print("[MAIN] exiting.")

if __name__ == "__main__":
    main()

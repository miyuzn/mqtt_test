# data_receive.py — UDP→(可选原始|解析后)→MQTT
"""
UDP ingress bridge that optionally republishes raw frames plus parsed JSON over MQTT.
UDP 接入桥，支持同时转发原始帧与解析后的 JSON 到 MQTT。
"""
import os
import sys
import configparser
import socket
import signal
import threading
import queue
import time
import json
from datetime import datetime
import paho.mqtt.client as mqtt

# ===== 新增：引入新版解析库 =====
# 解析逻辑与字段布局参考 sensor2.parse_sensor_data（DN=6字节，SN=压力通道数，Mag/Gyro/Acc为3f）【见 sensor2.py】
import app.sensor2 as sensor2  # 确保与同目录的 sensor2.py 同名

# ======================
# 配置（从 config.ini 读取，环境变量可覆盖）
# ======================
import uuid, re, configparser

CONFIG_PATH = os.getenv("CONFIG_PATH", "config.ini")

config = configparser.ConfigParser()
config.read(CONFIG_PATH, encoding="utf-8")

def _sanitize(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "-", s)[:64] if isinstance(s, str) else "auto"

def _short_mac() -> str:
    try:
        return f"{(uuid.getnode() & 0xFFFFFF):06X}"
    except Exception:
        return "000000"

def get_conf(section, key, default=None, cast=str):
    """Prefer env overrides (SECTION_KEY) over config.ini, falling back to defaults.
    优先 环境变量(section_key 大写) > config.ini > 默认值。
    """
    env_key = f"{section}_{key}".upper()
    val = os.getenv(env_key)
    if val is None:
        try:
            val = config.get(section, key)
            if val == "" and default is not None:
                val = default
        except Exception:
            val = default
    try:
        return cast(val) if cast else val
    except Exception:
        return val

# UDP
UDP_LISTEN_PORT = get_conf("UDP", "LISTEN_PORT", 13250, int)
UDP_COPY_LOCAL  = get_conf("UDP", "COPY_LOCAL", 0, int) == 1
LOCAL_FWD_IP    = get_conf("UDP", "LOCAL_FWD_IP", "127.0.0.1")
LOCAL_FWD_PORT  = get_conf("UDP", "LOCAL_FWD_PORT", 53000, int)
UDP_BUF_BYTES   = get_conf("UDP", "BUF_BYTES", 8192, int)
SO_RCVBUF_BYTES = get_conf("UDP", "SO_RCVBUF_BYTES", 4194304, int)

# MQTT（不再使用 DEVICE_ID；CLIENT_ID 可自动生成）
_default_client_id = f"udp-bridge-{_sanitize(socket.gethostname())}-{_short_mac()}"
BROKER_HOST     = get_conf("MQTT", "BROKER_HOST", "127.0.0.1")
BROKER_PORT     = get_conf("MQTT", "BROKER_PORT", 1883, int)
CLIENT_ID       = get_conf("MQTT", "CLIENT_ID", _default_client_id)
TOPIC_RAW       = get_conf("MQTT", "TOPIC_RAW", "etx/v1/raw")
TOPIC_PARSED_PR = get_conf("MQTT", "TOPIC_PARSED_PREFIX", "etx/v1/parsed")
PUBLISH_RAW     = get_conf("MQTT", "PUBLISH_RAW", 0, int) == 1
PUBLISH_PARSED  = get_conf("MQTT", "PUBLISH_PARSED", 1, int) == 1
MQTT_QOS        = get_conf("MQTT", "MQTT_QOS", 1, int)

# QUEUE
Q_MAXSIZE       = get_conf("QUEUE", "BRIDGE_QUEUE_SIZE", 2000, int)
DROP_POLICY     = get_conf("QUEUE", "DROP_POLICY", "drop_oldest")
BATCH_MAX_ITEMS = get_conf("QUEUE", "BATCH_MAX_ITEMS", 50, int)
BATCH_MAX_MS    = get_conf("QUEUE", "BATCH_MAX_MS", 40, int)
BATCH_SEPARATOR = get_conf("QUEUE", "BATCH_SEPARATOR", "NONE")
PRINT_EVERY_MS  = get_conf("QUEUE", "PRINT_EVERY_MS", 2000, int)

running = True
pkt_in = 0
pkt_pub_raw = 0
pkt_pub_parsed = 0
pkt_drop = 0
pkt_parse_err = 0

# 队列项：存 bytes，解析在发布线程做（降低主线程负担）
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
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, SO_RCVBUF_BYTES)
    except Exception:
        pass
    sock.bind(("", UDP_LISTEN_PORT))
    return sock

def make_local_fwd_sock():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((LOCAL_FWD_IP, LOCAL_FWD_PORT))
    return s

def udp_receiver():
    """Producer: receive UDP packets and push them into the bounded queue.
    生产者：从 UDP 收包并推入有界队列。
    """
    global pkt_in, pkt_drop
    sock = make_udp_sock()
    fwd = make_local_fwd_sock() if UDP_COPY_LOCAL else None

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

        if fwd:
            try:
                fwd.send(view[:n])
            except Exception:
                pass

        pkt_in += 1
        data_bytes = bytes(view[:n])

        try:
            q.put_nowait(data_bytes)
        except queue.Full:
            if DROP_POLICY == "drop_oldest":
                try:
                    q.get_nowait()
                except Exception:
                    pass
                try:
                    q.put_nowait(data_bytes)
                except Exception:
                    pkt_drop += 1
            else:
                pkt_drop += 1

    sock.close()
    if fwd:
        fwd.close()
    print("[BRIDGE/UDP] receiver stopped.")

def dn_to_hex(dn):
    """
    Normalize the DN (bytes/int/str) into uppercase HEX for topic grouping.
    将 sensor2.parse_sensor_data 返回的 dn（通常为6字节 tuple/bytes）转为大写 HEX 字符串（用于 topic 分组）。
    """
    if isinstance(dn, (bytes, bytearray)):
        b = bytes(dn)
    elif isinstance(dn, (tuple, list)):
        b = bytes(dn)
    elif isinstance(dn, int):
        b = dn.to_bytes(6, byteorder="big", signed=False)
    elif isinstance(dn, str):
        hex_str = dn.replace(" ", "").replace("-", "")
        b = bytes.fromhex(hex_str[-12:].rjust(12, "0"))
    else:
        # 尽量兜底
        b = bytes(bytearray(dn))
    return b.hex().upper()

def encode_parsed(sd):
    """
    Convert sensor2.SensorData into a JSON-serializable dictionary payload.
    将 sensor2.SensorData 转为 JSON 可序列化 dict。
    字段 (Fields)：
      ts: float 秒（已合成毫秒）
      dn: 大写HEX
      sn: 压力通道数
      p:  压力数组（int/float）
      mag, gyro, acc: 三轴数组
    """
    dn_hex = dn_to_hex(sd.dn)
    body = {
        "ts": float(sd.timestamp),
        "dn": dn_hex,
        "sn": int(sd.sn),
        "p":  [int(x) if isinstance(x, (int,)) else float(x) for x in sd.pressure_sensors],
        "mag": [float(sd.magnetometer[0]), float(sd.magnetometer[1]), float(sd.magnetometer[2])],
        "gyro": [float(sd.gyroscope[0]), float(sd.gyroscope[1]), float(sd.gyroscope[2])],
        "acc":  [float(sd.accelerometer[0]), float(sd.accelerometer[1]), float(sd.accelerometer[2])],
    }
    return dn_hex, body

def mqtt_worker():
    """Consumer: drain queue, emit optional raw batches, and publish parsed JSON.
    消费者：从队列取数据→（可选）原始聚合发布 + 解析后 JSON 发布。
    """
    global pkt_pub_raw, pkt_pub_parsed, pkt_parse_err

    client = mqtt.Client(client_id=CLIENT_ID, clean_session=True)
    client.connect(BROKER_HOST, BROKER_PORT, keepalive=30)
    client.loop_start()

    print(f"[BRIDGE/MQTT] broker={BROKER_HOST}:{BROKER_PORT}, qos={MQTT_QOS}, topics raw={PUBLISH_RAW}, parsed={PUBLISH_PARSED}")
    sep = b"\n" if BATCH_SEPARATOR == "NL" else b""

    # 为了不阻塞解析，维护一个“原始聚合缓冲区”
    raw_batch = []
    raw_t0 = None

    def flush_raw():
        nonlocal raw_batch, raw_t0
        global pkt_pub_raw
        if not PUBLISH_RAW or not raw_batch:
            raw_batch = []
            raw_t0 = None
            return
        payload = sep.join(raw_batch) if (len(raw_batch) > 1 or sep) else raw_batch[0]
        client.publish(TOPIC_RAW, payload=payload, qos=MQTT_QOS)
        pkt_pub_raw += len(raw_batch)
        raw_batch = []
        raw_t0 = None

    while running:
        try:
            data = q.get(timeout=0.1)
        except queue.Empty:
            # 时间窗到期时，冲刷原始批
            if PUBLISH_RAW and raw_batch and raw_t0 is not None:
                if (time.time() - raw_t0) * 1000.0 >= BATCH_MAX_MS:
                    flush_raw()
            continue

        # 1) 原始路径：聚合以降低开销
        if PUBLISH_RAW:
            if not raw_batch:
                raw_t0 = time.time()
            raw_batch.append(data)
            if len(raw_batch) >= BATCH_MAX_ITEMS:
                flush_raw()

        # 2) 解析路径：逐包解析、按 DN 分topic发布（NDJSON，一包一行）
        if PUBLISH_PARSED:
            try:
                sd = sensor2.parse_sensor_data(data)  # 解析逻辑与 sensor2.py 一致
                if sd is None:
                    # 非法帧：忽略
                    continue
                dn_hex, body = encode_parsed(sd)
                topic_parsed = f"{TOPIC_PARSED_PR}/{dn_hex}"  # 例如 etx/v1/parsed/E00AD6773866
                # 采用 NDJSON（每帧一行），便于下游流式消费
                payload = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
                client.publish(topic_parsed, payload=payload, qos=MQTT_QOS)
                pkt_pub_parsed += 1
            except Exception:
                pkt_parse_err += 1
                # 解析失败不终止流程，继续

    # 退出前冲刷一次原始批
    try:
        flush_raw()
    except Exception:
        pass

    client.loop_stop()
    client.disconnect()
    print("[BRIDGE/MQTT] worker stopped.")

def stats_printer():
    """Print moving throughput metrics so we can spot congestion quickly.
    打印移动窗口吞吐率，便于快速发现拥塞。
    """
    last = time.time()
    last_in, last_raw, last_parsed, last_drop, last_err = 0, 0, 0, 0, 0
    while running:
        time.sleep(PRINT_EVERY_MS / 1000.0)
        now = time.time()
        dt = max(now - last, 1e-6)
        in_rate = (pkt_in - last_in) / dt
        raw_rate = (pkt_pub_raw - last_raw) / dt
        parsed_rate = (pkt_pub_parsed - last_parsed) / dt
        drop_rate = (pkt_drop - last_drop) / dt
        err_rate = (pkt_parse_err - last_err) / dt
        qsize = q.qsize()
        print(
            f"[STATS] in={pkt_in} ({in_rate:.1f}/s)  "
            f"raw_pub={pkt_pub_raw} ({raw_rate:.1f}/s)  "
            f"parsed_pub={pkt_pub_parsed} ({parsed_rate:.1f}/s)  "
            f"drop={pkt_drop} ({drop_rate:.1f}/s)  "
            f"parse_err={pkt_parse_err} ({err_rate:.2f}/s)  q={qsize}"
        )
        last, last_in, last_raw, last_parsed, last_drop, last_err = now, pkt_in, pkt_pub_raw, pkt_pub_parsed, pkt_drop, pkt_parse_err

def main():
    install_signals()
    # Spin up UDP/MQTT/stats threads and keep looping until interrupted.
    # 启动 UDP、MQTT、统计线程并持续运行直到被中断。
    t_recv = threading.Thread(target=udp_receiver, daemon=True)
    t_mqtt = threading.Thread(target=mqtt_worker, daemon=True)
    t_stat = threading.Thread(target=stats_printer, daemon=True)

    t_recv.start()
    t_mqtt.start()
    t_stat.start()

    try:
        while running:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass

    time.sleep(0.3)
    print("[MAIN] exiting.")

if __name__ == "__main__":
    main()

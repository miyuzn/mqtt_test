# data_receive.py - UDP (raw or parsed) to MQTT bridge / UDP（可选原始|解析后）到 MQTT 桥
"""
UDP ingress bridge that optionally republishes raw frames plus parsed JSON over MQTT.
UDP 接入桥，支持同时转发原始帧与解析后的 JSON 到 MQTT。
"""
import os
import sys
import configparser
import socket
import signal
import ssl
import threading
import queue
import time
import json
from datetime import datetime, timezone
import uuid
import re
import ipaddress
from typing import Dict, Tuple, Optional
import paho.mqtt.client as mqtt

# ===== Added: load the updated parsing library / 新增：引入新版解析库 =====
# Parsing layout follows sensor2.parse_sensor_data (DN=6 bytes, SN=pressure channels, Mag/Gyro/Acc are float triples) / 解析逻辑与字段布局参考 sensor2.parse_sensor_data（DN=6字节，SN=压力通道数，Mag/Gyro/Acc为3f）
import app.sensor2 as sensor2  # Ensure the module name matches sensor2.py in the same directory / 确保与同目录的 sensor2.py 同名

# ======================
# Configuration (read from config.ini, overridable via environment variables) / 配置（从 config.ini 读取，环境变量可覆盖）
# ======================
CONFIG_PATH = os.getenv("CONFIG_PATH", "config.secure.ini")

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

# MQTT settings (DEVICE_ID unused; CLIENT_ID auto-generated) / MQTT（不再使用 DEVICE_ID；CLIENT_ID 可自动生成）
_default_client_id = f"udp-bridge-{_sanitize(socket.gethostname())}-{_short_mac()}"
BROKER_HOST     = get_conf("MQTT", "BROKER_HOST", "127.0.0.1")
BROKER_PORT     = get_conf("MQTT", "BROKER_PORT", 1883, int)
CLIENT_ID       = get_conf("MQTT", "CLIENT_ID", _default_client_id)
TOPIC_RAW       = get_conf("MQTT", "TOPIC_RAW", "etx/v1/raw")
TOPIC_PARSED_PR = get_conf("MQTT", "TOPIC_PARSED_PREFIX", "etx/v1/parsed")
PUBLISH_RAW     = get_conf("MQTT", "PUBLISH_RAW", 1, int) == 1
PUBLISH_PARSED  = get_conf("MQTT", "PUBLISH_PARSED", 0, int) == 1
MQTT_QOS        = get_conf("MQTT", "MQTT_QOS", 1, int)
MQTT_USERNAME   = get_conf("MQTT", "USERNAME", "", str)
MQTT_PASSWORD   = get_conf("MQTT", "PASSWORD", "", str)
MQTT_TLS_ENABLED = get_conf("MQTT", "TLS_ENABLED", 0, int) == 1
MQTT_CA_CERT     = get_conf("MQTT", "CA_CERT", "", str)
MQTT_CLIENT_CERT = get_conf("MQTT", "CLIENT_CERT", "", str)
MQTT_CLIENT_KEY  = get_conf("MQTT", "CLIENT_KEY", "", str)
MQTT_TLS_INSECURE = get_conf("MQTT", "TLS_INSECURE", 0, int) == 1

# QUEUE
Q_MAXSIZE       = get_conf("QUEUE", "BRIDGE_QUEUE_SIZE", 2000, int)
DROP_POLICY     = get_conf("QUEUE", "DROP_POLICY", "drop_oldest")
BATCH_MAX_ITEMS = get_conf("QUEUE", "BATCH_MAX_ITEMS", 50, int)
BATCH_MAX_MS    = get_conf("QUEUE", "BATCH_MAX_MS", 40, int)
BATCH_SEPARATOR = get_conf("QUEUE", "BATCH_SEPARATOR", "NONE")
PRINT_EVERY_MS  = get_conf("QUEUE", "PRINT_EVERY_MS", 2000, int)

# CONFIG settings (downlink control) / CONFIG（下发相关）
CONFIG_CMD_TOPIC        = get_conf("CONFIG", "CMD_TOPIC", "etx/v1/config/cmd")
CONFIG_RESULT_TOPIC     = get_conf("CONFIG", "RESULT_TOPIC", "etx/v1/config/result")
CONFIG_AGENT_TOPIC      = get_conf("CONFIG", "AGENT_TOPIC", "etx/v1/config/agents")
CONFIG_AGENT_ID         = get_conf("CONFIG", "AGENT_ID", f"agent-{_short_mac()}")
DEVICE_TCP_PORT         = get_conf("CONFIG", "DEVICE_TCP_PORT", 22345, int)
DEVICE_TCP_TIMEOUT      = get_conf("CONFIG", "DEVICE_TCP_TIMEOUT", 3.0, float)
REGISTRY_TTL            = get_conf("CONFIG", "REGISTRY_TTL", 300, int)
REGISTRY_PUBLISH_SEC    = get_conf("CONFIG", "REGISTRY_PUBLISH_SEC", 5, int)
DISCOVER_PORT           = get_conf("CONFIG", "DISCOVER_PORT", 22346, int)
DISCOVER_MAGIC          = get_conf("CONFIG", "DISCOVER_MAGIC", "GCU_DISCOVER")
DISCOVER_ATTEMPTS       = get_conf("CONFIG", "DISCOVER_ATTEMPTS", 2, int)
DISCOVER_GAP            = get_conf("CONFIG", "DISCOVER_GAP", 0.15, float)
DISCOVER_TIMEOUT        = get_conf("CONFIG", "DISCOVER_TIMEOUT", 5.0, float)
DISCOVER_BROADCASTS     = get_conf("CONFIG", "DISCOVER_BROADCASTS", "")

# GCU subscription / handshake settings
GCU_ENABLED               = get_conf("GCU", "ENABLED", 1, int) == 1
GCU_SUBSCRIBE_TOKEN       = get_conf("GCU", "SUBSCRIBE_TOKEN", "GCU_SUBSCRIBE").strip() or "GCU_SUBSCRIBE"
GCU_ACK_TOKEN             = get_conf("GCU", "ACK_TOKEN", "GCU_ACK").strip().upper() or "GCU_ACK"
GCU_BROADCAST_TOKEN       = get_conf("GCU", "BROADCAST_TOKEN", "GCU_BROADCAST").strip().upper() or "GCU_BROADCAST"
GCU_HEARTBEAT_SEC         = max(get_conf("GCU", "HEARTBEAT_SEC", 5.0, float), 1.0)
GCU_FALLBACK_SEC          = max(get_conf("GCU", "FALLBACK_SEC", 20.0, float), GCU_HEARTBEAT_SEC + 1.0)
GCU_SEND_BROADCAST_ON_EXIT = get_conf("GCU", "BROADCAST_ON_EXIT", 1, int) == 1

running = True
pkt_in = 0
pkt_pub_raw = 0
pkt_pub_parsed = 0
pkt_drop = 0
pkt_parse_err = 0

# Queue entries store (payload_bytes, addr) / 队列项：保存 (payload_bytes, addr)
q: "queue.Queue[Tuple[bytes, Tuple[str, int]]]" = queue.Queue(maxsize=Q_MAXSIZE)

# Device registry maps dn_hex -> {"ip": str, "last_seen": float} / 设备注册表：dn_hex -> {"ip": str, "last_seen": float}
device_registry: Dict[str, Dict[str, float | str]] = {}
registry_lock = threading.RLock()

# MQTT command queue / MQTT 命令队列
command_queue: "queue.Queue[dict]" = queue.Queue()

# Payload constraints (validated by downstream hardware) / 配置负载限制（由下游硬件自行校验）

class SubscriptionManager:
    """Maintain GCU subscription handshakes and heartbeats.
    负责与 GCU 设备的订阅/心跳握手，确保广播 -> 单播顺利转换。
    """

    def __init__(
        self,
        enabled: bool,
        subscribe_token: str,
        ack_token: str,
        broadcast_token: str,
        heartbeat_sec: float,
        fallback_sec: float,
        send_broadcast_on_exit: bool,
    ) -> None:
        self.enabled = enabled
        self.subscribe_payload = (subscribe_token or "GCU_SUBSCRIBE").encode("ascii", "ignore")
        self.ack_token = ack_token.upper()
        self.broadcast_token = broadcast_token.upper()
        self.heartbeat_sec = heartbeat_sec
        self.fallback_sec = fallback_sec
        self.send_broadcast_on_exit = send_broadcast_on_exit
        self._sessions: Dict[Tuple[str, int], dict] = {}
        self._lock = threading.RLock()
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._active = threading.Event()

    def bind_socket(self, sock: socket.socket) -> None:
        if not self.enabled:
            return
        self._sock = sock

    def start(self) -> None:
        if not self.enabled or self._thread:
            return
        self._active.set()
        self._thread = threading.Thread(target=self._heartbeat_loop, name="gcu-heartbeat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self.enabled:
            return
        self._active.clear()
        if self._thread:
            self._thread.join(timeout=1.5)
            self._thread = None
        if self.send_broadcast_on_exit:
            self.broadcast_all()
        with self._lock:
            self._sessions.clear()

    def broadcast_all(self) -> None:
        if not self.enabled or not self._sock:
            return
        payload = self.broadcast_token.encode("ascii", "ignore")
        with self._lock:
            targets = list(self._sessions.keys())
        for addr in targets:
            self._send(payload, addr)

    def handle_packet(self, payload: bytes, addr: Tuple[str, int]) -> bool:
        """Return True if the packet is a control frame and should not enter the data queue."""
        if not self.enabled or not self._sock:
            return False
        text = self._decode_control(payload)
        now = time.time()
        if text:
            if text == self.ack_token:
                self._mark_session(addr, now, mark_ack=True)
                return True
            if text == self.broadcast_token:
                with self._lock:
                    self._sessions.pop(addr, None)
                return True
        self._mark_session(addr, now)
        return False

    def _decode_control(self, payload: bytes) -> Optional[str]:
        if not payload or len(payload) > 64:
            return None
        try:
            text = payload.decode("ascii", errors="strict").strip().upper()
        except Exception:
            return None
        if not text:
            return None
        if any(ch < " " or ch > "~" for ch in text):
            return None
        return text

    def _mark_session(self, addr: Tuple[str, int], now: float, mark_ack: bool = False) -> None:
        with self._lock:
            session = self._sessions.get(addr)
            if session is None:
                session = {"last_seen": now, "last_sub": 0.0, "ack": False}
                self._sessions[addr] = session
            session["last_seen"] = now
            if mark_ack:
                session["ack"] = True
            if now - session["last_sub"] >= self.heartbeat_sec:
                self._send(self.subscribe_payload, addr)
                session["last_sub"] = now

    def _send(self, payload: bytes, addr: Tuple[str, int]) -> None:
        try:
            self._sock.sendto(payload, addr)
        except Exception:
            pass

    def _heartbeat_loop(self) -> None:
        interval = max(self.heartbeat_sec / 2.0, 0.5)
        while self._active.is_set():
            time.sleep(interval)
            now = time.time()
            with self._lock:
                for addr, session in list(self._sessions.items()):
                    if now - session.get("last_seen", 0.0) > self.fallback_sec:
                        self._sessions.pop(addr, None)
                        continue
                    if now - session.get("last_sub", 0.0) >= self.heartbeat_sec:
                        self._send(self.subscribe_payload, addr)
                        session["last_sub"] = now

gcu_manager = SubscriptionManager(
    enabled=GCU_ENABLED,
    subscribe_token=GCU_SUBSCRIBE_TOKEN,
    ack_token=GCU_ACK_TOKEN,
    broadcast_token=GCU_BROADCAST_TOKEN,
    heartbeat_sec=GCU_HEARTBEAT_SEC,
    fallback_sec=GCU_FALLBACK_SEC,
    send_broadcast_on_exit=GCU_SEND_BROADCAST_ON_EXIT,
)

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
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
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
    gcu_manager.bind_socket(sock)
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

        if gcu_manager.handle_packet(data_bytes, addr):
            continue

        try:
            q.put_nowait((data_bytes, addr))
        except queue.Full:
            if DROP_POLICY == "drop_oldest":
                try:
                    q.get_nowait()
                except Exception:
                    pass
                try:
                    q.put_nowait((data_bytes, addr))
                except Exception:
                    pkt_drop += 1
            else:
                pkt_drop += 1

    sock.close()
    if fwd:
        fwd.close()
    gcu_manager.broadcast_all()
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
        b = dn.to_bytes(6, byteorder="little", signed=False)
    elif isinstance(dn, str):
        hex_str = dn.replace(" ", "").replace("-", "").replace(":", "")
        try:
            b = bytes.fromhex(hex_str[-12:].rjust(12, "0"))
        except ValueError:
            return dn.strip().upper()
    else:
        # Best-effort fallback / 尽量兜底
        b = bytes(bytearray(dn))
    return b.hex().upper()


def quick_dn_from_payload(payload: bytes) -> Optional[str]:
    """
    Extract DN from raw payload without full parsing so we can keep the device registry updated
    even when parsing is disabled.
    在禁用完整解析时，仅检查帧头即可快速提取 DN，维持设备注册表。
    """
    if not payload or len(payload) < 8:
        return None
    if payload[0] != 0x5A or payload[1] != 0x5A:
        return None
    try:
        value = int.from_bytes(payload[2:8], byteorder="little", signed=False)
        return f"{value:012X}"
    except Exception:
        return None


def update_device_registry(dn_hex: str, ip: Optional[str]) -> None:
    """Normalize and store DN->IP mapping; ignore non-hex/short values."""
    if not dn_hex or not ip:
        return
    dn_clean = normalize_dn_str(dn_hex)
    if not dn_clean or len(dn_clean) < 8:
        return
    if not all(ch in "0123456789ABCDEF" for ch in dn_clean):
        return
    dn_norm = dn_clean[-12:] if len(dn_clean) >= 12 else dn_clean
    now = time.time()
    with registry_lock:
        device_registry[dn_norm] = {"ip": ip, "last_seen": now}


def resolve_device_ip(dn_hex: str) -> Optional[str]:
    if not dn_hex:
        return None
    now = time.time()
    with registry_lock:
        entry = device_registry.get(dn_hex)
        if not entry:
            return None
        last_seen = float(entry.get("last_seen", 0))
        if now - last_seen > REGISTRY_TTL:
            device_registry.pop(dn_hex, None)
            return None
        return entry.get("ip")

def _parse_broadcast_list(raw: str) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def collect_broadcast_addrs() -> list[str]:
    addrs = _parse_broadcast_list(DISCOVER_BROADCASTS)
    try:
        import psutil  # type: ignore

        for iface_addrs in psutil.net_if_addrs().values():
            for snic in iface_addrs:
                if snic.family != socket.AF_INET:
                    continue
                if snic.broadcast:
                    addrs.append(snic.broadcast)
                elif snic.netmask and snic.address:
                    try:
                        iface = ipaddress.ip_interface(f"{snic.address}/{snic.netmask}")  # type: ignore
                        addrs.append(str(iface.network.broadcast_address))
                    except Exception:
                        continue
    except Exception:
        pass

    addrs.append("255.255.255.255")
    seen = set()
    uniq = []
    for addr in addrs:
        if not addr or addr in seen or addr == "0.0.0.0":
            continue
        seen.add(addr)
        uniq.append(addr)
    return uniq


def normalize_dn_str(value: str | None) -> str:
    if not value:
        return ""
    return value.replace(":", "").replace("-", "").replace(" ", "").strip().upper()


def discover_devices(
    *,
    broadcast_addrs: Optional[list[str]] = None,
    attempts: int = DISCOVER_ATTEMPTS,
    gap: float = DISCOVER_GAP,
    timeout: float = DISCOVER_TIMEOUT,
) -> tuple[list[dict], list[str]]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)
    sock.bind(("", 0))

    targets = broadcast_addrs or collect_broadcast_addrs()
    deadline = time.time() + max(timeout, 0.1)
    try:
        for _ in range(max(1, attempts)):
            for addr in targets:
                try:
                    sock.sendto(DISCOVER_MAGIC.encode("ascii", "ignore"), (addr, DISCOVER_PORT))
                except OSError:
                    continue
            if gap > 0:
                time.sleep(gap)

        results: list[dict] = []
        seen = set()
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                sock.settimeout(remaining)
                data, addr = sock.recvfrom(1024)
            except socket.timeout:
                break
            except OSError:
                break
            if not data:
                continue
            try:
                obj = json.loads(data.decode(errors="ignore"))
                obj["from"] = addr[0]
                sig = (obj.get("ip"), obj.get("mac"), obj.get("model"), obj.get("port"))
                if sig in seen:
                    continue
                seen.add(sig)
                results.append(obj)
            except Exception:
                continue
        return results, targets
    finally:
        sock.close()


def resolve_ip_with_discovery(dn_hex: str, target_ip: Optional[str]) -> tuple[Optional[str], list[dict], list[str]]:
    if target_ip:
        return target_ip, [], []
    devices, targets = discover_devices()
    chosen_ip = None
    dn_key = normalize_dn_str(dn_hex)
    if dn_key:
        for item in devices:
            mac = normalize_dn_str(item.get("dn") or item.get("mac") or item.get("device_code") or item.get("ip"))
            if mac and mac == dn_key:
                chosen_ip = item.get("ip") or item.get("from")
                break
    if chosen_ip is None and len(devices) == 1:
        chosen_ip = devices[0].get("ip") or devices[0].get("from")
    if chosen_ip:
        update_device_registry(dn_key, chosen_ip)
    return chosen_ip, devices, targets


def pick_port_from_discovery(chosen_ip: Optional[str], discoveries: list[dict], default_port: int) -> int:
    if not chosen_ip:
        return default_port
    for item in discoveries:
        ip_val = item.get("ip") or item.get("from")
        if ip_val and ip_val == chosen_ip:
            try:
                port_val = int(item.get("port"))
                if port_val > 0:
                    return port_val
            except Exception:
                continue
    return default_port


def registry_snapshot() -> dict:
    now = time.time()
    items = []
    with registry_lock:
        stale = [
            dn for dn, rec in device_registry.items()
            if now - float(rec.get("last_seen", 0)) > REGISTRY_TTL
            or not dn
            or len(str(dn)) < 10
            or not all(ch in "0123456789ABCDEF" for ch in str(dn).upper())
        ]
        for dn in stale:
            device_registry.pop(dn, None)
        for dn, rec in device_registry.items():
            items.append({
                "dn": dn,
                "ip": rec.get("ip"),
                "last_seen": datetime.fromtimestamp(float(rec.get("last_seen", now)), timezone.utc).isoformat(),
            })
    return {"agent_id": CONFIG_AGENT_ID, "devices": items, "device_count": len(items)}

def encode_parsed(sd):
    """
    Convert sensor2.SensorData into a JSON-serializable dictionary payload.
    将 sensor2.SensorData 转为 JSON 可序列化 dict。
    Fields (字段)：
      ts: float seconds (already combined with milliseconds) / 秒
      dn: uppercase HEX string / 大写 HEX
      sn: pressure channel count / 压力通道数
      p:  array of pressures (int/float) / 压力数组
      mag, gyro, acc: 3-axis float arrays / 三轴数组
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


class ConfigCommandError(ValueError):
    pass


def build_config_payload(analog, select, model):
    payload_obj = {"analog": analog, "select": select, "model": model}
    payload_str = json.dumps(payload_obj, separators=(",", ":")) + "\n"
    return payload_obj, payload_str


def _send_tcp_json(ip: str, payload_str: str, port: int) -> dict:
    addr = (ip, port)
    with socket.create_connection(addr, timeout=DEVICE_TCP_TIMEOUT) as sock:
        sock.sendall(payload_str.encode("utf-8"))
        sock.settimeout(DEVICE_TCP_TIMEOUT)
        chunks = []
        while True:
            try:
                data = sock.recv(1024)
            except socket.timeout:
                break
            if not data:
                break
            chunks.append(data)
            if data.endswith(b"\n"):
                break
    raw_reply = b"".join(chunks).decode("utf-8", errors="replace").strip()
    if not raw_reply:
        return {"status": "no-reply"}
    try:
        return json.loads(raw_reply)
    except json.JSONDecodeError:
        return {"raw": raw_reply}


def send_config_payload(ip: str, payload_str: str, port: Optional[int] = None) -> dict:
    return _send_tcp_json(ip, payload_str, port or DEVICE_TCP_PORT)


def send_license_payload(ip: str, token: str, port: Optional[int] = None) -> dict:
    payload_str = json.dumps({"license": token}, ensure_ascii=False) + "\n"
    return _send_tcp_json(ip, payload_str, port or DEVICE_TCP_PORT)


def publish_device_registry(client: mqtt.Client) -> None:
    topic = f"{CONFIG_AGENT_TOPIC.rstrip('/')}/{CONFIG_AGENT_ID}"
    snapshot = registry_snapshot()
    snapshot["timestamp"] = datetime.now(timezone.utc).isoformat()
    client.publish(topic, payload=json.dumps(snapshot, ensure_ascii=False), qos=1, retain=True)


def registry_announcer(client: mqtt.Client):
    try:
        publish_device_registry(client)
    except Exception:
        print("[CONFIG] failed to publish registry snapshot", file=sys.stderr)
    interval = max(REGISTRY_PUBLISH_SEC, 1)
    while running:
        for _ in range(interval * 10):
            if not running:
                break
            time.sleep(0.1)
        if not running:
            break
        try:
            publish_device_registry(client)
        except Exception:
            print("[CONFIG] failed to publish registry snapshot", file=sys.stderr)


def publish_command_result(client: mqtt.Client, payload: dict) -> None:
    command_id = payload.get("command_id") or ""
    topic = f"{CONFIG_RESULT_TOPIC.rstrip('/')}/{CONFIG_AGENT_ID}/{command_id or 'unknown'}"
    body = {
        "agent_id": CONFIG_AGENT_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    body.update(payload)
    client.publish(topic, payload=json.dumps(body, ensure_ascii=False), qos=1, retain=False)


def on_config_connect(client: mqtt.Client, userdata, flags, rc):
    if rc != 0:
        print(f"[CONFIG] MQTT connect failed rc={rc}")
        return
    client.subscribe(CONFIG_CMD_TOPIC, qos=1)
    print(f"[CONFIG] subscribed: {CONFIG_CMD_TOPIC}")


def handle_config_command(client: mqtt.Client, userdata, message: mqtt.MQTTMessage):
    try:
        obj = json.loads(message.payload.decode("utf-8"))
    except Exception as exc:
        publish_command_result(client, {
            "command_id": "",
            "status": "error",
            "error": f"invalid-json: {exc}",
            "dn": None,
        })
        return
    if not isinstance(obj, dict):
        publish_command_result(client, {
            "command_id": obj if isinstance(obj, str) else "",
            "status": "error",
            "error": "payload must be JSON object",
            "dn": None,
        })
        return
    obj.setdefault("_source_topic", message.topic)
    command_queue.put(obj)


def command_worker(client: mqtt.Client):
    while running:
        try:
            cmd = command_queue.get(timeout=0.3)
        except queue.Empty:
            continue
        try:
            result = execute_command(cmd, client)
            publish_command_result(client, result)
        except ConfigCommandError as exc:
            publish_command_result(client, {
                "command_id": cmd.get("command_id") or "",
                "dn": cmd.get("target_dn") or cmd.get("dn"),
                "status": "error",
                "error": str(exc),
            })
        except Exception as exc:  # pragma: no cover - resilience / 容错
            publish_command_result(client, {
                "command_id": cmd.get("command_id") or "",
                "dn": cmd.get("target_dn") or cmd.get("dn"),
                "status": "error",
                "error": f"internal-error: {exc}",
            })


def execute_command(cmd: dict, client: mqtt.Client | None = None) -> dict:
    command_id = cmd.get("command_id") or f"cmd-{int(time.time()*1000)}"
    dn_raw = cmd.get("target_dn") or cmd.get("dn")
    if not dn_raw:
        raise ConfigCommandError("target_dn is required")
    dn_hex = dn_to_hex(dn_raw)
    payload_section = cmd.get("payload") if isinstance(cmd.get("payload"), dict) else {}
    cmd_type = (cmd.get("type") or payload_section.get("type") or "").strip().lower()
    
    target_ip = cmd.get("ip") or cmd.get("target_ip") or payload_section.get("ip")
    discoveries: list[dict] = []
    broadcast_targets: list[str] = []

    # Only resolve IP if it's NOT a discovery command (avoid blocking broadcast)
    if cmd_type not in ("discover", "discover_only", "discover_devices"):
        if not target_ip:
            target_ip = resolve_device_ip(dn_hex)
        if not target_ip:
            target_ip, discoveries, broadcast_targets = resolve_ip_with_discovery(dn_hex, target_ip)

    # Generic control payload path (standby/filter/calibration/spiffs or explicit raw/custom)
    control_keys = ("standby", "filter", "calibration", "spiffs", "log")
    if cmd_type in ("raw", "custom", "control") or any(k in payload_section for k in control_keys):
        if not target_ip:
            raise ConfigCommandError("Target DN currently is not associated with any IP (discovery failed)")
        payload_str = json.dumps(payload_section, ensure_ascii=False) + "\n"
        port = payload_section.get("port") or cmd.get("port")
        if port is not None:
            try:
                port = int(port)
            except Exception:
                port = None
        reply = send_config_payload(target_ip, payload_str, port=port)
        return {
            "command_id": command_id,
            "dn": dn_hex,
            "status": "ok",
            "ip": target_ip,
            "payload": payload_section,
            "reply": reply,
            "requested_by": cmd.get("requested_by") or payload_section.get("requested_by"),
            "source_topic": cmd.get("_source_topic"),
            "discoveries": discoveries,
            "broadcast": broadcast_targets,
        }
    if cmd_type in ("discover", "discover_only", "discover_devices"):
        attempts = payload_section.get("attempts") or cmd.get("attempts")
        gap = payload_section.get("gap") or cmd.get("gap")
        timeout = payload_section.get("timeout") or cmd.get("timeout")
        broadcasts = payload_section.get("broadcast") or payload_section.get("broadcast_addrs") or cmd.get("broadcast")
        try:
            attempts = int(attempts) if attempts is not None else DISCOVER_ATTEMPTS
        except Exception:
            attempts = DISCOVER_ATTEMPTS
        try:
            gap = float(gap) if gap is not None else DISCOVER_GAP
        except Exception:
            gap = DISCOVER_GAP
        try:
            timeout = float(timeout) if timeout is not None else DISCOVER_TIMEOUT
        except Exception:
            timeout = DISCOVER_TIMEOUT
        broadcast_list = _parse_broadcast_list(broadcasts) if broadcasts else collect_broadcast_addrs()
        discoveries, targets = discover_devices(
            broadcast_addrs=broadcast_list,
            attempts=max(1, attempts),
            gap=max(0.0, gap),
            timeout=max(0.1, timeout),
        )
        for item in discoveries:
            dn_val = normalize_dn_str(item.get("dn") or item.get("mac") or item.get("device_code") or item.get("ip"))
            if dn_val and item.get("ip") or item.get("from"):
                update_device_registry(dn_val, item.get("ip") or item.get("from"))
        if client is not None:
            try:
                publish_device_registry(client)
            except Exception:
                pass
        return {
            "command_id": command_id,
            "dn": "BROADCAST",
            "status": "ok",
            "ip": None,
            "payload": {"type": "discover", "attempts": attempts, "gap": gap, "timeout": timeout, "broadcast": targets},
            "reply": {"count": len(discoveries), "items": discoveries},
            "requested_by": cmd.get("requested_by") or payload_section.get("requested_by"),
            "source_topic": cmd.get("_source_topic"),
            "discoveries": discoveries,
            "broadcast": targets,
        }
    if cmd_type in ("license", "license_apply"):
        token = payload_section.get("license") or payload_section.get("license_token") or cmd.get("license")
        port = payload_section.get("port") or cmd.get("port")
        if port is not None:
            try:
                port = int(port)
            except Exception:
                port = None
        if port is None:
            port = pick_port_from_discovery(target_ip, discoveries, DEVICE_TCP_PORT)
        if not token:
            raise ConfigCommandError("license token is required")
        if not target_ip:
            raise ConfigCommandError("Target DN currently is not associated with any IP (discovery failed)")
        reply = send_license_payload(target_ip, token, port=port)
        return {
            "command_id": command_id,
            "dn": dn_hex,
            "status": "ok",
            "ip": target_ip,
            "payload": {"license": token, "type": "license"},
            "reply": reply,
            "requested_by": cmd.get("requested_by") or payload_section.get("requested_by"),
            "source_topic": cmd.get("_source_topic"),
            "discoveries": discoveries,
            "broadcast": broadcast_targets,
        }
    if cmd_type in ("license_query", "license_query_only"):
        port = payload_section.get("port") or cmd.get("port")
        if port is not None:
            try:
                port = int(port)
            except Exception:
                port = None
        if port is None:
            port = pick_port_from_discovery(target_ip, discoveries, DEVICE_TCP_PORT)
        if not target_ip:
            raise ConfigCommandError("Target DN currently is not associated with any IP (discovery failed)")
        reply = send_license_payload(target_ip, "?", port=port)
        return {
            "command_id": command_id,
            "dn": dn_hex,
            "status": "ok",
            "ip": target_ip,
            "payload": {"license": "?", "type": "license_query"},
            "reply": reply,
            "requested_by": cmd.get("requested_by") or payload_section.get("requested_by"),
            "source_topic": cmd.get("_source_topic"),
            "discoveries": discoveries,
            "broadcast": broadcast_targets,
        }
    analog = cmd.get("analog", payload_section.get("analog"))
    select = cmd.get("select", payload_section.get("select"))
    model = cmd.get("model", payload_section.get("model"))

    if analog is None and select is None and model is None:
        raise ConfigCommandError(f"Unknown command type '{cmd_type}' and no config pins provided")

    payload_obj, payload_str = build_config_payload(analog, select, model)
    if not target_ip:
        target_ip, discoveries, broadcast_targets = resolve_ip_with_discovery(dn_hex, target_ip)
    if not target_ip:
        raise ConfigCommandError("Target DN currently is not associated with any IP (discovery failed)")
    reply = send_config_payload(target_ip, payload_str)
    return {
        "command_id": command_id,
        "dn": dn_hex,
        "status": "ok",
        "ip": target_ip,
        "payload": payload_obj,
        "reply": reply,
        "requested_by": cmd.get("requested_by") or payload_section.get("requested_by"),
        "source_topic": cmd.get("_source_topic"),
        "discoveries": discoveries,
        "broadcast": broadcast_targets,
    }

def mqtt_worker():
    """Consumer: drain queue, emit optional raw batches, and publish parsed JSON (batched).
    消费者：从队列取数据→（可选）原始聚合发布 + 解析后 JSON 批量发布。
    """
    global pkt_pub_raw, pkt_pub_parsed, pkt_parse_err

    client = mqtt.Client(client_id=CLIENT_ID, clean_session=True)
    client.on_message = handle_config_command
    client.on_connect = on_config_connect

    if MQTT_USERNAME:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD or None)

    if MQTT_TLS_ENABLED:
        tls_version = getattr(ssl, "PROTOCOL_TLS_CLIENT", ssl.PROTOCOL_TLSv1_2)
        ca = MQTT_CA_CERT or None
        cert = MQTT_CLIENT_CERT or None
        key = MQTT_CLIENT_KEY or None
        client.tls_set(
            ca_certs=ca,
            certfile=cert,
            keyfile=key,
            tls_version=tls_version,
        )
        client.tls_insecure_set(MQTT_TLS_INSECURE)

    client.connect(BROKER_HOST, BROKER_PORT, keepalive=30)
    client.loop_start()

    print(f"[BRIDGE/MQTT] broker={BROKER_HOST}:{BROKER_PORT}, qos={MQTT_QOS}, topics raw={PUBLISH_RAW}, parsed={PUBLISH_PARSED}")
    print(f"[CONFIG] listening for commands on {CONFIG_CMD_TOPIC}")
    threading.Thread(target=command_worker, args=(client,), daemon=True).start()
    threading.Thread(target=registry_announcer, args=(client,), daemon=True).start()
    sep = b"\n" if BATCH_SEPARATOR == "NL" else b""

    # Raw aggregation buffer / 原始聚合缓冲区
    raw_batch = []
    raw_t0 = None

    # Parsed aggregation buffers: dn_hex -> list[body], dn_hex -> start_time
    # 解析聚合缓冲区：按 DN 分组
    parsed_batches: Dict[str, list] = {}
    parsed_t0: Dict[str, float] = {}

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

    def flush_parsed(dn_target: str):
        nonlocal parsed_batches, parsed_t0
        global pkt_pub_parsed
        batch = parsed_batches.get(dn_target)
        if not batch:
            return
        
        # Publish as a JSON array (batch)
        try:
            payload = json.dumps(batch, ensure_ascii=False, separators=(",", ":"))
            topic = f"{TOPIC_PARSED_PR}/{dn_target}"
            client.publish(topic, payload=payload, qos=MQTT_QOS)
            pkt_pub_parsed += len(batch)
        except Exception:
            pass
        
        parsed_batches[dn_target] = []
        parsed_t0.pop(dn_target, None)

    def check_timeouts():
        now = time.time()
        # Raw timeout
        if PUBLISH_RAW and raw_batch and raw_t0 is not None:
            if (now - raw_t0) * 1000.0 >= BATCH_MAX_MS:
                flush_raw()
        # Parsed timeouts
        if PUBLISH_PARSED:
            for dn, t0 in list(parsed_t0.items()):
                if (now - t0) * 1000.0 >= BATCH_MAX_MS:
                    flush_parsed(dn)

    while running:
        try:
            # Short timeout to allow frequent timeout checks
            payload_bytes, addr = q.get(timeout=0.01)
        except queue.Empty:
            check_timeouts()
            continue

        ip_source = addr[0] if isinstance(addr, tuple) and addr else None
        if ip_source:
            dn_hint = quick_dn_from_payload(payload_bytes)
            if dn_hint:
                update_device_registry(dn_hint, ip_source)

        # Path 1: Raw aggregation
        if PUBLISH_RAW:
            if not raw_batch:
                raw_t0 = time.time()
            raw_batch.append(payload_bytes)
            if len(raw_batch) >= BATCH_MAX_ITEMS:
                flush_raw()

        # Path 2: Parsed batching
        if PUBLISH_PARSED:
            try:
                sd = sensor2.parse_sensor_data(payload_bytes)
                if sd is None:
                    # check timeouts even if packet invalid, to avoid stall
                    check_timeouts()
                    continue
                
                dn_hex, body = encode_parsed(sd)
                update_device_registry(dn_hex, ip_source)
                
                if dn_hex not in parsed_batches:
                    parsed_batches[dn_hex] = []
                    parsed_t0[dn_hex] = time.time()
                
                parsed_batches[dn_hex].append(body)
                
                if len(parsed_batches[dn_hex]) >= BATCH_MAX_ITEMS:
                    flush_parsed(dn_hex)
                else:
                    # Optional: check timeouts periodically even during busy burst?
                    # For very high throughput, we rely on batch size trigger.
                    # But if we have mix of slow and fast devices, we should check timeouts.
                    # Doing it every packet might be too expensive if queue is full.
                    # Let's do it every 10 packets or simple modulo check if needed.
                    # For now, rely on queue.get timeout or batch size.
                    pass

            except Exception:
                pkt_parse_err += 1
        
        # Periodic timeout check (in case we are receiving data but not filling batches fast enough)
        # However, checking time.time() every loop is cheap enough.
        # But to be super safe against overhead:
        if q.qsize() == 0:
            check_timeouts()

    # Flush all before exit
    try:
        flush_raw()
        for dn in list(parsed_batches.keys()):
            flush_parsed(dn)
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
        with registry_lock:
            dev_count = len(device_registry)
        print(
            f"[STATS] in={pkt_in} ({in_rate:.1f}/s)  "
            f"raw_pub={pkt_pub_raw} ({raw_rate:.1f}/s)  "
            f"parsed_pub={pkt_pub_parsed} ({parsed_rate:.1f}/s)  "
            f"drop={pkt_drop} ({drop_rate:.1f}/s)  "
            f"parse_err={pkt_parse_err} ({err_rate:.2f}/s)  q={qsize}  devices={dev_count}"
        )
        last, last_in, last_raw, last_parsed, last_drop, last_err = now, pkt_in, pkt_pub_raw, pkt_pub_parsed, pkt_drop, pkt_parse_err

def main():
    install_signals()
    if BROKER_PORT == 8883 and not MQTT_TLS_ENABLED:
        print(
            "[BRIDGE/MQTT] ERROR: BROKER_PORT=8883 requires TLS. "
            "Set [MQTT] TLS_ENABLED=1 (and CA_CERT) in your config.ini.",
            file=sys.stderr,
        )
        sys.exit(2)
    if MQTT_TLS_ENABLED and not MQTT_TLS_INSECURE and not MQTT_CA_CERT:
        print(
            "[BRIDGE/MQTT] WARNING: TLS_ENABLED=1 but CA_CERT is empty; "
            "certificate verification may fail unless the CA is already trusted.",
            file=sys.stderr,
        )
    gcu_manager.start()
    # Spin up UDP/MQTT/stats threads and keep looping until interrupted.
    # Start UDP, MQTT, and stats threads until interrupted / 启动 UDP、MQTT、统计线程并持续运行直到被中断。
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
    gcu_manager.stop()
    print("[MAIN] exiting.")

if __name__ == "__main__":
    main()

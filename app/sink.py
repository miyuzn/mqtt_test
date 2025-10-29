# -*- coding: utf-8 -*-
"""
MQTT 接收端（JSON 优先，兼容二进制）：
- 订阅 etx/v1/raw/+（可在 config.ini / 环境变量覆盖）
- JSON 负载 -> 解析字段 -> 按 <DN>/<YYYYMMDD>/data.csv 追加
- 字段名可在 config.ini 中自定义映射
- 缺失 sn 时，按 pressure 数组长度推断
- 仍兼容 legacy 二进制帧（5A5A...A5A5 + sensor2.parse_sensor_data）
"""

import os, sys, csv, json, time, signal, pathlib, configparser
from datetime import datetime, timezone, timedelta
from typing import Dict, Tuple, Optional

import paho.mqtt.client as mqtt

JST = timezone(timedelta(hours=9))

# 可选：如存在则用于解析旧二进制帧
try:
    from sensor2 import parse_sensor_data as parse_binary_frame
except Exception:
    parse_binary_frame = None

# ========== 常量 ==========
START = b"\x5a\x5a"
END   = b"\xa5\xa5"

def extract_frames(payload: bytes):
    i, n = 0, len(payload)
    while True:
        s = payload.find(START, i)
        if s < 0: return
        e = payload.find(END, s + 2)
        if e < 0: return
        yield payload[s:e+2]
        i = e + 2

# ========== 配置读取 ==========
def load_config() -> dict:
    cfg = {
        "MQTT_BROKER_HOST": "127.0.0.1",
        "MQTT_BROKER_PORT": 1883,
        "MQTT_SUB_TOPIC":   "etx/v1/raw/+",
        "CLIENT_ID":        "mqtt-sink-store-json",
        "QOS":              1,
        "ROOT_DIR":         "./mqtt_store",
        "FLUSH_EVERY_ROWS": 200,
        "INACT_TIMEOUT_SEC": 5,  # 会话空闲超时（秒），超过则新文件
        # JSON 字段映射（可在 config.ini 覆盖）
        "F_DN":      "dn",         # 设备号（int/hex str/bytes/数组均可）
        "F_SN":      "sn",         # 压力点数量（可缺省）
        "F_TS":      "timestamp",  # 秒或毫秒均可（见 TS_UNIT）
        "F_TSMS":    "timems",     # 毫秒（可缺省）
        "F_PRESS":   "pressure",   # 压力数组
        "F_MAG":     "magnetometer",  # [x,y,z] 可缺省
        "F_GYRO":    "gyroscope",     # [x,y,z] 可缺省
        "F_ACC":     "accelerometer", # [x,y,z] 可缺省
        "TS_UNIT":   "s",          # "s" | "ms"  （若 timestamp 本身是毫秒，则设为 ms）
    }

    ini = "config.ini"
    if os.path.exists(ini):
        cp = configparser.ConfigParser()
        cp.read(ini, encoding="utf-8")
        if cp.has_section("mqtt"):
            cfg["MQTT_BROKER_HOST"] = cp.get("mqtt","broker_host",fallback=cfg["MQTT_BROKER_HOST"])
            cfg["MQTT_BROKER_PORT"] = cp.getint("mqtt","broker_port",fallback=cfg["MQTT_BROKER_PORT"])
            cfg["MQTT_SUB_TOPIC"]   = cp.get("mqtt","sub_topic",   fallback=cfg["MQTT_SUB_TOPIC"])
            cfg["QOS"]              = cp.getint("mqtt","qos",       fallback=cfg["QOS"])
            cfg["CLIENT_ID"]        = cp.get("mqtt","client_id",    fallback=cfg["CLIENT_ID"])
        if cp.has_section("store"):
            cfg["ROOT_DIR"]         = cp.get("store","root_dir",    fallback=cfg["ROOT_DIR"])
            cfg["FLUSH_EVERY_ROWS"] = cp.getint("store","flush_every_rows", fallback=cfg["FLUSH_EVERY_ROWS"])
            cfg["INACT_TIMEOUT_SEC"] = cp.getint("store", "inact_timeout_sec", fallback=cfg["INACT_TIMEOUT_SEC"])
        if cp.has_section("json"):
            for k in ["F_DN","F_SN","F_TS","F_TSMS","F_PRESS","F_MAG","F_GYRO","F_ACC","TS_UNIT"]:
                if cp.has_option("json", k.lower()):
                    cfg[k] = cp.get("json", k.lower())
    # 环境变量覆盖（可选）
    env = os.getenv
    cfg["MQTT_BROKER_HOST"] = env("MQTT_BROKER_HOST", cfg["MQTT_BROKER_HOST"])
    cfg["MQTT_BROKER_PORT"] = int(env("MQTT_BROKER_PORT", str(cfg["MQTT_BROKER_PORT"])))
    cfg["MQTT_SUB_TOPIC"]   = env("MQTT_SUB_TOPIC", cfg["MQTT_SUB_TOPIC"])
    cfg["CLIENT_ID"]        = env("CLIENT_ID", cfg["CLIENT_ID"])
    cfg["ROOT_DIR"]         = env("SINK_ROOT_DIR", cfg["ROOT_DIR"])
    return cfg

# ========== DN & CSV 句柄 ==========
def dn_to_hex(dn) -> str:
    """将 dn 统一为 12 位大写 HEX（假定 6 字节设备号）。"""
    if dn is None:
        return "000000000000"
    if isinstance(dn, (bytes, bytearray, list, tuple)):
        dn_bytes = bytes(dn)
    elif isinstance(dn, int):
        dn_bytes = dn.to_bytes(6, "big", signed=False)
    elif isinstance(dn, str):
        h = dn.replace(" ", "").replace("-", "").lower()
        if h.startswith("0x"): h = h[2:]
        dn_bytes = bytes.fromhex(h[-12:].rjust(12, "0"))
    else:
        # 最后兜底转字符串哈希（不推荐），但避免崩溃
        s = str(dn).encode("utf-8")
        dn_bytes = (s + b"\x00"*6)[:6]
    return dn_bytes.hex().upper()

class CsvHandle:
    def __init__(self, path: pathlib.Path, sn: int, dn_hex: str):
        self.path = path; self.sn = sn; self.dn_hex = dn_hex
        self.f = None; self.writer = None; self.rows_since_flush = 0

    def _ensure_open(self):
        new_file = not self.path.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(self.path, "a", newline="", encoding="utf-8")
        self.writer = csv.writer(self.f)
        if new_file:
            self.writer.writerow([f"// DN: {self.dn_hex}, SN: {self.sn}"])
            header = (["Timestamp"]
                      + [f"P{i+1}" for i in range(self.sn)]
                      + ["Mag_x","Mag_y","Mag_z","Gyro_x","Gyro_y","Gyro_z","Acc_x","Acc_y","Acc_z"])
            self.writer.writerow(header); self.f.flush()

    def write_row(self, ts: float, pressures, mag, gyro, acc, flush_every: int):
        if self.f is None: self._ensure_open()
        p = list(pressures[:self.sn]); 
        if len(p) < self.sn: p.extend([0]*(self.sn-len(p)))
        def v3(x): 
            x = (x or [0,0,0]) + [0,0,0]; return x[:3]
        row = [ts] + p + v3(mag) + v3(gyro) + v3(acc)
        self.writer.writerow(row); self.rows_since_flush += 1
        if self.rows_since_flush >= flush_every: self.f.flush(); self.rows_since_flush = 0

    def close(self):
        if self.f: self.f.flush(); self.f.close(); self.f=None; self.writer=None

class StoreManager:
    def __init__(self, root_dir, flush_every_rows, inactivity_timeout_sec: int = 5):
        self.root = pathlib.Path(root_dir)
        self.flush_every_rows = flush_every_rows
        self.inactivity_timeout_sec = inactivity_timeout_sec
        # 按 DN 维护当前会话：dn_hex -> {"day": "YYYYMMDD", "handle": CsvHandle, "last_seen": datetime, "sn": int}
        self.sessions: Dict[str, Dict[str, object]] = {}

    def _new_handle_path(self, dn_hex: str, when: datetime) -> pathlib.Path:
        day = when.strftime("%Y%m%d")
        now_str = when.strftime("%H%M%S")  # 文件名按时分秒
        return self.root / dn_hex / day / f"{now_str}.csv"

    def _open_new_session(self, dn_hex: str, sn: int, when: datetime):
        # 关闭旧句柄（若有）
        s = self.sessions.get(dn_hex)
        if s and s.get("handle"):
            try: s["handle"].close()
            except Exception: pass

        path = self._new_handle_path(dn_hex, when)
        h = CsvHandle(path, sn, dn_hex)
        self.sessions[dn_hex] = {
            "day": when.strftime("%Y%m%d"),
            "handle": h,
            "last_seen": when,
            "sn": int(sn),
        }
        return h

    def _get_handle_for_write(self, dn_hex: str, sn: int, when: datetime) -> CsvHandle:
        day = when.strftime("%Y%m%d")
        s = self.sessions.get(dn_hex)

        if s is None:
            return self._open_new_session(dn_hex, sn, when)

        # 跨天则强制新文件
        if s["day"] != day:
            return self._open_new_session(dn_hex, sn, when)

        # 会话空闲超时则新文件（视为新实验）
        last_seen: datetime = s["last_seen"]
        idle = (when - last_seen).total_seconds()
        if idle >= self.inactivity_timeout_sec:
            return self._open_new_session(dn_hex, sn, when)

        # SN 如变化，以新 SN 为准开新文件（避免列数不一致）
        if int(s["sn"]) != int(sn):
            return self._open_new_session(dn_hex, sn, when)

        return s["handle"]

    def write(self, dn_hex: str, sn: int, ts: float, pressures, mag, gyro, acc, when: datetime):
        h = self._get_handle_for_write(dn_hex, sn, when)
        h.write_row(ts, pressures, mag, gyro, acc, self.flush_every_rows)
        # 更新 last_seen
        sess = self.sessions[dn_hex]
        sess["last_seen"] = when

    def close_all(self):
        for s in self.sessions.values():
            h = s.get("handle")
            if h: 
                try: h.close()
                except Exception: pass
        self.sessions.clear()

# ========== JSON 解析 ==========
def parse_json_payload(b: bytes, cfg: dict):
    try:
        obj = json.loads(b.decode("utf-8"))
    except Exception:
        return None
    # 支持对象或数组（数组则逐条返回）
    if isinstance(obj, list):
        return [parse_json_obj(x, cfg) for x in obj if isinstance(x, dict)]
    elif isinstance(obj, dict):
        return [parse_json_obj(obj, cfg)]
    return None

def parse_json_obj(d: dict, cfg: dict):
    f = lambda k, default=None: d.get(cfg[k], default)
    dn = f("F_DN")
    dn_hex = dn_to_hex(dn)
    sn = f("F_SN")
    pressures = f("F_PRESS", []) or []
    if sn is None:
        sn = int(len(pressures))
    # 时间戳：支持 (ts, timems) 或 ts 毫秒
    ts = f("F_TS", 0) or 0
    timems = f("F_TSMS", 0) or 0
    try:
        ts = float(ts)
    except Exception:
        ts = 0.0
    if cfg["TS_UNIT"].lower() == "ms":
        ts = ts / 1000.0
    ts = ts + (float(timems)/1000.0 if timems else 0.0)
    return {
        "dn_hex": dn_hex,
        "sn": int(sn),
        "ts": float(ts),
        "pressures": list(pressures),
        "mag": d.get(cfg["F_MAG"], None),
        "gyro": d.get(cfg["F_GYRO"], None),
        "acc": d.get(cfg["F_ACC"], None),
    }

# ========== 主体 ==========
class MqttSink:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.client = mqtt.Client(client_id=cfg["CLIENT_ID"], clean_session=True)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.store = StoreManager(cfg["ROOT_DIR"], cfg["FLUSH_EVERY_ROWS"], cfg.get("INACT_TIMEOUT_SEC", 5))
        self._running = True
        self._rx = 0
        self._last_stat = time.time()

    def on_connect(self, client, userdata, flags, rc):
        print(f"[MQTT] connected rc={rc}")
        client.subscribe(self.cfg["MQTT_SUB_TOPIC"], qos=self.cfg["QOS"])
        print(f"[MQTT] subscribed: {self.cfg['MQTT_SUB_TOPIC']}")

    def on_message(self, client, userdata, msg):
        b = msg.payload or b""
        frames = None
        # 1) JSON 优先
        if b[:1] in (b"{", b"["):
            parsed = parse_json_payload(b, self.cfg) or []
            for item in parsed:
                if not item: continue
                now_local = datetime.now(JST)
                self.store.write(item["dn_hex"], item["sn"], item["ts"],
                                 item["pressures"], item["mag"], item["gyro"], item["acc"],
                                 when=now_local)
                self._rx += 1
        # 2) 兼容旧二进制
        elif parse_binary_frame is not None:
            frames = list(extract_frames(b))
            for fr in frames:
                try:
                    sd = parse_binary_frame(fr)
                except Exception:
                    sd = None
                if not sd: continue
                dn_hex = dn_to_hex(sd.dn)
                now_local = datetime.now(JST)
                self.store.write(dn_hex, int(sd.sn), float(sd.timestamp),
                                 sd.pressure_sensors, sd.magnetometer, sd.gyroscope, sd.accelerometer,
                                 when=now_local)
                self._rx += 1

        # 统计
        now = time.time()
        if (now - self._last_stat) >= 2.0:
            print(f"[STATS] rows_written={self._rx}")
            self._last_stat = now

    def run(self):
        self.client.connect(self.cfg["MQTT_BROKER_HOST"], self.cfg["MQTT_BROKER_PORT"], keepalive=30)
        self.client.loop_start()
        try:
            while self._running:
                time.sleep(0.2)
        finally:
            self.client.loop_stop(); self.client.disconnect(); self.store.close_all()
            print("[MAIN] sink stopped.")

    def stop(self): self._running = False

def install_signals(app: MqttSink):
    def _h(sig, frame): app.stop()
    signal.signal(signal.SIGINT, _h)
    if hasattr(signal, "SIGTERM"): signal.signal(signal.SIGTERM, _h)

def main():
    cfg = load_config()
    print(f"[CFG] broker={cfg['MQTT_BROKER_HOST']}:{cfg['MQTT_BROKER_PORT']}  sub={cfg['MQTT_SUB_TOPIC']}  root={cfg['ROOT_DIR']}")
    app = MqttSink(cfg); install_signals(app); app.run()

if __name__ == "__main__":
    main()

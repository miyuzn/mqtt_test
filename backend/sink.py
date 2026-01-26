# -*- coding: utf-8 -*-
"""
MQTT 接收端（JSON 优先，兼容二进制）：
- 订阅 etx/v1/raw/+（可在 config.ini / 环境变量覆盖）
- JSON 负载 -> 解析字段 -> <DN>/<YYYYMMDD>/data.csv 追加
- 字段名可在 config.ini 中自定义映射
- 缺失 sn 时，按 pressure 数组长度推断
- 仍兼容 legacy 二进制帧：A5A...A5A5 + sensor2.parse_sensor_data

MQTT sink that focuses on JSON payloads but still accepts legacy binary frames:
- Subscribes to etx/v1/raw/+ (config/env overridable)
- Parses JSON fields and appends rows to <DN>/<YYYYMMDD>/data.csv
- Field names stay configurable and missing SN falls back to pressure count
- Legacy binary frames (A5A...A5A5) are parsed via sensor2.parse_sensor_data
"""

import os, sys, csv, json, time, signal, pathlib, configparser, threading
import queue
from datetime import datetime, timezone, timedelta
from typing import Dict, Tuple, Optional

import paho.mqtt.client as mqtt
import psycopg2
from psycopg2 import sql

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
    # Iterate through legacy payloads and yield each framed segment.
    # 遍历旧版负载并逐帧返回被包裹的数据片段。
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
    """Load sink configuration from defaults + config.ini + environment overrides.
    从默认值、config.ini 与环境变量叠加加载接收端配置。
    """
    cfg = {
        "MQTT_BROKER_HOST": "127.0.0.1",
        "MQTT_BROKER_PORT": 1883,
        "MQTT_SUB_TOPIC":   "etx/v1/raw/+",
        
        "CLIENT_ID":        "mqtt-sink-store-json",
        "QOS":              1,
        "ROOT_DIR":         "./mqtt_store",
        "FLUSH_EVERY_ROWS": 200,
        "INACT_TIMEOUT_SEC": 20,  # 会话空闲超时（秒），超过则新文件
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
    # 兼容 docker-compose 中沿用的 BROKER_HOST/BROKER_PORT 命名
    alt_host = env("BROKER_HOST")
    if alt_host:
        cfg["MQTT_BROKER_HOST"] = alt_host
    alt_port = env("BROKER_PORT")
    if alt_port:
        cfg["MQTT_BROKER_PORT"] = int(alt_port)
    cfg["MQTT_SUB_TOPIC"]   = env("MQTT_SUB_TOPIC", cfg["MQTT_SUB_TOPIC"])
    cfg["MQTT_CONTROL_TOPIC"] = env("MQTT_CONTROL_TOPIC", "etx/v1/control/record")
    cfg["CLIENT_ID"]        = env("CLIENT_ID", cfg["CLIENT_ID"])
    cfg["ROOT_DIR"]         = env("SINK_ROOT_DIR", cfg["ROOT_DIR"])
    cfg["FLUSH_EVERY_ROWS"] = int(env("SINK_FLUSH_EVERY_ROWS", str(cfg["FLUSH_EVERY_ROWS"])))
    cfg["INACT_TIMEOUT_SEC"] = int(env("SINK_INACT_TIMEOUT_SEC", str(cfg["INACT_TIMEOUT_SEC"])))
    return cfg

# ========== 数据库工具 ==========
def get_db_connection():
    host = os.getenv("DB_HOST")
    if not host: return None
    return psycopg2.connect(
        host=host,
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        connect_timeout=10
    )

def get_csv_timestamp(filepath):
    """Attempt to read the first data row timestamp from CSV.
    尝试从 CSV 中读取第一行数据的 Timestamp。
    """
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            # Expected: // DN..., Header, Data
            lines = [f.readline() for _ in range(3)]
            if len(lines) < 3: return None
            
            headers = [h.strip() for h in lines[1].split(',')]
            row = [d.strip() for d in lines[2].split(',')]
            
            if "Timestamp" in headers:
                idx = headers.index("Timestamp")
                if idx < len(row):
                    ts_val = float(row[idx])
                    if ts_val > 0:
                        return datetime.fromtimestamp(ts_val, JST)
    except Exception:
        pass
    return None

def normalize_path_for_db(root: pathlib.Path, file_path: pathlib.Path) -> str:
    """Calculate directory path relative to root, formatted for DB (Windows separators).
    计算相对于 root 的目录路径，统一为 Windows 风格的反斜杠结尾（保持与旧逻辑兼容）。
    """
    try:
        # relative_to throws if not subpath
        rel = file_path.parent.relative_to(root)
        s = str(rel).replace("/", "\\")
        if not s.endswith("\\"):
            s += "\\"
        return s
    except Exception:
        # Fallback if path manipulation fails
        return f"{file_path.parent.name}\\"

class DBWriter(threading.Thread):
    """Background thread to handle DB inserts/updates without blocking MQTT loop."""
    def __init__(self, queue_obj, root_dir):
        super().__init__(daemon=True)
        self.queue = queue_obj
        self.root = pathlib.Path(root_dir)
        self._conn = None
    
    def _get_conn(self):
        if self._conn and self._conn.closed == 0:
            return self._conn
        try:
            self._conn = get_db_connection()
            return self._conn
        except Exception as e:
            print(f"[DBWriter] Connect failed: {e}")
            return None

    def run(self):
        print("[DBWriter] Started.")
        while True:
            item = self.queue.get()
            if item is None: break # Stop signal
            
            action, payload = item
            conn = self._get_conn()
            if not conn:
                self.queue.task_done()
                continue
            
            try:
                with conn:
                    with conn.cursor() as cur:
                        if action == "INSERT":
                            self._handle_insert(cur, payload)
                        elif action == "UPDATE":
                            self._handle_update(cur, payload)
            except Exception as e:
                print(f"[DBWriter] Error processing {action}: {e}")
                # Optional: retry logic could go here, but keep simple for now
                if self._conn:
                    try: self._conn.close()
                    except: pass
                    self._conn = None
            
            self.queue.task_done()
    
    def _handle_insert(self, cur, payload):
        # payload: (dn_hex, abs_path, timestamp, filename)
        dn_hex, abs_path_str, ts, filename = payload
        abs_path = pathlib.Path(abs_path_str)
        
        rel_path_str = normalize_path_for_db(self.root, abs_path)
        
        # Ensure timestamp is valid datetime
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts, JST)
        elif isinstance(ts, datetime):
            dt = ts
        else:
            dt = datetime.now(JST)

        sql_cmd = """
            INSERT INTO data_files 
            (mac_address, file_date, file_time, file_datetime, file_name, file_path, file_size, side_position, file_memo)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """
        cur.execute(sql_cmd, (
            dn_hex, dt.date(), dt.time(), dt,
            filename, rel_path_str, 0, None, 'Live Recording'
        ))
        # print(f"[DB] Inserted {filename}")

    def _handle_update(self, cur, payload):
        # payload: (abs_path, size)
        abs_path_str, size = payload
        abs_path = pathlib.Path(abs_path_str)
        filename = abs_path.name
        rel_path_str = normalize_path_for_db(self.root, abs_path)
        
        # Identify record by mac (implied by path structure?), filename and path
        # Actually mac is needed for index usage usually, but we have filename+path unique?
        # Let's try matching by filename + path
        sql_cmd = """
            UPDATE data_files SET file_size = %s 
            WHERE file_name = %s AND file_path = %s
        """
        cur.execute(sql_cmd, (size, filename, rel_path_str))
        # print(f"[DB] Updated size for {filename}: {size}")

def rebuild_file_index(root_dir):
    """Scan disk and sync DB. Serves as the 'Source of Truth' logic."""
    print("[DB-Sync] Starting full index rebuild...")
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            print("[DB-Sync] No DB config, skipping.")
            return

        root = pathlib.Path(root_dir)
        if not root.exists(): return

        # Pre-load valid MACs
        valid_macs = set()
        with conn.cursor() as cur:
            cur.execute("SELECT mac_address FROM device_info")
            for row in cur.fetchall():
                if row[0]: valid_macs.add(row[0])

        disk_files = []
        # Scan Level 1: DN
        for dn_dir in root.iterdir():
            if not dn_dir.is_dir(): continue
            dn_hex = dn_dir.name
            if len(dn_hex) < 4 or dn_hex not in valid_macs: continue

            # Scan Level 2+: CSVs
            for p in dn_dir.rglob("*.csv"):
                try:
                    ts = get_csv_timestamp(p)
                    if not ts:
                        ts = datetime.fromtimestamp(p.stat().st_mtime, JST)
                    
                    rel_path_str = normalize_path_for_db(root, p)
                    
                    disk_files.append({
                        'mac': dn_hex,
                        'name': p.name,
                        'path': rel_path_str,
                        'size': p.stat().st_size,
                        'dt': ts
                    })
                except Exception:
                    pass

        # Full Rebuild (Truncate + Insert)
        with conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE data_files RESTART IDENTITY CASCADE;")
                count = 0
                for f in disk_files:
                    cur.execute("""
                        INSERT INTO data_files 
                        (mac_address, file_date, file_time, file_datetime, file_name, file_path, file_size, side_position, file_memo)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        f['mac'], f['dt'].date(), f['dt'].time(), f['dt'], 
                        f['name'], f['path'], f['size'], None, 'Rebuilt Index'
                    ))
                    count += 1
        print(f"[DB-Sync] Sync complete. Inserted: {count}")
    except Exception as e:
        print(f"[DB-Sync] Failed: {e}")
    finally:
        if conn: conn.close()

class SchedulerThread(threading.Thread):
    def __init__(self, root_dir, interval_hours=24):
        super().__init__(daemon=True)
        self.root_dir = root_dir
        self.interval = interval_hours * 3600
        self._stop_event = threading.Event()

    def run(self):
        print(f"[Scheduler] Started. Scanning every {self.interval}s.")
        rebuild_file_index(self.root_dir)
        while not self._stop_event.is_set():
            if self._stop_event.wait(self.interval): break
            rebuild_file_index(self.root_dir)

    def stop(self):
        self._stop_event.set()

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
        if h.upper() == "ALL": return "ALL"
        if h.startswith("0x"): h = h[2:]
        dn_bytes = bytes.fromhex(h[-12:].rjust(12, "0"))
    else:
        # 最后兜底转字符串哈希（不推荐），但避免崩溃
        s = str(dn).encode("utf-8")
        dn_bytes = (s + b"\x00"*6)[:6]
    return dn_bytes.hex().upper()

class CsvHandle:
    """Manage a per-session CSV file for one DN/day.
    为同一 DN/日期维护单个 CSV 句柄。
    """
    def __init__(self, path: pathlib.Path, sn: int, dn_hex: str, db_queue: queue.Queue = None):
        self.path = path; self.sn = sn; self.dn_hex = dn_hex
        self.db_queue = db_queue
        self.f = None; self.writer = None; self.rows_since_flush = 0
        self.has_inserted_db = False

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
        
        # DB Hook: Insert on first data write
        if self.db_queue and not self.has_inserted_db:
            # Action: INSERT, Payload: (dn_hex, abs_path_str, timestamp, filename)
            # Use the sensor timestamp 'ts' for consistency with rebuild logic
            self.db_queue.put(("INSERT", (self.dn_hex, str(self.path.absolute()), ts, self.path.name)))
            self.has_inserted_db = True

        p = list(pressures[:self.sn]); 
        if len(p) < self.sn: p.extend([0]*(self.sn-len(p)))
        def v3(x):
            base = list(x) if isinstance(x, (list, tuple)) else list(x or [0,0,0])
            base += [0,0,0]
            return base[:3]
        
        row = [ts] + p + v3(mag) + v3(gyro) + v3(acc)
        self.writer.writerow(row); self.rows_since_flush += 1
        if self.rows_since_flush >= flush_every: self.f.flush(); self.rows_since_flush = 0

    def close(self):
        if self.f: 
            self.f.flush(); self.f.close()
            # DB Hook: Update size on close
            if self.db_queue and self.has_inserted_db:
                try:
                    final_size = self.path.stat().st_size
                    # Action: UPDATE, Payload: (abs_path_str, size)
                    self.db_queue.put(("UPDATE", (str(self.path.absolute()), final_size)))
                except Exception:
                    pass
            self.f=None; self.writer=None

class StoreManager:
    """Allocate CSV writers on demand and rotate based on time/session rules.
    根据时间/会话规则按需分配 CSV 写入句柄。
    """
    def __init__(self, root_dir, flush_every_rows, inactivity_timeout_sec: int = 20, db_queue: queue.Queue = None):
        self.root = pathlib.Path(root_dir)
        self.flush_every_rows = flush_every_rows
        self.inactivity_timeout_sec = inactivity_timeout_sec
        self.db_queue = db_queue
        # 按 DN 维护当前会话：dn_hex -> {"day": "YYYYMMDD", "handle": CsvHandle, "last_seen": datetime, "sn": int}
        self.sessions: Dict[str, Dict[str, object]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _resolve_event_time(ts: float, fallback: datetime) -> datetime:
        """Use payload timestamp when valid; otherwise fall back to ingest time.
        解析事件时间：优先采用 payload timestamp，不合法时退回接收时间。
        """
        event_time: Optional[datetime] = None
        try:
            if ts is None:
                raise ValueError
            if isinstance(ts, bool):  # bool 是 int 子类，单独剔除
                raise ValueError
            if isinstance(ts, (int, float)):
                if ts != ts or ts in (float("inf"), float("-inf")):
                    raise ValueError
                if ts <= 0:
                    raise ValueError
                event_time = datetime.fromtimestamp(float(ts), JST)
        except Exception:
            event_time = None
        return event_time or fallback

    def _new_handle_path(self, dn_hex: str, when: datetime) -> pathlib.Path:
        day = when.strftime("%Y%m%d")
        now_str = when.strftime("%H%M%S")  # 文件名按时分秒
        return self.root / dn_hex / day / f"{now_str}.csv"

    def _open_new_session(self, dn_hex: str, sn: int, when: datetime, ingest_time: datetime):
        # Must be called within lock
        # 关闭旧句柄（若有）
        s = self.sessions.get(dn_hex)
        if s and s.get("handle"):
            try: s["handle"].close()
            except Exception: pass

        path = self._new_handle_path(dn_hex, when)
        h = CsvHandle(path, sn, dn_hex, db_queue=self.db_queue)
        self.sessions[dn_hex] = {
            "day": when.strftime("%Y%m%d"),
            "handle": h,
            "last_seen": when,
            "last_ingest_time": ingest_time,
            "sn": int(sn),
        }
        return h

    def _get_handle_for_write(self, dn_hex: str, sn: int, when: datetime, ingest_time: datetime) -> CsvHandle:
        # Must be called within lock
        day = when.strftime("%Y%m%d")
        s = self.sessions.get(dn_hex)

        if s is None:
            return self._open_new_session(dn_hex, sn, when, ingest_time)

        # Rotate the file whenever day changes to keep folders tidy.
        # 一旦跨天就强制创建新文件，保持目录整洁。
        if s["day"] != day:
            return self._open_new_session(dn_hex, sn, when, ingest_time)

        # Treat long idle windows as new experiments -> new file.
        # 如空闲时间过长，则视为新实验并重启文件。
        # Use ingest_time for timeout logic to avoid device timestamp jumps/drifts.
        last_ingest = s.get("last_ingest_time") or s.get("last_seen")
        idle = (ingest_time - last_ingest).total_seconds()
        
        if idle < 0:
            idle = 0.0
        if idle >= self.inactivity_timeout_sec:
            return self._open_new_session(dn_hex, sn, when, ingest_time)

        # Column count depends on SN, so switch files when SN changes.
        # CSV 列数取决于 SN，发生变化时需切换文件。
        if int(s["sn"]) != int(sn):
            return self._open_new_session(dn_hex, sn, when, ingest_time)

        return s["handle"]

    def write(self, dn_hex: str, sn: int, ts: float, pressures, mag, gyro, acc, ingest_time: datetime):
        event_time = self._resolve_event_time(ts, ingest_time)
        with self._lock:
            h = self._get_handle_for_write(dn_hex, sn, event_time, ingest_time)
            h.write_row(ts, pressures, mag, gyro, acc, self.flush_every_rows)
            # 更新 last_seen 和 last_ingest_time
            sess = self.sessions[dn_hex]
            sess["last_seen"] = event_time
            sess["last_ingest_time"] = ingest_time

    def close_session(self, dn_hex: str):
        with self._lock:
            s = self.sessions.get(dn_hex)
            if s:
                h = s.get("handle")
                if h:
                    try: h.close()
                    except Exception: pass
                del self.sessions[dn_hex]
                # print(f"[Store] Closed session for {dn_hex} by request")

    def check_timeouts(self):
        """Actively close sessions that have been idle for too long.
        主动检查并关闭空闲超时的会话。
        """
        now = datetime.now(JST)
        with self._lock:
            # Collect keys to remove to avoid modifying dict while iterating
            to_remove = []
            for dn_hex, sess in self.sessions.items():
                # Use last_ingest_time for robust timeout check
                last_active = sess.get("last_ingest_time") or sess.get("last_seen")
                if not last_active:
                    continue
                idle = (now - last_active).total_seconds()
                if idle >= self.inactivity_timeout_sec:
                    # Close and mark for removal
                    h = sess.get("handle")
                    if h:
                        try:
                            h.close()
                        except Exception:
                            pass
                    to_remove.append(dn_hex)
            
            for k in to_remove:
                del self.sessions[k]
                # print(f"[Store] Closed idle session for {k}")

    def close_all(self):
        with self._lock:
            for s in self.sessions.values():
                h = s.get("handle")
                if h: 
                    try: h.close()
                    except Exception: pass
            self.sessions.clear()

# ========== JSON 解析 ==========
def parse_json_payload(b: bytes, cfg: dict):
    """Parse MQTT payload that may contain one dict or a list of dicts.
    解析可能为单对象或对象列表的 MQTT 负载。
    """
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
    """Project a JSON dict into canonical keys and normalize timestamp units.
    将 JSON 字典映射为统一字段并归一化时间戳单位。
    """
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
    """Consume MQTT messages, parse payloads, and persist them onto disk.
    负责消费 MQTT 消息、解析负载并将结果写入磁盘。
    """
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.client = mqtt.Client(client_id=cfg["CLIENT_ID"], clean_session=True)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        
        # Setup DB Queue and Threads
        self.db_queue = queue.Queue()
        
        # Pass db_queue to store
        self.store = StoreManager(
            cfg["ROOT_DIR"], 
            cfg["FLUSH_EVERY_ROWS"], 
            cfg.get("INACT_TIMEOUT_SEC", 5),
            db_queue=self.db_queue
        )
        
        # Threads
        self.db_thread = DBWriter(self.db_queue, cfg["ROOT_DIR"])
        self.scheduler = SchedulerThread(cfg["ROOT_DIR"])
        
        self._running = True
        self._rx = 0
        self._last_stat = time.time()
        self._recording_dns = set()

    def on_connect(self, client, userdata, flags, rc):
        print(f"[MQTT] connected rc={rc}")
        client.subscribe(self.cfg["MQTT_SUB_TOPIC"], qos=self.cfg["QOS"])
        client.subscribe(self.cfg["MQTT_CONTROL_TOPIC"], qos=1)
        print(f"[MQTT] subscribed: {self.cfg['MQTT_SUB_TOPIC']} & {self.cfg['MQTT_CONTROL_TOPIC']}")

    def on_message(self, client, userdata, msg):
        # Handle Control Messages
        if mqtt.topic_matches_sub(self.cfg["MQTT_CONTROL_TOPIC"], msg.topic):
            if msg.retain:
                print(f"[CTRL] Ignored retained message on {msg.topic}")
                return
            try:
                payload = json.loads(msg.payload.decode("utf-8"))
                dn_raw = payload.get("dn")
                should_record = bool(payload.get("record"))
                
                if dn_raw:
                    dn_hex = dn_to_hex(dn_raw)
                    # Ignore "ALL" requests for safety/multi-select logic
                    if dn_hex == "ALL":
                         print(f"[CTRL] Ignored 'ALL' record request (deprecated).")
                    else:
                        if should_record:
                            self._recording_dns.add(dn_hex)
                            print(f"[CTRL] Recording STARTED for {dn_hex}")
                        else:
                            self._recording_dns.discard(dn_hex)
                            self.store.close_session(dn_hex)
                            print(f"[CTRL] Recording STOPPED for {dn_hex}")
            except Exception as e:
                print(f"[CTRL] Failed to parse control message: {e}")
            return

        b = msg.payload or b""
        frames = None
        
        def is_recording(dn):
            return dn in self._recording_dns

        # 1) JSON takes priority because it already matches the CSV schema.
        # 首选 JSON 负载，因为字段布局与 CSV 完全一致。
        if b[:1] in (b"{", b"["):
            parsed = parse_json_payload(b, self.cfg) or []
            for item in parsed:
                if not item: continue
                if not is_recording(item["dn_hex"]): continue

                ingest_time = datetime.now(JST)
                self.store.write(item["dn_hex"], item["sn"], item["ts"],
                                 item["pressures"], item["mag"], item["gyro"], item["acc"],
                                 ingest_time=ingest_time)
                self._rx += 1
        # 2) Fall back to legacy binary frames when JSON is absent.
        # 如无 JSON，则兼容旧版二进制帧。
        elif parse_binary_frame is not None:
            frames = list(extract_frames(b))
            for fr in frames:
                try:
                    sd = parse_binary_frame(fr)
                except Exception:
                    sd = None
                if not sd: continue
                dn_hex = dn_to_hex(sd.dn)
                if not is_recording(dn_hex): continue

                ingest_time = datetime.now(JST)
                self.store.write(dn_hex, int(sd.sn), float(sd.timestamp),
                                 sd.pressure_sensors, sd.magnetometer, sd.gyroscope, sd.accelerometer,
                                 ingest_time=ingest_time)
                self._rx += 1

        now = time.time()

    def run(self):
        # Start helper threads
        self.db_thread.start()
        self.scheduler.start()
        
        self.client.connect(self.cfg["MQTT_BROKER_HOST"], self.cfg["MQTT_BROKER_PORT"], keepalive=30)
        self.client.loop_start()
        try:
            while self._running:
                time.sleep(1.0)  # 主循环 1秒检查一次超时
                self.store.check_timeouts()
        finally:
            self.client.loop_stop(); self.client.disconnect()
            self.store.close_all()
            
            # Stop DB thread gracefully
            self.scheduler.stop()
            self.db_queue.put(None) # Poison pill
            self.db_thread.join(timeout=2)
            
            print("[MAIN] sink stopped.")

    def stop(self): self._running = False

def install_signals(app: MqttSink):
    # Map OS signals to sink.stop so Ctrl+C flushes files gracefully.
    # 捕获 OS 信号并调用 stop，确保 Ctrl+C 时能优雅关闭文件。
    def _h(sig, frame): app.stop()
    signal.signal(signal.SIGINT, _h)
    if hasattr(signal, "SIGTERM"): signal.signal(signal.SIGTERM, _h)

def main():
    cfg = load_config()
    print(f"[CFG] broker={cfg['MQTT_BROKER_HOST']}:{cfg['MQTT_BROKER_PORT']}  sub={cfg['MQTT_SUB_TOPIC']}  root={cfg['ROOT_DIR']}")
    # Build sink instance, install signal handlers, then block until stop.
    # 构建 sink 实例并注册信号处理器后进入主循环。
    app = MqttSink(cfg); install_signals(app); app.run()

if __name__ == "__main__":
    main()
"""
Raw-to-parsed MQTT bridge running close to the broker.

Listens to binary payload topics on the broker's TCP port (1883 by default),
parses each frame using the existing sensor2 routine, and republishes JSON
frames through the broker's WebSocket port (9001 by default). This lets
resource-constrained Android/edge devices publish raw frames only.
"""

from __future__ import annotations

import configparser
import json
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import paho.mqtt.client as mqtt

# Allow importing app.sensor2 without installing as package.
ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "backend"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import sensor2  # type: ignore  # noqa: E402


START_MARKER = 0x5A
END_MARKER = 0xA5
MIN_HEADER_SIZE = 2 + 6 + 1 + 4 + 2  # markers + DN + SN + timestamp + ms
IMU_TAIL_BYTES = 36 + 2  # Magnetometer + gyro + acc + end markers


@dataclass
class ParserConfig:
    config_path: str = os.getenv("CONFIG_PATH", "config.ini")
    raw_broker_host: str = "mosquitto"
    raw_broker_port: int = 1883
    raw_topic: str = "etx/v1/raw/#"
    raw_qos: int = 1
    raw_client_id: str = "raw-parser-sub"
    parsed_broker_host: str = "mosquitto"
    parsed_broker_port: int = 9001
    parsed_transport: str = "websockets"
    parsed_ws_path: str = "/mqtt"
    parsed_topic_prefix: str = "etx/v1/parsed"
    parsed_qos: int = 1
    parsed_client_id: str = "raw-parser-pub"

    def __post_init__(self) -> None:
        self._load_from_file()
        self._override_from_env()

    def _load_from_file(self) -> None:
        if not self.config_path or not os.path.exists(self.config_path):
            return
        cp = configparser.ConfigParser()
        cp.read(self.config_path, encoding="utf-8")
        if cp.has_section("PARSER"):
            section = cp["PARSER"]
            self.raw_broker_host = section.get("RAW_BROKER_HOST", self.raw_broker_host)
            self.raw_broker_port = section.getint("RAW_BROKER_PORT", self.raw_broker_port)
            self.raw_topic = section.get("RAW_TOPIC", self.raw_topic)
            self.raw_qos = section.getint("RAW_QOS", self.raw_qos)
            self.raw_client_id = section.get("RAW_CLIENT_ID", self.raw_client_id)
            self.parsed_broker_host = section.get("PARSED_BROKER_HOST", self.parsed_broker_host)
            self.parsed_broker_port = section.getint("PARSED_BROKER_PORT", self.parsed_broker_port)
            self.parsed_transport = section.get("PARSED_TRANSPORT", self.parsed_transport)
            self.parsed_ws_path = section.get("PARSED_WS_PATH", self.parsed_ws_path)
            self.parsed_topic_prefix = section.get("PARSED_TOPIC_PREFIX", self.parsed_topic_prefix)
            self.parsed_qos = section.getint("PARSED_QOS", self.parsed_qos)
            self.parsed_client_id = section.get("PARSED_CLIENT_ID", self.parsed_client_id)

    def _override_from_env(self) -> None:
        env = os.getenv
        self.raw_broker_host = env("RAW_BROKER_HOST", self.raw_broker_host)
        self.raw_broker_port = int(env("RAW_BROKER_PORT", self.raw_broker_port))
        self.raw_topic = env("RAW_TOPIC", self.raw_topic)
        self.raw_qos = int(env("RAW_QOS", self.raw_qos))
        self.raw_client_id = env("RAW_CLIENT_ID", self.raw_client_id)
        self.parsed_broker_host = env("PARSED_BROKER_HOST", self.parsed_broker_host)
        self.parsed_broker_port = int(env("PARSED_BROKER_PORT", self.parsed_broker_port))
        self.parsed_transport = env("PARSED_TRANSPORT", self.parsed_transport)
        self.parsed_ws_path = env("PARSED_WS_PATH", self.parsed_ws_path)
        self.parsed_topic_prefix = env("PARSED_TOPIC_PREFIX", self.parsed_topic_prefix)
        self.parsed_qos = int(env("PARSED_QOS", self.parsed_qos))
        self.parsed_client_id = env("PARSED_CLIENT_ID", self.parsed_client_id)


class RawParserService:
    def __init__(self, cfg: ParserConfig) -> None:
        self.cfg = cfg
        self._running = threading.Event()
        self._running.set()
        self._pub_connected = threading.Event()
        self._sub_client = self._build_sub_client()
        self._pub_client = self._build_pub_client()
        self._lock = threading.Lock()
        self._pkt_in = 0
        self._frames_ok = 0
        self._frames_err = 0

    # ------------------------------------------------------------------ MQTT Clients
    def _build_sub_client(self) -> mqtt.Client:
        client = mqtt.Client(client_id=self.cfg.raw_client_id, protocol=mqtt.MQTTv311, transport="tcp")
        client.on_connect = self._on_sub_connect
        client.on_message = self._on_sub_message
        return client

    def _build_pub_client(self) -> mqtt.Client:
        transport = "websockets" if self.cfg.parsed_transport.lower().startswith("web") else "tcp"
        client = mqtt.Client(
            client_id=self.cfg.parsed_client_id,
            protocol=mqtt.MQTTv311,
            transport=transport,
        )
        if transport == "websockets":
            client.ws_set_options(path=self.cfg.parsed_ws_path)
        client.on_connect = self._on_pub_connect
        client.on_disconnect = self._on_pub_disconnect
        return client

    # ------------------------------------------------------------------ Lifecycle
    def start(self) -> None:
        self._install_signals()
        self._pub_client.connect(self.cfg.parsed_broker_host, self.cfg.parsed_broker_port, keepalive=30)
        self._pub_client.loop_start()
        self._sub_client.connect(self.cfg.raw_broker_host, self.cfg.raw_broker_port, keepalive=30)
        self._sub_client.loop_start()
        threading.Thread(target=self._stats_loop, daemon=True).start()
        try:
            while self._running.is_set():
                time.sleep(0.2)
        finally:
            self.stop()

    def stop(self) -> None:
        if not self._running.is_set():
            return
        self._running.clear()
        try:
            self._sub_client.loop_stop()
        except Exception:
            pass
        try:
            self._sub_client.disconnect()
        except Exception:
            pass
        try:
            self._pub_client.loop_stop()
        except Exception:
            pass
        try:
            self._pub_client.disconnect()
        except Exception:
            pass

    def _install_signals(self) -> None:
        def handler(_sig, _frame) -> None:
            self.stop()

        signal.signal(signal.SIGINT, handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, handler)

    # ------------------------------------------------------------------ MQTT callbacks
    def _on_sub_connect(self, client: mqtt.Client, _userdata, _flags, rc: int) -> None:
        if rc != 0:
            print(f"[RAW] MQTT connect failed rc={rc}")
            return
        client.subscribe(self.cfg.raw_topic, qos=self.cfg.raw_qos)
        print(f"[RAW] subscribed to {self.cfg.raw_topic} @ {self.cfg.raw_broker_host}:{self.cfg.raw_broker_port}")

    def _on_pub_connect(self, _client: mqtt.Client, _userdata, _flags, rc: int) -> None:
        if rc == 0:
            self._pub_connected.set()
            print(
                f"[PARSED] ready on {self.cfg.parsed_broker_host}:{self.cfg.parsed_broker_port}"
                f" ({self.cfg.parsed_transport})"
            )
        else:
            print(f"[PARSED] connect failed rc={rc}")

    def _on_pub_disconnect(self, _client: mqtt.Client, _userdata, rc: int) -> None:
        self._pub_connected.clear()
        if rc != 0:
            print(f"[PARSED] unexpected disconnect rc={rc}")

    def _on_sub_message(self, _client: mqtt.Client, _userdata, message: mqtt.MQTTMessage) -> None:
        payload = message.payload
        with self._lock:
            self._pkt_in += 1
        for frame in iter_frames(payload):
            self._handle_frame(frame)

    # ------------------------------------------------------------------ Frame handling
    def _handle_frame(self, frame: bytes) -> None:
        sd = sensor2.parse_sensor_data(frame)
        if sd is None:
            with self._lock:
                self._frames_err += 1
            return
        dn_hex, body = encode_parsed(sd)
        topic = f"{self.cfg.parsed_topic_prefix.rstrip('/')}/{dn_hex}"
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        if not self._pub_connected.wait(timeout=5):
            print("[PARSED] publish client not connected, dropping frame")
            with self._lock:
                self._frames_err += 1
            return
        result = self._pub_client.publish(topic, payload=payload, qos=self.cfg.parsed_qos)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            with self._lock:
                self._frames_ok += 1
        else:
            print(f"[PARSED] publish failed rc={result.rc}")
            with self._lock:
                self._frames_err += 1

    # ------------------------------------------------------------------ Stats
    def _stats_loop(self) -> None:
        last = time.time()
        last_pkt = last_ok = last_err = 0
        while self._running.is_set():
            time.sleep(5)
            with self._lock:
                pkt = self._pkt_in
                ok = self._frames_ok
                err = self._frames_err
            now = time.time()
            dt = max(now - last, 1e-6)
            pkt_rate = (pkt - last_pkt) / dt
            ok_rate = (ok - last_ok) / dt
            err_rate = (err - last_err) / dt
            print(
                f"[STATS] raw_packets={pkt} ({pkt_rate:.1f}/s)  parsed_frames={ok} ({ok_rate:.1f}/s)"
                f"  errors={err} ({err_rate:.2f}/s)"
            )
            last, last_pkt, last_ok, last_err = now, pkt, ok, err


# ---------------------------------------------------------------------- Helpers
def encode_parsed(sd: sensor2.SensorData) -> tuple[str, dict]:
    dn_hex = _dn_to_hex(sd.dn)
    body = {
        "ts": float(sd.timestamp),
        "dn": dn_hex,
        "sn": int(sd.sn),
        "p": [int(x) if isinstance(x, int) else float(x) for x in sd.pressure_sensors],
        "mag": [float(sd.magnetometer[0]), float(sd.magnetometer[1]), float(sd.magnetometer[2])],
        "gyro": [float(sd.gyroscope[0]), float(sd.gyroscope[1]), float(sd.gyroscope[2])],
        "acc": [float(sd.accelerometer[0]), float(sd.accelerometer[1]), float(sd.accelerometer[2])],
    }
    return dn_hex, body


def _dn_to_hex(dn: object) -> str:
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
        b = bytes(bytearray(dn))  # type: ignore[arg-type]
    return b.hex().upper()


def iter_frames(blob: bytes) -> Iterator[bytes]:
    """Yield well-formed frames from a possibly concatenated payload."""
    data = memoryview(blob)
    idx = 0
    length = len(data)
    while idx + MIN_HEADER_SIZE + 2 <= length:
        if data[idx] != START_MARKER or data[idx + 1] != START_MARKER:
            idx += 1
            continue
        if idx + MIN_HEADER_SIZE > length:
            break
        sn = data[idx + 8]
        frame_len = 2 + 6 + 1 + 4 + 2 + sn * 4 + IMU_TAIL_BYTES
        if frame_len <= 0:
            idx += 2
            continue
        end_idx = idx + frame_len
        if end_idx > length:
            break  # wait for the rest in the next packet
        if data[end_idx - 2] != END_MARKER or data[end_idx - 1] != END_MARKER:
            idx += 2
            continue
        yield bytes(data[idx:end_idx])
        idx = end_idx


def main() -> None:
    cfg = ParserConfig()
    service = RawParserService(cfg)
    service.start()


if __name__ == "__main__":
    main()

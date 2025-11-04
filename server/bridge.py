"""MQTT -> Web bridge service.

Subscribes to parsed MQTT topics, keeps the latest payload per DN and pushes
updates to connected WebSocket (Socket.IO) clients as well as SSE consumers.
"""

from __future__ import annotations

import base64
import json
import os
import queue
import signal
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

import configparser
import paho.mqtt.client as mqtt
from flask import Flask, Response, jsonify, stream_with_context
from flask_socketio import SocketIO, emit

APP = Flask(__name__)
SOCKETIO = SocketIO(APP, cors_allowed_origins="*", async_mode="threading")


class BridgeConfig:
    def __init__(self) -> None:
        self.mqtt_host = "mosquitto"
        self.mqtt_port = 1883
        self.mqtt_topic = "etx/v1/parsed/#"
        self.mqtt_qos = 1
        self.mqtt_username: Optional[str] = None
        self.mqtt_password: Optional[str] = None
        self.client_id = "mqtt-bridge"
        self.dn_field = "dn"
        self.http_port = 5001
        self.config_path = os.getenv("BRIDGE_CONFIG", "/app/config.ini")
        self._load_from_file()
        self._override_from_env()

    def _load_from_file(self) -> None:
        path = self.config_path
        if not path or not os.path.exists(path):
            return
        cp = configparser.ConfigParser()
        cp.read(path, encoding="utf-8")
        if cp.has_section("mqtt"):
            section = cp["mqtt"]
            self.mqtt_host = section.get("broker_host", self.mqtt_host)
            self.mqtt_port = section.getint("broker_port", self.mqtt_port)
            self.mqtt_topic = section.get("sub_topic", self.mqtt_topic)
            self.mqtt_qos = section.getint("qos", self.mqtt_qos)
            self.client_id = section.get("client_id", self.client_id)
            if section.get("username"):
                self.mqtt_username = section.get("username")
            if section.get("password"):
                self.mqtt_password = section.get("password")
        if cp.has_section("json"):
            self.dn_field = cp["json"].get("f_dn", self.dn_field)

    def _override_from_env(self) -> None:
        env = os.getenv
        self.mqtt_host = env("BROKER_HOST", self.mqtt_host)
        self.mqtt_port = int(env("BROKER_PORT", self.mqtt_port))
        self.mqtt_topic = env("MQTT_SUB_TOPIC", self.mqtt_topic)
        self.mqtt_qos = int(env("MQTT_QOS", self.mqtt_qos))
        self.client_id = env("CLIENT_ID", self.client_id)
        self.http_port = int(env("BRIDGE_PORT", self.http_port))
        self.dn_field = env("BRIDGE_DN_FIELD", self.dn_field)
        self.mqtt_username = env("BROKER_USERNAME", self.mqtt_username or "") or None
        self.mqtt_password = env("BROKER_PASSWORD", self.mqtt_password or "") or None


class BridgeService:
    def __init__(self, cfg: BridgeConfig) -> None:
        self.cfg = cfg
        self._latest_by_dn: Dict[str, Dict[str, Any]] = {}
        self._cache_lock = threading.Lock()
        self._listeners: list[queue.Queue] = []
        self._listeners_lock = threading.Lock()
        self._running = threading.Event()
        self._running.set()
        self._mqtt_client: Optional[mqtt.Client] = self._create_mqtt_client()

    # ------------------------------------------------------------------
    # MQTT handling
    def _create_mqtt_client(self) -> mqtt.Client:
        client = mqtt.Client(client_id=self.cfg.client_id, protocol=mqtt.MQTTv311)
        if self.cfg.mqtt_username:
            client.username_pw_set(self.cfg.mqtt_username, self.cfg.mqtt_password)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        return client

    def start(self) -> None:
        if self._mqtt_client is None:
            self._mqtt_client = self._create_mqtt_client()
        self._mqtt_client.connect(self.cfg.mqtt_host, self.cfg.mqtt_port, keepalive=30)
        self._mqtt_client.loop_start()

    def stop(self) -> None:
        self._running.clear()
        client = self._mqtt_client
        if client is None:
            return
        try:
            client.loop_stop()
            client.disconnect()
        finally:
            self._mqtt_client = None

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Dict[str, Any], rc: int) -> None:
        if rc == 0:
            print(f"[bridge] connected to {self.cfg.mqtt_host}:{self.cfg.mqtt_port}")
            client.subscribe(self.cfg.mqtt_topic, qos=self.cfg.mqtt_qos)
            print(f"[bridge] subscribed to {self.cfg.mqtt_topic}")
        else:
            print(f"[bridge] connection failed with rc={rc}")

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        payload = self._decode_payload(msg.payload)
        dn = self._extract_dn(msg.topic, payload)
        entry = {
            "dn": dn,
            "topic": msg.topic,
            "payload": payload,
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._cache_lock:
            self._latest_by_dn[dn] = entry
        self._broadcast(entry)

    def _decode_payload(self, payload: bytes | None) -> Any:
        if not payload:
            return None
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            return {
                "encoding": "base64",
                "data": base64.b64encode(payload).decode("ascii"),
            }
        text = text.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def _extract_dn(self, topic: str, payload: Any) -> str:
        dn_value: Optional[Any] = None
        if isinstance(payload, dict):
            dn_value = payload.get(self.cfg.dn_field)
        if dn_value is None:
            parts = topic.split("/")
            if len(parts) >= 4:
                dn_value = parts[3]
        return self._normalize_dn(dn_value)

    @staticmethod
    def _normalize_dn(value: Any) -> str:
        if value is None:
            return "UNKNOWN"
        if isinstance(value, (bytes, bytearray, memoryview)):
            return bytes(value).hex().upper()
        if isinstance(value, int):
            return f"{value:012X}"
        text = str(value).strip()
        clean = text.replace(":", "").replace("-", "")
        if len(clean) >= 12 and all(c in "0123456789ABCDEFabcdef" for c in clean):
            return clean[-12:].upper()
        return text or "UNKNOWN"

    # ------------------------------------------------------------------
    # Cache & broadcast helpers
    def snapshot(self) -> Iterable[Dict[str, Any]]:
        with self._cache_lock:
            return [self._latest_by_dn[k] for k in sorted(self._latest_by_dn.keys())]

    def get_dn(self, dn: str) -> Optional[Dict[str, Any]]:
        with self._cache_lock:
            return self._latest_by_dn.get(dn)

    def _broadcast(self, entry: Dict[str, Any]) -> None:
        SOCKETIO.emit("update", entry)
        self._push_to_listeners(entry)

    def _push_to_listeners(self, entry: Dict[str, Any]) -> None:
        with self._listeners_lock:
            for q in list(self._listeners):
                try:
                    q.put_nowait(entry)
                except queue.Full:
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        q.put_nowait(entry)
                    except queue.Full:
                        self._listeners.remove(q)

    def register_listener(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=20)
        with self._listeners_lock:
            self._listeners.append(q)
        return q

    def unregister_listener(self, q: queue.Queue) -> None:
        with self._listeners_lock:
            if q in self._listeners:
                self._listeners.remove(q)


bridge_config = BridgeConfig()
bridge_service = BridgeService(bridge_config)


@APP.get("/healthz")
def healthcheck() -> Any:
    return {"status": "ok", "topics": bridge_config.mqtt_topic}


@APP.get("/api/latest")
def latest_all() -> Any:
    return {"data": list(bridge_service.snapshot())}


@APP.get("/api/latest/<dn>")
def latest_by_dn(dn: str) -> Any:
    entry = bridge_service.get_dn(dn)
    if entry is None:
        return jsonify({"error": "not-found"}), 404
    return entry


def _format_sse(event: str, data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    lines = payload.splitlines() or [""]
    msg_lines = [f"event: {event}"] + [f"data: {line}" for line in lines]
    return "\n".join(msg_lines) + "\n\n"


@APP.get("/stream")
def stream() -> Response:
    def generate():
        yield _format_sse("snapshot", {"data": list(bridge_service.snapshot())})
        listener = bridge_service.register_listener()
        try:
            while bridge_service._running.is_set():
                try:
                    item = listener.get(timeout=1.0)
                except queue.Empty:
                    continue
                yield _format_sse("update", item)
        finally:
            bridge_service.unregister_listener(listener)

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@SOCKETIO.on("connect")
def handle_socket_connect():
    emit("snapshot", {"data": list(bridge_service.snapshot())})


def install_signals():
    def _stop(signum, frame):
        print(f"[bridge] stopping (signal {signum})")
        bridge_service.stop()

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)


def main() -> None:
    print(
        "[bridge] starting with broker="
        f"{bridge_config.mqtt_host}:{bridge_config.mqtt_port} topic={bridge_config.mqtt_topic}"
    )
    install_signals()
    bridge_service.start()
    try:
        SOCKETIO.run(APP, host="0.0.0.0", port=bridge_config.http_port, allow_unsafe_werkzeug=True)
    finally:
        bridge_service.stop()


if __name__ == "__main__":
    main()

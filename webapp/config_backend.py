import json
import os
import threading
import time
import uuid
from collections import deque
from datetime import datetime
from typing import Deque, Dict, List

import paho.mqtt.client as mqtt


class ConfigValidationError(ValueError):
    pass


def build_payload(analog, select, model):
    payload_obj = {"analog": analog, "select": select, "model": model}
    payload_str = json.dumps(payload_obj, separators=(",", ":")) + "\n"
    return payload_obj, payload_str


class ConfigService:
    def __init__(
        self,
        *,
        broker_host: str,
        broker_port: int,
        cmd_topic: str,
        agent_topic_base: str,
        result_topic_base: str,
        client_id: str | None = None,
        username: str | None = None,
        password: str | None = None,
        device_ttl: int = 300,
        max_results: int = 50,
    ) -> None:
        self._broker_host = broker_host
        self._broker_port = broker_port
        self._cmd_topic = cmd_topic.rstrip("/")
        self._agent_topic = agent_topic_base.rstrip("/") + "/#"
        self._result_topic = result_topic_base.rstrip("/") + "/#"
        self._device_ttl = device_ttl
        self._devices: Dict[str, dict] = {}
        self._agents: Dict[str, dict] = {}
        self._lock = threading.RLock()
        self._results: Deque[dict] = deque(maxlen=max_results)
        self._client = mqtt.Client(client_id=client_id or f"web-config-{uuid.uuid4().hex[:8]}")
        if username:
            self._client.username_pw_set(username, password or None)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._connected = threading.Event()
        self._client.connect(self._broker_host, self._broker_port, keepalive=30)
        self._client.loop_start()

    # MQTT callbacks --------------------------------------------------
    def _on_connect(self, client: mqtt.Client, userdata, flags, rc):
        if rc != 0:
            print(f"[config-web] MQTT connect failed rc={rc}")
            return
        client.subscribe(self._agent_topic, qos=1)
        client.subscribe(self._result_topic, qos=1)
        self._connected.set()
        print(f"[config-web] subscribed {self._agent_topic} & {self._result_topic}")

    def _on_message(self, client: mqtt.Client, userdata, message: mqtt.MQTTMessage):
        topic = message.topic
        payload = self._decode_json(message.payload)
        if mqtt.topic_matches_sub(self._agent_topic, topic):
            self._handle_agent_snapshot(topic, payload)
        elif mqtt.topic_matches_sub(self._result_topic, topic):
            self._handle_command_result(topic, payload)

    @staticmethod
    def _decode_json(raw: bytes | None):
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _handle_agent_snapshot(self, topic: str, payload: dict) -> None:
        agent_id = payload.get("agent_id") or topic.split("/")[-1]
        devices = payload.get("devices") or []
        ts = payload.get("timestamp") or time.time()
        with self._lock:
            self._agents[agent_id] = {"timestamp": ts, "topic": topic}
            now = time.time()
            for item in devices:
                dn = item.get("dn")
                if not dn:
                    continue
                self._devices[dn] = {
                    "dn": dn,
                    "ip": item.get("ip"),
                    "agent_id": agent_id,
                    "last_seen": item.get("last_seen") or ts,
                    "agent_topic": topic,
                    "agent_timestamp": ts,
                }
            # 清理过期 DN
            expired = [dn for dn, info in self._devices.items() if now - self._to_epoch(info.get("last_seen")) > self._device_ttl]
            for dn in expired:
                self._devices.pop(dn, None)

    def _handle_command_result(self, topic: str, payload: dict) -> None:
        payload = payload or {}
        payload.setdefault("topic", topic)
        with self._lock:
            self._results.appendleft(payload)

    @staticmethod
    def _to_epoch(value) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        try:
            dt = datetime.fromisoformat(value)
            return dt.timestamp()
        except Exception:
            return 0.0

    # Public API ------------------------------------------------------
    def list_devices(self) -> List[dict]:
        now = time.time()
        with self._lock:
            active = []
            for dn, info in list(self._devices.items()):
                if now - self._to_epoch(info.get("last_seen")) > self._device_ttl:
                    self._devices.pop(dn, None)
                    continue
                active.append(info)
            return sorted(active, key=lambda item: item["dn"])

    def list_results(self) -> List[dict]:
        with self._lock:
            return list(self._results)

    def publish_command(
        self,
        dn: str,
        analog,
        select,
        model,
        requested_by: str | None = None,
        target_ip: str | None = None,
    ) -> dict:
        self._connected.wait(timeout=10)
        payload_obj, _ = build_payload(analog, select, model)
        command_id = str(uuid.uuid4())
        target_dn = (dn or "").replace(" ", "").replace("-", "").upper()
        body = {
            "command_id": command_id,
            "target_dn": target_dn,
            "payload": payload_obj,
        }
        if requested_by:
            body["requested_by"] = requested_by
        if target_ip:
            body["target_ip"] = target_ip
        result = self._client.publish(self._cmd_topic, payload=json.dumps(body, ensure_ascii=False), qos=1)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT 发布失败: {mqtt.error_string(result.rc)}")
        return {"command_id": command_id, "dn": target_dn, "payload": payload_obj, "target_ip": target_ip}

    def stop(self) -> None:
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass


def build_config_service_from_env() -> ConfigService:
    broker_host = os.getenv("CONFIG_BROKER_HOST", os.getenv("BROKER_HOST", "mosquitto"))
    broker_port = int(os.getenv("CONFIG_BROKER_PORT", os.getenv("BROKER_PORT", "1883")))
    cmd_topic = os.getenv("CONFIG_CMD_TOPIC", "etx/v1/config/cmd")
    agent_topic = os.getenv("CONFIG_AGENT_TOPIC", "etx/v1/config/agents")
    result_topic = os.getenv("CONFIG_RESULT_TOPIC", "etx/v1/config/result")
    ttl = int(os.getenv("CONFIG_DEVICE_TTL", "300"))
    username = os.getenv("CONFIG_BROKER_USERNAME")
    password = os.getenv("CONFIG_BROKER_PASSWORD")
    client_id = os.getenv("CONFIG_CLIENT_ID")
    return ConfigService(
        broker_host=broker_host,
        broker_port=broker_port,
        cmd_topic=cmd_topic,
        agent_topic_base=agent_topic,
        result_topic_base=result_topic,
        client_id=client_id,
        username=username,
        password=password,
        device_ttl=ttl,
    )


__all__ = [
    "ConfigService",
    "ConfigValidationError",
    "build_payload",
    "build_config_service_from_env",
]

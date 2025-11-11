from __future__ import annotations

import json
import logging
from threading import Event, Thread
from typing import Any, Dict, Tuple

import paho.mqtt.client as mqtt

from .config import Settings
from .device_registry import DeviceRegistry

logger = logging.getLogger(__name__)


class ConsoleMQTTService:
    def __init__(self, settings: Settings, registry: DeviceRegistry) -> None:
        self._settings = settings
        self._registry = registry
        self._client = mqtt.Client(client_id=settings.client_id, clean_session=True)
        if settings.broker_username:
            self._client.username_pw_set(settings.broker_username, settings.broker_password)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect
        self._loop_thread: Thread | None = None
        self._stop_event = Event()

    def start(self) -> None:
        if self._loop_thread and self._loop_thread.is_alive():
            return
        logger.info("Connecting to MQTT broker %s:%s", self._settings.broker_host, self._settings.broker_port)
        self._client.connect(self._settings.broker_host, self._settings.broker_port)
        self._stop_event.clear()
        self._loop_thread = Thread(target=self._client.loop_forever, name="mqtt-loop", daemon=True)
        self._loop_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        try:
            self._client.disconnect()
        except Exception:  # pragma: no cover - best effort
            logger.exception("Failed to disconnect MQTT client")
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=5)

    def publish_config(self, dn: str, payload_str: str) -> str:
        topic = self._settings.config_topic_template.format(dn=dn)
        logger.info("Publishing config to %s", topic)
        result = self._client.publish(topic, payload=payload_str, qos=1, retain=self._settings.retain_messages)
        result.wait_for_publish()
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT 发布失败：{mqtt.error_string(result.rc)}")
        self._registry.update(dn, metadata={"last_config_topic": topic})
        return topic

    # MQTT callbacks
    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Dict[str, Any], rc: int) -> None:
        if rc != 0:
            logger.error("MQTT 连接失败：%s", mqtt.error_string(rc))
            return
        logger.info("MQTT connected, subscribing %s", self._settings.sensor_topic_filter)
        client.subscribe(self._settings.sensor_topic_filter)

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, rc: int) -> None:
        if rc != 0:
            logger.warning("MQTT 异常断开：%s", mqtt.error_string(rc))

    def _on_message(self, client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
        try:
            payload = message.payload.decode("utf-8", errors="replace")
        except Exception:
            payload = ""
        dn, ip = self._extract_dn_ip(message.topic, payload)
        if not dn:
            return
        meta = {"last_topic": message.topic}
        if payload:
            meta["last_payload"] = payload[:256]
        self._registry.update(dn, ip=ip, topic=message.topic, metadata=meta)

    @staticmethod
    def _extract_dn_ip(topic: str, raw_payload: str) -> Tuple[str | None, str | None]:
        dn = None
        ip = None
        try:
            payload_obj = json.loads(raw_payload)
        except json.JSONDecodeError:
            payload_obj = {}
        if isinstance(payload_obj, dict):
            dn = payload_obj.get("dn") or payload_obj.get("device") or payload_obj.get("device_id")
            ip = payload_obj.get("ip") or payload_obj.get("device_ip") or payload_obj.get("source_ip")
        if not dn:
            parts = [part for part in topic.split("/") if part]
            if len(parts) >= 2:
                dn = parts[-2]
        return dn, ip


__all__ = ["ConsoleMQTTService"]

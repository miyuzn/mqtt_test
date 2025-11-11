from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import List


@dataclass(frozen=True)
class Settings:
    broker_host: str
    broker_port: int
    broker_username: str | None
    broker_password: str | None
    client_id: str
    sensor_topic_filter: str
    config_topic_template: str
    retain_messages: bool
    device_ttl_seconds: int
    history_path: Path
    state_dir: Path
    allowed_origins: List[str]
    http_port: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    state_dir = Path(os.getenv("CONSOLE_STATE_DIR", "./broker_console/state")).resolve()
    history_path_env = os.getenv("CONSOLE_HISTORY_PATH")
    history_path = Path(history_path_env).resolve() if history_path_env else state_dir / "config-history.json"
    state_dir.mkdir(parents=True, exist_ok=True)
    history_path.parent.mkdir(parents=True, exist_ok=True)

    allowed_origins = [origin.strip() for origin in os.getenv("CONSOLE_ALLOWED_ORIGINS", "*").split(",") if origin.strip()]

    return Settings(
        broker_host=os.getenv("BROKER_HOST", "127.0.0.1"),
        broker_port=int(os.getenv("BROKER_PORT", "1883")),
        broker_username=os.getenv("BROKER_USERNAME"),
        broker_password=os.getenv("BROKER_PASSWORD"),
        client_id=os.getenv("CONSOLE_CLIENT_ID", "esp32-config-console"),
        sensor_topic_filter=os.getenv("SENSOR_TOPIC_FILTER", "etx/v1/parsed/#"),
        config_topic_template=os.getenv("CONFIG_TOPIC_TEMPLATE", "esp32/config/{dn}"),
        retain_messages=os.getenv("CONFIG_RETAIN", "true").lower() == "true",
        device_ttl_seconds=int(os.getenv("DEVICE_TTL_SECONDS", "300")),
        history_path=history_path,
        state_dir=state_dir,
        allowed_origins=allowed_origins or ["*"],
        http_port=int(os.getenv("CONSOLE_PORT", "5080")),
    )

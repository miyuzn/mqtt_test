#!/usr/bin/env python3
"""
devmin/data_receive_local.py
----------------------------

在宿主机快速运行 data_receive.py 的轻量入口：
- 默认加载 devmin/config/data_receive.dev.ini；
- 自动把 MQTT 主机/端口指向本地 parser 容器暴露的 127.0.0.1:1883；
- 允许通过环境变量覆盖（例如 MQTT_BROKER_HOST、MQTT_BROKER_PORT）。

使用方式：
    python devmin/data_receive_local.py
"""
#
# Note: data_receive.py now includes broadcast discovery + direct TCP send; this runner reuses it.

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


def _set_default_env(key: str, value: str) -> None:
    if not os.getenv(key):
        os.environ[key] = value


def main() -> None:
    devmin_dir = Path(__file__).resolve().parent
    repo_root = devmin_dir.parent
    entry = repo_root / "data_receive.py"
    if not entry.exists():
        raise SystemExit(f"[devmin] 未找到 {entry}")

    config_path = devmin_dir / "config" / "data_receive.dev.ini"
    _set_default_env("CONFIG_PATH", str(config_path))

    root_str = str(repo_root)
    app_str = str(repo_root / "app")
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    if app_str not in sys.path:
        sys.path.insert(0, app_str)

    mqtt_host = os.getenv("MQTT_BROKER_HOST") or os.getenv("BROKER_HOST") or "127.0.0.1"
    mqtt_port = os.getenv("MQTT_BROKER_PORT") or os.getenv("BROKER_PORT") or "1883"

    _set_default_env("MQTT_BROKER_HOST", mqtt_host)
    _set_default_env("BROKER_HOST", mqtt_host)
    _set_default_env("MQTT_BROKER_PORT", str(mqtt_port))
    _set_default_env("BROKER_PORT", str(mqtt_port))
    _set_default_env("CONFIG_DISCOVER_BROADCASTS", os.getenv("CONFIG_DISCOVER_BROADCASTS", ""))
    _set_default_env("CONFIG_DISCOVER_ATTEMPTS", os.getenv("CONFIG_DISCOVER_ATTEMPTS", "2"))
    _set_default_env("CONFIG_DISCOVER_GAP", os.getenv("CONFIG_DISCOVER_GAP", "0.15"))
    _set_default_env("CONFIG_DISCOVER_TIMEOUT", os.getenv("CONFIG_DISCOVER_TIMEOUT", "5"))
    _set_default_env("CONFIG_DISCOVER_PORT", os.getenv("CONFIG_DISCOVER_PORT", "22346"))
    _set_default_env("CONFIG_DISCOVER_MAGIC", os.getenv("CONFIG_DISCOVER_MAGIC", "GCU_DISCOVER"))

    print(
        "[devmin] 启动 data_receive.py，MQTT="
        f"{os.environ['MQTT_BROKER_HOST']}:{os.environ['MQTT_BROKER_PORT']}, "
        f"CONFIG_PATH={os.environ['CONFIG_PATH']}"
    )
    runpy.run_path(str(entry), run_name="__main__")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[devmin] 收到 Ctrl+C，采集终止。")
        sys.exit(0)

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

from __future__ import annotations

import os
import configparser
import socket
import runpy
import sys
import threading
import time
from pathlib import Path


def _set_default_env(key: str, value: str) -> None:
    if not os.getenv(key):
        os.environ[key] = value

def _load_startup(config_path: Path) -> tuple[float, int]:
    cfg = configparser.ConfigParser()
    cfg.read(config_path, encoding="utf-8")
    try:
        countdown = float(cfg.get("STARTUP", "FORWARD_COUNTDOWN_SEC", fallback="0").strip() or 0)
    except Exception:
        countdown = 0.0
    try:
        udp_port = int(cfg.get("UDP", "LISTEN_PORT", fallback="13250").strip() or 13250)
    except Exception:
        udp_port = 13250
    return max(countdown, 0.0), udp_port

def _drain_udp(stop_evt: threading.Event, port: int) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("", port))
    except Exception as exc:
        print(f"[devmin][COUNTDOWN] UDP drain bind failed on :{port}: {exc}")
        return
    sock.settimeout(0.5)
    buf = bytearray(8192)
    view = memoryview(buf)
    while not stop_evt.is_set():
        try:
            sock.recvfrom_into(view, len(buf))
        except socket.timeout:
            continue
        except Exception:
            break
    sock.close()


def main() -> None:
    devmin_dir = Path(__file__).resolve().parent
    repo_root = devmin_dir.parent
    entry = repo_root / "data_receive.py"
    if not entry.exists():
        raise SystemExit(f"[devmin] 未找到 {entry}")

    config_path = devmin_dir / "config" / "data_receive.dev.ini"
    _set_default_env("CONFIG_PATH", str(config_path))
    countdown_sec, udp_port = _load_startup(config_path)

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

    print(
        "[devmin] 启动 data_receive.py，MQTT="
        f"{os.environ['MQTT_BROKER_HOST']}:{os.environ['MQTT_BROKER_PORT']}, "
        f"CONFIG_PATH={os.environ['CONFIG_PATH']}"
    )

    if countdown_sec > 0:
        banner = "=" * 64
        print(banner)
        print(f"[devmin][COUNTDOWN] {countdown_sec:.1f}s 后开始转发，倒计时期间的 UDP 数据将被直接丢弃")
        print(banner)
        stop_evt = threading.Event()
        t = threading.Thread(target=_drain_udp, args=(stop_evt, udp_port), daemon=True)
        t.start()
        whole = int(countdown_sec)
        frac = countdown_sec - whole
        for i in range(whole, 0, -1):
            print(f"[devmin][COUNTDOWN] {i}s ...", flush=True)
            time.sleep(1)
        if frac > 0:
            time.sleep(frac)
        stop_evt.set()
        t.join(timeout=1.0)
        print("[devmin][COUNTDOWN] 倒计时结束，开始正式转发")

    runpy.run_path(str(entry), run_name="__main__")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[devmin] 收到 Ctrl+C，采集终止。")
        sys.exit(0)

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
import sys
import configparser
import queue
import runpy
import threading
import time
from pathlib import Path


def _set_default_env(key: str, value: str) -> None:
    if not os.getenv(key):
        os.environ[key] = value

def _load_startup(config_path: Path) -> float:
    cfg = configparser.ConfigParser()
    cfg.read(config_path, encoding="utf-8")
    try:
        countdown = float(cfg.get("STARTUP", "FORWARD_COUNTDOWN_SEC", fallback="0").strip() or 0)
    except Exception:
        countdown = 0.0
    return max(countdown, 0.0)

def _install_gate(dr: dict, gate: threading.Event) -> threading.Event:
    """Replace data_receive.q with a gated queue that drops during countdown."""
    pkt_drop_key = "pkt_drop"
    dq_mod = dr.get("queue") or queue
    maxsize = dr.get("Q_MAXSIZE", 0) or 0

    def _inc_drop() -> None:
        try:
            dr[pkt_drop_key] = dr.get(pkt_drop_key, 0) + 1
        except Exception:
            pass

    class GateQueue(dq_mod.Queue):
        def __init__(self, maxsize: int = 0) -> None:
            super().__init__(maxsize=maxsize)
        def put(self, item, block=True, timeout=None):  # type: ignore[override]
            if not gate.is_set():
                _inc_drop()
                return
            return super().put(item, block=block, timeout=timeout)
        def put_nowait(self, item):  # type: ignore[override]
            return self.put(item, block=False)

    gated_q = GateQueue(maxsize=maxsize)
    dr["q"] = gated_q
    return gate

def _wrap_udp_ready(dr: dict, ready_evt: threading.Event) -> None:
    """Signal readiness once UDP socket成功绑定。"""
    orig_make = dr.get("make_udp_sock")
    if not callable(orig_make):
        return
    def _make_udp_sock():
        sock = orig_make()
        ready_evt.set()
        return sock
    dr["make_udp_sock"] = _make_udp_sock


def main() -> None:
    devmin_dir = Path(__file__).resolve().parent
    repo_root = devmin_dir.parent
    entry = repo_root / "data_receive.py"
    if not entry.exists():
        raise SystemExit(f"[devmin] 未找到 {entry}")

    config_path = devmin_dir / "config" / "data_receive.dev.ini"
    _set_default_env("CONFIG_PATH", str(config_path))
    countdown_sec = _load_startup(config_path)

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
    # 载入 data_receive.py 但不立即触发 __main__ 分支，便于植入闸门
    dr = runpy.run_path(str(entry), run_name="data_receive_bootstrap")
    forward_gate = threading.Event()
    ready_evt = threading.Event()
    _install_gate(dr, forward_gate)
    _wrap_udp_ready(dr, ready_evt)

    def _countdown():
        ready_evt.wait()
        if countdown_sec <= 0:
            forward_gate.set()
            return
        banner = "=" * 64
        print(banner)
        print(f"[devmin][COUNTDOWN] {countdown_sec:.1f}s 后开始转发，倒计时期间接收到的 UDP 数据将直接丢弃")
        print(banner)
        whole = int(countdown_sec)
        frac = countdown_sec - whole
        for i in range(whole, 0, -1):
            print(f"[devmin][COUNTDOWN] {i}s ...", flush=True)
            time.sleep(1)
        if frac > 0:
            time.sleep(frac)
        forward_gate.set()
        print("[devmin][COUNTDOWN] 倒计时结束，开始正式转发")

    threading.Thread(target=_countdown, daemon=True).start()
    dr["main"]()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[devmin] 收到 Ctrl+C，采集终止。")
        sys.exit(0)

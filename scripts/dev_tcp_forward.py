"""
Simple TCP forwarder for local dev.

Why this exists:
- Some Windows + Docker Desktop setups can publish container ports on localhost fine,
  but behave strangely on privileged ports (e.g. :443) for IPv4/LAN access.
- This script forwards TCP :443 -> :8443 (or any other target) without needing admin.

Usage (PowerShell):
  py scripts\\dev_tcp_forward.py --listen-host 163.143.136.106 --listen-port 443 --target-host 127.0.0.1 --target-port 8443
"""

from __future__ import annotations

import argparse
import socket
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ForwardConfig:
    listen_host: str
    listen_port: int
    target_host: str
    target_port: int
    backlog: int = 128
    bufsize: int = 64 * 1024


def _relay(src: socket.socket, dst: socket.socket, bufsize: int) -> None:
    try:
        while True:
            chunk = src.recv(bufsize)
            if not chunk:
                break
            dst.sendall(chunk)
    except Exception:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except Exception:
            pass


def _handle_client(client: socket.socket, client_addr: tuple[str, int], cfg: ForwardConfig) -> None:
    target: socket.socket | None = None
    try:
        target = socket.create_connection((cfg.target_host, cfg.target_port), timeout=5)
        client.settimeout(None)
        target.settimeout(None)
        t1 = threading.Thread(target=_relay, args=(client, target, cfg.bufsize), daemon=True)
        t2 = threading.Thread(target=_relay, args=(target, client, cfg.bufsize), daemon=True)
        t1.start()
        t2.start()
        while t1.is_alive() or t2.is_alive():
            time.sleep(0.05)
    except Exception as exc:
        print(f"[forward] {client_addr[0]}:{client_addr[1]} -> connect failed: {exc}")
    finally:
        for s in (client, target):
            if s is None:
                continue
            try:
                s.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                s.close()
            except Exception:
                pass


def run(cfg: ForwardConfig) -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((cfg.listen_host, cfg.listen_port))
    server.listen(cfg.backlog)
    print(f"[forward] listening on {cfg.listen_host}:{cfg.listen_port} -> {cfg.target_host}:{cfg.target_port}")

    try:
        while True:
            client, addr = server.accept()
            threading.Thread(target=_handle_client, args=(client, addr, cfg), daemon=True).start()
    except KeyboardInterrupt:
        print("[forward] stopping...")
    finally:
        try:
            server.close()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Simple TCP forwarder (dev only).")
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=443)
    parser.add_argument("--target-host", default="127.0.0.1")
    parser.add_argument("--target-port", type=int, default=8443)
    args = parser.parse_args()
    cfg = ForwardConfig(
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        target_host=args.target_host,
        target_port=args.target_port,
    )
    run(cfg)


if __name__ == "__main__":
    main()


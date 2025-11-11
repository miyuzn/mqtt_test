#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import socket
import sys

MAX_ANALOG = 11
MAX_SELECT = 13
MAX_SENSORS = 11 * 13
VAL_MIN, VAL_MAX = 0, 255
MAX_BYTES = 512  # 含换行

def validate_pins(name, pins, max_len):
    if not isinstance(pins, list) or len(pins) == 0 or len(pins) > max_len:
        raise ValueError(f"{name} 数量必须在 1..{max_len} 之间")
    if any((not isinstance(x, int)) for x in pins):
        raise ValueError(f"{name} 只能是整数")
    if any(x < VAL_MIN or x > VAL_MAX for x in pins):
        raise ValueError(f"{name} 每个值需在 {VAL_MIN}..{VAL_MAX}")
    if len(set(pins)) != len(pins):
        raise ValueError(f"{name} 含有重复值")

def build_payload(analog, select):
    # 校验
    validate_pins("analog", analog, MAX_ANALOG)
    validate_pins("select", select, MAX_SELECT)
    if len(analog) * len(select) > MAX_SENSORS:
        raise ValueError("行列乘积超过 144（11×13）")

    payload_obj = {"analog": analog, "select": select}
    # 生成行终止 JSON（必须以 \n 结束）
    s = json.dumps(payload_obj, separators=(",", ":")) + "\n"

    # 长度限制（约 512 字节，这里严格按 512）
    if len(s.encode("utf-8")) > MAX_BYTES:
        raise ValueError("JSON 总长度超过 512 字节")
    return s

def send_config(host, port, analog, select, timeout):
    data = build_payload(analog, select)
    # 发送
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(data.encode("utf-8"))
        # 读取应答（简单起见，读到换行或超时/连接关闭）
        sock.settimeout(timeout)
        chunks = []
        while True:
            try:
                b = sock.recv(1024)
            except socket.timeout:
                break
            if not b:
                break
            chunks.append(b)
            if b.endswith(b"\n"):
                break
    reply = b"".join(chunks).decode("utf-8", errors="replace").strip()
    # 尝试解析 JSON
    try:
        obj = json.loads(reply) if reply else {}
    except Exception:
        obj = {"raw": reply}
    return obj or {"status": "no-reply"}

def main():
    p = argparse.ArgumentParser(description="Send matrix GPIO config over TCP 22345.")
    p.add_argument("host", help="设备 IP（例如 192.168.1.2）")
    p.add_argument("--port", type=int, default=22345, help="端口（默认 22345）")
    p.add_argument("--analog", type=int, nargs="+", required=True, help="analog 数组，如 --analog 1 2 3")
    p.add_argument("--select", type=int, nargs="+", required=True, help="select 数组，如 --select 17 18 19")
    p.add_argument("--timeout", type=float, default=3.0, help="超时时间秒（默认 3s）")
    args = p.parse_args()

    try:
        resp = send_config(args.host, args.po_

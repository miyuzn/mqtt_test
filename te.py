#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import socket
import sys

MAX_ANALOG = 11
MAX_SELECT = 13
MAX_SENSORS = 11 * 13
VAL_MIN, VAL_MAX = 0, 255
MAX_BYTES = 512  # 含换行

# ======== 静态配置部分（用于调试） ========
HOST = "192.168.137.4"     # 设备 IP
PORT = 22345             # 端口
TIMEOUT = 3.0            # 超时秒
ANALOG = [7,6,5,4,3,2,1]       # 模拟引脚
SELECT = [42,41,40,39,37]    # 选择引脚
# ========================================

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
    validate_pins("analog", analog, MAX_ANALOG)
    validate_pins("select", select, MAX_SELECT)
    if len(analog) * len(select) > MAX_SENSORS:
        raise ValueError("行列乘积超过 144（11×13）")

    payload_obj = {"analog": analog, "select": select}
    s = json.dumps(payload_obj, separators=(",", ":")) + "\n"

    if len(s.encode("utf-8")) > MAX_BYTES:
        raise ValueError("JSON 总长度超过 512 字节")
    return s

def send_config(host, port, analog, select, timeout):
    data = build_payload(analog, select)
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(data.encode("utf-8"))
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
    try:
        obj = json.loads(reply) if reply else {}
    except Exception:
        obj = {"raw": reply}
    return obj or {"status": "no-reply"}

def main():
    try:
        resp = send_config(HOST, PORT, ANALOG, SELECT, TIMEOUT)
    except Exception as e:
        print(f"发送失败：{e}", file=sys.stderr)
        sys.exit(2)
    print(json.dumps(resp, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

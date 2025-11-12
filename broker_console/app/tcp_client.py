from __future__ import annotations

import json
import socket
from typing import Any, Dict


def send_payload(host: str, port: int, payload: str, timeout: float) -> Dict[str, Any]:
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(payload.encode("utf-8"))
        sock.settimeout(timeout)
        chunks: list[bytes] = []
        while True:
            try:
                data = sock.recv(1024)
            except socket.timeout:
                break
            if not data:
                break
            chunks.append(data)
            if data.endswith(b"\n"):
                break
    reply = b"".join(chunks).decode("utf-8", errors="replace").strip()
    if not reply:
        return {"status": "no-reply"}
    try:
        parsed = json.loads(reply)
        if isinstance(parsed, dict):
            return parsed
        return {"data": parsed}
    except json.JSONDecodeError:
        return {"raw": reply}


__all__ = ["send_payload"]

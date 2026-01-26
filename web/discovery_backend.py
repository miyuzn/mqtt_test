import json
import os
import socket
import time
import ipaddress
from typing import Iterable, List, Tuple

DEFAULT_PORT = int(os.getenv("CONFIG_DEVICE_TCP_PORT", os.getenv("LICENSE_TCP_PORT", "22345")))
DISCOVER_PORT = int(os.getenv("CONFIG_DISCOVER_PORT", "22346"))
DISCOVER_MAGIC = os.getenv("CONFIG_DISCOVER_MAGIC", "GCU_DISCOVER")
DEFAULT_TIMEOUT = float(os.getenv("CONFIG_DISCOVER_TIMEOUT", "10"))


def _safe_ip(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except Exception:
        return None


def collect_broadcast_addrs(extra: Iterable[str] | None = None) -> List[str]:
    """
    Return a de-duplicated broadcast address list.
    Prefers interface broadcast/netmask info when psutil is available,
    falls back to 255.255.255.255.
    """
    addrs: List[str] = []
    if extra:
        for raw in extra:
            ip = _safe_ip(str(raw).strip())
            if ip:
                addrs.append(ip)

    try:
        import psutil  # type: ignore

        for iface_addrs in psutil.net_if_addrs().values():
            for snic in iface_addrs:
                if snic.family != socket.AF_INET:
                    continue
                if snic.broadcast:
                    ip = _safe_ip(snic.broadcast)
                    if ip:
                        addrs.append(ip)
                        continue
                if snic.netmask and snic.address:
                    try:
                        iface = ipaddress.ip_interface(f"{snic.address}/{snic.netmask}")
                        addrs.append(str(iface.network.broadcast_address))
                    except Exception:
                        continue
    except Exception:
        # psutil might be unavailable; ignore and use defaults.
        pass

    addrs.append("255.255.255.255")

    seen = set()
    unique = []
    for addr in addrs:
        if not addr or addr in seen or addr == "0.0.0.0":
            continue
        seen.add(addr)
        unique.append(addr)
    return unique


def discover_devices(
    *,
    broadcast_addrs: Iterable[str] | None = None,
    attempts: int = 2,
    gap: float = 0.15,
    timeout: float = DEFAULT_TIMEOUT,
) -> Tuple[List[dict], List[str]]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)
    sock.bind(("", 0))

    targets = collect_broadcast_addrs(broadcast_addrs)
    deadline = time.time() + max(timeout, 0.1)
    try:
        for _ in range(max(1, attempts)):
            for addr in targets:
                try:
                    sock.sendto(DISCOVER_MAGIC.encode("ascii", "ignore"), (addr, DISCOVER_PORT))
                except OSError:
                    continue
            if gap > 0:
                time.sleep(gap)

        results: List[dict] = []
        seen = set()
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                sock.settimeout(remaining)
                data, addr = sock.recvfrom(1024)
            except socket.timeout:
                break
            except OSError:
                break
            if not data:
                continue
            try:
                obj = json.loads(data.decode(errors="ignore"))
                obj["from"] = addr[0]
                sig = (obj.get("ip"), obj.get("mac"), obj.get("model"), obj.get("port"))
                if sig in seen:
                    continue
                seen.add(sig)
                results.append(obj)
            except Exception:
                continue
        return results, targets
    finally:
        sock.close()


def send_device_payload(host: str, payload: dict, *, port: int | None = None, timeout: float | None = None) -> dict:
    data = json.dumps(payload, ensure_ascii=False) + "\n"
    addr = (host, int(port or DEFAULT_PORT))
    chunks: List[bytes] = []
    with socket.create_connection(addr, timeout=timeout or DEFAULT_TIMEOUT) as sock:
        sock.sendall(data.encode("utf-8"))
        sock.settimeout(timeout or DEFAULT_TIMEOUT)
        while True:
            try:
                buf = sock.recv(4096)
            except socket.timeout:
                break
            if not buf:
                break
            chunks.append(buf)
            if buf.endswith(b"\n"):
                break
    raw_reply = b"".join(chunks).decode("utf-8", errors="replace").strip()
    parsed = None
    if raw_reply:
        try:
            parsed = json.loads(raw_reply)
        except Exception:
            parsed = None
    return {"raw": raw_reply, "json": parsed, "host": host, "port": addr[1]}


__all__ = [
    "collect_broadcast_addrs",
    "discover_devices",
    "send_device_payload",
    "DEFAULT_PORT",
    "DISCOVER_PORT",
    "DISCOVER_MAGIC",
    "DEFAULT_TIMEOUT",
]

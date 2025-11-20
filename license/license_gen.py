import argparse
import base64
import json
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_private_key

TYPE_CODES = {
    "basic": 0x01,
    "advanced": 0x02,
    "pro": 0x03,
}

DEFAULT_HISTORY = Path("licenses_history.json")


def normalize_mac(device_code: str) -> bytes:
    dev = device_code.replace(":", "").upper()
    if len(dev) != 12 or any(c not in "0123456789ABCDEF" for c in dev):
        raise ValueError("device_code must be 12 hex chars (no colons)")
    return bytes.fromhex(dev)


def compute_expiry(days: int) -> int:
    if days <= 0:
        raise ValueError("days must be positive")
    dt = datetime.now(timezone.utc) + timedelta(days=days)
    dt = dt.replace(hour=23, minute=59, second=59, microsecond=0)
    return int(dt.timestamp())


def parse_tier(tier_name: str) -> int:
    key = tier_name.strip().lower()
    if key not in TYPE_CODES:
        raise ValueError(f"tier must be one of: {', '.join(TYPE_CODES.keys())}")
    return TYPE_CODES[key]


def load_history(path: Path) -> list:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_history(path: Path, entries: list):
    path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def make_token(device_code: str, days: int, private_key_path: str, tier_name: str) -> (str, int):
    mac_bytes = normalize_mac(device_code)
    exp_ts = compute_expiry(days)
    tier_code = parse_tier(tier_name)
    payload = bytes([2, tier_code]) + exp_ts.to_bytes(4, "big") + mac_bytes

    pem = Path(private_key_path).read_bytes()
    private_key = load_pem_private_key(pem, password=None)
    signature = private_key.sign(payload, ec.ECDSA(hashes.SHA256()))
    sig_len = len(signature)
    if sig_len > 255:
        raise ValueError("Signature too long")
    token_bytes = payload + bytes([sig_len]) + signature
    token = base64.b32encode(token_bytes).decode().replace("=", "")
    return token, exp_ts


def send_via_tcp(ip: str, port: int, token: str, timeout: float = 5.0):
    payload = f"{{\"license\":\"{token}\"}}\n".encode()
    with socket.create_connection((ip, port), timeout=timeout) as s:
        s.sendall(payload)
        s.settimeout(timeout)
        try:
            resp = s.recv(256)
        except socket.timeout:
            resp = b""
    return resp.decode(errors="ignore")


def query_device(ip: str, port: int, timeout: float = 5.0):
    payload = "{\"license\":\"?\"}\n".encode()
    with socket.create_connection((ip, port), timeout=timeout) as s:
        s.sendall(payload)
        s.settimeout(timeout)
        try:
            resp = s.recv(1024)
        except socket.timeout:
            resp = b""
    return resp.decode(errors="ignore")


def pretty_print_query(resp: str):
    try:
        data = json.loads(resp)
    except Exception:
        print(resp or "<no response>")
        return
    device_mac = data.get("device_mac", "unknown")
    licenses = data.get("licenses", [])
    print(f"Device MAC: {device_mac}")
    if not licenses:
        print("No licenses stored")
        return
    for idx, lic in enumerate(licenses, 1):
        tier = lic.get("tier", "unknown")
        expiry = lic.get("expiry", 0)
        expiry_iso = datetime.fromtimestamp(expiry, tz=timezone.utc).isoformat() if expiry else "n/a"
        mac = lic.get("mac", "")
        valid = lic.get("valid", False)
        token = lic.get("token", "")
        print(f"{idx}. tier={tier} valid={valid} mac={mac} expiry={expiry_iso}")
        print(f"   token={token}")


def choose_from_history(history: list, index: int | None):
    if not history:
        print("No history available")
        return None
    if index is not None:
        if index < 1 or index > len(history):
            print("Index out of range")
            return None
        return history[index - 1]
    for idx, item in enumerate(history, 1):
        print(f"{idx}. {item['token']} | tier={item['tier']} | days={item['days']} | mac={item['device_code']} | expiry={item['expiry_iso']}")
    sel = input("Select entry number (or empty to cancel): ").strip()
    if not sel:
        return None
    try:
        idx = int(sel)
    except ValueError:
        return None
    if idx < 1 or idx > len(history):
        return None
    return history[idx - 1]


def interactive_menu():
    print("1) Generate only")
    print("2) Push existing from history")
    print("3) Generate and push")
    print("4) Query device (license list + mac)")
    choice = input("Select [1/2/3/4]: ").strip() or "1"
    return choice


def main():
    parser = argparse.ArgumentParser(description="Generate ECDSA license token (Base32) with history and optional TCP push")
    parser.add_argument("device_code", nargs="?", help="12-hex device code, colons ok")
    parser.add_argument("days", nargs="?", type=int, help="License duration in days")
    parser.add_argument("key", nargs="?", help="Path to ECDSA P-256 private key (PEM, no password)")
    parser.add_argument("--type", "-t", dest="tier", default=None, help="License tier: basic/advanced/pro")
    parser.add_argument("--push", metavar="IP", help="Optional: push token to target IP over TCP (port 22345)")
    parser.add_argument("--port", type=int, default=22345, help="TCP port for push (default 22345)")
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY, help="History file (default licenses_history.json)")
    parser.add_argument("--yes", action="store_true", help="Skip interactive prompts; no auto-push unless --push is set")
    parser.add_argument("--select", action="store_true", help="Select from history to push (non-interactive requires --push)")
    parser.add_argument("--index", type=int, help="History index to use with --select (1-based)")
    parser.add_argument("--query", metavar="IP", help="Query device licenses/mac (sends {license:\"?\"})")
    args = parser.parse_args()

    history = load_history(args.history)

    if args.query:
        try:
            resp = query_device(args.query, args.port)
            pretty_print_query(resp)
        except Exception as e:
            print(f"Query failed to {args.query}:{args.port}: {e}")
        return

    if args.select:
        entry = choose_from_history(history, args.index)
        if not entry:
            return
        token = entry["token"]
        if args.push:
            try:
                resp = send_via_tcp(args.push, args.port, token)
                print(f"Pushed to {args.push}:{args.port}, response: {resp or '<no response>'}")
            except Exception as e:
                print(f"Push failed to {args.push}:{args.port}: {e}")
        else:
            print(token)
        return

    choice = "1" if args.yes else interactive_menu()

    # Handle choices
    if choice in ("1", "3"):
        device_code = args.device_code or input("Device code (12-hex, colons ok): ").strip()
        days_str = str(args.days) if args.days is not None else input("License duration (days): ").strip()
        key_path = args.key or input("Private key path (PEM, no password, default priv.pem): ").strip() or "priv.pem"
        tier = args.tier or input("License type [basic/advanced/pro] (default basic): ").strip() or "basic"

        if not days_str.isdigit() or int(days_str) <= 0:
            raise SystemExit("days must be a positive integer")
        days = int(days_str)

        token, exp_ts = make_token(device_code, days, key_path, tier)
        expiry_iso = datetime.fromtimestamp(exp_ts, tz=timezone.utc).isoformat()
        print(token)
        print(f"expires_at_utc={expiry_iso}")

        history.append({
            "token": token,
            "device_code": device_code,
            "days": days,
            "tier": tier,
            "expiry": exp_ts,
            "expiry_iso": expiry_iso,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        })
        save_history(args.history, history)

    elif choice == "2":
        entry = choose_from_history(history, args.index)
        if not entry:
            return
        token = entry["token"]
        tier = entry.get("tier")
        expiry_iso = entry.get("expiry_iso")
        print(f"Using token tier={tier} expiry={expiry_iso}: {token}")

    elif choice == "4":
        target_ip = args.query or input("Target IP for query: ").strip()
        port_raw = input(f"Target port (default {args.port}): ").strip()
        port = int(port_raw) if port_raw else args.port
        try:
            resp = query_device(target_ip, port)
            pretty_print_query(resp)
        except Exception as e:
            print(f"Query failed to {target_ip}:{port}: {e}")
        return

    else:
        return

    # Push when applicable
    if choice in ("3", "2"):
        target_ip = args.push or input("Target IP: ").strip()
        port_raw = input(f"Target port (default {args.port}): ").strip()
        port = int(port_raw) if port_raw else args.port
        try:
            resp = send_via_tcp(target_ip, port, token)
            print(f"Pushed to {target_ip}:{port}, response: {resp or '<no response>'}")
        except Exception as e:
            print(f"Push failed to {target_ip}:{port}: {e}")


if __name__ == "__main__":
    main()

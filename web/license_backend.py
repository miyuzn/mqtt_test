import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class LicenseError(RuntimeError):
    pass


def _candidate_paths() -> list[Path]:
    env_dir = os.getenv("LICENSE_MODULE_DIR")
    paths = [
        Path(__file__).resolve().parent.parent / "license",
        Path(__file__).resolve().parent / "license",
        Path("/license"),
        Path("/workspace/license"),
    ]
    if env_dir:
        paths.insert(0, Path(env_dir))
    return paths


def _ensure_license_module_path() -> None:
    for path in _candidate_paths():
        if path.exists():
            parts = [path, path.parent] if path.name == "license" else [path]
            for p in parts:
                if str(p) not in sys.path:
                    sys.path.append(str(p))


def _import_license_gen():
    _ensure_license_module_path()
    for name in ("license_gen", "license.license_gen"):
        try:
            return __import__(name, fromlist=["*"])
        except ModuleNotFoundError:
            continue
    for base in _candidate_paths():
        file_path = base / "license_gen.py"
        if not file_path.exists():
            continue
        spec = importlib.util.spec_from_file_location("license_license_gen", file_path)
        if not spec or not spec.loader:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore
        return module
    return None


license_gen = _import_license_gen()
if license_gen:
    load_history = license_gen.load_history
    make_token = license_gen.make_token
    query_device = license_gen.query_device
    save_history = license_gen.save_history
    send_via_tcp = license_gen.send_via_tcp
else:
    def _missing(*_, **__):
        raise LicenseError("license_gen not found; 请检查 LICENSE_MODULE_DIR 或容器卷挂载 /license")
    load_history = lambda *_args, **_kwargs: []  # type: ignore
    save_history = lambda *_args, **_kwargs: None  # type: ignore
    make_token = _missing  # type: ignore
    query_device = _missing  # type: ignore
    send_via_tcp = _missing  # type: ignore


@dataclass
class LicenseConfig:
    key_path: Path
    history_path: Optional[Path]
    default_port: int = 22345
    timeout: float = 5.0
    tier_default: str = "basic"


class LicenseService:
    def __init__(self, config: LicenseConfig) -> None:
        self._config = config

    def _ensure_key(self) -> None:
        if not self._config.key_path.exists():
            raise LicenseError(f"license key not found: {self._config.key_path}")
        if not license_gen:
            raise LicenseError("license_gen not available; 检查 /license 挂载")

    def generate_token(self, device_code: str, days: int, tier: str) -> Dict[str, Any]:
        self._ensure_key()
        token, exp_ts = make_token(device_code, days, str(self._config.key_path), tier)
        expiry_iso = datetime.fromtimestamp(exp_ts, tz=timezone.utc).isoformat()
        entry = {
            "token": token,
            "device_code": device_code,
            "tier": tier,
            "days": days,
            "expiry": exp_ts,
            "expiry_iso": expiry_iso,
        }
        if self._config.history_path:
            try:
                history = load_history(self._config.history_path)
                history.append(entry)
                save_history(self._config.history_path, history[-200:])
            except Exception:
                pass
        return entry

    def push_token(self, ip: str, token: str, port: Optional[int] = None) -> Dict[str, Any]:
        target_port = port or self._config.default_port
        resp = send_via_tcp(ip, target_port, token, timeout=self._config.timeout)
        return {
            "ip": ip,
            "port": target_port,
            "response": resp,
        }

    def query_device(self, ip: str, port: Optional[int] = None) -> Dict[str, Any]:
        target_port = port or self._config.default_port
        raw = query_device(ip, target_port, timeout=self._config.timeout)
        parsed: Any = None
        try:
            parsed = json.loads(raw) if raw else None
        except Exception:
            parsed = None
        return {
            "ip": ip,
            "port": target_port,
            "raw": raw,
            "parsed": parsed,
            "licenses": (parsed or {}).get("licenses") if isinstance(parsed, dict) else None,
        }


__all__ = ["LicenseService", "LicenseConfig", "LicenseError"]

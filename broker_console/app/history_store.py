from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List


@dataclass
class ConfigRecord:
    dn: str
    payload: Dict[str, Any]
    topic: str
    issued_at: str

    @classmethod
    def from_payload(cls, dn: str, payload: Dict[str, Any], topic: str) -> "ConfigRecord":
        return cls(dn=dn, payload=payload, topic=topic, issued_at=datetime.now(timezone.utc).isoformat())


class ConfigHistoryStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = RLock()
        if not self._path.exists():
            self._path.write_text("[]", encoding="utf-8")

    def append(self, record: ConfigRecord) -> None:
        with self._lock:
            data = self._read_all_locked()
            data.append(asdict(record))
            self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def latest_for(self, dn: str) -> Dict[str, Any] | None:
        with self._lock:
            data = self._read_all_locked()
            for entry in reversed(data):
                if entry.get("dn") == dn:
                    return entry
            return None

    def all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return self._read_all_locked()

    def _read_all_locked(self) -> List[Dict[str, Any]]:
        raw = self._path.read_text(encoding="utf-8")
        try:
            data = json.loads(raw) if raw else []
        except json.JSONDecodeError:
            data = []
        if not isinstance(data, list):
            return []
        return data


__all__ = ["ConfigHistoryStore", "ConfigRecord"]

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any, Dict, List


@dataclass
class DeviceRecord:
    dn: str
    ip: str | None = None
    topic: str | None = None
    last_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_response(self) -> Dict[str, Any]:
        data = asdict(self)
        data["last_seen"] = self.last_seen.isoformat()
        return data


class DeviceRegistry:
    def __init__(self, ttl_seconds: int = 300) -> None:
        self._devices: Dict[str, DeviceRecord] = {}
        self._lock = RLock()
        self._ttl = timedelta(seconds=ttl_seconds)

    def update(self, dn: str, *, ip: str | None = None, topic: str | None = None, metadata: Dict[str, Any] | None = None) -> DeviceRecord:
        now = datetime.now(timezone.utc)
        with self._lock:
            record = self._devices.get(dn)
            if record is None:
                record = DeviceRecord(dn=dn)
                self._devices[dn] = record
            record.last_seen = now
            if ip:
                record.ip = ip
            if topic:
                record.topic = topic
            if metadata:
                record.metadata.update(metadata)
            return record

    def list_active(self) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._purge_locked(now)
            return [record.as_response() for record in self._devices.values()]

    def get(self, dn: str) -> DeviceRecord | None:
        with self._lock:
            record = self._devices.get(dn)
            if not record:
                return None
            if datetime.now(timezone.utc) - record.last_seen > self._ttl:
                return None
            return record

    def _purge_locked(self, ref_time: datetime) -> None:
        expired = [dn for dn, record in self._devices.items() if ref_time - record.last_seen > self._ttl]
        for dn in expired:
            del self._devices[dn]


__all__ = ["DeviceRegistry", "DeviceRecord"]

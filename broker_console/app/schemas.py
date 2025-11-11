from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ConfigRequest(BaseModel):
    dn: str = Field(..., description="目标设备 DN")
    ip: Optional[str] = Field(None, description="设备 IP（可选）")
    analog: List[int] = Field(..., min_length=1, description="analog 列表")
    select: List[int] = Field(..., min_length=1, description="select 列表")


class ConfigResponse(BaseModel):
    status: str
    topic: str
    payload: dict


class DeviceItem(BaseModel):
    dn: str
    ip: Optional[str] = None
    topic: Optional[str] = None
    last_seen: str
    metadata: dict = Field(default_factory=dict)


class DeviceListResponse(BaseModel):
    items: List[DeviceItem]


class ConfigHistoryResponse(BaseModel):
    dn: str
    payload: dict
    topic: str
    issued_at: str


__all__ = [
    "ConfigRequest",
    "ConfigResponse",
    "DeviceItem",
    "DeviceListResponse",
    "ConfigHistoryResponse",
]

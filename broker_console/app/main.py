from __future__ import annotations

import logging
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .device_registry import DeviceRegistry
from .history_store import ConfigHistoryStore, ConfigRecord
from .mqtt_service import ConsoleMQTTService
from .schemas import (
    ConfigHistoryResponse,
    ConfigRequest,
    ConfigResponse,
    DeviceListResponse,
)
from .validators import ConfigValidationError, build_payload

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()
registry = DeviceRegistry(ttl_seconds=settings.device_ttl_seconds)
history_store = ConfigHistoryStore(settings.history_path)
mqtt_service = ConsoleMQTTService(settings, registry)

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
STATIC_DIR = FRONTEND_DIR / "static"
INDEX_FILE = FRONTEND_DIR / "index.html"

app = FastAPI(title="ESP32 配置控制台", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
async def _startup() -> None:
    logger.info("配置控制台启动，静态目录：%s", FRONTEND_DIR)
    mqtt_service.start()


@app.on_event("shutdown")
async def _shutdown() -> None:
    mqtt_service.stop()


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    if not INDEX_FILE.exists():
        return JSONResponse({"status": "frontend-missing"}, status_code=404)
    return FileResponse(INDEX_FILE)


@app.get("/healthz", include_in_schema=False)
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/devices", response_model=DeviceListResponse)
async def list_devices() -> DeviceListResponse:
    items = registry.list_active()
    return DeviceListResponse(items=items)


@app.get("/api/config/latest/{dn}", response_model=Optional[ConfigHistoryResponse])
async def get_latest_config(dn: str):
    record = history_store.latest_for(dn)
    if not record:
        raise HTTPException(status_code=404, detail="未找到记录")
    return ConfigHistoryResponse(**record)


@app.post("/api/config/apply", response_model=ConfigResponse)
async def apply_config(request: ConfigRequest) -> ConfigResponse:
    dn = request.dn.strip()
    if not dn:
        raise HTTPException(status_code=422, detail="dn 不可为空")
    try:
        payload_obj, payload_str = build_payload(
            analog=request.analog,
            select=request.select,
        )
    except ConfigValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if request.ip:
        registry.update(dn, ip=request.ip)

    try:
        topic = mqtt_service.publish_config(dn, payload_str)
    except Exception as exc:  # pragma: no cover
        logger.exception("配置下发失败")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    history_store.append(ConfigRecord.from_payload(dn, payload_obj, topic))
    return ConfigResponse(status="ok", topic=topic, payload=payload_obj)


__all__ = ["app"]

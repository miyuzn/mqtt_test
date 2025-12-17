import json
import os
import sys
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import requests
from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    render_template,
    request,
    stream_with_context,
)

from config_backend import ConfigValidationError, build_config_service_from_env
from discovery_backend import (
    DEFAULT_PORT as CONFIG_DEVICE_TCP_PORT,
    DEFAULT_TIMEOUT as DISCOVER_DEFAULT_TIMEOUT,
    collect_broadcast_addrs,
    discover_devices as discover_lan_devices,
    send_device_payload,
)
from license_backend import LicenseConfig, LicenseError, LicenseService

"""
Tiny Flask app that proxies data from the MQTT bridge to the browser UI.
轻量级 Flask 应用，用于将 MQTT 桥服务安全地代理到浏览器界面。
"""


BRIDGE_API_BASE_URL = os.getenv("BRIDGE_API_BASE_URL", "http://localhost:5001")
BRIDGE_TIMEOUT_CONNECT = float(os.getenv("BRIDGE_CONNECT_TIMEOUT", "5"))
BRIDGE_TIMEOUT_READ = os.getenv("BRIDGE_READ_TIMEOUT")  # 允许为空
if BRIDGE_TIMEOUT_READ is not None:
    try:
        BRIDGE_TIMEOUT_READ = float(BRIDGE_TIMEOUT_READ)
    except ValueError:
        BRIDGE_TIMEOUT_READ = None  # 非法值视为 None（不设读超时）

CONFIG_CONSOLE_PORT = int(os.getenv("CONFIG_CONSOLE_PORT", "5002"))
CONFIG_CONSOLE_ENABLED = os.getenv("CONFIG_CONSOLE_ENABLED", "1") != "0"

LICENSE_ENABLED = os.getenv("LICENSE_ENABLED", "1") != "0"
_LICENSE_DIR_FALLBACK = Path(__file__).resolve().parent.parent / "license"
LICENSE_KEY_PATH = Path(os.getenv("LICENSE_KEY_PATH", _LICENSE_DIR_FALLBACK / "priv.pem"))
LICENSE_HISTORY_PATH_RAW = os.getenv("LICENSE_HISTORY_PATH", str(_LICENSE_DIR_FALLBACK / "licenses_history.json"))
LICENSE_TCP_PORT = int(os.getenv("LICENSE_TCP_PORT", os.getenv("CONFIG_DEVICE_TCP_PORT", "22345")))
LICENSE_TCP_TIMEOUT = float(os.getenv("LICENSE_TCP_TIMEOUT", "5"))
LICENSE_DEFAULT_DAYS = int(os.getenv("LICENSE_DEFAULT_DAYS", "365"))
LICENSE_DEFAULT_TIER = os.getenv("LICENSE_DEFAULT_TIER", "basic")
DISCOVER_DEFAULT_ATTEMPTS = int(os.getenv("CONFIG_DISCOVER_ATTEMPTS", "2"))
DISCOVER_DEFAULT_GAP = float(os.getenv("CONFIG_DISCOVER_GAP", "0.2"))

app = Flask(__name__)
config_app = Flask("config_console", template_folder="templates", static_folder="static")

if CONFIG_CONSOLE_ENABLED:
    try:
        config_service = build_config_service_from_env()
    except Exception as exc:  # pragma: no cover - 初始化容错
        print(f"[config-web] failed to start MQTT service: {exc}", file=sys.stderr)
        config_service = None
else:
    config_service = None

_license_history_path = Path(LICENSE_HISTORY_PATH_RAW) if LICENSE_HISTORY_PATH_RAW else None

if LICENSE_ENABLED:
    try:
        license_config = LicenseConfig(
            key_path=LICENSE_KEY_PATH,
            history_path=_license_history_path,
            default_port=LICENSE_TCP_PORT,
            timeout=LICENSE_TCP_TIMEOUT,
            tier_default=LICENSE_DEFAULT_TIER or "basic",
        )
        license_service = LicenseService(license_config)
    except Exception as exc:  # pragma: no cover - 初始化容错
        print(f"[config-web] failed to start license service: {exc}", file=sys.stderr)
        license_service = None
else:
    license_service = None


_direct_results = deque(maxlen=50)


def _bridge_url(path: str) -> str:
    # Build absolute path lazily so deployments can override the base URL.
    # 延迟构建绝对路径，便于不同环境覆写基础地址。
    return f"{BRIDGE_API_BASE_URL.rstrip('/')}{path}"


def _require_config_service():
    if config_service is None:
        abort(503, description="config service unavailable")
    return config_service


def _require_license_service():
    if license_service is None:
        abort(503, description="license service unavailable")
    return license_service


def _resolve_ip_from_dn(dn: str) -> str | None:
    if not dn or config_service is None:
        return None
    device = config_service.get_device(dn.strip())
    if not device:
        return None
    return device.get("ip")


def _parse_pins(value):
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        tokens = [item.strip() for item in value.replace("\n", ",").split(",")]
        return [int(token) for token in tokens if token]
    raise ValueError("pin list must be array or comma separated string")


def _normalize_dn(value: str | None) -> str:
    if not value:
        return ""
    return value.replace(":", "").replace("-", "").strip().upper()


def _parse_broadcast_inputs(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        parts = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, (list, tuple, set)):
        parts = [str(item).strip() for item in raw]
    else:
        parts = [str(raw).strip()]
    return [item for item in parts if item]


def _resolve_ip_from_discovery(dn: str | None, target_ip: str | None, devices: list[dict]) -> str | None:
    if target_ip:
        return target_ip
    dn_key = _normalize_dn(dn or "")
    if dn_key:
        for item in devices:
            mac = _normalize_dn(item.get("dn") or item.get("mac") or item.get("device_code"))
            if mac and mac == dn_key:
                return item.get("ip") or item.get("from")
    if len(devices) == 1:
        return devices[0].get("ip") or devices[0].get("from")
    return None


def _extract_direct_payload(data: dict):
    payload_section = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    if payload_section:
        return payload_section
    analog_raw = data.get("analog") if data.get("analog") is not None else payload_section.get("analog")
    select_raw = data.get("select") if data.get("select") is not None else payload_section.get("select")
    try:
        analog = _parse_pins(analog_raw)
        select = _parse_pins(select_raw)
    except Exception as exc:
        raise ConfigValidationError(str(exc))
    if analog is None and select is None:
        return None
    return {
        "analog": analog or [],
        "select": select or [],
        "model": data.get("model") or payload_section.get("model"),
    }


def _merge_results() -> list[dict]:
    items: list[dict] = list(_direct_results)
    if config_service:
        items.extend(config_service.list_results())
    items.sort(key=lambda item: item.get("timestamp") or "", reverse=True)
    return items[:50]


@app.route("/")
def index() -> str:
    return render_template(
        "index.html",
        bridge_api_base=BRIDGE_API_BASE_URL,
    )


@app.route("/api/latest")
def proxy_latest() -> Response:
    # Proxy the latest cache endpoint without altering payload format.
    # 透明转发最新缓存接口，保持数据格式完全一致。
    try:
        resp = requests.get(
            _bridge_url("/api/latest"),
            timeout=(BRIDGE_TIMEOUT_CONNECT, BRIDGE_TIMEOUT_READ or 10),
        )
        resp.raise_for_status()
    except requests.RequestException as exc:  # pragma: no cover
        return jsonify({"error": "bridge_unavailable", "detail": str(exc)}), 502
    return jsonify(resp.json())


@app.route("/stream")
def proxy_stream() -> Response:
    def generate() -> Iterator[bytes]:
        # Keep an upstream SSE request open and relay bytes verbatim.
        # 持续保持与上游的 SSE 请求，并逐字节透传。
        headers = {
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
        try:
            with requests.get(
                _bridge_url("/stream"),
                headers=headers,
                stream=True,
                timeout=(BRIDGE_TIMEOUT_CONNECT, None),  # 关键：不设读超时
            ) as upstream:
                upstream.raise_for_status()

                # Trigger EventSource to enter the open state immediately.
                # 让浏览器端 EventSource 立即进入 open 状态。
                yield b": proxy connected\n\n"

                # Pass through upstream chunks directly without re-encoding.
                # 不重新编码，直接透传上游返回的原始 chunk。
                for chunk in upstream.iter_content(chunk_size=2048):
                    if not chunk:
                        continue
                    # Never append extra newlines; keep the byte stream 1:1.
                    # 禁止追加换行，保持字节流完全一致。
                    yield chunk

        except requests.RequestException as exc:  # pragma: no cover
            payload = json.dumps({"error": "bridge_unavailable", "detail": str(exc)})
            # Emit a standards-compliant SSE error event for the browser.
            # 使用标准 SSE 语法通知浏览器发生错误。
            yield f"event: error\ndata: {payload}\n\n".encode("utf-8")

    # Wrap generator output with SSE-friendly headers to avoid buffering.
    # 使用生成器输出并添加 SSE 友好的响应头，避免代理缓冲。
    response = Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
    )
    response.headers["Content-Type"] = "text/event-stream; charset=utf-8"
    response.headers["Cache-Control"] = "no-cache, no-transform"
    response.headers["X-Accel-Buffering"] = "no"  # Nginx 关闭代理缓冲
    response.headers["Connection"] = "keep-alive"
    return response


@app.route("/healthz")
def healthz() -> Response:
    return jsonify({
        "status": "ok",
        "bridge": BRIDGE_API_BASE_URL,
        "config_console": "ready" if config_service else "disabled",
    })


@config_app.route("/")
def config_index() -> str:
    return render_template(
        "config_console.html",
        config_enabled=config_service is not None,
        license_enabled=license_service is not None,
        license_default_days=LICENSE_DEFAULT_DAYS,
        license_default_tier=LICENSE_DEFAULT_TIER,
        license_port=LICENSE_TCP_PORT,
    )


@config_app.route("/api/devices")
def config_devices() -> Response:
    svc = _require_config_service()
    return jsonify({"items": svc.list_devices()})


@config_app.route("/api/discover", methods=["POST"])
def config_discover() -> Response:
    svc = _require_config_service()
    payload = request.get_json(silent=True) or {}
    attempts = payload.get("attempts")
    gap = payload.get("gap")
    timeout = payload.get("timeout")
    broadcast = _parse_broadcast_inputs(payload.get("broadcast") or payload.get("broadcast_addrs"))
    try:
        result = svc.publish_discover(
            attempts=int(attempts) if attempts is not None else None,
            gap=float(gap) if gap is not None else None,
            timeout=float(timeout) if timeout is not None else None,
            broadcast=broadcast or None,
            requested_by=payload.get("requested_by"),
        )
    except RuntimeError as exc:
        return jsonify({"error": "mqtt_publish_failed", "detail": str(exc)}), 502
    return jsonify({
        "status": "queued",
        **result,
        "attempts": attempts,
        "gap": gap,
        "timeout": timeout,
        "broadcast": broadcast or [],
    })


@config_app.route("/api/commands/latest")
def config_results() -> Response:
    items = _merge_results()
    return jsonify({"items": items})


@config_app.route("/api/config/control", methods=["POST"])
def config_control() -> Response:
    svc = _require_config_service()
    data = request.get_json(silent=True) or {}
    dn = (data.get("dn") or data.get("target_dn") or data.get("device_dn") or data.get("mac") or "").strip()
    if not dn:
        return jsonify({"error": "dn_required"}), 400
    payload_obj = data.get("payload")
    if not isinstance(payload_obj, dict):
        return jsonify({"error": "payload_required"}), 400
    target_ip = (data.get("target_ip") or data.get("ip") or payload_obj.get("target_ip") or "").strip() or None
    try:
        result = svc.publish_custom(
            dn,
            payload_obj,
            requested_by=data.get("requested_by"),
            target_ip=target_ip,
        )
    except RuntimeError as exc:
        return jsonify({"error": "mqtt_publish_failed", "detail": str(exc)}), 502
    return jsonify({"status": "queued", **result})


@config_app.route("/api/config/apply", methods=["POST"])
def config_apply() -> Response:
    svc = _require_config_service()
    data = request.get_json(silent=True) or {}
    dn = (data.get("dn") or data.get("target_dn") or "").strip()
    if not dn:
        return jsonify({"error": "dn_required"}), 400
    payload_section = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    try:
        analog = _parse_pins(data.get("analog") if data.get("analog") is not None else payload_section.get("analog"))
        select = _parse_pins(data.get("select") if data.get("select") is not None else payload_section.get("select"))
    except Exception as exc:
        return jsonify({"error": "invalid_pins", "detail": str(exc)}), 400
    if analog is None or select is None:
        return jsonify({"error": "pins_required"}), 400
    target_ip = (data.get("target_ip") or data.get("ip") or payload_section.get("target_ip") or "").strip() or None
    model = data.get("model") or payload_section.get("model")
    try:
        result = svc.publish_command(
            dn,
            analog,
            select,
            model=model,
            requested_by=data.get("requested_by"),
            target_ip=target_ip,
        )
    except ConfigValidationError as exc:
        return jsonify({"error": "validation_failed", "detail": str(exc)}), 422
    except RuntimeError as exc:
        return jsonify({"error": "mqtt_publish_failed", "detail": str(exc)}), 502
    return jsonify({"status": "queued", **result})


@config_app.route("/api/config/direct", methods=["POST"])
def config_apply_direct() -> Response:
    data = request.get_json(silent=True) or {}
    dn_raw = data.get("dn") or data.get("target_dn") or data.get("device_dn") or data.get("mac")
    dn = _normalize_dn(dn_raw or "")
    target_ip = (data.get("target_ip") or data.get("ip") or "").strip()
    try:
        port = int(data.get("port") or CONFIG_DEVICE_TCP_PORT)
    except Exception:
        return jsonify({"error": "port_invalid"}), 400

    try:
        payload_obj = _extract_direct_payload(data)
    except ConfigValidationError as exc:
        return jsonify({"error": "invalid_payload", "detail": str(exc)}), 400
    if payload_obj is None:
        return jsonify({"error": "payload_required"}), 400

    attempts = int(data.get("attempts") or DISCOVER_DEFAULT_ATTEMPTS)
    gap = float(data.get("gap") or DISCOVER_DEFAULT_GAP)
    timeout = float(data.get("timeout") or DISCOVER_DEFAULT_TIMEOUT)
    broadcast = _parse_broadcast_inputs(data.get("broadcast") or data.get("broadcast_addrs"))

    devices, broadcast_targets = discover_lan_devices(
        broadcast_addrs=broadcast or collect_broadcast_addrs(),
        attempts=max(1, attempts),
        gap=max(0.0, gap),
        timeout=max(0.1, timeout),
    )
    resolved_ip = _resolve_ip_from_discovery(dn, target_ip, devices)
    if not resolved_ip:
        return jsonify({
            "error": "ip_unresolved",
            "detail": "未能通过广播匹配到目标 IP，请手动填写或检查设备响应。",
            "discoveries": devices,
            "broadcast": broadcast_targets,
        }), 400

    status = "ok"
    reply = {}
    try:
        send_result = send_device_payload(resolved_ip, payload_obj, port=port, timeout=timeout)
        reply = send_result.get("json") if isinstance(send_result.get("json"), dict) else {}
        if not reply:
            raw = send_result.get("raw")
            if raw:
                reply = {"raw": raw}
        reply.setdefault("status", "ok")
    except Exception as exc:
        status = "error"
        reply = {"status": "error", "error": str(exc)}

    entry = {
        "command_id": data.get("command_id") or str(uuid.uuid4()),
        "dn": dn or None,
        "status": status,
        "ip": resolved_ip,
        "port": port,
        "payload": payload_obj,
        "reply": reply,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "method": "direct",
        "broadcast": broadcast_targets,
    }
    _direct_results.appendleft(entry)
    return jsonify({**entry, "discoveries": devices}), (200 if status == "ok" else 502)


@config_app.route("/api/license/apply", methods=["POST"])
def config_license_apply() -> Response:
    cfg_svc = _require_config_service()
    lic_svc = _require_license_service()
    data = request.get_json(silent=True) or {}
    dn = (data.get("dn") or data.get("target_dn") or data.get("device_dn") or "").strip().upper()
    device_code = (data.get("device_code") or data.get("mac") or dn).replace(":", "").strip()
    if not device_code:
        return jsonify({"error": "device_code_required"}), 400
    try:
        days_val = int(data.get("days") or data.get("duration_days") or data.get("duration") or LICENSE_DEFAULT_DAYS)
    except Exception:
        return jsonify({"error": "days_invalid"}), 400
    if days_val <= 0:
        return jsonify({"error": "days_invalid"}), 400
    tier = (data.get("tier") or LICENSE_DEFAULT_TIER).strip().lower() or LICENSE_DEFAULT_TIER
    port_raw = data.get("port")
    try:
        port_val = int(port_raw) if port_raw is not None else LICENSE_TCP_PORT
    except Exception:
        return jsonify({"error": "port_invalid"}), 400
    try:
        token_entry = lic_svc.generate_token(device_code, days_val, tier)
    except LicenseError as exc:
        return jsonify({"error": "license_unavailable", "detail": str(exc)}), 503
    except Exception as exc:
        return jsonify({"error": "license_generate_failed", "detail": str(exc)}), 400
    target_ip = (data.get("target_ip") or data.get("ip") or "").strip()
    if not target_ip and dn:
        target_ip = _resolve_ip_from_dn(dn)
    try:
        result = cfg_svc.publish_license(
            dn=dn or device_code,
            token=token_entry["token"],
            requested_by=data.get("requested_by"),
            target_ip=target_ip,
            port=port_val,
            query=False,
        )
    except RuntimeError as exc:
        return jsonify({"error": "mqtt_publish_failed", "detail": str(exc)}), 502
    result.update({
        "status": "queued",
        "dn": dn or device_code,
        "target_ip": target_ip or None,
        "port": port_val,
        **token_entry,
    })
    return jsonify(result)


@config_app.route("/api/license/query")
def config_license_query() -> Response:
    cfg_svc = _require_config_service()
    dn = (request.args.get("dn") or request.args.get("target_dn") or request.args.get("device_dn") or "").strip().upper()
    target_ip = (request.args.get("target_ip") or request.args.get("ip") or "").strip()
    port_raw = request.args.get("port")
    try:
        port_val = int(port_raw) if port_raw else LICENSE_TCP_PORT
    except Exception:
        return jsonify({"error": "port_invalid"}), 400
    if not target_ip and dn:
        target_ip = _resolve_ip_from_dn(dn)
    if not target_ip and not dn:
        return jsonify({"error": "ip_required"}), 400
    try:
        result = cfg_svc.publish_license(
            dn=dn or target_ip,
            token="?",
            requested_by=None,
            target_ip=target_ip or None,
            port=port_val,
            query=True,
        )
    except RuntimeError as exc:
        return jsonify({"error": "mqtt_publish_failed", "detail": str(exc)}), 502
    result.update({
        "status": "queued",
        "dn": dn or None,
        "target_ip": target_ip or None,
        "port": port_val,
    })
    return jsonify(result)


def _run_config_console():
    config_app.run(host="0.0.0.0", port=CONFIG_CONSOLE_PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    # Run in threaded mode locally so SSE streaming is not blocked.
    # 本地启动时启用多线程，防止单线程阻塞 SSE。
    if CONFIG_CONSOLE_ENABLED:
        threading.Thread(target=_run_config_console, name="config-console", daemon=True).start()

    web_port = int(os.getenv("WEB_PORT", "5000"))
    ssl_enabled = os.getenv("WEB_SSL_ENABLED", "0") not in ("0", "", "false", "False", "FALSE")
    ssl_cert = os.getenv("WEB_SSL_CERT")
    ssl_key = os.getenv("WEB_SSL_KEY")
    ssl_context = None
    if ssl_enabled:
        if ssl_cert and ssl_key:
            ssl_context = (ssl_cert, ssl_key)
        else:
            print("[web] WEB_SSL_ENABLED is set but WEB_SSL_CERT/WEB_SSL_KEY missing; falling back to HTTP.")

    app.run(host="0.0.0.0", port=web_port, threaded=True, use_reloader=False, ssl_context=ssl_context)

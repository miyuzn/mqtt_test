import json
import os
import sys
import threading
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


@config_app.route("/api/commands/latest")
def config_results() -> Response:
    svc = _require_config_service()
    return jsonify({"items": svc.list_results()})


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
    app.run(host="0.0.0.0", port=5000, threaded=True, use_reloader=False)

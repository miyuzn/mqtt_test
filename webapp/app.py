import json
import os
import sys
import threading
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


def _bridge_url(path: str) -> str:
    # Build absolute path lazily so deployments can override the base URL.
    # 延迟构建绝对路径，便于不同环境覆写基础地址。
    return f"{BRIDGE_API_BASE_URL.rstrip('/')}{path}"


def _require_config_service():
    if config_service is None:
        abort(503, description="config service unavailable")
    return config_service


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
    return render_template("config_console.html", config_enabled=config_service is not None)


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
    try:
        result = svc.publish_command(
            dn,
            analog,
            select,
            requested_by=data.get("requested_by"),
            target_ip=target_ip,
        )
    except ConfigValidationError as exc:
        return jsonify({"error": "validation_failed", "detail": str(exc)}), 422
    except RuntimeError as exc:
        return jsonify({"error": "mqtt_publish_failed", "detail": str(exc)}), 502
    return jsonify({"status": "queued", **result})


def _run_config_console():
    config_app.run(host="0.0.0.0", port=CONFIG_CONSOLE_PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    # Run in threaded mode locally so SSE streaming is not blocked.
    # 本地启动时启用多线程，防止单线程阻塞 SSE。
    if CONFIG_CONSOLE_ENABLED:
        threading.Thread(target=_run_config_console, name="config-console", daemon=True).start()
    app.run(host="0.0.0.0", port=5000, threaded=True, use_reloader=False)

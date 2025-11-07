import json
import os
from typing import Iterator

import requests
from flask import Flask, Response, jsonify, render_template, stream_with_context

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

app = Flask(__name__)


def _bridge_url(path: str) -> str:
    # Build absolute path lazily so deployments can override the base URL.
    # 延迟构建绝对路径，便于不同环境覆写基础地址。
    return f"{BRIDGE_API_BASE_URL.rstrip('/')}{path}"


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
    return jsonify({"status": "ok", "bridge": BRIDGE_API_BASE_URL})


if __name__ == "__main__":
    # Run in threaded mode locally so SSE streaming is not blocked.
    # 本地启动时启用多线程，防止单线程阻塞 SSE。
    app.run(host="0.0.0.0", port=5000, threaded=True, use_reloader=False)

import json
import os
from typing import Iterator

import requests
from flask import Flask, Response, jsonify, render_template, stream_with_context

BRIDGE_API_BASE_URL = os.getenv("BRIDGE_API_BASE_URL", "http://localhost:5001")
BRIDGE_TIMEOUT_CONNECT = float(os.getenv("BRIDGE_CONNECT_TIMEOUT", "5"))
BRIDGE_TIMEOUT_READ = os.getenv("BRIDGE_READ_TIMEOUT")  # 允许为空
if BRIDGE_TIMEOUT_READ is not None:
    try:
        BRIDGE_TIMEOUT_READ = float(BRIDGE_TIMEOUT_READ)
    except ValueError:
        BRIDGE_TIMEOUT_READ = None  # 非法值则视为 None（不设读超时）

app = Flask(__name__)


def _bridge_url(path: str) -> str:
    return f"{BRIDGE_API_BASE_URL.rstrip('/')}{path}"


@app.route("/")
def index() -> str:
    return render_template(
        "index.html",
        bridge_api_base=BRIDGE_API_BASE_URL,
    )


@app.route("/api/latest")
def proxy_latest() -> Response:
    try:
        resp = requests.get(
            _bridge_url("/api/latest"),
            timeout=(BRIDGE_TIMEOUT_CONNECT, BRIDGE_TIMEOUT_READ or 10),
        )
        resp.raise_for_status()
    except requests.RequestException as exc:  # pragma: no cover
        return jsonify({"error": "bridge_unavailable", "detail": str(exc)}), 502
    # 原样转成 JSON 返回
    return jsonify(resp.json())


@app.route("/stream")
def proxy_stream() -> Response:
    def generate() -> Iterator[bytes]:
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

                # 让浏览器端 EventSource 立即进入 open 状态
                yield b": proxy connected\n\n"

                # 原样透传字节；不要用 iter_lines / 不要重新编码
                for chunk in upstream.iter_content(chunk_size=2048):
                    if not chunk:
                        continue
                    # 禁止在这里追加换行！保持字节流 1:1 转发
                    yield chunk

        except requests.RequestException as exc:  # pragma: no cover
            payload = json.dumps({"error": "bridge_unavailable", "detail": str(exc)})
            # 用标准 SSE 语法发错误事件
            yield f"event: error\ndata: {payload}\n\n".encode("utf-8")

    # 用生成器构造流式响应；显式声明 SSE + 反缓冲的头
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
    # 显式启用多线程，避免开发服务器单线程阻塞 SSE
    app.run(host="0.0.0.0", port=5000, threaded=True, use_reloader=False)

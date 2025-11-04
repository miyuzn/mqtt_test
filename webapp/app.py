import json
import os
from typing import Iterator

import requests
from flask import Flask, Response, jsonify, render_template, stream_with_context

BRIDGE_API_BASE_URL = os.getenv("BRIDGE_API_BASE_URL", "http://bridge:5001")
BRIDGE_TIMEOUT_CONNECT = float(os.getenv("BRIDGE_CONNECT_TIMEOUT", "5"))
BRIDGE_TIMEOUT_READ = float(os.getenv("BRIDGE_READ_TIMEOUT", "30"))

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
            timeout=(BRIDGE_TIMEOUT_CONNECT, BRIDGE_TIMEOUT_READ),
        )
        resp.raise_for_status()
    except requests.RequestException as exc:  # pragma: no cover - network errors
        return jsonify({"error": "bridge_unavailable", "detail": str(exc)}), 502
    return jsonify(resp.json())


@app.route("/stream")
def proxy_stream() -> Response:
    def generate() -> Iterator[str]:
        headers = {"Accept": "text/event-stream"}
        try:
            with requests.get(
                _bridge_url("/stream"),
                headers=headers,
                stream=True,
                timeout=(BRIDGE_TIMEOUT_CONNECT, BRIDGE_TIMEOUT_READ),
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines(decode_unicode=True):
                    if line is None:
                        continue
                    yield f"{line}\n"
        except requests.RequestException as exc:  # pragma: no cover - network errors
            payload = json.dumps(
                {"error": "bridge_unavailable", "detail": str(exc)}
            )
            yield f"event: error\ndata: {payload}\n\n"

    response = Response(stream_with_context(generate()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@app.route("/healthz")
def healthz() -> Response:
    return jsonify({"status": "ok", "bridge": BRIDGE_API_BASE_URL})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

# Repository Guidelines

## Always respond in Chinese-simplified

## Project Structure & Module Organization
- `app/`: MQTT clients and utilities (`sink.py`, `sensor2.py`, `publisher.py`), Dockerfile, `requirements.txt`, `config.ini`.
- `server/`: MQTT↔Web bridge (`bridge.py`).
- `webapp/`: Flask UI (`app.py`), `templates/`, `static/`, Dockerfile, `requirements.txt`.
- `mosquitto/config/`: Broker configuration (`mosquitto.conf`).
- Root: `docker-compose.yml`, `config.ini`, `data_receive.py`, `readme.md`.

## Build, Test, and Development Commands
- Run stack: `docker compose up -d` — starts broker, clients, bridge, and web UI.
- Rebuild images: `docker compose up -d --build`.
- Logs: `docker compose logs -f` (add `web`/`app`/`server` service name to filter).
- Stop: `docker compose down`.
- Local dev (Python): `python -m venv .venv && .venv\\Scripts\\activate && pip install -r app/requirements.txt` then `python app/sink.py` or `python data_receive.py`. For UI: `pip install -r webapp/requirements.txt` then `python webapp/app.py`.

## Coding Style & Naming Conventions
- Python: PEP 8, 4-space indent, `snake_case` for modules/functions/vars; `UPPER_CASE` for constants; descriptive module names (e.g., `mqtt_utils.py`).
- Config: prefer `config.ini` and `docker-compose.yml` env vars over hardcoded values.
- Keep functions small; isolate MQTT, I/O, and parsing in `app/` helpers.

## Testing Guidelines
- Framework: pytest (recommended). Place tests under `tests/` using `test_*.py` (e.g., `tests/test_bridge.py`).
- Run: `pytest -q` (from repo root).
- Target: prioritize message parsing, MQTT topic routing, and web handlers. Aim for meaningful coverage of critical paths.

## Commit & Pull Request Guidelines
- History uses short topic/date labels (e.g., `1104-bridge`). For new commits, prefer clear, imperative summaries: “Add sink CSV writer”, “Fix bridge reconnect logic”.
- Keep subject ≤ 72 chars; include context in body when needed.
- PRs: include purpose, linked issues, run instructions, and screenshots for UI changes. Ensure `docker compose up -d` works locally.

## Security & Configuration Tips
- Do not commit secrets. Broker creds and host/ports belong in `config.ini` or compose env vars.
- Avoid exposing Mosquitto to the public Internet without auth/TLS. Scope published ports to local dev.

## Debugging
- When developing the front-end, please connect to localhost:5001 for debugging.
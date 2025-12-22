# Gemini Agent Context & Project Guidelines

**Project Name:** MQTT Sensor System (ETX Protocol)
**Updated:** 2025-12

## 1. Project Overview
This is a full-stack IoT system designed to collect, parse, store, and visualize sensor data using MQTT.
**Core Data Flow:**
1.  **Sensors:** Publish raw binary/JSON data to `etx/v1/raw/#`.
2.  **Backend (`app/`):**
    - Subscribes to raw data.
    - Parses payloads (via `parser_service` or embedded logic).
    - Republishes parsed JSON to `etx/v1/parsed/#`.
    - Persists data to disk (`sink.py`).
3.  **Bridge (`server/`):** Proxies MQTT messages to HTTP/SSE for the frontend.
4.  **Web UI (`webapp/`):**
    - **Dashboard:** Visualizes real-time data via Server-Sent Events (SSE).
    - **Config Console:** Manages device settings (discovery, IP config) via `config_backend.py`.
    - **License:** Handles feature activation via `license_backend.py`.

## 2. Directory Structure & Key Components

### Root Level
- `docker-compose.secure.yml`: **Primary** deployment configuration (TLS enabled).
- `config.ini` / `config.secure.ini`: Base configuration files.
- `GEMINI.md`: This file.

### Modules
- **`app/` (Backend Core)**
    - `main_subscriber.py`: Entry point for data processing.
    - `sink.py`: Data storage worker.
    - `backend_entrypoint.sh`: Container startup script.
    - `utils.py`: Shared utilities.
- **`webapp/` (Frontend & API)**
    - `app.py`: Main Flask application (Gateway).
    - `config_backend.py`: MQTT service for device management (Discovery, Commands).
    - `license_backend.py`: License validation logic.
    - `static/`: JS/CSS assets (includes `dashboard.js`, `three.js` visualization).
- **`server/` (Bridge)**
    - `bridge.py`: Legacy/Simple bridge service.
- **`mosquitto/` (Broker)**
    - `config/mosquitto.secure.conf`: Broker config (Ports: 1883 Internal, 8883 TLS).
- **`certs/`**: TLS certificates for secure MQTT communication.
- **`devmin/`**: Minimal development environments and scripts.

## 3. Development Workflows

### Docker Environment (Primary)
The standard runtime uses secure MQTT.
*   **Start:** `docker-compose -f docker-compose.secure.yml up -d`
*   **Rebuild:** `docker-compose -f docker-compose.secure.yml up -d --build`
*   **Logs:** `docker-compose -f docker-compose.secure.yml logs -f`
*   **Access:**
    *   Main UI: `https://localhost` (Accept self-signed cert)
    *   Config Console: `http://localhost:5002`

### Local Development (Python)
*   **Python Version:** 3.11+
*   **Setup:**
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # or .venv\Scripts\activate
    pip install -r app/requirements.txt -r webapp/requirements.txt
    ```
*   **Running Components:**
    Ensure `BROKER_HOST` environment variable is set correctly (e.g., `localhost`).
    *   Web: `python webapp/app.py`
    *   Bridge: `python server/bridge.py`

## 4. Coding Conventions & Language
*   **Language:** Python (Backend), JavaScript (Frontend/Three.js).
*   **Style:** PEP 8 compliance.
*   **Text/Encoding:**
    *   Code comments and output are primarily in **Chinese (Simplified)** or English.
    *   **Do not** modify existing Chinese characters to English unless requested.
    *   Files should be UTF-8 encoded.

## 5. Troubleshooting & Debugging
*   **503 Service Unavailable:** Usually means the `config_service` or `license_service` failed to connect to the MQTT broker. Check `BROKER_HOST` env vars in `docker-compose.secure.yml`.
*   **Certificate Errors:** Ensure `certs/` contains valid `ca.crt`, `server.crt`, `server.key`.
*   **Port Conflicts:** Check ports `443`, `1883`, `8883`, `5000-5002`.

## 6. Git Guidelines
*   **Commits:** Use imperative, descriptive messages (e.g., "Fix broken pipe in sink.py", "Update dashboard layout").
*   **Branches:** Feature branching recommended.

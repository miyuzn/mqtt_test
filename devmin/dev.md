# MQTT Sensor System - Local Development & Testing Guide

This document provides instructions on how to set up a local development environment that mirrors the production environment, allowing for safe testing and deployment of new business logic.

## 1. Core Concepts
- **Environment Alignment**: Uses Docker to simulate production SSL, database structures, and directory hierarchies.
- **Source Mounting**: Local source code from `backend/` and `web/` is mounted into containers via Docker Volumes. Changes take effect immediately after a container restart without rebuilding images.
- **Universal Certificates**: A self-signed "Wildcard" certificate for `localhost` and `broker` ensures seamless SSL connectivity between your host machine and containers.

---

## 2. Setup Instructions

### 2.1 Generate Development Certificates
Navigate to the `devmin/` directory and run the certificate generation script (requires `openssl`):
```bash
cd devmin
# If using Windows Git Bash or Linux/macOS
bash gen_dev_certs.sh
```
This will generate `ca.crt`, `server.crt`, and `server.key` inside the `devmin/certs/` directory.

### 2.2 Start Local Containers
Ensure Docker and Docker Compose are installed and running.
```bash
docker-compose -f docker-compose.dev.yml up -d
```
Once started, the following ports will be mapped to your host machine:
- **MQTT (SSL)**: `localhost:8883`
- **MQTT (TCP/Plain)**: `localhost:1883`
- **Web UI**: `http://localhost:5000`
- **Postgres DB**: `localhost:5432`

---

## 3. Development & Debugging Workflow

### 3.1 Modifying Business Logic
You can edit the source code in your IDE directly within the root `backend/` or `web/` directories. Because of the volume mounting in `docker-compose.dev.yml`:
- **Backend changes** (e.g., `sink.py`): Run `docker restart devmin-sink-1` to apply changes.
- **Web changes**: Run `docker restart devmin-web-1` to apply changes.

### 3.2 Simulating Data Transmission
Use a test script or MQTT Explorer on your local machine to send data to the local container.
- **Broker Host**: `localhost`
- **Port**: `8883`
- **SSL**: Enabled (Load `devmin/certs/ca.crt` as the trusted CA).

### 3.3 Verifying Database Records
Connect to the local database using a client (e.g., DBeaver or pgAdmin):
- **Host**: `localhost`
- **User/Password**: `admin` / `devpassword`
- **Database**: `iot_data`
Check the `data_files` table for real-time record insertions.

---

## 4. Deployment to Production

Once local testing is successful, follow these steps to sync with the production server:

### 4.1 Commit and Push
```bash
git add .
git commit -m "feat: your descriptive commit message"
git push origin <your-branch>
```

### 4.2 Update Production Server (Manual)
SSH into the production server and run:
```bash
cd /path/to/project
git pull
# Rebuild and restart affected services gracefully
docker-compose -f docker-compose.secure.yml up -d --build
```
The `--build` flag ensures that changes in `requirements.txt` or Dockerfiles are correctly applied.

---

## 5. Important Notes
- **Security Warning**: The keys generated in `devmin/certs/` are for **local testing only**. NEVER use them in production or commit sensitive private keys to public repositories.
- **Data Isolation**: Local test data is stored in `devmin/data/` and is ignored by Git (via `.gitignore`).
- **Environment Differences**: The local Web UI defaults to HTTP for convenience. Always ensure `WEB_SSL_ENABLED=true` is maintained in the production `docker-compose.secure.yml`.
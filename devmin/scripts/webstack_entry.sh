#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[webstack] $*"
}

FORWARD_PID=""
BRIDGE_PID=""
WEB_PID=""

start_forwarder() {
  if [[ "${BROKER_FORWARD_ENABLED:-1}" == "0" ]]; then
    log "MQTT forwarder disabled"
    return
  fi
  local target_host="${BROKER_FORWARD_HOST:-parser}"
  local target_port="${BROKER_FORWARD_PORT:-1883}"
  local local_port="${BROKER_LOCAL_PORT:-1883}"
  log "forwarding localhost:${local_port} -> ${target_host}:${target_port}"
  socat TCP-LISTEN:${local_port},fork,reuseaddr TCP:${target_host}:${target_port} &
  FORWARD_PID=$!
}

stop_all() {
  for pid in "${WEB_PID}" "${BRIDGE_PID}" "${FORWARD_PID}"; do
    if [[ -n "${pid}" ]]; then
      kill "${pid}" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
}

trap 'stop_all; exit 0' INT TERM

export PYTHONPATH="/workspace/server:/workspace/web:/workspace/backend:${PYTHONPATH:-}"
start_forwarder

log "starting bridge service"
python /workspace/server/bridge.py &
BRIDGE_PID=$!

log "starting Flask web UI"
cd /workspace/web
python app.py &
WEB_PID=$!

set +e
wait -n "${BRIDGE_PID}" "${WEB_PID}"
STATUS=$?
set -e
stop_all
exit ${STATUS}

#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[collector] $*"
}

FORWARD_PID=""
WORKER_PID=""

start_forwarder() {
  if [[ "${BROKER_FORWARD_ENABLED:-1}" == "0" ]]; then
    log "local MQTT forwarder disabled"
    return
  fi
  local target_host="${BROKER_FORWARD_HOST:-parser}"
  local target_port="${BROKER_FORWARD_PORT:-1883}"
  local local_port="${BROKER_LOCAL_PORT:-1883}"
  log "forwarding localhost:${local_port} -> ${target_host}:${target_port}"
  socat TCP-LISTEN:${local_port},fork,reuseaddr TCP:${target_host}:${target_port} &
  FORWARD_PID=$!
}

stop_forwarder() {
  if [[ -n "${FORWARD_PID}" ]]; then
    log "stopping MQTT forwarder (pid=${FORWARD_PID})"
    kill "${FORWARD_PID}" 2>/dev/null || true
    wait "${FORWARD_PID}" 2>/dev/null || true
    FORWARD_PID=""
  fi
}

shutdown() {
  log "shutting down collector"
  if [[ -n "${WORKER_PID}" ]]; then
    kill "${WORKER_PID}" 2>/dev/null || true
  fi
  stop_forwarder
}

trap 'shutdown; exit 0' INT TERM

export PYTHONPATH="/workspace:${PYTHONPATH:-}"
start_forwarder

log "starting data_receive.py with CONFIG_PATH=${CONFIG_PATH:-config.ini}"
python /workspace/data_receive.py &
WORKER_PID=$!

set +e
wait "${WORKER_PID}"
STATUS=$?
set -e
shutdown
exit ${STATUS}

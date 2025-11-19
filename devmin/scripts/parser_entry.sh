#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[parser] $*"
}

MOSQUITTO_PID=""
PARSER_PID=""

stop_all() {
  for pid in "${MOSQUITTO_PID}" "${PARSER_PID}"; do
    if [[ -n "${pid}" ]]; then
      kill "${pid}" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
}

trap 'stop_all; exit 0' INT TERM

SINK_ROOT=${SINK_ROOT_DIR:-/workspace/data/mqtt_store}
mkdir -p "${SINK_ROOT}"
log "using sink directory ${SINK_ROOT}"

log "starting mosquitto"
mosquitto -c /etc/mosquitto/mosquitto.conf &
MOSQUITTO_PID=$!

wait_for_port() {
  local host=$1
  local port=$2
  local retries=${3:-30}
  while true; do
    if exec 3<>"/dev/tcp/${host}/${port}"; then
      exec 3>&-
      break
    fi
    sleep 1
    retries=$((retries - 1))
    if [[ ${retries} -le 0 ]]; then
      log "timeout waiting for ${host}:${port}"
      exit 1
    fi
  done
}

wait_for_port "127.0.0.1" "${MQTT_BROKER_PORT:-1883}"

export PYTHONPATH="/workspace/app:/workspace/server:${PYTHONPATH:-}"

log "starting raw_parser_service"
python /workspace/server/raw_parser_service.py &
PARSER_PID=$!

set +e
wait -n "${MOSQUITTO_PID}" "${PARSER_PID}"
STATUS=$?
set -e
stop_all
exit ${STATUS}

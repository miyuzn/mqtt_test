#!/bin/bash
set -euo pipefail

/usr/sbin/mosquitto -c /mosquitto/config/mosquitto.conf &
MOSQ_PID=$!

uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${CONSOLE_PORT:-5080}" \
  --proxy-headers &
API_PID=$!

terminate() {
  local signal=$1
  echo "捕获信号 ${signal}，准备停止服务" >&2
  kill -TERM "${MOSQ_PID}" 2>/dev/null || true
  kill -TERM "${API_PID}" 2>/dev/null || true
}

trap 'terminate INT' INT
trap 'terminate TERM' TERM

wait -n "${MOSQ_PID}" "${API_PID}"
EXIT_CODE=$?
terminate "WAIT"
wait || true
exit "${EXIT_CODE}"

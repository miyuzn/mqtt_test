#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[sink] $*"
}

trap 'exit 0' INT TERM

export PYTHONPATH="/workspace/backend:${PYTHONPATH:-}"

log "starting sink.py"
python /workspace/backend/sink.py

#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[sink] $*"
}

trap 'exit 0' INT TERM

export PYTHONPATH="/workspace/app:${PYTHONPATH:-}"

log "starting sink.py"
python /workspace/app/sink.py

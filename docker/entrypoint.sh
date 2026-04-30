#!/bin/sh
set -eu

CONFIG_PATH="${CONFIG_PATH:-/app/config.json}"
API_HOST="${API_HOST:-0.0.0.0}"
API_PORT="${API_PORT:-8080}"
STATIC_DIR="${STATIC_DIR:-/app/dist}"

python3 -m backend.status_monitor.worker --config "$CONFIG_PATH" &
worker_pid="$!"

cleanup() {
  kill "$worker_pid" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

python3 -m backend.status_monitor.api \
  --config "$CONFIG_PATH" \
  --host "$API_HOST" \
  --port "$API_PORT" \
  --static-dir "$STATIC_DIR"

#!/usr/bin/env bash
set -euo pipefail
PORT="${PORT:-8080}"
URL="${SANHUA_LLAMA_BASE_URL:-http://127.0.0.1:$PORT/v1}"
TRIES="${TRIES:-60}"   # 最多试 60 次
SLEEP="${SLEEP:-1}"    # 每次间隔 1s

for i in $(seq 1 "$TRIES"); do
  if curl -sf --max-time 1 "$URL/models" >/dev/null; then
    echo "READY after ${i}s"
    exit 0
  fi
  sleep "$SLEEP"
done

echo "Not ready after ${TRIES}s"
exit 1

#!/usr/bin/env bash
set -euo pipefail
PORT="${PORT:-8080}"
URL="${SANHUA_LLAMA_BASE_URL:-http://127.0.0.1:$PORT/v1}"

# 进程级检测
if pgrep -fal "llama-server.*--port $PORT" >/dev/null; then
  PIDS="$(pgrep -fal "llama-server.*--port $PORT" | awk '{print $1}' | paste -sd, -)"
  echo "llama-server process: ${PIDS}"
else
  echo "llama-server NOT running"; exit 1
fi

# 端口监听检测
if lsof -iTCP:$PORT -sTCP:LISTEN >/dev/null; then
  echo "port $PORT: LISTENING"
else
  echo "port $PORT: not listening"; exit 2
fi

# HTTP 就绪（模型可能还在加载）
if curl -sf --max-time 1 "$URL/models" >/dev/null; then
  echo "API ready ✔"
  curl -s "$URL/models" | head -c 200; echo
else
  echo "API not ready (model loading)"
  exit 3
fi

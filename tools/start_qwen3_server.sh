#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PORT:-8080}"
CTX="${CTX:-4096}"
HOST="${HOST:-127.0.0.1}"

BIN="${LLAMA_SERVER_BIN:-$ROOT_DIR/llama.cpp/build/bin/llama-server}"
MODEL="${SANHUA_ACTIVE_MODEL:-$ROOT_DIR/models/qwen3-latest/qwen3-latest.gguf}"
PID_FILE="$ROOT_DIR/logs/llama_server.pid"
LOG_FILE="$ROOT_DIR/logs/llama_server.log"

echo "ROOT_DIR=$ROOT_DIR"
echo "BIN=$BIN"
echo "MODEL=$MODEL"

mkdir -p "$ROOT_DIR/logs"

if [[ ! -x "$BIN" ]]; then
  echo "❌ llama-server binary not found or not executable:"
  echo "   $BIN"
  exit 1
fi

if [[ ! -f "$MODEL" ]]; then
  echo "❌ model file not found:"
  echo "   $MODEL"
  exit 1
fi

# 环境变量同步：控制面和数据面对齐
export SANHUA_ACTIVE_MODEL="$MODEL"
export SANHUA_MODEL="$MODEL"
export LLAMA_MODEL="$MODEL"
export SANHUA_LLAMA_BASE_URL="http://${HOST}:${PORT}/v1"
export LLAMA_SERVER_BIN="$BIN"
export LLAMA_PORT="$PORT"
export LLAMA_CTX="$CTX"

echo "==> 环境变量同步"
echo "SANHUA_ACTIVE_MODEL=$SANHUA_ACTIVE_MODEL"
echo "SANHUA_MODEL=$SANHUA_MODEL"
echo "LLAMA_MODEL=$LLAMA_MODEL"
echo "SANHUA_LLAMA_BASE_URL=$SANHUA_LLAMA_BASE_URL"
echo "LLAMA_SERVER_BIN=$LLAMA_SERVER_BIN"
echo "LLAMA_PORT=$LLAMA_PORT"
echo "LLAMA_CTX=$LLAMA_CTX"

# 如果 PID 文件存在，先尝试停掉旧进程
if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "${OLD_PID:-}" ]] && ps -p "$OLD_PID" > /dev/null 2>&1; then
    echo "==> 停止旧 llama-server PID=$OLD_PID"
    kill "$OLD_PID" || true
    sleep 1
  fi
fi

# 如果端口上还有旧进程，占用就杀掉
OLD_PORT_PID="$(lsof -tiTCP:${PORT} -sTCP:LISTEN 2>/dev/null || true)"
if [[ -n "${OLD_PORT_PID:-}" ]]; then
  echo "==> 释放端口 ${PORT}, PID=$OLD_PORT_PID"
  kill $OLD_PORT_PID || true
  sleep 1
fi

echo "==> 启动 qwen3-latest ..."
nohup "$BIN" \
  -m "$MODEL" \
  --host "$HOST" \
  --port "$PORT" \
  -c "$CTX" \
  -ngl 99 \
  > "$LOG_FILE" 2>&1 &

NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

sleep 3

echo "==> 监听检查"
lsof -nP -iTCP:${PORT} -sTCP:LISTEN || true

echo
echo "==> 模型检查"
curl -s "http://${HOST}:${PORT}/v1/models" || true
echo

if lsof -nP -iTCP:${PORT} -sTCP:LISTEN | grep -q LISTEN; then
  echo "✅ 启动完成，PID=$NEW_PID"
else
  echo "❌ 启动失败，请检查日志：$LOG_FILE"
  echo "------------------------------------------------------------------------"
  tail -n 80 "$LOG_FILE" 2>/dev/null || true
  exit 1
fi
#!/usr/bin/env bash
set -euo pipefail

# 项目根目录
ROOT="$(cd -- "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"

# ===== 可配置项（带默认值） =====

# llama-server 二进制：
# - 默认：$ROOT/llama.cpp/build/bin/llama-server
# - 或通过 SANHUA_SERVER 指定
SERVER_DEFAULT="$ROOT/llama.cpp/build/bin/llama-server"
SERVER="${SANHUA_SERVER:-$SERVER_DEFAULT}"

# 模型路径逻辑：
# - 若设置 SANHUA_MODEL：
#     * 以 / 开头 => 视为绝对路径
#     * 否则 => 视为相对 ROOT/models 的路径，例如：
#         SANHUA_MODEL="deepseek-r1-32b/deepseek-r1-32b.gguf"
#         => $ROOT/models/deepseek-r1-32b/deepseek-r1-32b.gguf
# - 若未设置 SANHUA_MODEL => 默认 llama3-8b
MODEL_DEFAULT="$ROOT/models/llama3-8b/llama3-8b.gguf"

if [[ -n "${SANHUA_MODEL:-}" ]]; then
  if [[ "$SANHUA_MODEL" == /* ]]; then
    MODEL="$SANHUA_MODEL"
  else
    MODEL="$ROOT/models/$SANHUA_MODEL"
  fi
else
  MODEL="$MODEL_DEFAULT"
fi

# 端口 / 主机
PORT="${SANHUA_LLAMA_PORT:-8080}"
HOST="${SANHUA_LLAMA_HOST:-127.0.0.1}"

# CPU 线程数
CORES="$(sysctl -n hw.ncpu 2>/dev/null || echo 4)"

# 日志
LOG_DIR="$ROOT/logs"
LOG_FILE="$LOG_DIR/llama_server.log"
mkdir -p "$LOG_DIR"

# ===== 基本检查 =====

if [[ ! -x "$SERVER" ]]; then
  echo "❌ llama-server binary not found or not executable:"
  echo "   $SERVER"
  exit 1
fi

if [[ ! -f "$MODEL" ]]; then
  echo "❌ model file not found:"
  echo "   $MODEL"
  exit 1
fi

# macOS: 让 dyld 能在 server 同目录找到 libmtmd.dylib 等
export DYLD_LIBRARY_PATH="$(dirname "$SERVER"):${DYLD_LIBRARY_PATH:-}"

echo "llama-server launching..."
echo "  host  = $HOST"
echo "  port  = $PORT"
echo "  model = $MODEL"
echo "  cores = $CORES"
echo "  log   = $LOG_FILE"

# 后台启动
nohup "$SERVER" -m "$MODEL" \
  --host "$HOST" \
  --port "$PORT" \
  -t "$CORES" \
  -c 4096 \
  -ngl 999 \
  >>"$LOG_FILE" 2>&1 &

PID=$!
echo "✅ llama-server started, pid=$PID"
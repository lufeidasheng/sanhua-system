#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-$PWD}"
ROOT_DIR="$(cd "$ROOT_DIR" && pwd)"

NEW_MODEL="$ROOT_DIR/models/qwen3-latest/qwen3-latest.gguf"
NEW_BASE_URL="http://127.0.0.1:8080"
NEW_API_BASE="$NEW_BASE_URL/v1"
NEW_BIN="$ROOT_DIR/llama.cpp/build/bin/llama-server"

echo "========================================================================"
echo "修正当前 shell 的模型环境变量"
echo "========================================================================"
echo "ROOT_DIR=$ROOT_DIR"
echo "NEW_MODEL=$NEW_MODEL"
echo "NEW_BIN=$NEW_BIN"
echo "------------------------------------------------------------------------"

if [[ ! -f "$NEW_MODEL" ]]; then
  echo "❌ 模型文件不存在: $NEW_MODEL"
  exit 1
fi

if [[ ! -x "$NEW_BIN" ]]; then
  echo "❌ llama-server 不可执行: $NEW_BIN"
  exit 1
fi

export SANHUA_ACTIVE_MODEL="$NEW_MODEL"
export SANHUA_MODEL="$NEW_MODEL"
export LLAMA_MODEL="$NEW_MODEL"
export SANHUA_LLAMA_BASE_URL="$NEW_API_BASE"
export LLAMA_SERVER_BIN="$NEW_BIN"
export LLAMA_PORT="8080"
export LLAMA_CTX="4096"

echo "✅ 已导出以下环境变量："
echo "SANHUA_ACTIVE_MODEL=$SANHUA_ACTIVE_MODEL"
echo "SANHUA_MODEL=$SANHUA_MODEL"
echo "LLAMA_MODEL=$LLAMA_MODEL"
echo "SANHUA_LLAMA_BASE_URL=$SANHUA_LLAMA_BASE_URL"
echo "LLAMA_SERVER_BIN=$LLAMA_SERVER_BIN"
echo "LLAMA_PORT=$LLAMA_PORT"
echo "LLAMA_CTX=$LLAMA_CTX"
echo "========================================================================"
echo "提示：本脚本只影响当前 shell，会话关掉就失效。"
echo "如果要长期生效，请再执行 patch_zsh_model_env.py。"
echo "========================================================================"

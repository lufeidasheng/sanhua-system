#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$DIR/stop_llama_server.sh" || true
"$DIR/start_llama_server.sh"
# 等到 /v1/models 可用再汇报状态
if ! "$DIR/wait_llama_ready.sh"; then
  echo "Server not ready; printing last 60 lines of log:"
  tail -n 60 "$HOME/Desktop/聚核助手2.0/logs/llama_server.log" || true
  exit 1
fi
"$DIR/status_llama_server.sh"

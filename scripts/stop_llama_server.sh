#!/usr/bin/env bash
set -euo pipefail
pkill -f 'llama-server.*--port 8080' 2>/dev/null && \
  echo "llama-server stopped" || echo "no llama-server on :8080"

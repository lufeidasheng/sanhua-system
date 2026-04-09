#!/usr/bin/env bash
# scripts/run_dev.sh
# 三花聚顶 · 本地 llama.cpp 管理器启动脚本（企业标准版）
# 用法：
#   ./scripts/run_dev.sh              # 正常启动（会自动检查/自检）
#   SANHUA_NGL=32 ./scripts/run_dev.sh  # 临时覆盖某个参数
# 需要：curl、jq（建议装）

set -Eeuo pipefail

### ---------- 基础工具检查 ----------
need() { command -v "$1" >/dev/null 2>&1 || { echo "缺少依赖：$1"; exit 1; }; }
need curl
if ! command -v jq >/dev/null 2>&1; then
  echo "提示：未检测到 jq，输出会少点花样（仍可运行）。建议：sudo dnf install -y jq"
  JQ="cat"
else
  JQ="jq"
fi

### ---------- 目录 / 二进制 / 模型 ----------
ROOT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
: "${LLAMA_BUILD:="$HOME/文档/聚核助手2.0/juyuan_models/llama.cpp-master/build"}"
: "${SANHUA_SERVER:="$LLAMA_BUILD/bin/llama-server"}"
: "${SANHUA_MODEL:="$HOME/文档/聚核助手2.0/models/qwen3-latest/qwen3-latest.gguf"}"

### ---------- 动态库路径 ----------
export LD_LIBRARY_PATH="${LLAMA_BUILD}/bin:/usr/local/cuda/lib64:/usr/local/cuda-12.9/lib64:${LD_LIBRARY_PATH:-}"

### ---------- 性能参数（可被外部 env 覆盖） ----------
: "${GGML_CUDA_FORCE_MMQ:=1}"   # 30 系列常有收益
: "${OMP_NUM_THREADS:=16}"      # 你机器上日志显示 total_threads=12~16；这里给 16
: "${SANHUA_NGL:=38}"           # GPU offload 层数（Qwen3-8B GGUF，8GB 显卡常见 12~22，稳定后 32）
: "${SANHUA_CTX:=5120}"         # 上下文窗口
: "${SANHUA_BATCH:=4096}"       # 推理批大小（大幅影响吞吐和首 token 延迟）
: "${SANHUA_IDLE:=600}"         # 空闲多少秒自动关闭 llama-server

### ---------- 端口（可被外部 env 覆盖） ----------
# API 管理端口（uvicorn）
: "${APP_HOST:=127.0.0.1}"
: "${APP_PORT:=9000}"
# llama-server 端口
: "${LLAMA_HOST:=127.0.0.1}"
: "${LLAMA_PORT:=8080}"

### ---------- 小工具 ----------
is_port_busy() { lsof -iTCP:"$1" -sTCP:LISTEN -nP >/dev/null 2>&1; }
wait_http_up() { # url timeout_sec
  local url="$1" t="${2:-15}" i=0
  until curl -sS "$url" >/dev/null 2>&1; do
    (( i++ >= t )) && return 1
    sleep 1
  done
  return 0
}

### ---------- 前置校验 ----------
[ -x "$SANHUA_SERVER" ] || { echo "❌ 未找到 llama-server: $SANHUA_SERVER"; exit 1; }
[ -f "$SANHUA_MODEL" ]  || { echo "❌ 未找到模型文件: $SANHUA_MODEL"; exit 1; }

# 尝试预加载依赖提示
if ldd "$SANHUA_SERVER" 2>/dev/null | grep -q "not found"; then
  echo "⚠️  警告：llama-server 仍有未解析的动态库："
  ldd "$SANHUA_SERVER" | grep "not found" || true
  echo "   请确认 LD_LIBRARY_PATH 已包含：${LLAMA_BUILD}/bin"
fi

### ---------- GPU 自检（可选） ----------
if command -v nvidia-smi >/dev/null 2>&1; then
  echo "—— GPU 自检（nvidia-smi 摘要）——"
  nvidia-smi --query-gpu=name,memory.total,memory.used,driver_version --format=csv -i 0 || true
  echo
else
  echo "提示：未检测到 nvidia-smi（仍可运行 CPU/部分 CUDA 路径）。"
fi

### ---------- 参数摘要 ----------
cat <<EOF
=== 三花聚顶 · 本地管理器启动参数 ===
llama-server : $SANHUA_SERVER
model        : $SANHUA_MODEL
LD_LIBRARY   : $LD_LIBRARY_PATH
APP          : http://$APP_HOST:$APP_PORT
LLAMA        : http://$LLAMA_HOST:$LLAMA_PORT
GGML_CUDA_FORCE_MMQ=$GGML_CUDA_FORCE_MMQ  OMP_NUM_THREADS=$OMP_NUM_THREADS
SANHUA_NGL=$SANHUA_NGL  SANHUA_CTX=$SANHUA_CTX  SANHUA_BATCH=$SANHUA_BATCH  SANHUA_IDLE=$SANHUA_IDLE
=====================================
EOF

### ---------- 优雅停止（如果在跑） ----------
stop_if_running() {
  # 停 llama-server（通过管理 API，如果在跑）
  if curl -fsS "http://$APP_HOST:$APP_PORT/health" >/dev/null 2>&1; then
    echo "→ 检测到管理器在线，尝试优雅停止 llama-server ..."
    curl -fsS -X POST "http://$APP_HOST:$APP_PORT/stop" >/dev/null 2>&1 || true
    sleep 1
  fi

  # 如果端口仍占用，提示
  if is_port_busy "$LLAMA_PORT"; then
    echo "⚠️  端口 $LLAMA_PORT 依然占用（可能残留进程），尝试提示："
    lsof -i:"$LLAMA_PORT" -nP || true
  fi
}
stop_if_running

### ---------- 起管理器 ----------
echo "→ 启动 uvicorn 管理器 ..."
# 用 python -m 保持和原脚本一致；必要时可改为直接 uvicorn 命令
# 注：如果你希望热更新，可以加 --reload
python -m uvicorn server.app:app --host "$APP_HOST" --port "$APP_PORT" >/dev/null 2>&1 &
APP_PID=$!
sleep 1

if ! kill -0 "$APP_PID" 2>/dev/null; then
  echo "❌ uvicorn 启动失败（可能端口 $APP_PORT 被占用）"
  lsof -i:"$APP_PORT" -nP || true
  exit 1
fi

# 等待管理器活起来
wait_http_up "http://$APP_HOST:$APP_PORT/health" 15 || {
  echo "❌ 管理器 /health 未就绪"
  exit 1
}

### ---------- 通过管理器唤醒 llama-server ----------
echo "→ 唤醒 llama-server ..."
curl -fsS -X POST "http://$APP_HOST:$APP_PORT/start" | $JQ || true

# 查看健康与启动参数
echo "—— /status ——"
curl -fsS "http://$APP_HOST:$APP_PORT/status" | $JQ || true
echo "—— /health ——"
curl -fsS "http://$APP_HOST:$APP_PORT/health"  | $JQ || true

# 额外打印关键日志片段（确认 GPU offload / KV / batch）
echo "—— 关键日志（GPU/KV/Batch）——"
curl -fsS "http://$APP_HOST:$APP_PORT/health" \
  | $JQ -r '.stderr_tail[]' \
  | egrep -i 'offloaded|CUDA0|compute buffer|Flash|n_ctx|n_batch|model buffer|KV buffer' || true

echo
echo "✅ 启动完成：管理器 http://$APP_HOST:$APP_PORT  · llama-server http://$LLAMA_HOST:$LLAMA_PORT"
echo "小贴士："
echo "  1) 改参数时只需：编辑本文件顶部的 export 默认值，或在命令前临时导出（SANHUA_NGL=... ./scripts/run_dev.sh）"
echo "  2) 如果显存没吃满，可提高 SANHUA_NGL、SANHUA_BATCH 或 SANHUA_CTX（注意 OOM 风险）"
echo "  3) 想看更详细日志：把 uvicorn 那行的输出重定向去掉（去掉 >/dev/null 2>&1）"

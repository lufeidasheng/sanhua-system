#!/usr/bin/env bash
# 一键 Ollama GPU 测试脚本
# 功能：杀掉旧服务 → 启动新服务（GPU 模式） → 监控 GPU → 跑测试 Prompt

set -e

MODEL="llama3:8b"
PROMPT="用中文写一篇关于未来人工智能的2000字短文"

echo ">>> Step 1: 杀掉旧的 ollama serve ..."
PID=$(lsof -ti:11434 || true)
if [ -n "$PID" ]; then
  echo "    找到占用 11434 端口的进程 PID=$PID，准备 kill"
  kill -9 $PID
  sleep 1
else
  echo "    没有旧的 ollama serve 在跑"
fi

echo ">>> Step 2: 以 GPU 模式启动 Ollama 服务 ..."
export OLLAMA_NUM_GPU=-1
ollama serve > /tmp/ollama_serve.log 2>&1 &
SERVE_PID=$!
sleep 2
echo "    ollama serve 已启动 (PID=$SERVE_PID)"

echo ">>> Step 3: 启动 GPU 监控 (nvidia-smi，每秒刷新一次)"
echo "    (按 Ctrl+C 停止监控)"
watch -n 1 nvidia-smi &
WATCH_PID=$!

sleep 2

echo ">>> Step 4: 运行测试 Prompt ..."
ollama run $MODEL "$PROMPT"

echo ">>> Step 5: 清理监控进程"
kill -9 $WATCH_PID || true
echo ">>> 完成！"

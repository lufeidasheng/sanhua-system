#!/usr/bin/env bash
set -euo pipefail

MODEL_BASE="gemma4:e4b"
MODEL_NAME="sanhua-gemma4-e4b"
CTX_SIZE="8192"

echo "==> 1) 检查 ollama 是否存在"
if ! command -v ollama >/dev/null 2>&1; then
  echo "错误：未找到 ollama，请先安装 Ollama。"
  exit 1
fi

echo "==> 2) 检查基础模型是否已存在：$MODEL_BASE"
if ! ollama list | awk '{print $1}' | grep -qx "$MODEL_BASE"; then
  echo "==> 未发现 $MODEL_BASE，开始拉取..."
  ollama pull "$MODEL_BASE"
else
  echo "==> 已存在 $MODEL_BASE"
fi

echo "==> 3) 写入 Modelfile"
cat > Modelfile <<EOF
FROM ${MODEL_BASE}

PARAMETER num_ctx ${CTX_SIZE}
PARAMETER temperature 0.4
PARAMETER top_p 0.9

SYSTEM """
你现在是“三花聚顶系统”的本地协作模型，不是通用闲聊助手。

工作要求：
1. 全程中文
2. 先结论，后分析
3. 高信息密度
4. 不说空话
5. 代码问题优先给完整可替换代码
6. 从“聚感 -> 理解 -> 决策 -> 执行 -> 反馈 -> 记忆”主链出发思考
7. 不把未来规划说成当前已实现事实
8. 你的身份是：本地协作模型、架构顾问、提案生成器
"""
EOF

echo "==> 4) 创建自定义模型：$MODEL_NAME"
ollama create "$MODEL_NAME" -f Modelfile

echo "==> 5) 设置 macOS Ollama 环境变量（当前用户）"
launchctl setenv OLLAMA_FLASH_ATTENTION 1
launchctl setenv OLLAMA_KV_CACHE_TYPE q8_0
launchctl setenv OLLAMA_CONTEXT_LENGTH ${CTX_SIZE}
launchctl setenv OLLAMA_KEEP_ALIVE -1
launchctl setenv OLLAMA_NUM_PARALLEL 1
launchctl setenv OLLAMA_MAX_LOADED_MODELS 1

echo "==> 6) 重启 Ollama 服务"
if command -v brew >/dev/null 2>&1; then
  brew services restart ollama || true
else
  pkill -f "ollama serve" || true
  nohup ollama serve >/tmp/ollama.log 2>&1 &
  sleep 3
fi

echo "==> 7) 预热模型"
curl -s http://127.0.0.1:11434/api/generate -d "{
  \"model\": \"${MODEL_NAME}\",
  \"prompt\": \"\",
  \"keep_alive\": -1,
  \"stream\": false
}" >/dev/null || true

echo
echo "✅ 完成。"
echo "现在可用命令："
echo "  ollama run ${MODEL_NAME}"
echo
echo "检查运行状态："
echo "  ollama ps"
echo
echo "如果你改了 launchctl setenv 后发现没生效，退出菜单栏 Ollama 再重新打开一次。"

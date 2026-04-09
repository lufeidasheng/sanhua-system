#!/bin/bash
set -e

echo "🔧 正在执行三花聚顶路径和依赖修复..."

# 设置工作目录为项目根目录
cd "$(dirname "$0")"

# 确保 Python 能找到 core2_0 模块
export PYTHONPATH="$PYTHONPATH:$(pwd)/core"

# 补全 __init__.py 文件（递归）
echo "📦 检查并补全 __init__.py ..."
find . -type d -not -path "./.git*" -not -path "./venv*" | while read dir; do
  if [ ! -f "$dir/__init__.py" ]; then
    touch "$dir/__init__.py"
    echo "🧩 添加: $dir/__init__.py"
  fi
done

# 检查 config.py 中是否定义了 REPLY_THREAD_POOL_SIZE，没有就补上
CONFIG_PATH="./core/core2_0/config.py"
if grep -q "REPLY_THREAD_POOL_SIZE" "$CONFIG_PATH"; then
  echo "✅ config.py 已包含 REPLY_THREAD_POOL_SIZE"
else
  echo "⚙️  补充 config.py 缺失项: REPLY_THREAD_POOL_SIZE"
  echo -e "\n# 自动补充的默认配置\nREPLY_THREAD_POOL_SIZE = 8" >> "$CONFIG_PATH"
fi

# 修复 event_bus.py 中 SSL datetime 的弃用警告（使用 UTC 时间）
EVENT_BUS_PATH="./core/core2_0/event_bus.py"
if grep -q "not_valid_before" "$EVENT_BUS_PATH"; then
  echo "🛠️  修复 SSL 证书时间格式弃用警告..."
  sed -i 's/cert\.not_valid_before/cert.not_valid_before_utc/g' "$EVENT_BUS_PATH"
  sed -i 's/cert\.not_valid_after/cert.not_valid_after_utc/g' "$EVENT_BUS_PATH"
fi

# 启动 CLI
echo -e "\n🚀 启动 CLI 企业控制台...\n"
python entry/cli_entry/cli_entry.py

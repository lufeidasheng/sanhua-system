#!/bin/bash

# 设定 swap 文件路径和大小（默认 8G）
SWAPFILE="/swapfile"
SWAPSIZE="8G"

echo "🛠️ 正在创建 $SWAPSIZE 的 swap 文件: $SWAPFILE"

# 1. 创建空文件
sudo fallocate -l $SWAPSIZE $SWAPFILE

# 2. 设置权限（防止权限问题）
sudo chmod 600 $SWAPFILE

# 3. 初始化 swap 文件格式
sudo mkswap $SWAPFILE

# 4. 启用 swap 文件
sudo swapon $SWAPFILE

# 5. 设置优先级（比 zram 优先级低，避免浪费 IO）
sudo swapon --priority 50 $SWAPFILE

# 6. 添加到 /etc/fstab（开机自动挂载）
if ! grep -q "$SWAPFILE" /etc/fstab; then
  echo "$SWAPFILE none swap sw,pri=50 0 0" | sudo tee -a /etc/fstab
fi

echo "✅ 已启用 swap 文件！当前 swap 状态如下："
swapon --show

echo "✨ 你现在可以继续跑大模型啦！🧠🔥"

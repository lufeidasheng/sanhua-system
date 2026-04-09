#!/bin/bash
set -e

echo "🚀 开始安装 Piper（国内优化版）..."

# ✅ 安装依赖
echo "📦 安装基础依赖..."
sudo dnf install -y git cmake gcc-c++ espeak-ng-devel libonnxruntime-devel \
  python3-devel python3-pip make pkg-config

# ✅ 设置国内 pip 源
echo "🌐 配置国内 pip 镜像..."
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# ✅ 克隆 Piper 仓库（如已有则跳过）
if [ ! -d "piper" ]; then
  echo "🔽 克隆 Piper 源码..."
  git clone https://ghproxy.com/https://github.com/rhasspy/piper.git
else
  echo "📂 已存在 piper 目录，跳过 clone。"
fi

cd piper

# ✅ 安装 Python 依赖
echo "📦 安装 Python 依赖..."
pip install -r requirements.txt

# ✅ 编译 piper
echo "🔨 编译 Piper..."
make -j$(nproc)

# ✅ 下载一个模型（比如 en_US-amy）并测试（可换中文模型）
echo "📦 下载示例模型..."
mkdir -p voices && cd voices
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/en_US-amy-low.onnx
cd ..

# ✅ 测试语音合成
echo "🗣️ 测试 TTS 输出..."
echo "Hello from Piper in the midnight!" | ./piper --model voices/en_US-amy-low.onnx --output_file test.wav

echo "✅ 安装完成！输出文件为 test.wav，快去听听有没有灵魂～"

#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/Users/lufei/Desktop/聚核助手2.0"

echo "==> 检查项目目录"
if [ ! -d "$PROJECT_DIR" ]; then
  echo "❌ 项目目录不存在: $PROJECT_DIR"
  exit 1
fi

echo "==> 检查 Node/npm"
if ! command -v npm >/dev/null 2>&1; then
  echo "❌ 未检测到 npm。"
  echo "请先安装 Node.js（建议通过 Homebrew 安装 node），然后再重跑本脚本。"
  exit 1
fi

echo "==> 检查 Codex CLI"
if ! command -v codex >/dev/null 2>&1; then
  echo "📦 未检测到 codex，开始安装..."
  npm i -g @openai/codex
else
  echo "✅ 已检测到 codex: $(command -v codex)"
fi

echo "==> 进入项目目录"
cd "$PROJECT_DIR"

echo "==> 当前目录: $(pwd)"
echo "==> 建议首次运行先完成登录认证"
echo
echo "下一步手动执行："
echo "  cd \"$PROJECT_DIR\""
echo "  codex"
echo
echo "首次运行会要求你用 ChatGPT 账号或 API key 登录。"
echo "登录完成后，Codex 就能在这个目录里读、改、跑代码。"

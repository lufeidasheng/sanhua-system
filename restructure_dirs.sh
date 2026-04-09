#!/usr/bin/env bash
set -e

echo "🔧 正在创建标准目录..."

mkdir -p runtime/{logs,temp,recordings}
mkdir -p external/{rust_example,go_example,cpp_example}
mkdir -p tests

# 放置占位文件避免空目录被 Git 忽略
touch runtime/.keep external/.keep tests/.keep

echo "✅ 目录结构创建完成"

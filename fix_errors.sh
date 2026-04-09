#!/bin/bash

# 聚核助手2.0 错误修复脚本
# 修复以下问题：
# 1. CryptographyDeprecationWarning 证书时间检查弃用警告
# 2. Module import failed: No module named 'core.core2_0.aicore'
# 3. module 'config' has no attribute 'REPLY_PROCESSING_TIMEOUT'

# 检查是否在项目根目录运行
if [ ! -f "entry/cli_entry/cli_entry.py" ] || [ ! -d "core" ]; then
    echo "错误：请在项目根目录运行此脚本"
    echo "当前目录：$(pwd)"
    exit 1
fi

echo "开始修复聚核助手2.0错误..."

# 1. 修复弃用警告
echo "修复证书时间检查弃用警告..."
sed -i 's/cert.not_valid_before.replace(tzinfo=None)/cert.not_valid_before_utc/g' core/core2_0/event_bus.py
sed -i 's/cert.not_valid_after.replace(tzinfo=None)/cert.not_valid_after_utc/g' core/core2_0/event_bus.py

# 添加时区支持
if ! grep -q "from datetime import timezone" core/core2_0/event_bus.py; then
    sed -i '/import datetime/a from datetime import timezone' core/core2_0/event_bus.py
    sed -i 's/current_time = datetime.datetime.now()/current_time = datetime.datetime.now(timezone.utc)/g' core/core2_0/event_bus.py
fi

# 2. 修复 aicore 模块导入问题
echo "修复 aicore 模块导入..."
AICORE_SOURCE="core/aicore"
AICORE_TARGET="core/core2_0/aicore"

# 删除可能存在的错误目录
if [ -d "$AICORE_TARGET" ] && [ ! -L "$AICORE_TARGET" ]; then
    echo "删除无效的 aicore 目录: $AICORE_TARGET"
    rm -rf "$AICORE_TARGET"
fi

# 创建符号链接
if [ ! -e "$AICORE_TARGET" ]; then
    echo "创建符号链接: $AICORE_TARGET -> $AICORE_SOURCE"
    ln -s "../../$AICORE_SOURCE" "$AICORE_TARGET"
else
    echo "符号链接已存在: $AICORE_TARGET"
fi

# 3. 添加缺失的配置属性
echo "添加 REPLY_PROCESSING_TIMEOUT 配置..."
CONFIG_FILE="config.py"

# 检查文件是否存在
if [ ! -f "$CONFIG_FILE" ]; then
    echo "创建配置文件: $CONFIG_FILE"
    touch "$CONFIG_FILE"
fi

# 添加配置项
if ! grep -q "REPLY_PROCESSING_TIMEOUT" "$CONFIG_FILE"; then
    echo -e "\n# 回复处理超时时间 (秒)" >> "$CONFIG_FILE"
    echo "REPLY_PROCESSING_TIMEOUT = 30" >> "$CONFIG_FILE"
    echo "已添加 REPLY_PROCESSING_TIMEOUT 配置"
else
    echo "REPLY_PROCESSING_TIMEOUT 配置已存在"
fi

# 4. 验证修复
echo -e "\n验证修复:"
echo "1. 证书时间检查修复:"
grep "not_valid_before_utc" core/core2_0/event_bus.py && echo "  ✓ 已修复"
echo "2. aicore 符号链接:"
ls -l "$AICORE_TARGET" && echo "  ✓ 已修复"
echo "3. 配置项检查:"
grep "REPLY_PROCESSING_TIMEOUT" "$CONFIG_FILE" && echo "  ✓ 已修复"

echo -e "\n修复完成！请执行以下命令测试:"
echo "python entry/cli_entry/cli_entry.py"
echo "如果仍有问题，请检查:"
echo "1. aicore 模块的实际路径是否正确: $AICORE_SOURCE"
echo "2. 符号链接是否有效: ls -l $AICORE_TARGET"
echo "3. 证书验证逻辑是否正常工作"

#!/usr/bin/env bash
# 自动检测并禁用终端默认进入 Python 虚拟环境

set -e

CONFIG_FILES=("$HOME/.bashrc" "$HOME/.zshrc")
FOUND=false

echo "🔍 正在扫描终端配置文件中的自动激活虚拟环境命令..."

for file in "${CONFIG_FILES[@]}"; do
    if [[ -f "$file" ]]; then
        MATCH_LINES=$(grep -nE "source .*activate|\. .*activate" "$file" || true)
        if [[ -n "$MATCH_LINES" ]]; then
            echo "⚠️  发现自动激活命令在: $file"
            echo "$MATCH_LINES"
            # 备份
            cp "$file" "$file.bak.$(date +%Y%m%d%H%M%S)"
            # 注释掉匹配的行
            sed -i 's/^\(.*activate.*\)$/# \1  # 已自动禁用虚拟环境自动激活/' "$file"
            FOUND=true
        fi
    fi
done

if [ "$FOUND" = true ]; then
    echo "✅ 已禁用自动进入虚拟环境功能"
    echo "💡 请执行以下命令重新加载配置:"
    echo "   exec \$SHELL -l"
else
    echo "ℹ️ 未发现自动进入虚拟环境的配置"
fi

#!/bin/bash

echo "📌 开始注册三花聚顶系统入口模块..."

# 显式声明每个入口模块对应的 entry 文件
declare -A entry_files=(
  ["cli_entry"]="cli_main"
  ["gui_entry"]="module"
  ["voice_entry"]="module"
)

for module in "${!entry_files[@]}"; do
  init_path="modules/$module/__init__.py"
  entry_file="${entry_files[$module]}"
  
  echo "📥 正在更新 $init_path ..."
  echo "from .${entry_file} import entry" > "$init_path"
done

echo ""
echo "✅ 已成功写入 entry 引用到 __init__.py 中"

# 🔄 更新 manifest.json 中的 is_entry 字段（需 jq 工具）
echo ""
echo "📄 正在尝试更新 manifest.json 的 is_entry 字段..."

if ! command -v jq &> /dev/null; then
  echo "⚠️  未检测到 jq，跳过 manifest.json 的更新。"
else
  for module in "${!entry_files[@]}"; do
    manifest_path="modules/$module/manifest.json"
    
    if [ -f "$manifest_path" ]; then
      tmp_file="${manifest_path}.tmp"
      jq '. + {"is_entry": true}' "$manifest_path" > "$tmp_file" &&
      mv "$tmp_file" "$manifest_path"
      echo "✅ 已更新 $manifest_path"
    else
      echo "⚠️  未找到 $manifest_path，跳过。"
    fi
  done
fi

echo ""
echo "🎉 所有入口模块注册完毕！"

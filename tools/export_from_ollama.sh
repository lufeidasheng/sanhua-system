#!/usr/bin/env bash
set -euo pipefail

# === 可按需修改的默认参数 ===
PROJECT_ROOT="${PROJECT_ROOT:-$HOME/文档/聚核助手2.0}"   # 你的工程根目录
MODELS_DIR="${MODELS_DIR:-$PROJECT_ROOT/models}"        # 导出到哪里
OLLAMA_HOME="${OLLAMA_HOME:-$HOME/.ollama/models}"      # Ollama 本地仓库
PREFER_GPU_LAYERS="${PREFER_GPU_LAYERS:-35}"            # 3060Ti/8GB 的友好档位
CTX_LEN="${CTX_LEN:-4096}"
TEMPLATE="${TEMPLATE:-chatml}"                           # chatml/llama2/mistral 可改
COPY_MODE="${COPY_MODE:-copy}"                           # copy | link（硬链接省空间）

BLOBS="$OLLAMA_HOME/blobs"
MANI="$OLLAMA_HOME/manifests/registry.ollama.ai/library"

usage() {
  cat <<EOF
用法:
  $(basename "$0") <模型标识> [<更多模型标识>]
  $(basename "$0") --all

模型标识格式:
  - 形如 "llama3:8b" 或 "qwen3:latest"
  - 也可用 "llava:latest"（不建议先导出多模态）

环境变量(可选):
  PROJECT_ROOT, MODELS_DIR, OLLAMA_HOME, COPY_MODE=copy|link, PREFER_GPU_LAYERS, CTX_LEN, TEMPLATE

示例:
  $(basename "$0") llama3:8b qwen3:latest
  COPY_MODE=link $(basename "$0") llama3:8b
  $(basename "$0") --all
EOF
  exit 1
}

require() {
  command -v "$1" >/dev/null 2>&1 || { echo "缺少命令: $1"; exit 1; }
}

require jq
require stat
require awk
require sed

# 将 "llama3:8b" -> "llama3/8b"
tag_to_path() {
  echo "$1" | sed 's/:/\//'
}

# 将 "llama3:8b" -> "llama3-8b"（目录安全名）
tag_to_safe() {
  echo "$1" | sed 's/[:\/]/-/g'
}

# 从清单里挑出最大的 blob（通常就是主 GGUF）
pick_biggest_blob() {
  local mani_file="$1"
  # 抽取所有 digest，过滤存在的 blob，按大小降序取第一
  jq -r '..|.digest? // empty' "$mani_file" | while read -r d; do
    f="$BLOBS/$d"
    [[ -f "$f" ]] && stat --printf "%s %n\n" "$f"
  done | sort -nr | head -n1 | awk '{print $2}'
}

export_one() {
  local tag="$1"
  local path
  path="$(tag_to_path "$tag")"
  local mani_file="$MANI/$path"

  if [[ ! -f "$mani_file" ]]; then
    echo "❌ 找不到清单: $mani_file   (模型: $tag)"
    return 1
  fi

  local blob_file
  blob_file="$(pick_biggest_blob "$mani_file")"
  if [[ -z "$blob_file" ]]; then
    echo "❌ 未找到有效 blob（可能还没下完？）: $tag"
    return 1
  fi

  local safe
  safe="$(tag_to_safe "$tag")"
  local dest_dir="$MODELS_DIR/$safe"
  local dest_model="$dest_dir/$safe.gguf"
  mkdir -p "$dest_dir"

  # 复制 or 硬链接
  if [[ "$COPY_MODE" == "link" ]]; then
    ln -f "$blob_file" "$dest_model"
  else
    cp -f "$blob_file" "$dest_model"
  fi

  # 生成三花聚顶的 manifest.json
  cat > "$dest_dir/manifest.json" <<EOF
{
  "name": "$safe",
  "backend": "llamacpp",
  "path": "models/$safe/$safe.gguf",
  "ctx_len": $CTX_LEN,
  "gpu_layers": $PREFER_GPU_LAYERS,
  "template": "$TEMPLATE",
  "device": "auto",
  "notes": "exported from Ollama: $tag"
}
EOF

  echo "✅ 导出完成：$dest_dir"
}

# 处理 --all
if [[ $# -eq 1 && "$1" == "--all" ]]; then
  # 列出所有 manifests 下的 <name>/<tag> 组合
  mapfile -t all_tags < <(find "$MANI" -type f -printf '%P\n' | sed 's#/#:#')
  if [[ ${#all_tags[@]} -eq 0 ]]; then
    echo "未在 $MANI 下发现任何模型清单。"
    exit 1
  fi
  for t in "${all_tags[@]}"; do
    echo ">>> 导出 $t"
    export_one "$t" || true
  done
  exit 0
fi

# 单个/多个指定
[[ $# -ge 1 ]] || usage
for tag in "$@"; do
  export_one "$tag" || true
done

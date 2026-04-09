#!/usr/bin/env bash
# setup_cuda_env.sh — 清理并设置 CUDA 12.9 环境变量 +（可选）重编译 llama-cpp-python
# 适配：Fedora，RTX 3060 Ti（sm_86）。其他显卡可覆盖 CUDA_ARCHS 环境变量。

set -Eeuo pipefail

CUDA_VER_DIR="/usr/local/cuda-12.9"
CUDA_SYMLINK="/usr/local/cuda"
BASHRC="$HOME/.bashrc"
TS="$(date +%Y%m%d%H%M%S)"

# === 0) 小工具函数 ===
say()  { printf "\033[1;36m>>> %s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m[OK]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[WARN]\033[0m %s\n" "$*"; }
err()  { printf "\033[1;31m[ERR]\033[0m %s\n" "$*"; }

# === 1) 校验 CUDA 12.9 是否已安装 ===
say "检查 CUDA 12.9 安装目录：$CUDA_VER_DIR"
if [[ ! -d "$CUDA_VER_DIR" ]]; then
  err "未发现 $CUDA_VER_DIR。请先运行 CUDA 12.9 安装（仅 Toolkit），再执行本脚本。"
  exit 1
fi
ok "找到 $CUDA_VER_DIR"

# === 2) 兜底：/usr/local/cuda -> /usr/local/cuda-12.9 的符号链接 ===
say "确保 $CUDA_SYMLINK 指向 $CUDA_VER_DIR"
if [[ -L "$CUDA_SYMLINK" || -e "$CUDA_SYMLINK" ]]; then
  sudo ln -sfn "$CUDA_VER_DIR" "$CUDA_SYMLINK"
else
  sudo ln -s "$CUDA_VER_DIR" "$CUDA_SYMLINK"
fi
ok "$CUDA_SYMLINK -> $(readlink -f "$CUDA_SYMLINK")"

# === 3) 备份并清理 ~/.bashrc 中旧的 CUDA PATH/LD_LIBRARY_PATH 行 ===
say "备份并清理 $BASHRC"
cp -a "$BASHRC" "$BASHRC.bak.$TS"

# 删除常见重复/旧配置（按前缀匹配）
sed -i \
  -e '/^export \s*PATH=.*\/usr\/local\/cuda[^:]*\/bin/d' \
  -e '/^export \s*LD_LIBRARY_PATH=.*\/usr\/local\/cuda[^:]*\/lib64/d' \
  -e '/^export \s*PATH=.*\/usr\/local\/cuda\/bin/d' \
  -e '/^export \s*LD_LIBRARY_PATH=.*\/usr\/local\/cuda\/lib64/d' \
  "$BASHRC"

# 追加最简、唯一、可维护的两行
cat >> "$BASHRC" <<EOF

# >>> CUDA 12.9 BEGIN (managed by setup_cuda_env.sh)
export PATH="$CUDA_VER_DIR/bin:\$PATH"
export LD_LIBRARY_PATH="$CUDA_VER_DIR/lib64:\${LD_LIBRARY_PATH:-}"
# >>> CUDA 12.9 END
EOF
ok "已写入最简 CUDA 环境变量到 $BASHRC"
echo "已备份为: $BASHRC.bak.$TS"

# === 4) 让当前会话立即生效（避免 source /etc/bashrc 在 set -u 下的问题）===
say "让当前会话立即生效（不直接 source /etc/bashrc）"
export PATH="$CUDA_VER_DIR/bin:$PATH"
export LD_LIBRARY_PATH="$CUDA_VER_DIR/lib64:${LD_LIBRARY_PATH:-}"
ok "当前 shell 已加载 CUDA 12.9 路径"

# === 5) 基本验证 ===
say "验证 nvcc / nvidia-smi"
if command -v nvcc >/dev/null 2>&1; then
  nvcc --version | sed 's/^/    /'
else
  warn "nvcc 不在 PATH，检查 $CUDA_VER_DIR/bin 是否存在。"
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi | sed 's/^/    /' | head -n 10
else
  warn "未找到 nvidia-smi（驱动命令）。若未安装专有驱动，请先安装并重启。"
fi

# === 6) （可选）用 CUDA 重新编译 llama-cpp-python ===
# 如不需要，请在执行脚本前设置环境变量： SKIP_LLAMA_BUILD=1
if [[ "${SKIP_LLAMA_BUILD:-0}" != "1" ]]; then
  say "准备用 CUDA 重编译 llama-cpp-python（默认 sm_86，适配 RTX 3060 Ti）"

  # 允许用户覆盖架构：bash -c 'CUDA_ARCHS=89 bash setup_cuda_env.sh'
  CUDA_ARCHS_VAL="${CUDA_ARCHS:-86}"

  # 选择一个 Python 执行器
  PY="python3"
  command -v "$PY" >/dev/null 2>&1 || PY="python"

  # pip 可能需要 --user
  PIP="${PIP:-pip}"
  command -v "$PIP" >/dev/null 2>&1 || PIP="$PY -m pip"

  say "使用 CUDA_ARCHS=$CUDA_ARCHS_VAL"
  export CUDAToolkit_ROOT="$CUDA_SYMLINK"
  export CMAKE_ARGS="-DGGML_CUDA=on -DGGML_CUDA_F16=on -DCMAKE_CUDA_ARCHITECTURES=${CUDA_ARCHS_VAL}"
  export FORCE_CMAKE=1

  set +e
  $PIP install --user --no-cache-dir --force-reinstall --no-binary llama-cpp-python llama-cpp-python
  RC=$?
  set -e
  if [[ $RC -ne 0 ]]; then
    warn "llama-cpp-python 重编译失败（返回码 $RC）。你可稍后手动重试："
    echo "     CUDAToolkit_ROOT=$CUDA_SYMLINK CMAKE_ARGS=\"$CMAKE_ARGS\" FORCE_CMAKE=1 \\"
    echo "     $PIP install --user --no-cache-dir --force-reinstall --no-binary llama-cpp-python llama-cpp-python"
  else
    ok "llama-cpp-python 已用 CUDA 成功重编（或已可用）"
  fi
else
  warn "已按你的设置跳过 llama-cpp-python 重编译（SKIP_LLAMA_BUILD=1）"
fi

# === 7) 结束提示 ===
say "完成。新开终端将自动使用 CUDA 12.9 环境。"
echo "如需立即测试：  python3 quick_gpu_check.py"

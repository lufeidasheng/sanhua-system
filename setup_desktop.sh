#!/usr/bin/env bash
# 三花聚顶 · 台式机一键部署 & 启动脚本（Fedora）
# 回到笔记本“21个模块可用”的状态：锁定 Python3.11、关键依赖、修复已知日志Bug。
# 可选 GPU 加速：--cuda 或 --rocm（默认CPU）。

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

info()  { echo -e "\033[1;34m[INFO]\033[0m $*"; }
warn()  { echo -e "\033[1;33m[WARN]\033[0m $*"; }
err()   { echo -e "\033[1;31m[ERR ]\033[0m $*"; }

# -------- 参数 --------
USE_MIRROR=1
INSTALL_TRACKER=1
WANT_CUDA=0
WANT_ROCM=0

for a in "$@"; do
  case "$a" in
    --no-mirror)  USE_MIRROR=0 ;;
    --no-tracker) INSTALL_TRACKER=0 ;;
    --cuda)       WANT_CUDA=1 ;;
    --rocm)       WANT_ROCM=1 ;;
    *) warn "忽略未知参数: $a" ;;
  esac
done

if [[ ! -f "entry/cli_entry/cli_entry.py" ]]; then
  err "请在项目根目录运行（能看到 entry/cli_entry/cli_entry.py）。"; exit 1
fi

# -------- 系统依赖（台式机通用）--------
info "安装系统依赖（构建工具、音频头文件、FFmpeg等）……"
sudo dnf --setopt=max_parallel_downloads=1 --setopt=minrate=50k --setopt=timeout=60 \
  install -y \
  gcc gcc-c++ make cmake pkgconfig \
  python3.11 python3.11-devel \
  portaudio-devel alsa-lib-devel \
  opus-devel libsndfile libsndfile-devel \
  ffmpeg \
  git curl wget

if [[ $INSTALL_TRACKER -eq 1 ]]; then
  info "安装 GNOME 文件索引依赖（tracker3）……"
  sudo dnf --setopt=max_parallel_downloads=1 --setopt=minrate=50k --setopt=timeout=60 \
    install -y tracker3 tracker3-miners || warn "tracker3 安装失败，可忽略。"
fi

# -------- Python 3.11 虚拟环境 --------
VENV="${PROJECT_ROOT}/.venv311"
if [[ ! -d "$VENV" ]]; then
  info "创建虚拟环境: $VENV"
  python3.11 -m venv "$VENV"
fi
# shellcheck disable=SC1090
source "$VENV/bin/activate"

if [[ $USE_MIRROR -eq 1 ]]; then
  export PIP_INDEX_URL="https://mirrors.aliyun.com/pypi/simple/"
  info "使用 PyPI 镜像: $PIP_INDEX_URL"
fi

python -m pip install --upgrade pip setuptools wheel
export PIP_DEFAULT_TIMEOUT=60

# -------- 基础Python依赖（与笔记本一致）--------
# 先把必须跑起来的依赖装齐
BASE_PKGS=(
  edge-tts watchdog psutil netifaces
  pyaudio soundfile
)
info "安装基础依赖：${BASE_PKGS[*]}"
python -m pip install "${BASE_PKGS[@]}" || true

# -------- 模型相关（默认CPU，可选CUDA/ROCm）--------
# 你笔记本上成功过 torch==2.5.1；tv的对应版本镜像可能不稳，这里分情况：
if [[ $WANT_CUDA -eq 1 ]]; then
  info "准备安装 CUDA 版 PyTorch（需已装 NVIDIA 驱动/CUDA 工具链，Fedora上通过 rpmfusion-nonfree）。"
  # 通常 2.5.x 对应 torchvision 0.20.x/0.21.x，镜像不一定齐，就分步装。
  python -m pip install "torch==2.5.1+cu121" --extra-index-url https://download.pytorch.org/whl/cu121 || \
    python -m pip install "torch==2.5.1" || warn "CUDA 版 torch 装失败，已尝试CPU版/跳过。"
  python -m pip install "torchvision==0.21.0+cu121" --extra-index-url https://download.pytorch.org/whl/cu121 || \
    python -m pip install "torchvision==0.21.0" || warn "torchvision 装不上，先跳过。"
elif [[ $WANT_ROCM -eq 1 ]]; then
  info "准备安装 ROCm 版 PyTorch（实验性，Fedora上不总是顺滑）。"
  python -m pip install "torch==2.5.1+rocm6.1" --extra-index-url https://download.pytorch.org/whl/rocm6.1 || \
    python -m pip install "torch==2.5.1" || warn "ROCm 版失败，已尝试CPU版/跳过。"
  python -m pip install "torchvision==0.21.0" || warn "torchvision 装不上，先跳过。"
else
  info "安装 CPU 版 PyTorch（稳定第一）……"
  python -m pip install "torch==2.5.1" || warn "CPU 版 torch 装失败，先跳过（非硬依赖也能跑）。"
  python -m pip install "torchvision==0.21.0" || warn "torchvision 装不上，先跳过。"
fi

# -------- 若有项目 requirements.txt，再尝试一遍 --------
if [[ -f dependencies/requirements.txt ]]; then
  info "检测到 requirements.txt，尝试补齐："
  python -m pip install -r dependencies/requirements.txt || warn "requirements 有个别失败，已忽略（核心依赖已装）。"
fi

# -------- 修复 system_control 的日志 bug （已知问题）--------
SC="modules/system_control/module.py"
if [[ -f "$SC" ]]; then
  info "修复 system_control 日志格式化（EnterpriseLogger 不支持 % 占位符）……"
  sed -i.bak \
    's/log\.info("system_control 已启动 (uptime=%.2fs)", time\.time() - self\.init_ts)/log.info(f"system_control 已启动 (uptime={time.time() - self.init_ts:.2f}s)")/g' \
    "$SC" || true
fi

# -------- 健康自检 --------
MISSING=$(python - <<'PY'
import importlib
miss=[]
for m in ["edge_tts","watchdog","psutil","netifaces","pyaudio"]:
    try: importlib.import_module(m)
    except Exception: miss.append(m)
print(" ".join(miss))
PY
)
if [[ -n "$MISSING" ]]; then
  warn "缺少依赖：$MISSING  -> 尝试补装"
  python -m pip install $MISSING || warn "仍有缺失，启动后再根据报错补装。"
fi

# -------- 启动 CLI --------
info "环境就绪，启动 CLI……"
export PYTHONPATH="."
python entry/cli_entry/cli_entry.py || warn "CLI 退出。如有报错，把终端输出发我继续定位。"

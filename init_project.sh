#!/usr/bin/env bash
# ============================================================
# 三花聚顶 · 项目初始化脚本  v2
#   1) 初始化 / 检查  Git 仓库
#   2) 生成 .gitignore
#   3) 可选创建 Python venv 并安装依赖
#   4) 创建标准目录骨架
#   5) 安装 pre-commit 钩子（Black + 大文件检查 + 单测）
# ============================================================

set -euo pipefail

# ---------- 彩色输出助手 ----------
ce() { printf "\033[1;%sm%s\033[0m\n" "$2" "$1"; }  # $1=文本 $2=颜色码

# ---------- ASCII LOGO ----------
ce "   ███████╗ █████╗ ██╗  ██╗██╗  ██╗ █████╗ ████████╗██╗   ██╗██████╗ ██╗ ██████╗" 36
ce "   ██╔════╝██╔══██╗██║  ██║██║  ██║██╔══██╗╚══██╔══╝██║   ██║██╔══██╗██║██╔════╝" 36
ce "   ███████╗███████║███████║███████║███████║   ██║   ██║   ██║██████╔╝██║██║     " 36
ce "   ╚════██║██╔══██║██╔══██║██╔══██║██╔══██║   ██║   ██║   ██║██╔══██╗██║██║     " 36
ce "   ███████║██║  ██║██║  ██║██║  ██║██║  ██║   ██║   ╚██████╔╝██║  ██║██║╚██████╗" 36
ce "   ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝╚═╝ ╚═════╝" 36
ce "========== [三花聚顶 · 项目初始化脚本 v2] ==========" 0

# ---------- 函数 ----------
error_exit() { ce "❌ 错误: $1" 31; exit 1; }

# ---------- 项目根目录校验 ----------
if [[ ! -f "main.py" && ! -d "core" ]]; then
  error_exit "未在项目根目录运行！请进入项目目录后执行此脚本。"
fi
PROJECT_DIR=$(pwd)
ce "📁 项目根目录: $PROJECT_DIR" 34

# ---------- 初始化 Git ----------
if [[ -d ".git" ]]; then
  ce "✅ 已初始化 Git 仓库，跳过 git init" 32
else
  ce "🛠️  初始化 Git 仓库..." 33
  git init
  git add .
  git commit -m "初始化三花聚顶项目结构（重构前快照）"
  ce "✅ Git 初始化完成" 32
fi

# ---------- 生成 / 更新 .gitignore ----------
if [[ -f ".gitignore" ]]; then
  ce "✅ .gitignore 已存在" 32
else
  ce "🧹 创建 .gitignore..." 33
  cat > .gitignore <<'EOF'
# ── Python ─────────────────────────
__pycache__/
*.py[cod]
.mypy_cache/
.pytest_cache/
.venv/
venv/
env/

# ── 构建 ───────────────────────────
build/
dist/
*.egg-info/

# ── IDE / 编辑器 ───────────────────
.vscode/
.idea/
*.swp
.DS_Store

# ── 运行数据与日志 ─────────────────
logs/
*.log
rollback_snapshots/
recordings/
*.wav
*.mp3
memory_*.json
assistant.log
juhe_system.log

# ── 备份 / 临时 ───────────────────
*.bak
*.tmp
*.old
EOF
  git add .gitignore
  git commit -m "添加 .gitignore（缓存 & 日志排除）"
fi

# ---------- 询问并创建 venv ----------
read -rp "🐍 是否创建 Python 虚拟环境? [Y/n] " create_venv
if [[ ${create_venv:-Y} =~ ^[Yy]$ ]]; then
  if [[ ! -d "venv" ]]; then
    ce "🛠️  创建 venv ..." 33
    python3 -m venv venv || error_exit "虚拟环境创建失败"
  fi
  VENV_ACTIVATE="source \"$PROJECT_DIR/venv/bin/activate\""
  ce "🔧 激活虚拟环境: $VENV_ACTIVATE" 35
  eval "$VENV_ACTIVATE"
fi

# ---------- 安装依赖 ----------
if [[ -f "requirements.txt" ]]; then
  read -rp "📦 检测到 requirements.txt，是否安装依赖? [Y/n] " install_deps
  if [[ ${install_deps:-Y} =~ ^[Yy]$ ]]; then
    ce "🔧 安装依赖..." 33
    python -m pip install --upgrade pip
    python -m pip install --upgrade -r requirements.txt
    ce "✅ 依赖安装完成" 32
  fi
else
  ce "ℹ️ 未找到 requirements.txt，跳过依赖安装" 36
fi

# ---------- 创建标准目录 ----------
ce "📂 创建标准目录结构..." 33
mkdir -p data/{logs,recordings,models} docs/{design,api} tests/{unit,integration} scripts || true
touch tests/__init__.py
ce "✅ 目录骨架已就绪" 32

# ---------- 安装 pre-commit 钩子 ----------
HOOK=".git/hooks/pre-commit"
if [[ ! -f "$HOOK" ]]; then
  ce "🔧 安装 pre-commit 钩子..." 33
  cat > "$HOOK" <<'EOF'
#!/usr/bin/env bash
set -e

# 自动格式化（若已安装 Black）
if command -v black &>/dev/null; then
  echo "🚧 运行 Black 格式化..."
  black . --quiet
else
  echo "⚠️  未安装 Black，跳过格式化"
fi

# 大文件检查 >1 MB
echo "🔍 检查大文件..."
for file in $(git diff --cached --name-only --diff-filter=ACM); do
  [[ -f "$file" ]] || continue
  size=$(wc -c <"$file")
  if (( size > 1048576 )); then
    echo "❌ $file 大于 1 MB，请使用 Git LFS 或排除"
    exit 1
  fi
done

# 运行单元测试（若存在 tests/unit/）
if [[ -d tests/unit ]]; then
  echo "🧪 运行快速单测..."
  python -m unittest discover -s tests/unit -p 'test_*.py' || {
    echo "⚠️  单元测试未通过"
    exit 1
  }
fi

echo "✅ pre-commit 检查通过"
EOF
  chmod +x "$HOOK"
  ce "✅ pre-commit 钩子安装完毕" 32
fi

# ---------- 完成 ----------
ce "\n✨ 项目初始化完成！" 32
echo -e "📌 接下来建议：\n" \
        "  1. 激活虚拟环境：\033[1;32m${VENV_ACTIVATE:-source venv/bin/activate}\033[0m\n" \
        "  2. 启动主程序：   \033[1;32mpython main.py\033[0m\n" \
        "  3. 新建分支开发： \033[1;32mgit checkout -b feature/<描述>\033[0m\n" \
        "  4. 推送到远端：   \033[1;32mgit remote add origin <your_repo>\033[0m\n" \
        "                    \033[1;32mgit branch -M main && git push -u origin main\033[0m\n"
ce "三花聚顶，有容乃大，言出法随，祝你开发顺利！" 35

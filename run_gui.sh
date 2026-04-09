#!/usr/bin/env bash
set -euo pipefail

# ============== 基本配置 ==============
PROJECT="/Users/lufei/Desktop/聚核助手2.0"
cd "$PROJECT"

HOST="${SANHUA_HOST:-127.0.0.1}"
PORT="${SANHUA_PORT:-8080}"

MODELS_DIR="$PROJECT/models"
SERVER="${SANHUA_SERVER:-$PROJECT/llama.cpp/build/bin/llama-server}"
LOG_FILE="${SANHUA_LLAMA_LOG:-/tmp/llama_server.log}"

# ============== 工具函数 ==============
die() { echo "[run_gui] ERROR: $*" >&2; exit 1; }
have_cmd() { command -v "$1" >/dev/null 2>&1; }

list_models() {
  (cd "$MODELS_DIR" && find . -type f -name "*.gguf" -print | sed 's|^\./||') || true
}

choose_model_popup() {
  local items="$1"
  /usr/bin/osascript <<OSA
set AppleScript's text item delimiters to linefeed
set theList to {${items}}
set picked to choose from list theList with title "三花聚顶 · 选择模型权重" with prompt "请选择要加载的 GGUF 模型：" OK button name "确认" cancel button name "取消"
if picked is false then
  return ""
else
  return item 1 of picked
end if
OSA
}

choose_model_terminal() {
  local -a arr=("$@")
  echo "[run_gui] 当前环境不支持弹窗或你取消了弹窗，改用终端选择："
  select opt in "${arr[@]}"; do
    if [[ -n "${opt:-}" ]]; then
      echo "$opt"
      return 0
    fi
    echo "无效选择，请重试。"
  done
}

server_ready() {
  curl -sS "http://$HOST:$PORT/v1/models" >/dev/null 2>&1
}

stop_server_if_running() {
  set +u
  local pid=""
  pid="$(lsof -ti :"$PORT" 2>/dev/null || true)"
  pid="${pid:-}"
  if [[ -n "$pid" ]]; then
    echo "[run_gui] 端口 $PORT 已被占用（PID=${pid:-}），准备停止旧服务..."
    kill "$pid" 2>/dev/null || true
    for i in {1..30}; do
      [[ -z "$(lsof -ti :"$PORT" 2>/dev/null || true)" ]] && break
      sleep 0.2
    done
  fi
  set -u
}

start_server() {
  local model_abs="$1"

  echo "[run_gui] 启动 llama-server ..."
  echo "[run_gui] SERVER: $SERVER"
  echo "[run_gui] MODEL : $model_abs"
  echo "[run_gui] HOST  : $HOST"
  echo "[run_gui] PORT  : $PORT"
  echo "[run_gui] LOG   : $LOG_FILE"

  nohup "$SERVER" -m "$model_abs" --host "$HOST" --port "$PORT" >"$LOG_FILE" 2>&1 &

  for i in {1..30}; do
    if server_ready; then
      echo "[run_gui] llama-server ready."
      return 0
    fi
    sleep 0.5
  done

  echo "[run_gui] llama-server 启动未就绪，最后 80 行日志："
  tail -n 80 "$LOG_FILE" || true
  die "llama-server 未能在预期时间内就绪。"
}

# ============== 主流程 ==============
[[ -d "$MODELS_DIR" ]] || die "models 目录不存在：$MODELS_DIR"
[[ -x "$SERVER" ]] || die "llama-server 不可执行或不存在：$SERVER"

models_list="$(list_models)"
[[ -n "$models_list" ]] || die "未在 $MODELS_DIR 下找到任何 .gguf 模型文件"

# 若显式传 SANHUA_MODEL 则跳过选择；否则弹窗/终端选择
chosen_abs=""
if [[ -n "${SANHUA_MODEL:-}" ]]; then
  [[ -f "$SANHUA_MODEL" ]] || die "SANHUA_MODEL 指向的文件不存在：$SANHUA_MODEL"
  chosen_abs="$SANHUA_MODEL"
  echo "[run_gui] 使用 SANHUA_MODEL 指定的模型：$chosen_abs"
else
  items_escaped=$(printf '%s\n' "$models_list" | sed 's/"/\\"/g' | awk '{print "\"" $0 "\""}' | paste -sd, -)

  chosen_rel=""
  if have_cmd osascript; then
    chosen_rel="$(choose_model_popup "$items_escaped" | tr -d '\r')"
  fi

  if [[ -z "${chosen_rel:-}" ]]; then
    mapfile -t arr < <(printf '%s\n' "$models_list")
    chosen_rel="$(choose_model_terminal "${arr[@]}")"
  fi

  [[ -n "${chosen_rel:-}" ]] || die "未选择模型（已取消）。"
  chosen_abs="$MODELS_DIR/$chosen_rel"
fi

[[ -f "$chosen_abs" ]] || die "选择的模型文件不存在：$chosen_abs"

stop_server_if_running
start_server "$chosen_abs"

# ============== server-first：把选模结果注入给 GUI/Python ==============
# 关键原则：Python/AICore 只做 client，不接管 gguf 权重切换
export SANHUA_LLM_BACKEND="llamacpp_server"
export SANHUA_LLAMACPP_BASE_URL="http://$HOST:$PORT"      # 新命名（不带 /v1 也行）
export SANHUA_LLAMA_BASE_URL="http://$HOST:$PORT/v1"      # 旧命名（兼容 engine_compat）
export SANHUA_ACTIVE_MODEL="$(basename "$chosen_abs")"    # 软模型名：用于展示/日志/请求字段

# 可选：兼容旧代码（只作为展示/排障，不要让 Python 用它去切权重）
export SANHUA_MODEL="$chosen_abs"

echo "[run_gui] 启动三花聚顶 GUI..."
echo "[run_gui] ENV  SANHUA_LLM_BACKEND=$SANHUA_LLM_BACKEND"
echo "[run_gui] ENV  SANHUA_LLAMA_BASE_URL=$SANHUA_LLAMA_BASE_URL"
echo "[run_gui] ENV  SANHUA_ACTIVE_MODEL=$SANHUA_ACTIVE_MODEL"
exec ./.venv/bin/python entry/gui_entry/gui_main.py
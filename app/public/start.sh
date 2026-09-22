#!/usr/bin/env bash
# 一键启动（R1.2 v2）：零依赖起步。uv 与 Python 全装进 workspace/.runtime。
# 用法：bash tools/start.sh [workspace]
set -euo pipefail
WS="${1:-${ASSIST_WORKSPACE:-$HOME/assignment-assistant-workspace}}"
mkdir -p "$WS"
LOG="$WS/start.log"; echo "=== START $(date) ===" >> "$LOG"
export PATH="$WS/.runtime/uv:$HOME/.local/bin:$PATH"
export UV_TOOL_BIN_DIR="$WS/.runtime/uv"
export UV_PYTHON_INSTALL_DIR="$WS/.runtime/python"
export UV_CACHE_DIR="$WS/.runtime/cache/uv"
export UV_PROJECT_ENVIRONMENT="$WS/.runtime/venv"
export ASSIST_WORKSPACE="$WS"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "[1/5] 确保工作区 $WS"
[ -d "$WS" ] || mkdir -p "$WS"
echo "[2/5] 安装 uv（若无）"
command -v uv >/dev/null 2>&1 || {
  curl -LsSf https://astral.sh/uv/install.sh | sh | tee -a "$LOG" |
    grep -v "^\s*$" || true
  export PATH="$HOME/.local/bin:$PATH"
}
command -v uv >/dev/null 2>&1 || { echo "uv 安装失败"; exit 1; }
echo "[3/5] 为 workspace 准备 Python（uv 托管至 $WS/.runtime/python）"
uv python install 3.13 >>"$LOG" 2>&1 || echo "[WARN] 已有可用 Python 则忽略"
[ -x "$WS/.runtime/venv/bin/python" ] || uv venv --python 3.13 "$WS/.runtime/venv" >>"$LOG" 2>&1
echo "[3/5] 安装引擎依赖"
uv pip install -e "$ROOT/engine" --python "$WS/.runtime/venv/bin/python" >>"$LOG" 2>&1
echo "[4/5] 起引擎 http://127.0.0.1:8601/"
ASSIST="$WS/.runtime/venv/bin/assist"
(sleep 1.2; BROWSER=""; for b in xdg-open open; do command -v "$b" >/dev/null && BROWSER="$b" && break; done
 [ -n "$BROWSER" ] && "$BROWSER" "http://127.0.0.1:8601/" 2>/dev/null) &
"$ASSIST" serve --port 8601 2>&1 | tee -a "$LOG"
echo "引擎已退出。日志： $LOG"

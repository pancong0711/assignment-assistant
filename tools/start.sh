#!/usr/bin/env bash
# 一键启动（R1.2）：教师双击/一行命令即可进入 Companion 模式。
# 流程：确保 uv → 建/更新 workspace/.runtime/venv（D14）→ 装依赖 → 起引擎 → 自动开浏览器。
# 用法：bash tools/start.sh [workspace]   （缺省自动查找/创建 ~/assignment-assistant-workspace）
set -euo pipefail
WS="${1:-${ASSIST_WORKSPACE:-$HOME/assignment-assistant-workspace}}"
mkdir -p "$WS"
export ASSIST_WORKSPACE="$WS"
if ! command -v uv >/dev/null 2>&1; then
  echo "安装 uv（本地用户级）…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
ENGINE_DIR="$(cd "$(dirname "$0")/../engine" && pwd)"
VENV="$WS/.runtime/venv"
if [ ! -x "$VENV/bin/python" ]; then uv venv --python 3.13 "$VENV"; fi
export UV_CACHE_DIR="$WS/.runtime/cache/uv" UV_PROJECT_ENVIRONMENT="$VENV"
uv pip install -e "$ENGINE_DIR" --python "$VENV/bin/python"
ASSIST="$VENV/bin/assist"
ASSIST="$VENV/bin/assist"
BROWSER=""
for B in xdg-open open; do command -v $B >/dev/null && BROWSER="$B" && break; done
"$ASSIST" bootstrap --workspace "$WS" --no-sync --quiet || true
("$ASSIST" serve --port 8601 &) && sleep 1.2
echo "引擎 http://127.0.0.1:8601/ 已启动（本终端关闭即停）"
if [ -n "${BROWSER:-}" ]; then "$BROWSER" "http://127.0.0.1:8601/" 2>/dev/null || true; fi
wait

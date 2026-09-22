#!/usr/bin/env bash
# [R1.2 v6] assignment-assistant launcher (bash side; zero-dependency bootstrap).
# D28: the folder THIS script lives in IS the workspace.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WS="${1:-$SCRIPT_DIR}"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG="$WS/start.log"
mkdir -p "$WS" "$WS/.runtime/cache/uv" "$WS/.runtime/browsers"
export PATH="$WS/.runtime/uv:$WS/.runtime/python:$HOME/.local/bin:$PATH"
export UV_INSTALL_DIR="$WS/.runtime/uv"
export UV_PYTHON_INSTALL_DIR="$WS/.runtime/python"
export UV_CACHE_DIR="$WS/.runtime/cache/uv"
export UV_PROJECT_ENVIRONMENT="$WS/.runtime/venv"
export ASSIST_WORKSPACE="$WS"
echo =============================== >> "$LOG"
echo "[1/6] workspace = $WS"
echo "[2/6] install uv if missing"
command -v uv >/dev/null 2>&1 || {
  if [ "${CN_OFFICIAL:-}" = "official" ]; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  else
    curl -LsSf https://ghfast.top/https://astral.sh/uv/install.sh | sh || curl -LsSf https://astral.sh/uv/install.sh | sh
  fi
  export PATH="$HOME/.local/bin:$PATH"
  command -v uv >/dev/null 2>&1 || { echo "[FAIL] uv not available - retry"; exit 1; }
}
echo "[3/6] install managed python 3.13"
uv python install 3.13 >> "$LOG" 2>&1 || true
echo "[4/6] create venv (D14)"
[ -x "$WS/.runtime/venv/bin/python" ] || uv venv --python 3.13 "$WS/.runtime/venv" >> "$LOG" 2>&1
echo "[5/6] install engine dependencies"
if [ -f "$ROOT/engine/pyproject.toml" ]; then
  uv pip install -e "$ROOT/engine" --python "$WS/.runtime/venv/bin/python" >> "$LOG" 2>&1
else
  echo "[INFO] no engine source next to script - installing assist-engine from PyPI"
  uv pip install assist-engine --python "$WS/.runtime/venv/bin/python" >> "$LOG" 2>&1
fi
echo "[6/6] start engine http://127.0.0.1:8601/"
(sleep 1.2; BROWSER=""; for b in xdg-open open; do command -v "$b" >/dev/null && BROWSER="$b" && break; done
 [ -n "$BROWSER" ] && "$BROWSER" "http://127.0.0.1:8601/" 2>/dev/null) &
"$WS/.runtime/venv/bin/assist" serve --port 8601 2>&1 | tee -a "$LOG"
echo engine exited. log: "$LOG"

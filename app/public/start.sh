#!/usr/bin/env bash
# [R1.2 v9] launcher (bash side) - PYTHON-FIRST bootstrap (D32), zero system pollution.
# TUNA mirrors by default: pypi/tuna + miniconda/tuna. Everything under <this dir>/.runtime.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WS="${1:-$SCRIPT_DIR}"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG="$WS/start.log"
mkdir -p "$WS" "$WS/.runtime/cache/uv" "$WS/.runtime/browsers"
: > "$LOG" || true
echo =============================== >> "$LOG"
export PATH="$WS/.runtime/miniconda/bin:$HOME/.local/bin:$PATH"
export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export PLAYWRIGHT_DOWNLOAD_HOST="${PLAYWRIGHT_DOWNLOAD_HOST:-https://npmmirror.com/mirrors/playwright/}"
export ASSIST_WORKSPACE="$WS"
echo "[1/6] workspace = $WS"
echo "[2/6] detect python (system first; miniconda fallback from TUNA)"
PY="py"
PY="python3"
command -v python3 >/dev/null 2>&1 && PY="python3" || :
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "[2/6] no system python - downloading Miniconda3-latest from TUNA (into workspace)"
  curl -fL --retry 2 --connect-timeout 20 -o "$WS/.runtime/miniconda.sh" \
    "https://mirrors.tuna.tsinghua.edu.cn/anaconda/miniconda/Miniconda3-latest-$(case "$(uname -m)" in x86_64) echo Linux-x86_64 ;; aarch64) echo Linux-aarch64 ;; *) echo Linux-x86_64 ;; esac).sh"
  bash "$WS/.runtime/miniconda.sh" -b -p "$WS/.runtime/miniconda" >> "$LOG" 2>&1
  PY="$WS/.runtime/miniconda/bin/python3"
fi
echo "using python: $PY"
echo "[3/6] create venv (workspace/.runtime/venv, D14)"
[ -x "$WS/.runtime/venv/bin/python" ] || "$PY" -m venv "$WS/.runtime/venv" >> "$LOG" 2>&1
VP="$(cd "$WS/.runtime/venv/bin" && pwd)/pip"
"$VP" --version >> "$LOG" 2>&1
echo "[5/6] install engine dependencies (TUNA index)"
if [ -f "$ROOT/engine/pyproject.toml" ]; then
  ENGINE_DIR="$ROOT/engine"
fi
if [ -z "${ENGINE_DIR:-}" ] && [ -x "$WS/_engine/engine/pyproject.toml" ]; then
  ENGINE_DIR="$WS/_engine/engine"
fi
if [ -z "${ENGINE_DIR:-}" ]; then
  echo "[5/6a] engine source: github.io Pages (5 attempts x sleep10) -> github release -> full repo"
  for i in 1 2 3 4 5; do
    curl -fL --connect-timeout 60 --max-time 180 -o "$WS/engine-main.zip" \
      "https://pancong0711.github.io/assignment-assistant/dl/engine-main.zip" && break
    sleep 10
  done
  [ -s "$WS/engine-main.zip" ] || curl -fL --retry 3 --connect-timeout 60 --retry-delay 10 -o "$WS/engine-main.zip" \
    "https://github.com/pancong0711/assignment-assistant/releases/download/dl/engine-main.zip"
  if [ -s "$WS/engine-main.zip" ]; then
    mkdir -p "$WS/_engine"
    unzip -q -o "$WS/engine-main.zip" -d "$WS/_engine" >> "$LOG" 2>&1
    ENGINE_DIR="$WS/_engine/engine"
  else
    echo "[5/6c] last resort: full repo (ghfast -> github direct)"
    curl -fL --retry 2 --connect-timeout 20 -o "$WS/full-repo.zip" \
      "https://ghfast.top/https://github.com/pancong0711/assignment-assistant/archive/refs/heads/main.zip" \
      || curl -fL --retry 2 --connect-timeout 20 -o "$WS/full-repo.zip" \
      "https://github.com/pancong0711/assignment-assistant/archive/refs/heads/main.zip"
    mkdir -p "$WS/_enginefull"
    unzip -q -o "$WS/full-repo.zip" -d "$WS/_enginefull" >> "$LOG" 2>&1
    ENGINE_DIR=$(find "$WS/_enginefull" -maxdepth 3 -name engine -type d | head -1)
  fi
fi
if [ ! -f "$ENGINE_DIR/pyproject.toml" ]; then
  echo "[FAIL] engine source unusable across all mirrors - see guide"
  notepad "$LOG" 2>/dev/null || true
  exit 1
fi
"$VP" install -e "$ENGINE_DIR" --index-url "$UV_DEFAULT_INDEX" >> "$LOG" 2>&1
echo "[6/6] start engine http://127.0.0.1:8601/"
(sleep 1.2; BROWSER=""; for b in xdg-open open; do command -v "$b" >/dev/null && BROWSER="$b" && break; done
 [ -n "$BROWSER" ] && "$BROWSER" "http://127.0.0.1:8601/" 2>/dev/null) &
"$WS/.runtime/venv/bin/assist" serve --port 8601 2>&1 | tee -a "$LOG"
echo engine exited. log: "$LOG"

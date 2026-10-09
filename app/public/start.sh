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
export ASSIST_SUPERVISED=1
STAGE="$WS/_engine/staging"
PENDING="$WS/_engine/update.pending"
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
apply_pending() {
  [ -f "$PENDING" ] || return 0
  if [ ! -f "$STAGE/engine/pyproject.toml" ]; then
    echo "[update] staging missing: $STAGE/engine/pyproject.toml"
    return 1
  fi
  echo "[update] applying staged engine before start..."
  rm -rf "$ENGINE_DIR.bak"
  mv "$ENGINE_DIR" "$ENGINE_DIR.bak"
  cp -a "$STAGE/engine/." "$ENGINE_DIR/"
  if "$VP" install -e "$ENGINE_DIR" -i "$UV_DEFAULT_INDEX" >>"$LOG" 2>&1; then
    [ -f "$STAGE/engine-version.json" ] && cp -f "$STAGE/engine-version.json" "$WS/_engine/engine-version.json"
    rm -rf "$ENGINE_DIR.bak" "$STAGE" "$PENDING"
    echo "[update] engine update applied successfully."
    return 0
  fi
  echo "[update] pip install failed; rolling back..."
  rm -rf "$ENGINE_DIR"
  mv "$ENGINE_DIR.bak" "$ENGINE_DIR"
  "$VP" install -e "$ENGINE_DIR" -i "$UV_DEFAULT_INDEX" >>"$LOG" 2>&1 || true
  mv -f "$PENDING" "$PENDING.failed" 2>/dev/null || true
  return 1
}

echo "[6/6] start engine http://127.0.0.1:8601/"
(sleep 1.2; BROWSER=""; for b in xdg-open open; do command -v "$b" >/dev/null && BROWSER="$b" && break; done
 [ -n "$BROWSER" ] && "$BROWSER" "http://127.0.0.1:8601/" 2>/dev/null) &
apply_pending || exit 1
while true; do
  set +e
  if [ -x "$ENGINE_DIR/run_engine.sh" ]; then
    "$ENGINE_DIR/run_engine.sh" "$WS/.runtime/venv/bin/python" "$WS" 8601
  else
    "$WS/.runtime/venv/bin/python" -m assist.cli serve --workspace "$WS" --port 8601
  fi
  rc=$?
  set -e
  if [ "$rc" -eq 75 ]; then
    echo "[restart] engine restart requested; applying pending update if any..."
    apply_pending || exit 1
    continue
  fi
  echo "engine exited (rc=$rc). log: $LOG"
  break
done

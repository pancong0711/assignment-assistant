#!/usr/bin/env bash
# D71 stable engine adapter: the external launcher calls this file by path;
# engine internals (assist.cli / future entrypoints) are adapted here.
set -euo pipefail
PY="${1:-python3}"
WS="${2:-$(cd "$(dirname "$0")/../.." && pwd)}"
PORT="${3:-8601}"
exec "$PY" -m assist.cli serve --workspace "$WS" --port "$PORT"

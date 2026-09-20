"""workspace 解析与 settings.local.json 读取（05-D14：一切引擎环境收纳在 workspace/.runtime）。"""

import json
import os
from pathlib import Path

DEFAULT_WORKSPACE = Path.home() / "assignment-assistant-workspace"

WORKSPACE_DIR_HINTS = {
    "kb": None,
    "classes": None,
    "exports": None,
    ".runtime": None,
}


def find_workspace(explicit: str | None = None, cwd: Path | None = None) -> Path:
    """定位 workspace：显式参数 > ASSIST_WORKSPACE 环境变量 > 从 cwd 向上找 kb/ > 默认目录。"""
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("ASSIST_WORKSPACE")
    if env:
        return Path(env).expanduser().resolve()
    cwd = (cwd or Path.cwd()).resolve()
    for p in [cwd, *cwd.parents]:
        if (p / "kb" / "problems.xlsx").exists() or (p / "settings.local.json").exists():
            return p
    return DEFAULT_WORKSPACE


def load_workspace_settings(ws: Path) -> dict:
    fn = ws / "settings.local.json"
    if fn.exists():
        try:
            return json.loads(fn.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def runtime_env(ws: Path) -> dict[str, str]:
    """返回 D14 所需环境变量（venv/uv 缓存/Playwright 内核全部收纳进 .runtime）。"""
    rt = ws / ".runtime"
    return {
        "UV_PROJECT_ENVIRONMENT": str(rt / "venv"),
        "UV_CACHE_DIR": str(rt / "cache" / "uv"),
        "PLAYWRIGHT_BROWSERS_PATH": str(rt / "browsers"),
        "ASSIST_WORKSPACE": str(ws),
    }


def apply_runtime_env(ws: Path) -> None:
    for k, v in runtime_env(ws).items():
        os.environ.setdefault(k, v)

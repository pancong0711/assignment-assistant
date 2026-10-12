"""assist — assignment-assistant engine.

来源合并自 _legacy/2603paperDesign 与 _legacy/2601playwright（见 docs/03、07）。
"""

from pathlib import Path

# engine/ 目录（package src/assist → 上3级）
ASSIST_ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR = ASSIST_ROOT / "assets"

__version__ = "0.4.0"

_COMMIT_CACHE: str | None = None


def get_commit() -> str:
    """D77：返回短 commit（优先 env ASSIST_ENGINE_COMMIT，其次本地 git）。"""
    global _COMMIT_CACHE
    if _COMMIT_CACHE is not None:
        return _COMMIT_CACHE
    import os
    v = (os.environ.get("ASSIST_ENGINE_COMMIT") or "").strip()
    if v:
        _COMMIT_CACHE = v[:12]
        return _COMMIT_CACHE
    try:
        import subprocess
        repo_root = Path(__file__).resolve().parents[3]
        cp = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(repo_root),
                            capture_output=True, text=True, timeout=1)
        _COMMIT_CACHE = cp.stdout.strip()[:12] if cp.returncode == 0 else ""
    except Exception:
        _COMMIT_CACHE = ""
    return _COMMIT_CACHE

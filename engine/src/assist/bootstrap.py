"""assist bootstrap / workspace 初始化（05-D14）。

职责：
1. 创建 workspace 目录骨架（kb/ classes/ exports/）
2. 在 workspace/.runtime 下建立引擎环境（venv + 缓存 + 浏览器内核）
3. 写 settings.local.json 雏形（不含任何敏感数据）
4. uninstall = 删除 workspace 一个目录（README/手册指引）
"""

import os
import shutil
import subprocess
from pathlib import Path

from loguru import logger

from .log import setup_logging
from .workspace import find_workspace, load_workspace_settings

_SKELETON = ["kb/fig", "kb/.history", "kb/export", "classes", "exports"]
_SETTINGS_EXAMPLE = {
    "course_default": "",
    "engine_addr": "http://127.0.0.1:8601",
    "llm": {"api_key": "", "transcription_model": "", "evaluation_model": ""},
    "fonts": {},
    "confirm_before_upload": False,
}


def bootstrap(
    ws: str | None,
    sync_deps: bool = True,
    quiet: bool = False,
) -> Path:
    """初始化/修复 workspace；返回 workspace 路径。

    sync_deps=True 时在 workspace/.runtime/venv 建立/更新引擎环境：
        uv venv + uv pip install <engine root>
    并把 UV_CACHE_DIR / PLAYWRIGHT_BROWSERS_PATH 指进 .runtime（05-D14）。
    """
    setup_logging(not quiet)
    ws_path = Path(ws).expanduser().resolve() if ws else find_workspace()
    logger.info(f"workspace: {ws_path}")

    for d in _SKELETON:
        (ws_path / d).mkdir(parents=True, exist_ok=True)

    settings_fn = ws_path / "settings.local.json"
    if not settings_fn_exists(settings_fn):
        settings = dict(_SETTINGS_EXAMPLE)
        settings_fn.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(f"已生成 {settings_fn.name}（不含密钥，请自行填写）")

    rt = ws_path / ".runtime"
    (rt / "cache" / "uv").mkdir(parents=True, exist_ok=True)
    (rt / "browsers").mkdir(parents=True, exist_ok=True)

    if sync_deps:
        engine_root = _engine_root()
        if shutil.which("uv") is None:
            logger.warning("未检测到 uv，跳过依赖安装。安装：curl -LsSf https://astral.sh/uv/install.sh | sh")
            return ws_path
        env = {
            **os.environ,
            "UV_CACHE_DIR": str(rt / "cache" / "uv"),
            "UV_PROJECT_ENVIRONMENT": str(rt / "venv"),
        }
        rc = subprocess.call(
            ["uv", "pip", "install", "-e", str(engine_root)],
            env=env,
            stdout=(subprocess.DEVNULL if quiet else None),
            stderr=(subprocess.STDOUT if quiet else None),
        )
        if rc == 0:
            logger.info(f"依赖已安装到 {rt / 'venv'}（删除 workspace 即完全卸载）")
        else:
            logger.warning(f"依赖安装失败（exit {rc}），可用安装脚本重试")
    return ws_path


def settings_fn_exists(fn: Path) -> bool:
    return fn.exists()


def _engine_root() -> Path:
    return Path(__file__).resolve().parents[2]

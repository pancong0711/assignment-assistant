"""fonts — 迁移自 _legacy/2603paperDesign/src/paperdesign/config/settings.py 的字体 fallback 链，
改为显式参数：workspace 用户字体 → engine assets（Noto，OFL，可随仓库分发）→ 系统字体。"""

import json
from pathlib import Path

from loguru import logger

from .. import ASSETS_DIR

_ENGINE_FONTS = ASSETS_DIR / "fonts"
_ENGINE_FONTS_JSON = _ENGINE_FONTS / "fonts.json"


def register_font(reportlab_name: str, primary_name: str, fallback_name: str,
                  workspace: Path | None = None, user_cfg: dict | None = None) -> str:
    """按 fallback 链注册中文字体，返回实际路径。找不到任何文件时返回 primary_name
    （交给 reportlab TTFSearchPath 找系统字体，如 Windows 的 simsun.ttc）。"""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase import ttfonts

    candidates: list[Path] = []

    fonts_cfg = {}
    if user_cfg:
        fonts_cfg = user_cfg.get("fonts", {}) or {}
    elif _ENGINE_FONTS_JSON.exists():
        try:
            fonts_cfg = json.loads(_ENGINE_FONTS_JSON.read_text(encoding="utf-8")) or {}
        except Exception:
            fonts_cfg = {}
    if (u := fonts_cfg.get(primary_name) or fonts_cfg.get(fallback_name)):
        candidates.append(Path(u).expanduser())

    if workspace is not None:
        candidates += [workspace / primary_name,
                       workspace / "assets" / "fonts" / primary_name]

    # fonts.json 映射：simsun.ttc/simkai.ttf → 开源 TextBox 备选（wqy，GPL+字体例外）
    try:
        mapping = json.loads(_ENGINE_FONTS_JSON.read_text(encoding="utf-8"))
    except FileNotFoundError:
        mapping = {}
    mapped = mapping.get(primary_name)
    if mapped:
        candidates.insert(0, _ENGINE_FONTS / mapped)
    candidates += [_ENGINE_FONTS / fallback_name, Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
                   Path(primary_name)]

    for p in candidates:
        if Path(p).exists():
            try:
                pdfmetrics.registerFont(ttfonts.TTFont(reportlab_name, str(p)))
                logger.debug(f"字体 {reportlab_name} = {p}")
                return str(p)
            except Exception as exc:  # noqa: TRY203 — 继续尝试下一个候选
                logger.warning(f"字体加载失败 {p}: {exc}")
    logger.warning(f"未找到字体 {primary_name}/{fallback_name}，交系统字体处理")
    return primary_name

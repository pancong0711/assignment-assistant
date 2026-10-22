"""fonts — 迁移自 _legacy/2603paperDesign/src/paperdesign/config/settings.py 的字体 fallback 链，
改为显式参数：workspace 用户字体 → engine assets（Noto，OFL，可随仓库分发）→ 系统字体。"""

import json
from pathlib import Path

from loguru import logger

from .. import ASSETS_DIR

_ENGINE_FONTS = ASSETS_DIR / "fonts"
_ENGINE_FONTS_JSON = _ENGINE_FONTS / "fonts.json"

# reportlab 自带的中文 CID 字体（不需要外部字体文件）；无系统/workspace 中文字体时兜底。
CID_FALLBACK_NAME = "STSong-Light"


def register_font(reportlab_name: str, primary_name: str, fallback_name: str,
                  workspace: Path | None = None, user_cfg: dict | None = None) -> str:
    """按 fallback 链注册中文字体，返回**实际可用**的字体名。

    返回：注册成功时的**字体名**（即 `reportlab_name`），或 `CID_FALLBACK_NAME`
    （内置 CID 中文字体兜底），或 ""（全部不可用）。
    调用方应使用返回值作为 fontName，而不是假定 `reportlab_name` 一定可渲染。
    """
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
                return reportlab_name   # 返回注册名（不是文件路径）
            except Exception as exc:  # noqa: TRY203 — 继续尝试下一个候选
                logger.warning(f"字体加载失败 {p}: {exc}")

    # 全部候选不存在 → 降级用 reportlab 内置 CID 中文字体（无需字体文件），
    # 以 `reportlab_name` 注册，调用方无感。避免旧行为返回 primary_name 导致
    # reportlab 抛 "Can't map determine family/bold/italic"（CI 无中文字体时必挂）。
    try:
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        if reportlab_name not in pdfmetrics.getRegisteredFontNames():
            font = UnicodeCIDFont(CID_FALLBACK_NAME)
            # UnicodeCIDFont 的 fontName 是 CID_FALLBACK_NAME；用别名注册不可行，
            # 因此调用方通过返回值拿到实际可用名字（见 layout 的 _body_font）。
            pdfmetrics.registerFont(font)
        logger.warning(
            f"未找到中文字体 {primary_name}/{fallback_name}，"
            f"降级为内置 CID 字体 {CID_FALLBACK_NAME}（中文可显示，字重/字形与宋体不同）。"
            "建议安装 fonts-wqy-microhei 或运行 tools/fonts-download.sh")
        return CID_FALLBACK_NAME
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"内置 CID 中文字体也不可用：{exc}")
        return ""

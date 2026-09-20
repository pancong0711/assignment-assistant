"""水印生成与合并。迁移自 _legacy/2603paperDesign/src/paperdesign/output/watermark.py：
- 移除 pandas 依赖、底部试用脚本；
- supports pagesize 参数（竖/横版通吃：横版水印画布传 landscape(A4)）；
- PyPDF2 → pypdf（同一作者的延续库）。"""

import io
from pathlib import Path

from loguru import logger
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .fonts import register_font

_LOGO_FILES = {"01": "logo.png", "university": "logo.png"}
# logo 路径与用户覆盖简化为 assets/watermark/ 目录（旧 get_watermark_path 的覆盖链由 assets/fonts 的 fallback 思想落地）


def _ovarg(overrides, name, pos, ratio, alpha):
    o = (overrides or {}).get(name)
    if isinstance(o, dict):
        return o.get("pos", pos), float(o.get("ratio", ratio)), float(o.get("alpha", alpha))
    return pos, ratio, alpha


def _watermark_paths(assets_dir: Path, overrides: dict | None = None) -> dict:
    """默认占位 logo；可被用户配置覆盖（迁移自 2603 config/settings.py get_watermark_path 的
    用户覆盖链，05-D15 同思路）。settings.local.json: watermark: {university: 路径, text:..., boat:...}"""
    d = {"university": assets_dir / "watermark" / "logo-university.png",
         "text": assets_dir / "watermark" / "logo-text.png",
         "boat": assets_dir / "watermark" / "logo-boat.png"}
    for k, v in (overrides or {}).items():
        if k in d and v:
            p = Path(v)
            d[k] = p if p.is_absolute() else assets_dir / str(v)  # 相对则相对 assets
    return d


def watermark_preset(assets_dir: Path, pagesize=A4) -> dict:
    """生成承载水印的 canvas（内存）。迁移自 _watermarkPreset()，增加 pagesize 参数。"""
    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=pagesize)
    return {"canvas_obj": c, "packet": packet, "width": pagesize[0], "height": pagesize[1]}


def watermark_gen(canvas_info: dict, page_info, assets_dir: Path,
                  preset: str = "2603", overrides: dict | None = None) -> dict:
    """单页水印（logo + 页码文字）。迁移自 _watermarkGen()/_watermarkGen2603()。

    overrides: {logo名: True|路径|{path?, pos?, ratio?, alpha?}} —— 支持
    用户自定义图片路径与摆位(pos)/大小(ratio)/透明度(alpha)（为 PWA
    水印设计器铺位）。preset "2603" 为现行版式，"2512" 为旧版回退。
    """
    paths = _watermark_paths(assets_dir, overrides)
    ov = overrides or {}
    if preset == "2603":
        u = _ovarg(ov, "university", "rt", 0.125, 0.5)
        tl = _ovarg(ov, "text", "lc", 0.1, 0.3)
        bb = _ovarg(ov, "boat", "lb", 0.3, 0.5)
        canvas_info = logo_draw(canvas_info, paths["university"], *u)
        canvas_info = logo_draw(canvas_info, paths["text"], *tl)
        canvas_info = logo_draw(canvas_info, paths["boat"], *bb)
        text_draw_enhanced(canvas_info, page_info if isinstance(page_info, list) else [page_info],
                           "rc", fontsize=60, transparency=0.4, direction="horizontal")
    else:  # legacy "2512"
        canvas_info = logo_draw(canvas_info, paths["university"], "rt", 0.125, 0.5)
        canvas_info = logo_draw(canvas_info, paths["text"], "rc", 0.1, 0.3)
        canvas_info = logo_draw(canvas_info, paths["boat"], "rb", 0.3, 0.5)
        text_draw_enhanced(canvas_info, [str(p) for p in page_info], "c",
                           fontsize=60, transparency=0.4, direction="vertical")
    canvas_info["canvas_obj"].showPage()
    return canvas_info


def watermark_end(fn_content: str, canvas_info: dict) -> str:
    """把水印页写出为 <content>-watermark.pdf。迁移自 _watermarkEnd()。"""
    c, packet = canvas_info["canvas_obj"], canvas_info["packet"]
    c.save()
    packet.seek(0)
    fn_watermark = fn_content[:-4] + "-watermark.pdf"
    Path(fn_watermark).write_bytes(packet.getvalue())
    logger.info("watermark_end() 完成")
    return fn_watermark


def logo_draw(canvas_info: dict, logo_path: str | Path, pos_sp: str,
              ratio: float = 0.2, transparency: float = 0.3) -> dict:
    """logo 绘制。迁移自 _logoDraw()。"""
    c, packet = canvas_info["canvas_obj"], canvas_info["packet"]
    width, height = canvas_info["width"], canvas_info["height"]
    pic = ImageReader(str(logo_path))
    pw, ph_ = pic.getSize()
    target_width = ratio * width
    rate = pw / target_width
    pw /= rate; ph_ /= rate
    pos = _anchor(pos_sp, width, height, pw, ph_)
    c.setFillAlpha(transparency)
    c.drawImage(str(logo_path), pos[0], pos[1], width=pw, height=ph_,
                preserveAspectRatio=True, mask="auto")
    return canvas_info


def text_draw(canvas_info: dict, text: str, pos_sp: str, fontname: str = "simsun",
              fontsize: int = 40, transparency: float = 0.3) -> dict:
    """单行文字水印。迁移自 _textDraw()。"""
    c = canvas_info["canvas_obj"]
    c.setFont(fontname, fontsize)
    c.setFillColor("blue", alpha=transparency)
    c.setFillAlpha(transparency)
    x, y = _text_anchor(canvas_info, text, pos_sp, fontname, fontsize)
    c.drawString(x, y, text)
    return canvas_info


def _text_anchor(canvas_info, text, pos_sp, fontname, fontsize):
    c = canvas_info["canvas_obj"]
    w = c.stringWidth(text, fontname, fontsize)
    h = fontsize
    return _anchor(pos_sp, canvas_info["width"], canvas_info["height"], w, h)


def _anchor(pos_sp, W, H, w, h):
    table = {
        "c":  ((W - w) / 2, (H - h) / 2),
        "lc": (0, (H - h) / 2),
        "rc": (W - w, (H - h) / 2),
        "lb": (0, 0),
        "lt": (0, H - h),
        "rb": (W - w, 0),
        "rt": (W - w, H - h),
    }
    return table.get(pos_sp, table["c"])


def _text_pos(canvas_info, c, text, pos_sp, fontname, fontsize):
    w = c.stringWidth(text, fontname, fontsize)
    h = fontsize
    return _anchor(pos_sp, canvas_info["width"], canvas_info["height"], w, h)


def text_draw_enhanced(canvas_info: dict, text_list, pos_sp: str, fontname: str = "simsun",
                       fontsize: int = 40, transparency: float = 0.3,
                       direction: str = "horizontal", line_spacing: float = 1.2,
                       column_spacing: float | None = None) -> dict:
    """多行/多列文字水印。迁移自 _textDrawEnhanced()（精简为 horizontal/vertical 两分支）。"""
    c, packet = canvas_info["canvas_obj"], canvas_info["packet"]
    width, height = canvas_info["width"], canvas_info["height"]
    c.setFont(fontname, fontsize)
    c.setFillColor("blue", alpha=transparency)
    c.setFillAlpha(transparency)
    char_width = max(c.stringWidth("中", fontname, fontsize), 1e-6)  # 中文字符宽
    line_h = fontsize * line_spacing

    if column_spacing is None:
        column_spacing = char_width * 0.5

    def pos_for(block_w, block_h):
        return _anchor(pos_sp, width, height, block_w, block_h)

    if direction == "horizontal":
        max_w = max(c.stringWidth(line, fontname, fontsize) for line in text_list)
        block_h = len(text_list) * line_h
        x0, y_top = pos_for(max_w, block_h)
        y_top = y_top + block_h - fontsize
        for i, line in enumerate(text_list):
            c.drawString(x0, y_top - i * line_h, line)
    else:  # vertical：每元素一列，自上而下逐字
        cw = [char_width] * len(text_list)
        max_col_h = max(len(col) for col in text_list) * line_h
        total_w = sum(cw) + column_spacing * (len(text_list) - 1)
        x0, y_top = pos_for(total_w, max_col_h)
        y_top = y_top + max_col_h - fontsize
        x = x0
        for col in text_list:
            for i, ch in enumerate(col):
                c.drawString(x, y_top - i * line_h, ch)
            x += column_spacing
    return canvas_info


def merge_watermark(fn_content: str, fn_watermark: str) -> str:
    """内容页与水印页合并。迁移自 _mergeWatermark()（PyPDF2 → pypdf），
    保留清理中间产物的行为，返回最终文件。"""
    content = PdfReader(fn_content)
    marks = PdfReader(fn_watermark)
    writer = PdfWriter()
    for i, page in enumerate(content.pages):
        if i < len(marks.pages):
            page.merge_page(marks.pages[i])
        writer.add_page(page)
    fn_out = fn_watermark[:-4] + "-combine.pdf"
    with open(fn_out, "wb") as f:
        writer.write(f)
    for p in (fn_content, fn_watermark):
        Path(p).unlink(missing_ok=True)
    logger.info("merge_watermark() 完成")
    return fn_out

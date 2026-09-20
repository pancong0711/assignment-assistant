"""作业纸排版：竖版 A4（基线还原）+ 横版 A4 双题（新增）。

迁移/改造自 _legacy/2603paperDesign/src/paperdesign/output/reportlabtools.py：
- _reportlabPreset/_tmpPageFilling/assignment2512 → 竖版管线（图缩放逻辑保留）；
- 去 numpy/pandas 依赖；PyPDF2 → pypdf（watermark 模块）；
- 页眉/页脚改为 PageTemplate.onPage 回调逐页直接绘制：
  旧结构中页眉页脚也占用 frame，多题多页时页脚易被挤到次页；
  onPage 后每页固定、行为稳定；
- 横版：landscape(A4)，中部左右两个内容 frame，各承载一道题（FrameBreak 分隔）。
"""

from datetime import datetime
from pathlib import Path

from loguru import logger
from PIL import Image as PILImage
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (BaseDocTemplate, Frame, FrameBreak, Image,
                                PageBreak, PageTemplate, Paragraph)

from .. import ASSETS_DIR
from .fonts import register_font
from .watermark import merge_watermark, watermark_end, watermark_gen, watermark_preset

A4_W, A4_H = A4


# ---------------- 样式 ----------------

def _contents_style():
    return ParagraphStyle("assign_text", fontName="simsun", fontSize=11, leading=16)


def _fitted_image(img_path: str, max_w: float, max_h: float) -> Image:
    """300dpi 图按最大宽/高比例缩放（迁移自 _tmpPageFilling 的 ratio 逻辑）。"""
    img_w, img_h = PILImage.open(img_path).size
    ratio = min(max_w / img_w, max_h / img_h)
    return Image(img_path, width=img_w * ratio, height=img_h * ratio)


# ---------------- 内容 frame ----------------

def portrait_frames():
    """竖版：单个内容 frame（头部/页脚由 onPage 画）。尺寸沿用 _reportlabPreset 比例。"""
    x1 = 0.04 * A4_W
    width = 0.92 * A4_W
    top = 0.885 * A4_H
    bottom = 0.055 * A4_H
    return [Frame(x1=x1, y1=bottom, width=width, height=top - bottom,
                  topPadding=0, id="content_frame_id", showBoundary=False)]


def landscape_frames():
    """横版：中部左右两个内容 frame，各一道题；头/页脚由 onPage 画。"""
    pw, ph = landscape(A4)
    x1 = 0.03 * pw
    margin_w = 0.94 * pw
    gap = 0.02 * pw
    half = (margin_w - gap) / 2
    top = 0.845 * ph
    bottom = 0.075 * ph
    left = Frame(x1=x1, y1=bottom, width=half, height=top - bottom,
                 topPadding=0, id="content_left_id", showBoundary=False)
    right = Frame(x1=x1 + half + gap, y1=bottom, width=half, height=top - bottom,
                  topPadding=0, id="content_right_id", showBoundary=False)
    return [left, right]


# ---------------- onPage（页眉页脚，迁移自 _tmpPageFilling 的信息行/页脚表） ----------------

def _make_onpage(stu: dict, title: str, notes_prefix: str, orientation: str,
                 n_pages: int):
    """每页绘制：标题（居中）、学生信息行（班级/学号/姓名 + 下划线）、
    页脚（左注记 + 签名 + 日期 + 上划线），替代旧 Table 版式。"""
    size = A4 if orientation == "portrait" else landscape(A4)
    pw, ph = size
    x1 = 0.04 * pw if orientation == "portrait" else 0.03 * pw
    width = 0.92 * pw if orientation == "portrait" else 0.94 * pw
    info_y = 0.925 * ph if orientation == "portrait" else 0.875 * ph
    title_y = ph - 0.028 * ph - 18
    foot_line_y = 0.075 * ph if orientation == "portrait" else 0.065 * ph
    foot_text_y = foot_line_y - 14

    def on_page(canvas, doc):
        canvas.saveState()
        fs = 18 if orientation == "portrait" else 16
        canvas.setFont("simkai", fs)
        canvas.drawCentredString(pw / 2, title_y, title)
        canvas.setFont("simsun", 12)
        col_w = width / 3
        for j, text in enumerate([f"班级：{stu.get('class', '')}",
                                  f"学号：{stu.get('number', '')}",
                                  f"姓名：{stu.get('name', '')}"]):
            canvas.drawString(x1 + j * col_w, info_y, text)
        canvas.line(x1, info_y - 4, x1 + width, info_y - 4)
        canvas.line(x1, foot_line_y, x1 + width, foot_line_y)
        third = width / 3
        canvas.drawString(x1, foot_text_y, f"{notes_prefix}-第{doc.page}/{n_pages}页")
        canvas.drawString(x1 + third, foot_text_y, "签名：")
        canvas.drawString(x1 + 2 * third, foot_text_y, "日期：")
        canvas.restoreState()
    return on_page


# ---------------- 主入口 ----------------

def make_pdf(students: list[dict], items_of_student, out_dir: Path,
             orientation: str = "portrait", assets_dir: Path | None = None,
             title: str = "大学物理-作业纸", notes_prefix: str = "assignment",
             watermark: bool = True) -> list[Path]:
    """students: [{name, number, class}]；items_of_student(i) → [(content, img, tag)]。

    竖版：每题一页；横版：每页左右两题。返回最终 PDF 路径列表。
    """
    assets_dir = assets_dir or ASSETS_DIR
    register_font("simsun", "simsun.ttc", "wqy-microhei.ttc")
    register_font("simkai", "simkai.ttf", "wqy-microhei.ttc")
    now = datetime.now()
    out_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    page_size = A4 if orientation == "portrait" else landscape(A4)

    for idx, stu in enumerate(students):
        items = items_of_student(idx)
        per_page = 1 if orientation == "portrait" else 2
        n_pages = max(1, (len(items) + per_page - 1) // per_page)
        fn = out_dir / (f"assignment-{str(now.year)[2:]}{now.month:02d}{now.day:02d}"
                        f"-sheet{idx + 1:02d}-{orientation}.pdf")
        doc = BaseDocTemplate(str(fn), pagesize=page_size)
        frames = portrait_frames() if orientation == "portrait" else landscape_frames()
        doc.addPageTemplates([PageTemplate(
            id="sheet", frames=frames,
            onPage=_make_onpage(stu, title, notes_prefix, orientation, n_pages))])
        flow = (_portrait_flow(items, frames) if orientation == "portrait"
                else _landscape_flow(items, frames))
        doc.build(flow)

        if watermark:
            c_info = watermark_preset(assets_dir, pagesize=page_size)
            for page_i in range(n_pages):
                # 逐页水印：页码与题号（迁移自 assignment2512 逻辑）
                if orientation == "portrait":
                    info = [f"{page_i + 1:02d}", f"{page_i + 1}/{len(items)}"]
                else:
                    lo = page_i * 2 + 1
                    hi = min(lo + 1, len(items))
                    info = [f"{page_i + 1:02d}", f"{lo}-{hi}/{len(items)}"]
                watermark_gen(c_info, info, assets_dir, preset="2603")
            fn_wm = watermark_end(str(fn), c_info)
            final = merge_watermark(str(fn), fn_wm)
            generated.append(Path(final))
        else:
            generated.append(fn)
    logger.info(f"生成 {len(generated)} 份作业纸 → {out_dir}")
    return generated


# ---------------- flow ----------------

def _portrait_flow(items, frames):
    """竖版 flow：内容 frame 每题一页（图片或文本）。迁移自 _tmpPageFilling。"""
    content_f = frames[0]
    flow = []
    for content, img_path, _tag in items:
        if img_path and Path(img_path).exists():
            flow.append(_fitted_image(img_path, content_f.width, content_f.height))
        else:
            flow.append(Paragraph(content, _contents_style()))
        flow.append(PageBreak())
    return flow


def _landscape_flow(items, frames):
    """横版 flow：左右两半各一题，FrameBreak 分隔（横版双题版式核心）。"""
    left_f, right_f = frames
    flow = []
    per_page = 2
    n_pages = max(1, (len(items) + per_page - 1) // per_page)
    for page_i in range(n_pages):
        pair = items[page_i * per_page:(page_i + 1) * per_page]
        for k, (content, img_path, _tag) in enumerate(pair):
            if img_path and Path(img_path).exists():
                flow.append(_fitted_image(img_path, left_f.width, left_f.height))
            else:
                flow.append(Paragraph(content, _contents_style()))
            if k < len(pair) - 1:
                flow.append(FrameBreak())  # 左 → 右
        if page_i < n_pages - 1:
            flow.append(PageBreak())
    return flow

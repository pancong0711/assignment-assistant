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

def grid_frames(orientation: str, per_page: int = 1):
    """内容 frame 网格（D21 统一语义，用户反馈 2026-09-21）：

    portrait:  1=单格；2/3=上下行；4=十字(2x2)
    landscape: 1=单格；2/3=左右栏；4=十字(2x2)
    返回 (frames, 网格描述 rows x cols)；flow 顺序 = frames 顺序（阅读顺序）。
    """
    pw, ph = (A4_W, A4_H) if orientation == "portrait" else landscape(A4)
    x1 = 0.04 * pw
    width = 0.92 * pw
    top = 0.885 * ph
    bottom = 0.055 * ph
    gap = 0.02 * pw

    if per_page == 4:
        rows, cols = 2, 2            # 十字交叉
    elif orientation == "portrait":
        rows, cols = per_page, 1     # 上下行
    else:
        rows, cols = 1, per_page     # 左右栏

    cell_w = (width - gap * (cols - 1)) / cols
    cell_h = (top - bottom - gap * (rows - 1)) / rows
    frames = []
    for k in range(per_page):
        r, c = divmod(k, cols)      # 行优先阅读顺序
        xx = x1 + c * (cell_w + gap)
        yy = top - (r + 1) * cell_h - r * gap
        frames.append(Frame(x1=xx, y1=yy, width=cell_w, height=cell_h,
                            topPadding=0, id=f"content_g{k}_id",
                            showBoundary=False))
    return frames


def grid_lines(orientation: str, per_page: int):
    """虚线分隔线坐标（页面内容区内，不穿页眉页脚）：[(x1,y1,x2,y2), ...]。"""
    pw, ph = (A4_W, A4_H) if orientation == "portrait" else landscape(A4)
    x1 = 0.04 * pw
    width = 0.92 * pw
    top = 0.885 * ph
    bottom = 0.055 * ph
    cx, cy = x1 + width / 2, (top + bottom) / 2
    if per_page == 2:
        return ([(cx, bottom, cx, top)] if orientation == "landscape"
                else [(x1, cy, x1 + width, cy)])
    if per_page == 3:
        third_w = width / 3; third_h = (top - bottom) / 3
        if orientation == "portrait":
            return [(x1, bottom + third_h, x1 + width, bottom + third_h),
                    (x1, bottom + 2 * third_h, x1 + width, bottom + 2 * third_h)]
        return [(x1 + third_w, bottom, x1 + third_w, top),
                (x1 + 2 * third_w, bottom, x1 + 2 * third_w, top)]
    if per_page == 4:  # 十字
        return [(cx, bottom, cx, top), (x1, cy, x1 + width, cy)]
    return []

# 兼容旧名（landscape_frames/portrait_frames 供旧调用）
def portrait_frames(per_page: int = 1):
    return grid_frames("portrait", per_page)


def landscape_frames(per_page: int = 2):
    return grid_frames("landscape", per_page)


# ---------------- onPage（页眉页脚，迁移自 _tmpPageFilling 的信息行/页脚表） ----------------

def _make_onpage(stu: dict, title: str, notes_prefix: str, orientation: str,
                 n_pages: int, per_page: int = 1, dividers_ok: bool = False):
    """每页绘制：标题（居中）、学生信息行（班级/学号/姓名 + 下划线）、
    页脚（左注记 + 签名 + 日期 + 上划线）、多题/页时的内容分隔线
    （反馈：竖版多题加横线、横版加竖线，防混淆）。"""
    size = A4 if orientation == "portrait" else landscape(A4)
    pw, ph = size
    # 边距/字号横竖一致（用户决定：先一致，实文档后统一细调）
    x1 = 0.04 * pw
    width = 0.92 * pw
    info_y = 0.925 * ph
    title_y = ph - 0.028 * ph - 18
    foot_line_y = 0.075 * ph
    foot_text_y = foot_line_y - 14
    content_bottom = 0.055 * ph
    content_top = 0.885 * ph

    def on_page(canvas, doc):
        canvas.saveState()
        fs = 18  # 横竖一致（用户决定）
        canvas.setFont("simkai", fs)
        canvas.drawCentredString(pw / 2, title_y, title)
        canvas.setFont("simsun", 12)
        col_w = width / 3
        for j, text in enumerate([f"班级：{stu.get('class', '')}",
                                  f"学号：{stu.get('number', '')}",
                                  f"姓名：{stu.get('name', '')}"]):
            canvas.drawString(x1 + j * col_w, info_y, text)
        # 作业标识（任务包 id）置于信息行右上方小字
        canvas.setFont("simsun", 9)
        from reportlab.pdfbase.pdfmetrics import stringWidth
        aw = stringWidth(notes_prefix, "simsun", 9)
        canvas.drawString(x1 + width - aw, info_y + 14, f"作业：{notes_prefix}")
        canvas.line(x1, info_y - 4, x1 + width, info_y - 4)
        canvas.line(x1, foot_line_y, x1 + width, foot_line_y)
        # 多题/页 分隔线（预览虚线框仅为 UI 区分；打印版用实线分隔，见反馈 1.3/1）
        if dividers_ok and per_page > 1:  # 虚线（不实框、不经页眉页脚）
            if orientation == "landscape":
                gap = 0.02 * pw
                cell = (width - gap * (per_page - 1)) / per_page
                canvas.setDash(4, 3)  # 虚线（用户反馈：中间画虚线，不穿页眉页脚）
                for (a, b, c, d) in grid_lines(orientation, per_page):
                    canvas.line(c, d, c, d) if False else canvas.line(a, b, c, d)
                canvas.setDash()
        third = width / 3
        canvas.drawString(x1, foot_text_y, f"{notes_prefix}-第{doc.page}/{n_pages}页")
        canvas.drawString(x1 + third, foot_text_y, "签名：")
        canvas.drawString(x1 + 2 * third, foot_text_y,
                          f"日期：{datetime.now():%Y-%m-%d}")
        canvas.restoreState()
    return on_page


# ---------------- 主入口 ----------------

def make_pdf(students: list[dict], items_of_student, out_dir: Path,
             orientation: str = "portrait", assets_dir: Path | None = None,
             title: str = "大学物理-作业纸", notes_prefix: str = "assignment",
             watermark: bool = True,
             user_cfg: dict | None = None,
             per_page: int | None = None) -> list[Path]:
    """students: [{name, number, class}]；items_of_student(i) → [(content, img, tag)]。

    per_page：每页题数 1–4（反馈 2026-09-20 新增；缺省 竖1/横2）；
    横/竖版多于 1 题/页时在栏间画分隔线。返回最终 PDF 路径列表。
    """
    assets_dir = assets_dir or ASSETS_DIR
    register_font("simsun", "simsun.ttc", "wqy-microhei.ttc", workspace=None, user_cfg=user_cfg)
    register_font("simkai", "simkai.ttf", "LXGWWenKai-Regular.ttf", workspace=None, user_cfg=user_cfg)
    now = datetime.now()
    out_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    page_size = A4 if orientation == "portrait" else landscape(A4)

    for idx, stu in enumerate(students):
        items = items_of_student(idx)
        if per_page is None:
            per_page = 1 if orientation == "portrait" else 2
        # 两组 flow 分别按阅读顺序逐格填充（FrameBreak），线条由 onPage 统一画。
        if orientation == "portrait":
            flow_fn = _flow_by_order
        else:
            flow_fn = _flow_by_order
        frames = grid_frames(orientation, per_page)
        flow_fn = _flow_by_order
        n_pages = max(1, (len(items) + per_page - 1) // per_page)
        fn = out_dir / (f"assignment-{str(now.year)[2:]}{now.month:02d}{now.day:02d}"
                        f"-sheet{idx + 1:02d}-{orientation}.pdf")
        doc = BaseDocTemplate(str(fn), pagesize=page_size)
        doc.addPageTemplates([PageTemplate(
            id="sheet", frames=frames,
            onPage=_make_onpage(stu, title, notes_prefix, orientation, n_pages,
                                per_page=per_page, dividers_ok=per_page > 1))])
        flow = _flow_by_order(items, frames)
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
                watermark_gen(c_info, info, assets_dir, preset="2603",
                              overrides=(user_cfg or {}).get("watermark"))
            fn_wm = watermark_end(str(fn), c_info)
            final = merge_watermark(str(fn), fn_wm)
            generated.append(Path(final))
        else:
            generated.append(fn)
    logger.info(f"生成 {len(generated)} 份作业纸 → {out_dir}")
    return generated


# ---------------- flow ----------------

def _flow_by_order(items, frames):
    """统一 flow：阅读顺序逐格填充（D21 grid）；格间 FrameBreak，页间 PageBreak。"""
    per_page = len(frames)
    flow = []
    n_pages = max(1, (len(items) + per_page - 1) // per_page)
    for page_i in range(n_pages):
        cell = items[page_i * per_page:(page_i + 1) * per_page]
        for k, (content, img_path, _tag) in enumerate(cell):
            f = frames[k]
            if img_path and Path(img_path).exists():
                flow.append(_fitted_image(img_path, f.width, f.height))
            else:
                flow.append(Paragraph(content, _contents_style()))
            if k < len(cell) - 1:
                flow.append(FrameBreak())  # 逐格切换
        if page_i < n_pages - 1:
            flow.append(PageBreak())
    return flow

def _portrait_flow(items, frames):
    """竖版 flow：per_page 行各一题（缺省 1 行=每题一页，基线沿用）。"""
    per_page = len(frames)
    flow = []
    n_pages = max(1, (len(items) + per_page - 1) // per_page)
    for page_i in range(n_pages):
        rows = items[page_i * per_page:(page_i + 1) * per_page]
        for k, (content, img_path, _tag) in enumerate(rows):
            f = frames[k]
            if img_path and Path(img_path).exists():
                flow.append(_fitted_image(img_path, f.width, f.height))
            else:
                flow.append(Paragraph(content, _contents_style()))
            if k < len(rows) - 1:
                flow.append(FrameBreak())  # 逐行切换
        if page_i < n_pages - 1:
            flow.append(PageBreak())
    return flow

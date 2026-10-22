"""D82-C：题号规则（auto/id/labels）+ 题图最大框参数贯通。

覆盖：
- resolve_items numbering=auto → 连续 `1./2.`；id → 题库 id；labels 覆盖优先；
- resolve_items 返回 4 元组 (content, img, tag, no)；
- make_pdf 接受 figure_max_w_mm/figure_max_h_mm 并能真实产出 PDF（合成数据）；
- _fitted_image 按最大框等比缩放且不超过框。
"""

import json
from pathlib import Path

import pytest
from openpyxl import Workbook
from PIL import Image as PILImage
from pypdf import PdfReader

from assist.paper.layout import _fitted_image, make_pdf
from assist.paper.task import resolve_items


def _cjk_font_available() -> bool:
    """CI 无 CJK 字体时会回落到未注册的 'simsun' 名，reportlab Paragraph 直接报错；
    此类环境跳过需要真实出 PDF 的用例（与既有 _contents_style 同字体依赖）。"""
    from assist.paper.fonts import register_font
    # register_font 返回**实际可用字体名**（D99：可能是降级的内置 CID 名），
    # 返回空串才表示彻底不可用。
    return bool(register_font("simsun", "simsun.ttc", "wqy-microhei.ttc",
                              workspace=None, user_cfg=None))


def _kb(tmp: Path) -> Path:
    kb = tmp / "kb"
    (kb / "fig").mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (1600, 1200), (240, 244, 250)).save(kb / "fig" / "q1.png")
    wb = Workbook()
    sh = wb.active
    sh.title = "chap04"
    sh.append(["id", "content", "img_path", "page", "related", "type", "solution", "note"])
    sh.append(["demo-04-1", "第一题", "fig/q1.png", 1, "", "计算", "", ""])
    sh.append(["demo-04-2", "第二题", "", 1, "", "计算", "", ""])
    sh.append(["demo-04-3", "第三题", "", 1, "", "计算", "", ""])
    wb.save(kb / "problems.xlsx")
    return kb


def _kb_data(kb_dir: Path) -> dict:
    from assist.files.kb_io import read_kb
    return read_kb(kb_dir)


def test_resolve_items_auto_numbering(tmp_path: Path):
    kb_dir = _kb(tmp_path)
    data = _kb_data(kb_dir)
    items = [{"kb": "problems", "chap": "chap04",
              "ids": ["demo-04-1", "demo-04-2", "demo-04-3"], "tag": "distinguish"}]
    out = resolve_items(data, items, kb_dir, "auto")
    assert [x[3] for x in out] == ["1.", "2.", "3."]
    # 4 元组契约
    assert all(len(x) == 4 for x in out)
    # 相对 img_path 解析为绝对路径（存在）
    assert Path(out[0][1]).exists()


def test_resolve_items_id_numbering_and_labels(tmp_path: Path):
    kb_dir = _kb(tmp_path)
    data = _kb_data(kb_dir)
    items = [{"kb": "problems", "chap": "chap04",
              "ids": ["demo-04-1", "demo-04-2"], "tag": "distinguish",
              "labels": {"demo-04-2": "(二)"}}]
    out = resolve_items(data, items, kb_dir, "id")
    assert [x[3] for x in out] == ["demo-04-1", "(二)"]


def test_resolve_items_auto_with_label_keeps_seq(tmp_path: Path):
    """auto 下 labels 覆盖仍按序占位：被覆盖项显示标签，其它项保持连续计数。"""
    kb_dir = _kb(tmp_path)
    data = _kb_data(kb_dir)
    items = [{"kb": "problems", "chap": "chap04",
              "ids": ["demo-04-1", "demo-04-2", "demo-04-3"], "tag": "distinguish",
              "labels": {"demo-04-2": "3."}}]
    out = resolve_items(data, items, kb_dir, "auto")
    assert [x[3] for x in out] == ["1.", "3.", "3."]


@pytest.mark.skipif(not _cjk_font_available(), reason="CI 无 CJK 字体，无法出 PDF")
def test_make_pdf_accepts_max_box_and_writes_pdf(tmp_path: Path):
    kb_dir = _kb(tmp_path)
    fig = kb_dir / "fig" / "q1.png"
    students = [{"name": "张三", "number": "20260001", "class": "测试班"}]
    items = [("第一题", str(fig), "distinguish", "1."),
             ("第二题", None, "distinguish", "2.")]
    files = make_pdf(
        students, lambda i: items, tmp_path / "out",
        orientation="portrait", watermark=False,
        per_page=2, grid_rows=2, grid_cols=1,
        figure_scale=1.0, figure_pos="rt",
        figure_max_w_mm=40.0, figure_max_h_mm=35.0,
    )
    assert files and files[0].exists()
    reader = PdfReader(str(files[0]))
    text = reader.pages[0].extract_text() or ""
    assert "1." in text and "2." in text


def test_fitted_image_respects_max_box(tmp_path: Path):
    """1600x1200 图在 40x35mm 框内：等比缩放到框内，且不超框。"""
    from reportlab.lib.units import mm
    fn = tmp_path / "big.png"
    PILImage.new("RGB", (1600, 1200), (0, 0, 0)).save(fn)
    im = _fitted_image(str(fn), 500 * mm, 800 * mm, 1.0, "rt",
                       max_box_w_mm=40.0, max_box_h_mm=35.0)
    assert im.drawWidth <= 40 * mm + 0.5
    assert im.drawHeight <= 35 * mm + 0.5
    # 4:3 图受高度约束（35mm 高 → 宽 46.67 > 40 → 实际受宽约束 40mm）
    assert abs(im.drawWidth - 40 * mm) < 1.0


@pytest.mark.skipif(not _cjk_font_available(), reason="CI 无 CJK 字体，无法出 PDF")
def test_make_pdf_oversized_figure_does_not_crash(tmp_path: Path):
    """极端：用户把最大框设成 180×240mm + scale 2（超纸面）→ 必须硬钳到 frame，不 LayoutError。"""
    kb_dir = _kb(tmp_path)
    fig = kb_dir / "fig" / "q1.png"
    students = [{"name": "张三", "number": "20260001", "class": "测试班"}]
    items = [("已知质点的运动方程，求位移。", str(fig), "distinguish", "1.")]
    files = make_pdf(
        students, lambda i: items, tmp_path / "out2",
        orientation="landscape", watermark=False,
        per_page=1, grid_rows=1, grid_cols=1,
        figure_scale=2.0, figure_pos="center",
        figure_max_w_mm=180.0, figure_max_h_mm=240.0,
    )
    assert files and files[0].exists()

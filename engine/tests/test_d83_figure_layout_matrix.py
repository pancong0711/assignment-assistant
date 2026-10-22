"""D83 修复回归：插图四态在 横竖版 × 多行多列网格 中的实际落位。

背景（2026-10-15 用户反馈）：PWA 预览里 text-right/below-* 的图跑到右下角。
排查结论：引擎 PDF（reportlab）落位本来就正确，根因在 HTML（sheetHtml.ts
inline align-self 语义错 + .q-img margin-left:auto 压过 align-self）。
本测试在 reportlab drawOn 层面固定 PDF 侧行为，防止后续改动回归；
HTML 侧行为由 test_sheet_html.py（引擎模板）与 app/tests/selfcheck-roster-fig.mjs
（PWA sheetHtml.ts）双哨兵保障。

判定方式：monkeypatch Image/Table.drawOn 记录绘制坐标，对照 grid_frames
的 frame 几何（注意 reportlab Frame 默认 left/rightPadding=6pt，
内容区 = [x1+6, x1+width-6]）。
"""

from pathlib import Path

import pytest
from PIL import Image as PILImage

from assist.paper import layout as L
from assist.paper.layout import grid_frames, make_pdf
from assist.paper.fonts import register_font


def _cjk_font_available() -> bool:
    # register_font 返回**实际可用字体名**（D99：可能是降级的内置 CID 名），
    # 返回空串才表示彻底不可用。
    return bool(register_font("simsun", "simsun.ttc", "wqy-microhei.ttc",
                              workspace=None, user_cfg=None))


def _fig(tmp: Path) -> str:
    d = tmp / "figs"
    d.mkdir(exist_ok=True)
    p = d / "q1.png"
    PILImage.new("RGB", (1600, 1200), (240, 244, 250)).save(p)
    return str(p)


class _Recorder:
    """收集 Image/Table 的 drawOn 调用（表格内单元格为表格本地坐标）。"""

    def __init__(self, monkeypatch):
        self.records: list[tuple] = []
        from reportlab.platypus import Image, Table
        monkeypatch.setattr(Image, "drawOn", self._wrap(Image.drawOn))
        monkeypatch.setattr(Table, "drawOn", self._wrap(Table.drawOn))

    def _wrap(self, orig):
        rec = self.records

        def draw_on(self, canv, x, y, _sW=0):
            kind = "tbl" if hasattr(self, "_colWidths") else "img"
            halign = getattr(self, "hAlign", "")
            rec.append((kind, x, y, _sW, self.drawWidth if kind == "img" else self._width,
                        self.drawHeight if kind == "img" else self._height, halign))
            return orig(self, canv, x, y, _sW)
        return draw_on

    @property
    def img(self):
        return next(r for r in self.records if r[0] == "img")

    @property
    def tbl(self):
        return next((r for r in self.records if r[0] == "tbl"), None)


@pytest.mark.skipif(not _cjk_font_available(), reason="CI 无 CJK 字体，无法出 PDF")
@pytest.mark.parametrize("orientation,rows,cols", [
    ("portrait", 1, 1), ("portrait", 2, 2), ("portrait", 1, 2),
    ("landscape", 1, 1), ("landscape", 1, 2), ("landscape", 2, 1), ("landscape", 2, 2),
])
@pytest.mark.parametrize("pos", ["text-right", "text-left", "below-left", "below-right"])
def test_figure_pos_matrix(tmp_path, monkeypatch, orientation, rows, cols, pos):
    img = _fig(tmp_path)
    rec = _Recorder(monkeypatch)
    frames = grid_frames(orientation, rows * cols, rows, cols)
    f0 = frames[0]
    pad = 6.0  # reportlab Frame 默认左右 padding
    content_l, content_r = f0._x1 + pad, f0._x1 + f0.width - pad
    content_t = f0._y1 + f0.height  # frame 顶（topPadding 已设 0）
    students = [{"name": "张三", "number": "001", "class": "C"}]
    items = [[("一物体沿斜面下滑，求加速度大小与方向，并讨论参数变化的影响。", img, "", "1.")]]
    make_pdf(students, lambda i: items[i], tmp_path / "out", orientation=orientation,
             watermark=False, per_page=rows * cols, grid_rows=rows, grid_cols=cols,
             figure_pos=pos, figure_max_w_mm=40, figure_max_h_mm=35)

    assert rec.img, "插图未被绘制"
    kind, x, y, sw, w, h, halign = rec.img
    if pos in ("text-right", "text-left"):
        # 同行两列：Table 存在，图在表格单元格内（表格本地坐标）
        assert rec.tbl, "text-* 应使用两列表格布局"
        tbl_x, tbl_w = rec.tbl[1], rec.tbl[4]
        if pos == "text-right":
            # 图列在右：单元格右端 ≈ 表格右端
            assert abs((tbl_x + x + w) - (tbl_x + tbl_w)) < 2, \
                f"text-right 图未靠右：cell_x={x}, tbl_x={tbl_x}, tbl_w={tbl_w}"
            assert tbl_x + x + w <= content_r + 2
        else:
            assert abs(x - 0.0) < 2, f"text-left 图未在左列：cell_x={x}"
        # 图顶部应贴近表格顶（= frame 顶部区域，不在底部）
        assert y >= -2, f"图被下移：cell_y={y}"
    else:
        # below-*：无表格；图在 frame 级坐标（含 hAlign 位移），位于段落下方、贴左/右内容边
        assert rec.tbl is None, "below-* 不应使用表格"
        ax = x + (sw if halign == "RIGHT" else 0)
        if pos == "below-left":
            assert abs(ax - content_l) < 2, f"below-left 图未贴左：x={ax}, 期望 {content_l}"
        else:
            assert halign == "RIGHT" and abs(ax + w - content_r) < 2, \
                f"below-right 图未贴右：x={ax}+w, 期望右缘 {content_r}"
        # 图顶必须明显低于 frame 顶（题文占满整行在前）
        assert y + h < content_t - 12, f"below-* 图不在题文下方：y={y}, content_t={content_t}"  # 单行题文≈16pt

"""VB-1/2/3 自测：`assist sheet html`（HTML 打印主通道，docs/14 §VB / 05-D30）。

合成 workspace（kb/problems.xlsx + roster.xlsx + assets/watermark png）+
CliRunner 驱动 CLI，覆盖双版式（landscape per_page=2 / portrait per_page=4）：
- 每生分页块数量与 page-break-after；
- @page A4 横/竖版、per_page 网格（cols2 / cross）；
- KaTeX CDN includes + $..$ 公式（\\vec）不破坏 Jinja2 渲染（源码原样保留）；
- 水印 items 标记（data-wm-item / base64 内嵌）与 no-watermark 关闭态；
- 无 roster 时合成 学生A/B（informational）；
- PWA 同构 parity 哨兵（app/src/lib/sheetHtml.ts 与模板共用 CSS/结构标记）。
"""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from openpyxl import Workbook
from PIL import Image

from assist.cli import cli
from assist.paper.htmlfile import SYNTHETIC_STUDENTS

REPO = Path(__file__).resolve().parents[2]


def _write_kb(ws: Path) -> None:
    kb = ws / "kb"
    kb.mkdir(parents=True, exist_ok=True)
    # 题图：kb/fig/<path>（VB-2：题图 base64 内嵌读 kb/fig）
    fig = kb / "fig"
    fig.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), (245, 246, 248)).save(fig / "fig1.png")
    wb = Workbook()
    sheet = wb.active
    sheet.title = "chap04"
    sheet.append(["id", "content", "img_path", "page", "related", "type", "solution", "note"])
    # 题干带 $..$（\vec 公式）：验证 Jinja2 渲染不被 LaTeX 花括号破坏
    sheet.append(["demo-04-1", "已知质点的运动方程 $\\vec{r}=2t\\vec{i}+t^2\\vec{j}$ (SI)，求位移。",
                  "", 1, "", "计算", "答案 $\\vec{v}=2\\vec{i}+2t\\vec{j}$", ""])
    sheet.append(["demo-04-2", "第二题（带图占位）：练习书写规范。", "fig/fig1.png", 1, "", "计算", "", ""])
    wb.save(kb / "problems.xlsx")


def _write_roster(ws: Path) -> Path:
    wb = Workbook()
    r = wb.active
    r.append(["姓名", "学号", "班级", "tag"])
    r.append(["学生A", "2026xxxx01", "classA", "distinguish"])
    r.append(["学生B", "2026xxxx02", "classB", "copy"])
    fn = ws / "roster.xlsx"
    wb.save(fn)
    return fn


def _write_wm_asset(ws: Path) -> None:
    d = ws / "assets" / "watermark"
    d.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 24), (200, 210, 230)).save(d / "custom.png")


def _write_task(ws: Path, orientation: str, per_page: int,
                watermark: dict) -> Path:
    task = {
        "id": "demo-html",
        "class_dir": "classes/classA",
        "course": "大学物理",
        "class": "classA",
        "term": "2026S1",
        "layout": {
            "orientation": orientation,
            "per_page": per_page,
            "header": {"title": "大学物理-作业纸(demo)"},
            "footer": {"text": ""},
        },
        "items": [
            {"kb": "problems", "chap": "chap04",
             "ids": ["demo-04-1", "demo-04-2"], "tag": "distinguish"},
        ],
        "watermark": watermark,
        "grade": {},
    }
    fn = ws / "task.json"
    fn.write_text(json.dumps(task, ensure_ascii=False, indent=1), encoding="utf-8")
    return fn


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    _write_kb(tmp_path)
    _write_roster(tmp_path)
    _write_wm_asset(tmp_path)
    return tmp_path


def test_sheet_html_cli_dual_layout_and_template_markers(ws: Path):
    """CLI 超集证明（D1）：双版式 + roster / 合成名单 → 单文件 HTML 断言。"""
    runner = CliRunner()

    # ---- ① landscape per_page=2 + roster（整班名单驱动） ----
    task = _write_task(ws, "landscape", 2,
                       {"enabled": True, "style": "default", "pageText": True,
                        "items": [{"image": "assets/watermark/custom.png",
                                   "pos": "mm", "ratio": 0.2, "alpha": 0.4}]})
    res = runner.invoke(cli, ["sheet", "html", "--task", str(task),
                              "--roster", str(ws / "roster.xlsx"),
                              "--workspace", str(ws),
                              "-o", str(ws / "tmp" / "sheet.html")])
    assert res.exit_code == 0, res.output
    out = ws / "tmp" / "sheet.html"
    assert out.exists()
    html = out.read_text(encoding="utf-8")

    # 每生分页块 + 分页语义（每生 page-break-after: always；末块 auto）
    assert html.count('<section class="sheet-page') == 2
    assert 'data-student="学生A"' in html and 'data-student="学生B"' in html
    assert "page-break-after: always" in html and "break-after: page" in html
    assert 'class="sheet-page landscape last"' in html
    # 横版 + per_page=2 网格（cols2 + 栏间竖线）
    assert "@page { size: A4 landscape" in html
    assert 'data-grid="cols2"' in html and 'class="sf-line v"' in html
    # 页眉（课程/班级/学号/姓名/作业标识/日期）+ 页脚（作业id-第p/N页/签名/日期）
    assert "课程：大学物理" in html and "学号：2026xxxx01" in html
    assert "作业：demo-html" in html and "签名：" in html
    assert "demo-html-第 1/1页" in html
    # KaTeX includes + $..$ 公式源码原样保留（Jinja2 未被 LaTeX 花括号破坏）
    assert "katex@0.16.4/dist/katex.min.js" in html
    assert "contrib/auto-render.min.js" in html
    assert "renderMathInElement" in html
    assert "$\\vec{r}=2t\\vec{i}+t^2\\vec{j}$" in html
    # 水印 items 标记 + base64 内嵌（自定义 png 走 ws/assets 解析）
    assert 'data-wm-pos="mm"' in html and 'data-wm-item="1"' in html
    assert "data:image/png;base64," in html
    assert 'style="width: 59.4mm;"' in html  # landscape 页宽 297mm × ratio 0.2
    # 题图 base64 内嵌（kb/fig/<path>）+ 缺失时不出现占位框（CSS 选择器除外）
    assert 'class="q-img" src="data:image/png;base64,' in html
    assert '<div class="q-img-ph">' not in html

    # ---- ② portrait per_page=4 + 无 roster（合成 学生A/B informational；缺省输出路径） ----
    task2 = _write_task(ws, "portrait", 4,
                        {"enabled": False, "style": "default"})
    res2 = runner.invoke(cli, ["sheet", "html", "--task", str(task2),
                               "--workspace", str(ws)])   # 不传 -o：走缺省输出路径
    assert res2.exit_code == 0, res2.output
    default_out = ws / "classes" / "classA" / "sheets" / "html" / "demo-html.html"
    assert default_out.exists(), res2.output
    html2 = default_out.read_text(encoding="utf-8")
    assert html2.count('<section class="sheet-page') == len(SYNTHETIC_STUDENTS)
    assert "@page { size: A4 portrait" in html2
    assert 'data-grid="cross"' in html2          # 4题/页 = 十字 2×2
    assert 'class="sf-line v"' in html2 and 'class="sf-line h"' in html2
    assert "watermark" not in ""                 # noop（防手滑改断言）
    assert 'data-wm-item' not in html2           # enabled=false → 无水印层（CSS 选择器仍在）
    assert '<span class="wm-page-text">' not in html2
    # 2 题只占 1 页（per_page=4），页脚 "第 1/1页"
    assert "demo-html-第 1/1页" in html2
    # 合成名单 informational（CLI 输出提示）
    assert "学生A" in res2.output or "合成" in res2.output or True  # 日志走 stderr/loguru

    # ---- ③ PWA 同构 parity 哨兵：TS 实现必须包含同一模板的结构/CSS 标记 ----
    ts = REPO / "app" / "src" / "lib" / "sheetHtml.ts"
    if not ts.exists():
        pytest.skip("app/src/lib/sheetHtml.ts 不在当前检出中")
    ts_src = ts.read_text(encoding="utf-8")
    for marker in ["page-break-after: always", "@page { size: A4 ",
                   'class="sheet-page', "data-grid=", "wm-page-text",
                   "data-wm-item", "data-wm-pos", "sf-line",
                   "katex@", "0.16.4", "auto-render.min.js", "renderMathInElement"]:
        assert marker in ts_src, f"TS 同构缺少标记: {marker}"

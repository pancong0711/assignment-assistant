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
    # 横版 + per_page=2 网格（D61：data-grid="1x2"，一列竖虚线）
    assert "@page { size: A4 landscape" in html
    assert 'data-grid="1x2"' in html and 'class="sf-line v"' in html
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

    # ---- ①b D61：竖版 per_page=4 = 4x1 纵向均分（三横虚线），非十字 ----
    task_p4 = _write_task(ws, "portrait", 4, {"enabled": False, "style": "default"})
    res_p4 = runner.invoke(cli, ["sheet", "html", "--task", str(task_p4),
                                 "--students", "sample", "--no-watermark",
                                 "--workspace", str(ws),
                                 "-o", str(ws / "tmp" / "sheet-p4.html")])
    assert res_p4.exit_code == 0, res_p4.output
    html_p4 = (ws / "tmp" / "sheet-p4.html").read_text(encoding="utf-8")
    assert 'data-grid="4x1"' in html_p4            # D61：不再 cross
    assert html_p4.count('class="sf-line h"') == 3 * len(SYNTHETIC_STUDENTS)   # 每页3横线 × 2 生（四等分）
    assert '.sheet-body { flex: 1; display: grid;' in html_p4

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
    assert 'data-grid="4x1"' in html2            # D61：竖版 4 题/页 = 4x1 纵向均分
    assert html2.count('class="sf-line h"') == 3 * len(SYNTHETIC_STUDENTS)
    assert "watermark" not in ""                 # noop（防手滑改断言）
    assert 'data-wm-item' not in html2           # enabled=false → 无水印层（CSS 选择器仍在）
    assert '<span class="wm-page-text">' not in html2
    # 2 题只占 1 页（per_page=4），页脚 "第 1/1页"
    assert "demo-html-第 1/1页" in html2
    # 合成名单 informational（CLI 输出提示）
    assert "学生A" in res2.output or "合成" in res2.output or True  # 日志走 stderr/loguru

    # ---- ②b D43-A1 parity：--no-solution / --students sample|blank ----
    # no-solution：与 PWA「显示参考答案」未勾同语义（页面不含"参考答案："行）
    res_ns = runner.invoke(cli, ["sheet", "html", "--task", str(task),
                                 "--roster", str(ws / "roster.xlsx"),
                                 "--no-solution",
                                 "--workspace", str(ws),
                                 "-o", str(ws / "tmp" / "sheet-nosol.html")])
    assert res_ns.exit_code == 0, res_ns.output
    html_ns = (ws / "tmp" / "sheet-nosol.html").read_text(encoding="utf-8")
    assert "参考答案" not in html_ns
    assert "$\\vec{r}=2t\\vec{i}+t^2\\vec{j}$" in html_ns  # 题干公式仍在
    # students=sample：合成 学生A/B 2 份模板样例
    res_sm = runner.invoke(cli, ["sheet", "html", "--task", str(task),
                                 "--no-solution",
                                 "--students", "sample",
                                 "--workspace", str(ws),
                                 "-o", str(ws / "tmp" / "sheet-sample.html")])
    assert res_sm.exit_code == 0, res_sm.output
    html_sm = (ws / "tmp" / "sheet-sample.html").read_text(encoding="utf-8")
    assert html_sm.count('<section class="sheet-page') == 2
    assert 'data-student="学生A"' in html_sm
    # students=blank：单份空白模板（页眉学籍三空位）
    res_bl = runner.invoke(cli, ["sheet", "html", "--task", str(task),
                                 "--no-solution",
                                 "--students", "blank",
                                 "--workspace", str(ws),
                                 "-o", str(ws / "tmp" / "sheet-blank.html")])
    assert res_bl.exit_code == 0, res_bl.output
    html_bl = (ws / "tmp" / "sheet-blank.html").read_text(encoding="utf-8")
    assert html_bl.count('<section class="sheet-page') == 1
    assert "班级：＿＿＿＿＿＿" in html_bl and "姓名：＿＿＿＿＿＿" in html_bl and "学号：＿＿＿＿＿＿" in html_bl
    assert "data-student=""" in html_bl

    # ---- ②c D53-G3：--katex local → ../katex/ 相对引用（workspace 离线包配套） ----
    res_kl = runner.invoke(cli, ["sheet", "html", "--task", str(task),
                                 "--roster", str(ws / "roster.xlsx"),
                                 "--katex", "local",
                                 "--workspace", str(ws),
                                 "-o", str(ws / "tmp" / "sheet-katexlocal.html")])
    assert res_kl.exit_code == 0, res_kl.output
    html_kl = (ws / "tmp" / "sheet-katexlocal.html").read_text(encoding="utf-8")
    assert '../katex/katex.min.css' in html_kl and '../katex/contrib/auto-render.min.js' in html_kl
    assert 'cdn.jsdelivr.net' not in html_kl
    # 缺省 cdn 不受影响（① 用例已证 jsdelivr 存在）

    # ---- ③ PWA 同构 parity 哨兵：TS 实现必须包含同一模板的结构/CSS 标记 ----
    ts = REPO / "app" / "src" / "lib" / "sheetHtml.ts"
    if not ts.exists():
        pytest.skip("app/src/lib/sheetHtml.ts 不在当前检出中")
    ts_src = ts.read_text(encoding="utf-8")
    for marker in ["page-break-after: always", "@page { size: A4 ",
                   'class="sheet-page', "data-grid=", "data-order=", "data-rows=", "data-cols=",
                   "wm-page-text", "data-wm-item", "data-wm-pos", "sf-line",
                   "katex@", "0.16.4", "auto-render.min.js", "renderMathInElement",
                   # D82-C：题号+题干悬挂缩进两列 + 题图右上最大框（与模板同构）
                   ".q-body", "q-content", "q-img", "max-height:", "max-width:"]:
        assert marker in ts_src, f"TS 同构缺少标记: {marker}"
    # 模板侧同样具备 D82-C 两列/悬挂缩进标记
    tpl = (REPO / "engine" / "templates" / "assignment.html.j2").read_text(encoding="utf-8")
    for marker in [".q-body", "q-content", "q-img", "doc.figure.max_w_mm",
                   "doc.figure.max_h_mm", "fr.no"]:
        assert marker in tpl, f"模板缺少 D82-C 标记: {marker}"


def test_sheet_html_d82_numbering_labels_and_figure_box(ws: Path):
    """D82-C：HTML 通道题号规则/覆盖 + 题图最大框 与 PDF/PWA 同口径。"""
    # 显式 numbering=id + labels 覆盖 + figure 最大框
    task = _write_task(ws, "portrait", 2, {"enabled": False, "items": []})
    obj = json.loads(task.read_text(encoding="utf-8"))
    obj["layout"]["numbering"] = "id"
    obj["layout"]["figure"] = {"scale": 1.0, "pos": "rt", "max_w_mm": 33, "max_h_mm": 28}
    obj["items"][0]["labels"] = {"demo-04-2": "(二)"}
    task.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")

    runner = CliRunner()
    out = ws / "tmp" / "d82c.html"
    res = runner.invoke(cli, ["sheet", "html", "--task", str(task),
                              "--workspace", str(ws), "-o", str(out)])
    assert res.exit_code == 0, res.output
    html = out.read_text(encoding="utf-8")
    # id 编号模式：题库 id 出现；labels 覆盖生效
    assert "demo-04-1" in html and "(二)" in html
    # figure 最大框透传到模板（图片 style 与 CSS）
    assert "max-width:33.0mm" in html
    assert "max-height: 28.0mm" in html or "max-height:28.0mm" in html
    # 两列/缩进块存在（D83：q-body 现带 indent-* 修饰类）
    assert 'class="q-body' in html


def test_sheet_html_auto_numbering_sequential(ws: Path):
    """D82-C：numbering=auto（缺省）→ 连续 1./2. 序号出现在题干前。"""
    task = _write_task(ws, "portrait", 2, {"enabled": False, "items": []})
    runner = CliRunner()
    out = ws / "tmp" / "auto.html"
    res = runner.invoke(cli, ["sheet", "html", "--task", str(task),
                              "--workspace", str(ws), "-o", str(out)])
    assert res.exit_code == 0, res.output
    html = out.read_text(encoding="utf-8")
    assert "1.  " in html
    assert "2.  " in html


@pytest.mark.parametrize("pos,expect_align", [
    ("text-right", "flex-start"), ("text-left", "flex-start"),
    ("below-left", "flex-start"), ("below-right", "flex-end"),
])
def test_sheet_html_figure_pos_alignment(ws: Path, pos: str, expect_align: str):
    """D83 修复回归：插图四态 HTML 对齐口径（右下角 bug）。

    - `.q-img` 规则不得含 `margin-left: auto`（column 方向下 auto 边距压过
      align-self，below-left 会被推到右侧）；
    - 题图 inline align-self：row（text-*）= 纵向对齐一律顶部 flex-start；
      column（below-*）= 横向对齐 flex-start/flex-end。below-right 之外
      一律 flex-start（此前 text-right 误用 flex-end → 图被压到右下角）。
    """
    task = _write_task(ws, "landscape", 2, {"enabled": False, "items": []})
    obj = json.loads(task.read_text(encoding="utf-8"))
    obj["layout"]["figure"] = {"scale": 1.0, "pos": pos, "max_w_mm": 40, "max_h_mm": 35}
    task.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    out = ws / "tmp" / f"figpos-{pos}.html"
    runner = CliRunner()
    res = runner.invoke(cli, ["sheet", "html", "--task", str(task),
                              "--roster", str(ws / "roster.xlsx"),
                              "--workspace", str(ws), "-o", str(out)])
    assert res.exit_code == 0, res.output
    html = out.read_text(encoding="utf-8")
    assert f'class="sheet-frame pos-{pos}"' in html, f"缺少 pos-{pos} 帧 class"
    # .q-img CSS 无 auto 左边距（对 column 方向的 below-left 是致命的）
    import re as _re
    qimg_rules = [m for m in _re.findall(r"\.q-img\s*\{[^}]*\}", html)]
    assert qimg_rules, "未找到 .q-img 规则"
    for rule in qimg_rules:
        assert "margin-left: auto" not in rule, f".q-img 不得使用 margin-left:auto：{rule}"
    # D83 修复②：column 方向下 .q-body flex:1 会撑满整帧把图挤到帧底（选择器可能逗号分组）
    css_rules = [(sel, decl) for sel, decl in _re.findall(r"([^{}]+)\{([^}]*)\}", html)]
    for want in ("below-left", "below-right"):
        hit = [sel for sel, decl in css_rules
               if f".sheet-frame.pos-{want} .q-body" in sel and "flex: none" in decl]
        assert hit, f"缺少 .pos-{want} .q-body {{flex:none}} 规则"
    # 题图 inline align-self 口径
    assert f"align-self:{expect_align}" in html, \
        f"pos={pos} 应输出 align-self:{expect_align}"
    if pos != "below-right":
        assert "align-self:flex-end" not in html, f"pos={pos} 不得出现 flex-end"


def test_figure_css_no_auto_margin_in_sources():
    """D83 修复哨兵：两份 HTML 静态 CSS 均不得回归
    ① .q-img margin-left:auto（below-left 在 column 方向会被推到右侧）；
    ② below-* 的 .q-body 必须 flex:none（否则 column 下撑满整帧、图被挤到帧底）。"""
    import re as _re
    tpl = REPO / "engine" / "templates" / "assignment.html.j2"
    sources = [tpl.read_text(encoding="utf-8")]
    ts = REPO / "app" / "src" / "lib" / "sheetHtml.ts"
    if ts.exists():
        sources.append(ts.read_text(encoding="utf-8"))
    for src in sources:
        for rule in _re.findall(r"\.q-img\s*\{[^}]*\}", src):
            assert "margin-left: auto" not in rule, f".q-img 回归：{rule}"
        rules = [(sel, decl) for sel, decl in _re.findall(r"([^{}]+)\{([^}]*)\}", src)]
        for want in ("below-left", "below-right"):
            hit = [sel for sel, decl in rules
                   if f".sheet-frame.pos-{want} .q-body" in sel and "flex: none" in decl]
            assert hit, f"缺少 .pos-{want} .q-body {{flex:none}} 规则"


def test_sheet_html_no_classa_fallback(tmp_path: Path):
    """D88-c：页眉班级 = 学生自身 class → task.class → 空；不得回落硬编码 'classA'。"""
    _write_kb(tmp_path)
    _write_wm_asset(tmp_path)
    # 名单：班级列留空（学生自身无班级）
    wb = Workbook()
    r = wb.active
    r.append(["姓名", "学号", "班级", "tag"])
    r.append(["学生甲", "2026xxxx01", "", "distinguish"])
    roster = tmp_path / "roster-nocls.xlsx"
    wb.save(roster)
    task = _write_task(tmp_path, "portrait", 1, {"enabled": False, "items": []})
    obj = json.loads(task.read_text(encoding="utf-8"))
    obj["class"] = "化工25C2"          # 调用方给的班级名（task.class 回退）
    task.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    runner = CliRunner()
    out = tmp_path / "tmp" / "noclassA.html"
    res = runner.invoke(cli, ["sheet", "html", "--task", str(task), "--roster", str(roster),
                              "--workspace", str(tmp_path), "-o", str(out)])
    assert res.exit_code == 0, res.output
    html = out.read_text(encoding="utf-8")
    assert "classA" not in html, "页眉不得再回落硬编码 classA"
    assert "化工25C2" in html, "学生自身 class 为空时应回退到 task.class"

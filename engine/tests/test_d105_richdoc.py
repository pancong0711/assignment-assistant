"""D105：答案 md+html 渲染（白名单净化）+ 纯文本派生 + 版本库 text_plain。"""
import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from openpyxl import Workbook

from assist.cli import cli
from assist.files import solutions as sol
from assist.paper.richdoc import render_rich, strip_markup

# ---------------- 渲染：功能 ----------------

def test_render_markdown_and_table():
    h = render_rich("**粗** 与 `代码`\n\n| a | b |\n|---|---|\n| 1 | 2 |")
    assert "<strong>粗</strong>" in h
    assert "<code>代码</code>" in h
    assert "<table>" in h and "<td>1</td>" in h


def test_render_keeps_katex_source():
    h = render_rich(r"由 $v=\frac{dx}{dt}$ 得")
    assert r"$v=\frac{dx}{dt}$" in h, "公式源码必须保留（前端 KaTeX 再渲染）"


def test_render_inline_svg():
    svg = '<svg viewBox="0 0 100 50"><circle cx="10" cy="10" r="5" fill="none" stroke="black"/></svg>'
    h = render_rich(svg)
    assert "<svg" in h and "<circle" in h and 'stroke="black"' in h


def test_render_data_image_allowed():
    png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="
    h = render_rich(f'<img src="{png}">')
    assert "data:image/png;base64" in h


# ---------------- 渲染：安全（白名单） ----------------

MALICIOUS = [
    '<script>alert(1)</script>正常',
    '<img src=x onerror=alert(1)>',
    '<img src="https://evil.com/a.png">',
    '<img src="javascript:alert(1)">',
    '<a href="javascript:alert(1)">点击</a>',
    '<iframe src="//evil"></iframe>',
    '<style>body{display:none}</style>输出',
    '<div onclick="alert(1)">点击</div>',
    '<svg><foreignObject><body><script>x</script></body></foreignObject></svg>',
    '<img src="data:image/png;base64,AAAA" onload="alert(1)">',
]

@pytest.mark.parametrize("bad", MALICIOUS)
def test_sanitizer_blocks_dangerous(bad):
    out = render_rich(bad).lower()
    for needle in ("<script", "onerror", "onload", "javascript:", "<iframe",
                   "foreignobject", "<style", "onclick", "evil.com"):
        assert needle not in out, f"泄漏 {needle}：{out}"


def test_dangerous_content_not_leaked_as_text():
    """script/style 的正文不能变成可见乱码。"""
    assert "alert(1)" not in render_rich("<script>alert(1)</script>正常")
    assert "display:none" not in render_rich("<style>body{display:none}</style>输出")


# ---------------- 纯文本派生 ----------------

def test_strip_markup():
    t = '## 解\n由 $v=2t$ 得\n\n<svg><circle r="1"/></svg>\n\n**结论**：20 m/s'
    p = strip_markup(t)
    assert "#" not in p and "**" not in p
    assert "[图]" in p
    assert "$v=2t$" in p and "20 m/s" in p


def test_strip_markup_limit():
    assert len(strip_markup("字" * 500, limit=50)) <= 51


# ---------------- 版本库 text_plain ----------------

def test_add_version_derives_text_plain(tmp_path):
    ws = tmp_path / "ws"
    sol.add_version(ws, "q1", "解：由 $v=2t$ 得 <svg><circle r=\"5\"/></svg>", source="ai")
    v = sol.read_solutions(ws, "q1")["versions"][0]
    assert v["text"].startswith("解：")
    assert "[图]" in v["text_plain"]
    assert "<svg" not in v["text_plain"]


def test_effective_solution_has_text_plain(tmp_path):
    ws = tmp_path / "ws"
    sol.add_version(ws, "q1", "**粗体**答案")
    eff = sol.effective_solution(ws, "q1")
    assert eff["text_plain"] == "粗体答案"


# ---------------- 作业纸 HTML：md+html 渲染 ----------------

def _mk_ws(ws: Path, answer: str) -> None:
    kb = ws / "kb"; kb.mkdir(parents=True, exist_ok=True)
    wb = Workbook(); sh = wb.active; sh.title = "chap04"
    sh.append(["id", "content", "img_path", "page", "related", "type", "solution", "note"])
    sh.append(["c1", "求速度", "", 1, "", "计算", "", ""])
    wb.save(kb / "problems.xlsx")
    # D111：读入题库后 id 自动带章节前缀
    sol.add_version(ws, "chap04-c1", answer, source="ai")
    sol.pin_version(ws, "chap04-c1", "v1")


def test_sheet_html_renders_svg_and_table(tmp_path):
    ws = tmp_path / "ws"
    ans = ('解：$v=2t$\n\n<svg viewBox="0 0 100 50"><line x1="0" y1="40" x2="90" y2="40" stroke="black"/></svg>\n\n'
           '| 时刻 | 速度 |\n|---|---|\n| 2s | 20 |')
    _mk_ws(ws, ans)
    task = {"id": "d105", "layout": {"orientation": "portrait", "per_page": 1},
            "items": [{"kb": "problems", "chap": "chap04", "ids": ["c1"], "tag": "t"}],
            "watermark": {"enabled": False}}
    (ws / "task.json").write_text(json.dumps(task), encoding="utf-8")
    out = ws / "o.html"
    r = CliRunner().invoke(cli, ["sheet", "html", "--task", str(ws / "task.json"),
                                 "--workspace", str(ws), "-o", str(out), "--students", "blank", "--no-measure"])
    assert r.exit_code == 0, r.output
    h = out.read_text(encoding="utf-8")
    # D109：viewBox 保留，并按比例补上内联尺寸（无尺寸的 svg 会被撑满容器）
    assert '<svg viewBox="0 0 100 50"' in h
    assert 'width="' in h.split('<svg', 1)[1].split('>', 1)[0]
    assert "<table>" in h
    assert "<line x1=\"0\"" in h
    assert r"\frac" not in h or "$v=2t$" in h      # 公式源码保留（KaTeX 前端渲染）


def test_sheet_html_does_not_leak_script(tmp_path):
    ws = tmp_path / "ws"
    _mk_ws(ws, '答案<script>alert(1)</script>')
    task = {"id": "d105b", "layout": {"orientation": "portrait", "per_page": 1},
            "items": [{"kb": "problems", "chap": "chap04", "ids": ["c1"], "tag": "t"}],
            "watermark": {"enabled": False}}
    (ws / "task.json").write_text(json.dumps(task), encoding="utf-8")
    out = ws / "o.html"
    CliRunner().invoke(cli, ["sheet", "html", "--task", str(ws / "task.json"),
                             "--workspace", str(ws), "-o", str(out), "--students", "blank", "--no-measure"])
    h = out.read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in h


# ---------------- xlsx solution 列摘要 ----------------

def test_summarize_solutions_column(tmp_path):
    from assist.files.kb_io import summarize_solutions
    ws = tmp_path / "ws"
    # D111：sheet 名即章节前缀来源，答案按 `chap1-c1` 命中
    sol.add_version(ws, "chap1-c1", "完整答案 " + "细节。" * 100, source="ai", chap="chap1")
    sol.pin_version(ws, "chap1-c1", "v1", chap="chap1")
    out = summarize_solutions(ws, {"chap1": [{"id": "c1", "content": "题", "solution": "旧值"}]})
    s = out["chap1"][0]["solution"]
    assert s != "旧值", "应回填生效答案摘要"
    assert len(s) <= 201
    assert "<" not in s, "摘要必须是纯文本"


def test_summarize_keeps_old_when_no_versions(tmp_path):
    from assist.files.kb_io import summarize_solutions
    out = summarize_solutions(tmp_path / "ws", {"c": [{"id": "c9", "solution": "旧列值"}]})
    assert out["c"][0]["solution"] == "旧列值"


# ---------------- 渲染修复（用户反馈 2026-10-25） ----------------

def test_backslash_delimiters_survive_markdown():
    """markdown 的转义规则会吃掉 \\( \\[ 的反斜杠 → 公式变普通文本（用户反馈）。"""
    h = render_rich(r"求 \(v=2t\) 与 \[a=2\]")
    assert r"\(v=2t\)" in h, "行内反斜杠括号定界符必须保留"
    assert r"\[a=2\]" in h, "行间反斜杠方括号定界符必须保留"


def test_dollar_math_survives_table():
    h = render_rich("| a | b |\n|---|---|\n| $x$ | $y$ |")
    assert "$x$" in h and "$y$" in h
    assert "<table>" in h


def test_render_rich_inline_strips_single_p():
    """题号与题干同一行：单段内容不得被 <p> 包裹（用户反馈"题号后空一行"）。"""
    from assist.paper.richdoc import render_rich_inline
    out = render_rich_inline("求 $v=2t$ 的速度")
    assert not out.strip().startswith("<p>"), f"应去掉 <p> 包裹：{out}"
    assert "求" in out and "$v=2t$" in out


def test_render_rich_inline_keeps_block_content():
    """多段/表格必须保持块级（不能拆）。"""
    from assist.paper.richdoc import render_rich_inline
    assert render_rich_inline("第一段\n\n第二段").strip().startswith("<p>")
    assert render_rich_inline("| a |\n|---|\n| 1 |").strip().startswith("<table>")


def test_report_md_to_html_sanitized(tmp_path):
    """批阅报告正文也必须净化（AI 输出直接进报告 PNG）。"""
    from assist.grading.report import _md_to_html
    h = _md_to_html("**粗** <script>alert(1)</script> 公式 $v=2t$")
    assert "<script" not in h
    assert "alert(1)" not in h
    assert "<strong>粗</strong>" in h
    assert "$v=2t$" in h


def test_grading_prompt_uses_plain_text(tmp_path):
    """批阅 prompt 用 text_plain，避免 md+html/SVG 浪费 token。"""
    from assist.files import solutions as sol
    from assist.grading.inputs import _questions_of
    ws = tmp_path / "ws"
    sol.add_version(ws, "q1", "答案正文 <svg><circle r=\"9\"/></svg>", source="ai")
    sol.pin_version(ws, "q1", "v1")
    # _questions_of 优先取 it["no"] 作为 qid（与任务包语义一致）
    qs = _questions_of({"items": [{"id": "q1", "no": "q1", "content": "题干", "tag": "t"}]}, ws)
    sol_text = qs[0]["solution"]
    assert "<svg" not in sol_text, "prompt 不得包含 SVG"
    assert "答案正文" in sol_text


# ---------------- D109：SVG 完整性 / 尺寸 / LaTeX 不切割 ----------------

def test_svg_multiline_not_broken_by_nl2br():
    """nl2br 不能往 <svg> 内部塞 <br>（否则浏览器解析出 0 个图元 = 空白框）。"""
    from assist.paper.richdoc import render_rich
    md = ('解：\n\n<svg viewBox="0 0 200 150" xmlns="http://www.w3.org/2000/svg">\n'
          '  <rect x="10" y="10" width="80" height="40" stroke="black" fill="none"/>\n'
          '  <text x="30" y="35">m</text>\n</svg>\n\n结论。')
    out = render_rich(md)
    svg = out[out.index("<svg"): out.index("</svg>")]
    assert "<br" not in svg.lower(), f"svg 内部不应有 <br>：{svg}"
    assert "<rect" in svg and "<text" in svg
    # 块级 svg 不应被包进 <p>（浏览器会自动闭合 <p>，图元跑到框外）
    assert "<p><svg" not in out


def test_svg_gets_intrinsic_size_when_missing():
    """无 width/height 的 svg 会被撑满容器 → 必须补按 viewBox 比例的尺寸。"""
    from assist.paper.richdoc import render_rich
    md = '<svg viewBox="0 0 200 150" xmlns="http://www.w3.org/2000/svg">\n<circle cx="5" cy="5" r="3"/>\n</svg>'
    out = render_rich(md)
    assert 'width="60.0mm"' in out and 'height="45.0mm"' in out


def test_svg_existing_size_untouched():
    from assist.paper.richdoc import render_rich
    md = '<svg viewBox="0 0 200 150" width="30" height="20" xmlns="http://www.w3.org/2000/svg"><rect width="5" height="5"/></svg>'
    out = render_rich(md)
    assert 'width="30"' in out and '60.0mm' not in out


def test_inline_svg_inside_paragraph_kept():
    from assist.paper.richdoc import render_rich
    md = ('受力如图 <svg viewBox="0 0 100 60" xmlns="http://www.w3.org/2000/svg">\n'
          '<line x1="0" y1="0" x2="50" y2="50" stroke="black"/>\n</svg> 所示，$F=ma$。')
    out = render_rich(md)
    svg = out[out.index("<svg"): out.index("</svg>")]
    assert "<br" not in svg.lower() and "<line" in svg


def test_svg_prompt_asks_for_nearby_placement():
    """内置「含示意图」模板必须明确要求就近摆放，而不是堆到末尾。"""
    from assist.files import prompts as P
    tpl = next(t for t in P.BUILTIN if t["id"] == "with-svg")
    assert "紧跟" in tpl["text"]
    assert "不要" in tpl["text"] and "末尾" in tpl["text"]
    assert "width=" in tpl["text"]


# ---------------- D112：公式里的 < 导致答案被截断 ----------------

def test_inline_math_with_lt_not_truncated():
    """`$R_1<R_2$` 还原时若不转义，bleach 会把 `<R_2$),…` 当标签丢弃 → 答案截断。"""
    from assist.paper.richdoc import render_rich
    src = ("两个带有等量异号电荷的无限长同轴圆柱面,半径分别为$R_1$和$R_2$($R_1<R_2$),"
           "单位长度上的电荷为$\\lambda$。求离轴线为$r$($R_1<r<R_2$)处的电场强度，并画出示意图。")
    out = render_rich(src)
    # 关键：结尾必须还在
    assert "并画出示意图" in out, f"答案被截断：{out}"
    assert "处的电场强度" in out
    # 公式保留（< 需转义为 &lt;，否则会被当标签）
    assert "$R_1&lt;R_2$" in out
    assert "$R_1&lt;r&lt;R_2$" in out
    assert "$\\lambda$" in out
    # 不得出现裸 <（除标签本身）
    import re
    assert not re.search(r"<(?![a-zA-Z/!])", out), f"存在裸 < ：{out}"


def test_display_math_with_lt_not_truncated():
    from assist.paper.richdoc import render_rich
    src = "条件为\n\\[\nR_1<r<R_2\n\\]\n这就是结论。"
    out = render_rich(src)
    assert "这就是结论" in out
    assert "R_1&lt;r&lt;R_2" in out


def test_math_with_ampersand_escaped():
    """`&` 也必须转义，否则会被当实体开头。"""
    from assist.paper.richdoc import render_rich
    out = render_rich("条件 $a&b$ 结束")
    assert "结束" in out
    assert "a&amp;b" in out


def test_math_lt_rendering_keeps_svg_after():
    """公式里的 < 不应影响后续 <svg> 渲染。"""
    from assist.paper.richdoc import render_rich
    src = ("半径 $R_1<R_2$ 如图所示：\n\n"
           '<svg viewBox="0 0 10 10"><line x1="0" y1="0" x2="5" y2="5"/></svg>\n\n完毕。')
    out = render_rich(src)
    assert "<svg" in out and "<line" in out
    assert "完毕" in out

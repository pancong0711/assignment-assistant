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
    sol.add_version(ws, "c1", answer, source="ai")
    sol.pin_version(ws, "c1", "v1")


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
    assert "<svg viewBox=\"0 0 100 50\">" in h
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
    sol.add_version(ws, "c1", "完整答案 " + "细节。" * 100, source="ai")
    sol.pin_version(ws, "c1", "v1")
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

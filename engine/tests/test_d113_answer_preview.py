"""D113：参考答案独立预览 / 行间公式独立成段 / CLI 对等。

覆盖用户反馈的三类问题：
1. `\\[..\\]` 与正文同段 → 被 nl2br 插 `<br>` 拆断 → 公式显示成源码；
2. `\\begin{cases}` 长篇答案在预览里"空了一片"（渲染层其实正常，根因是 PWA 测量探针，见前端自检）；
3. 参考答案需要独立于作业纸预览（竖版单列、一题一页、CLI 与 PWA 同构）。
"""
import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from openpyxl import Workbook

from assist.cli import cli
from assist.files import solutions as sol
from assist.paper.htmlfile import render_answer_html
from assist.paper.richdoc import render_rich

FIXTURE = Path(__file__).parent / "fixtures" / "d113_answer.txt"


# ---------------- R6：行间公式必须独立成段 ----------------

def test_display_math_becomes_own_paragraph():
    """\\[ 前只有单换行时，也必须独立成段（否则 nl2br 的 <br> 会拆断定界符）。"""
    out = render_rich("正文：\n\\[\nE=mc^2\n\\]\n后续。")
    assert "<p>正文：</p>" in out, f"正文应独立成段：{out}"
    assert "\\[\nE=mc^2\n\\]" in out
    # 行间公式不得与正文同处一个 <p>
    assert "正文：<br>" not in out, f"行间公式未被独立成段：{out}"
    assert "后续。" in out


def test_display_dollar_math_becomes_own_paragraph():
    out = render_rich("因此\n$$\nE=1\n$$\n若 q>0")
    assert "因此<br>" not in out, f"$$ 未被独立成段：{out}"
    assert "<p>因此</p>" in out
    assert "若 q&gt;0" in out


def test_inline_math_stays_inline():
    """R7：行内公式必须保持行内（不得被提升成独立成行）。"""
    out = render_rich("行内 $a=1$ 与 \\(b=2\\) 结束")
    assert "<p>行内 $a=1$ 与 \\(b=2\\) 结束</p>" in out, f"行内公式被破坏：{out}"


def test_display_math_no_extra_blank_paragraph():
    """已带空行的行间公式不应额外产生空 <p>。"""
    out = render_rich("正文\n\n\\[\nE=1\n\\]\n\n后续")
    assert out.count("<p>") == 3, f"出现了多余的空段落：{out}"


def test_user_fixture_cases_not_truncated():
    """用户提供的真实长答案（含 cases + \\\\[4pt] + 两个 svg）不得被截断。"""
    md = FIXTURE.read_text(encoding="utf-8").strip()
    out = render_rich(md)
    assert "柱面处电场发生突变" in out, "答案尾部内容丢失"
    assert out.count("<svg") == 2, f"示意图数量不对：{out.count('<svg')}"
    # 行间公式应与正文分离（不出现"正文：<br>\["）
    import re
    assert not re.search(r"<br\s*/?>\s*\\\[", out), "行间公式仍与正文同段"


# ---------------- R2/R3：参考答案独立文档 ----------------

def _mk_ws(tmp_path: Path, answer: str) -> Path:
    ws = tmp_path / "ws"
    (ws / "kb").mkdir(parents=True)
    wb = Workbook(); sh = wb.active; sh.title = "chap04"
    sh.append(["id", "content", "img_path", "page", "related", "type", "solution", "note"])
    sh.append(["c1", "求同轴圆柱面电场", "", 1, "", "计算", "", ""])
    sh.append(["c2", "第二题", "", 1, "", "计算", "", ""])
    wb.save(ws / "kb" / "problems.xlsx")
    sol.add_version(ws, "chap04-c1", answer, source="ai", kb="problems", chap="chap04", pin=True)
    sol.add_version(ws, "chap04-c2", "简答 $E=\\frac{\\lambda}{2\\pi\\varepsilon_0 r}$。",
                    source="ai", kb="problems", chap="chap04", pin=True)
    task = {"id": "d113", "layout": {"orientation": "portrait", "per_page": 1},
            "items": [{"kb": "problems", "chap": "chap04", "ids": ["c1", "c2"], "tag": "t"}],
            "watermark": {"enabled": False}}
    (ws / "task.json").write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
    return ws


def test_render_answer_html_structure(tmp_path):
    ws = _mk_ws(tmp_path, FIXTURE.read_text(encoding="utf-8").strip())
    task = json.loads((ws / "task.json").read_text(encoding="utf-8"))
    html = render_answer_html(task, ws, title="参考答案 · d113")
    assert html.count('class="answer-card"') == 2, "每题一卡片"
    assert "参考答案 · d113" in html
    assert 'data-qid="chap04-c1"' in html and 'data-qid="chap04-c2"' in html
    # 一题一页：相邻卡片 break-before: page
    assert "break-before: page" in html
    # 超高题必须允许题内跨页（否则首页只剩标题）
    assert "break-inside: auto" in html
    # 两个业务 svg（来自长答案）
    assert html.count("<svg") == 2
    # 公式定界符保留（由前端 KaTeX 渲染）
    assert "\\\\[" in html or "\\[" in html


def test_render_answer_html_no_page_break(tmp_path):
    ws = _mk_ws(tmp_path, "简短答案 $E=1$")
    task = json.loads((ws / "task.json").read_text(encoding="utf-8"))
    html = render_answer_html(task, ws, one_page_per_question=False)
    assert "break-before: auto" in html, "连排模式应关闭强制分页"


def test_cli_sheet_answers(tmp_path):
    ws = _mk_ws(tmp_path, FIXTURE.read_text(encoding="utf-8").strip())
    out = ws / "answers.html"
    r = CliRunner().invoke(cli, ["sheet", "answers", "--task", str(ws / "task.json"),
                                 "-w", str(ws), "-o", str(out)])
    assert r.exit_code == 0, r.output
    assert out.is_file()
    html = out.read_text(encoding="utf-8")
    assert html.count('class="answer-card"') == 2
    assert "一题一页" in r.output


def test_cli_sheet_answers_no_content(tmp_path):
    ws = _mk_ws(tmp_path, "答案 $x=1$")
    out = ws / "a2.html"
    r = CliRunner().invoke(cli, ["sheet", "answers", "--task", str(ws / "task.json"),
                                 "-w", str(ws), "-o", str(out), "--no-content"])
    assert r.exit_code == 0, r.output
    html = out.read_text(encoding="utf-8")
    assert 'class="answer-q"' not in html, "--no-content 不应输出题干"


# ---------------- 执行后审查补充（D113 复审发现的问题） ----------------

def test_cli_answers_default_out_under_sheets_html(tmp_path):
    """local KaTeX 装在 <ws>/sheets/katex/，默认输出必须落在 <ws>/sheets/html/，
    否则 `../katex/` 相对路径指错 → 公式显示成源码。"""
    ws = _mk_ws(tmp_path, "答案 $x=1$")
    r = CliRunner().invoke(cli, ["sheet", "answers", "--task", str(ws / "task.json"), "-w", str(ws)])
    assert r.exit_code == 0, r.output
    out = ws / "sheets" / "html" / "answers-d113.html"
    assert out.is_file(), f"默认输出应在 sheets/html/：{r.output}"
    html = out.read_text(encoding="utf-8")
    assert 'href="../katex/katex.min.css"' in html


def test_cli_answers_katex_href_follows_output_dir(tmp_path):
    """用 -o 输出到其它目录时，KaTeX 相对路径必须按实际位置计算（不能固定 ../katex/）。"""
    ws = _mk_ws(tmp_path, "答案 $x=1$")
    deep = ws / "classes" / "classA" / "sheets" / "html"
    deep.mkdir(parents=True, exist_ok=True)
    out = deep / "a.html"
    r = CliRunner().invoke(cli, ["sheet", "answers", "--task", str(ws / "task.json"),
                                 "-w", str(ws), "-o", str(out)])
    assert r.exit_code == 0, r.output
    html = out.read_text(encoding="utf-8")
    # classes/classA/sheets/html → ../../../sheets/katex/ ... 至少不能是错的 "../katex/"
    assert "katex.min.css" in html
    import re
    href = re.search(r'href="([^"]*katex\.min\.css)"', html).group(1)
    expect = (ws / "sheets" / "html").resolve().parent  # 反推：相对路径应指向 ws/sheets/katex
    resolved = (out.parent / href).resolve()
    assert resolved == (ws / "sheets" / "katex" / "katex.min.css").resolve(), (
        f"KaTeX 相对路径指错：{href} → {resolved}")


def test_user_fixture_inline_and_display_math_classified():
    """R7：用户真实答案里行内/行间必须分类正确（行间 # = 8 个 $$ + 行间 \\[）。"""
    import re
    md = FIXTURE.read_text(encoding="utf-8").strip()
    out = render_rich(md)
    # 行内公式不得被塞进独立 <p> 独占一段（允许与正文同段）
    assert "取球心为原点" in out
    # 行间公式应独立成段：每个 \n\[\n 之前必须是 </p> 或换段边界
    assert not re.search(r"<br\s*/?>\s*\\\[", out), "存在行间公式与正文同段"
    # svg 完整
    assert out.count("<svg") == 2


# ---------------- D115：参考答案必须显示题目插图 ----------------

def test_answer_html_includes_figure(tmp_path):
    """D115：参考答案预览必须带题目插图（base64 内嵌），此前被丢弃。"""
    from PIL import Image
    ws = _mk_ws(tmp_path, "答案 $x=1$")
    (ws / "kb" / "fig").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 30), (240, 242, 246)).save(ws / "kb" / "fig" / "fig1.png")
    # 给第一题挂题图
    from openpyxl import load_workbook
    p = ws / "kb" / "problems.xlsx"
    wb = load_workbook(p); sh = wb["chap04"]
    sh.append(["c3", "带图题", "fig/fig1.png", 1, "", "计算", "", ""])
    wb.save(p)
    task = json.loads((ws / "task.json").read_text(encoding="utf-8"))
    task["items"] = [{"kb": "problems", "chap": "chap04", "ids": ["c3"], "tag": "t"}]
    (ws / "task.json").write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
    sol.add_version(ws, "chap04-c3", "带图题的答案", source="ai",
                    kb="problems", chap="chap04", pin=True)
    html = render_answer_html(task, ws)
    assert 'class="answer-fig"' in html, "参考答案必须内嵌题图"
    assert "data:image/png;base64," in html


def test_answer_html_figure_placeholder_when_missing(tmp_path):
    """题图文件读不到时给占位框（与作业纸一致，不静默消失）。"""
    ws = _mk_ws(tmp_path, "答案 $x=1$")
    from openpyxl import load_workbook
    p = ws / "kb" / "problems.xlsx"
    wb = load_workbook(p); sh = wb["chap04"]
    sh.append(["c4", "缺图题", "fig/not-exist.png", 1, "", "计算", "", ""])
    wb.save(p)
    task = json.loads((ws / "task.json").read_text(encoding="utf-8"))
    task["items"] = [{"kb": "problems", "chap": "chap04", "ids": ["c4"], "tag": "t"}]
    (ws / "task.json").write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
    sol.add_version(ws, "chap04-c4", "答案", source="ai", kb="problems", chap="chap04", pin=True)
    html = render_answer_html(task, ws)
    assert "answer-fig-ph" in html and "fig/not-exist.png" in html

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

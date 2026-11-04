"""D162：一批修复的回归。

- LaTeX 里**裸换行**导致 JSON 解析失败（模型直接把真实换行写进字符串）；
- 题库编辑器看不到 AI 标注的 related（前端内存副本 vs 引擎权威）；
- 作业包删除作业纸后计数不减（只删清单、没清包内引用）。
"""
from __future__ import annotations

import json

import pytest

from assist.grading.transcribe import parse_llm_json


# ---------------- LaTeX + 裸换行 ----------------
def test_bare_newline_in_json_string_recovers():
    """模型直接输出真实换行（JSON 非法）→ 必须能救回来。"""
    raw = '{"s": "第一行\n第二行"}'
    assert parse_llm_json(raw)["s"] == "第一行\n第二行"


def test_bare_newline_with_latex():
    """裸换行 + LaTeX 同时出现（最容易触发的一种）。"""
    raw = '{"s": "第一行\n公式 ' + '\\' + 'frac{1}{2}"}'
    out = parse_llm_json(raw)["s"]
    assert "\\frac" in out
    assert "\n" in out
    assert "\x0c" not in out


def test_latex_still_ok():
    out = parse_llm_json('{"s": "公式 ' + '\\' + 'frac{1}{2} 与 ' + '\\' + 'beta"}')["s"]
    assert "\\frac" in out and "\\beta" in out


# ---------------- /kb/full ----------------
def test_kb_full_endpoint_returns_related(tmp_path, monkeypatch):
    """D162：引擎应能返回**含 related** 的题库（供前端重载）。"""
    from openpyxl import Workbook
    from assist.files import kb_io as K
    ws = tmp_path
    (ws / "kb").mkdir()
    wb = Workbook(); sh = wb.active; sh.title = "chap04"
    sh.append(["id", "content", "related"])
    sh.append(["01", "题1", "动量守恒"])
    wb.save(ws / "kb" / "problems.xlsx")
    kb = K.read_kb(ws / "kb")
    assert kb["problems"]["chap04"][0]["related"] == "动量守恒"


def test_apply_related_writes_then_readable(tmp_path):
    """标注写回后，重新 read_kb 能读到（前端重载的数据来源）。"""
    from openpyxl import Workbook
    from assist.files import kb_io as K
    from assist.grading import rubric as RB
    ws = tmp_path
    (ws / "kb").mkdir()
    wb = Workbook(); sh = wb.active; sh.title = "chap04"
    sh.append(["id", "content", "related"])
    sh.append(["01", "题1", ""])
    wb.save(ws / "kb" / "problems.xlsx")
    qid = K.read_kb(ws / "kb")["problems"]["chap04"][0]["id"]
    RB.apply_related(ws, [{"kb": "problems", "chap": "chap04", "qid": qid,
                           "related": "角动量守恒", "meta": {"source": "ai"}}])
    got = K.read_kb(ws / "kb")["problems"]["chap04"][0]["related"]
    assert got == "角动量守恒"


# ---------------- 翻译 tag 是确定性的 ----------------
def test_translation_tag_is_deterministic():
    """translation 用等距选点（可复现），重算不会换人。"""
    from assist.roster.grouping import tag_students
    students = [{"name": f"S{i}", "number": str(i)} for i in range(20)]
    scores = {f"S{i}": {"mean": 100 - i} for i in range(20)}
    a = tag_students(students, scores)
    b = tag_students(students, scores)
    ta = {r["name"]: r["tag"] for r in a}
    tb = {r["name"]: r["tag"] for r in b}
    assert ta == tb
    assert any(t == "translation" for t in ta.values())

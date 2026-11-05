"""D168-B5：`example` 例题库 + 标准共现图。

教师口径（docs/112-D168 §2.1）：
> 从课程资料整理出来的知识点共现应该只限于从**例题**中得出，而大纲、ppt、
> 授课计划应该不支持这样的数据。例题共现图是**标准图**，反映授课过程的特点；
> 作业题的共现图反映的是学生作答情况。

→ `example` 是**分析专用**题库：只画标准共现图，**不布置、不批阅**。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from assist.grading import kb_examples as KE


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    (tmp_path / "kb").mkdir()
    return tmp_path


PARSED = {"examples": [
    {"content": "求两点电荷作用力", "solution": "F=kq1q2/r²",
     "knowledge": ["库仑定律", "电场强度"], "source": "第4章 例1"},
    {"content": "求球面电场", "solution": "用高斯定理",
     "knowledge": ["高斯定理", "电场强度"], "source": "第4章 例2"},
]}


# ---------------- kind 定位 ----------------

def test_example_kind_registered_but_not_gradable():
    """`example` 必须被认成已知 kind，但**不能**进批阅范式。"""
    from assist.grading.rules import ANALYSIS_ONLY_KINDS, SUPPORTED_KINDS
    from assist.files.kb_io import _KNOWN_KINDS
    assert "example" in _KNOWN_KINDS
    assert "example" not in SUPPORTED_KINDS
    assert "example" in ANALYSIS_ONLY_KINDS


# ---------------- 转换 ----------------

def test_examples_from_parsed():
    items = KE.examples_from_parsed(PARSED)
    assert len(items) == 2
    assert items[0]["related"] == "库仑定律,电场强度"
    assert items[0]["type"] == "example"
    assert "第4章" in items[0]["note"]


def test_string_knowledge_split():
    """`knowledge` 是字符串时按分隔符拆，不能逐字。"""
    items = KE.examples_from_parsed({"examples": [
        {"content": "题", "knowledge": "库仑定律，电场强度"}]})
    assert items[0]["related"] == "库仑定律,电场强度"


def test_skip_example_without_content():
    items = KE.examples_from_parsed({"examples": [
        {"solution": "只有解答没有题干", "knowledge": ["A"]}]})
    assert items == []


def test_empty_parsed_refused(ws):
    r = KE.import_examples(ws, {"examples": []})
    assert r["ok"] is False and "没有可用例题" in r["error"]


# ---------------- 导入 ----------------

def test_import_creates_kb_file(ws):
    r = KE.import_examples(ws, PARSED)
    assert r["ok"] and r["count"] == 2
    assert (ws / "kb" / "example.xlsx").is_file()


def test_import_appends_without_id_collision(ws):
    KE.import_examples(ws, PARSED)
    r2 = KE.import_examples(ws, PARSED)
    assert r2["total"] == 4
    ids = [e["id"] for e in KE.load_examples(ws)["examples"]]
    assert len(ids) == len(set(ids)), f"题号撞车：{ids}"


def test_import_replace_mode(ws):
    KE.import_examples(ws, PARSED)
    r = KE.import_examples(ws, PARSED, replace=True)
    assert r["total"] == 2


def test_import_snapshots_for_rollback(ws):
    KE.import_examples(ws, PARSED)
    r = KE.import_examples(ws, PARSED)
    assert r["snapshot"], "导入前应有快照（可回滚）"


# ---------------- 转成共现记录 ----------------

def test_examples_as_records_shape(ws):
    KE.import_examples(ws, PARSED)
    recs = KE.examples_as_records(ws)
    assert len(recs) == 2
    assert recs[0]["source"] == "example"
    q = recs[0]["analysis"]["questions"][0]
    terms = {e["knowledge"][0] for e in q["errors"]}
    assert terms == {"库仑定律", "电场强度"}


def test_standard_cooccurrence_works(ws):
    """标准图能算出来（与作答图同一套算法，只是数据源不同）。"""
    from assist.grading import cooccurrence as C
    KE.import_examples(ws, PARSED)
    recs = KE.examples_as_records(ws)
    co = C.cooccurrence(recs, n=2)
    assert co["total"] == 2
    assert any(set(c["terms"]) == {"库仑定律", "电场强度"} for c in co["combos"])


# ---------------- 概览 ----------------

def test_summary_not_ready_when_empty(ws):
    s = KE.summary(ws)
    assert s["count"] == 0 and s["ready"] is False


def test_summary_ready_after_import(ws):
    KE.import_examples(ws, PARSED)
    s = KE.summary(ws)
    assert s["count"] == 2 and s["ready"] is True and s["terms"] == 3


def test_summary_handles_missing_file(ws):
    assert KE.load_examples(ws) == {}

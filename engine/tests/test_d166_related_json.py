"""D166：知识点 JSON 化（与参考答案版本库同构）。

教师诉求：知识点要能像参考答案一样「预览 + 整理」，而不是只有一个被截断的 xlsx 单元格。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from assist.grading import rubric as RB


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    (tmp_path / "kb").mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_add_version_appends_not_overwrites(ws):
    RB.add_related_version(ws, kb="qa", chap="chap01", qid="c1",
                           terms=["库仑定律"], source="ai", model="m1", note="AI 标注")
    RB.add_related_version(ws, kb="qa", chap="chap01", qid="c1",
                           terms=["库仑定律", "电场强度"], source="human", note="教师补充")
    got = RB.get_related(ws, kb="qa", chap="chap01", qid="c1")
    assert [v["id"] for v in got["versions"]] == ["v1", "v2"]
    assert got["versions"][0]["terms"] == ["库仑定律"]
    assert got["versions"][1]["terms"] == ["库仑定律", "电场强度"]
    assert got["related"] == "库仑定律,电场强度"
    assert got["pinned_by"] == "human"


def test_get_related_falls_back_to_kb_column(ws):
    """还没有版本记录时，回落 xlsx `related` 列（兼容旧数据）。"""
    got = RB.get_related(ws, kb="qa", chap="chap01", qid="c1", fallback="旧标注A,旧标注B")
    assert got["fromKbFallback"] is True
    assert got["terms"] == ["旧标注A", "旧标注B"]
    assert got["versions"] == []


def test_vocab_hits_and_misses(ws):
    """受控词表命中的术语与词表外的术语要分开标出。"""
    (ws / "knowledge-terms.json").write_text(json.dumps({
        "version": 1, "terms": [{"term": "库仑定律"}, {"term": "电场强度"}]
    }, ensure_ascii=False), encoding="utf-8")
    RB.add_related_version(ws, kb="qa", chap="chap01", qid="c1",
                           terms=["库仑定律", "某个词表外概念"])
    got = RB.get_related(ws, kb="qa", chap="chap01", qid="c1")
    assert got["vocabHits"] == ["库仑定律"]
    assert got["vocabMisses"] == ["某个词表外概念"]


def test_apply_related_records_version(ws):
    """apply_related 写回 xlsx 的同时必须留下版本记录（可追溯）。"""
    from assist.files import kb_io
    kb_io.write_chapters_preserving(
        ws / "kb" / "qa.xlsx",
        {"chap01": [{"id": "c1", "content": "题", "solution": "", "related": ""}]})
    # 题号读回时会被加章节前缀（D111），写回必须用**规范化后**的 id
    rep = RB.apply_related(ws, [{"kb": "qa", "chap": "chap01", "qid": "chap01-c1",
                                 "related": "库仑定律，电场强度",
                                 "meta": {"source": "ai", "model": "m1"}}])
    assert rep["ok"] and rep["written"] == 1
    got = RB.get_related(ws, kb="qa", chap="chap01", qid="chap01-c1")
    assert len(got["versions"]) == 1
    assert got["versions"][0]["source"] == "ai"
    assert got["versions"][0]["model"] == "m1"
    # xlsx 列也写进去了（速查口径不变）
    row = kb_io.read_xlsx(ws / "kb" / "qa.xlsx", ws / "kb")["chap01"][0]
    assert "库仑定律" in row["related"]


def test_pinned_by_human_blocks_ai(ws):
    """教师锁定后，AI 标注应被跳过（D130 验收 6 口径不变）。"""
    RB.set_meta(ws, "qa", "chap01", "c1", {"pinned_by": "human"})
    plan = RB.plan_tagging(ws, [{"kb": "qa", "chap": "chap01", "qid": "c1",
                                 "related": "已有"}])
    assert plan["todo"] == []
    assert "教师已锁定" in plan["skipped"][0]["reason"]

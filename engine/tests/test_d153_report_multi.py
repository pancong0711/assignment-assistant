"""D153：教师报告多选（班级 × 作业包 × tag）。

教师要求：报告支持勾选多个班级/作业包，看更宏观的情况；能按 tag 筛选更好。
注意：**评阅结果里没有 tag 字段**，按 tag 筛选必须从名单 join。
"""
from __future__ import annotations

import json

import pytest

from assist.grading import teacher_report as TR


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "kb").mkdir()
    return tmp_path


def _put(ws, class_dir, pack, student, score, terms=("动量守恒",)):
    d = ws / class_dir / "grading" / pack / "evaluations"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{student}.json").write_text(json.dumps({
        "student": student, "total_score": score, "timestamp": "2026-10-30",
        "analysis": {"questions": [{"id": 1, "errors": [
            {"knowledge": [t], "confidence": "high"} for t in terms]}]},
    }, ensure_ascii=False), encoding="utf-8")


def _roster(ws, class_dir, pairs):
    d = ws / class_dir / "roster"
    d.mkdir(parents=True, exist_ok=True)
    payload = [{"name": n, "tag": t} for n, t in pairs]
    (d / "roster.json").write_text(json.dumps({"students": payload}, ensure_ascii=False),
                                   encoding="utf-8")


def test_collect_single(ws):
    _put(ws, "classes/A", "p1", "张三", 90)
    recs, srcs = TR.collect_multi(ws, ["classes/A"], ["p1"])
    assert len(recs) == 1
    assert srcs == ["classes/A/p1"]


def test_collect_multiple_packs(ws):
    _put(ws, "classes/A", "p1", "张三", 90)
    _put(ws, "classes/A", "p2", "张三", 80)
    recs, srcs = TR.collect_multi(ws, ["classes/A"], ["p1", "p2"])
    assert len(recs) == 2
    assert len(srcs) == 2


def test_collect_multiple_classes(ws):
    _put(ws, "classes/A", "p1", "张三", 90)
    _put(ws, "classes/B", "p1", "李四", 70)
    recs, srcs = TR.collect_multi(ws, ["classes/A", "classes/B"], ["p1"])
    assert {r["student"] for r in recs} == {"张三", "李四"}


def test_missing_pack_skipped(ws):
    _put(ws, "classes/A", "p1", "张三", 90)
    recs, srcs = TR.collect_multi(ws, ["classes/A"], ["p1", "nope"])
    assert len(recs) == 1 and srcs == ["classes/A/p1"]


def test_tag_filter_joins_roster(ws):
    """按 tag 筛选需要从名单 join（评阅结果里没有 tag）。"""
    _put(ws, "classes/A", "p1", "张三", 90)
    _put(ws, "classes/A", "p1", "李四", 60)
    _roster(ws, "classes/A", [("张三", "top"), ("李四", "middle")])
    recs, _ = TR.collect_multi(ws, ["classes/A"], ["p1"], tags=["top"])
    assert [r["student"] for r in recs] == ["张三"]


def test_no_tag_filter_returns_all(ws):
    _put(ws, "classes/A", "p1", "张三", 90)
    _put(ws, "classes/A", "p1", "李四", 60)
    recs, _ = TR.collect_multi(ws, ["classes/A"], ["p1"], tags=None)
    assert len(recs) == 2


def test_analyze_merged_records(ws):
    _put(ws, "classes/A", "p1", "张三", 90)
    _put(ws, "classes/A", "p2", "李四", 60)
    recs, _ = TR.collect_multi(ws, ["classes/A"], ["p1", "p2"])
    stat = TR.analyze(recs)
    assert stat["students"] == 2
    assert stat["avg"] > 0
    assert stat["knowledge_errors"][0]["term"] == "动量守恒"


def test_source_pack_annotated(ws):
    _put(ws, "classes/A", "p1", "张三", 90)
    recs, _ = TR.collect_multi(ws, ["classes/A"], ["p1"])
    assert recs[0]["_sourcePack"] == "classes/A/p1"

"""D149：把「AI 批阅成绩」作为一种成绩源（每次作业包 = 一列，可加权）。

教师口径：
- **未批阅 / 未提交 → 记 0 分**（不是空白）；
- 每包一列，可加权到总成绩；
- 输出与现有成绩源同构，直接复用 `merge_scores` 加权聚合。
"""
from __future__ import annotations

import json

import pytest

from assist.roster import grading_scores as G
from assist.roster.grouping import merge_scores

CLASS = "classes/化工25"


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "kb").mkdir()
    return tmp_path


def _put(ws, pack, student, score, ts="2026-10-30 10:00"):
    d = ws / CLASS / "grading" / pack / "evaluations"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{student}.json").write_text(json.dumps({
        "student": student, "total_score": score, "timestamp": ts,
    }, ensure_ascii=False), encoding="utf-8")


def test_list_packs_only_with_evaluations(ws):
    _put(ws, "p1", "张三", 90)
    (ws / CLASS / "grading" / "p2" / "evaluations").mkdir(parents=True)
    packs = G.list_grading_packs(ws, CLASS)
    assert [p["packId"] for p in packs] == ["p1"]
    assert packs[0]["graded"] == 1


def test_list_packs_skips_internal_dirs(ws):
    _put(ws, "p1", "张三", 90)
    (ws / CLASS / "grading" / "_trend").mkdir(parents=True)
    assert [p["packId"] for p in G.list_grading_packs(ws, CLASS)] == ["p1"]


def test_scores_from_evaluations(ws):
    _put(ws, "p1", "张三", 88)
    r = G.grading_scores(ws, CLASS, "p1", students=["张三"])
    assert r["rows"][0]["score"] == 88.0
    assert r["rows"][0]["graded"] is True


def test_ungraded_student_gets_zero(ws):
    """**核心口径**：名单里有但没批阅 → 0 分（不是缺行）。"""
    _put(ws, "p1", "张三", 88)
    r = G.grading_scores(ws, CLASS, "p1", students=["张三", "李四"])
    by = {x["name"]: x for x in r["rows"]}
    assert by["李四"]["score"] == 0.0
    assert by["李四"]["graded"] is False
    assert r["zeroFilled"] == 1


def test_unsubmitted_is_zero_and_flagged(ws):
    _put(ws, "p1", "张三", 88)
    r = G.grading_scores(ws, CLASS, "p1", students=["张三", "没交的"])
    row = next(x for x in r["rows"] if x["name"] == "没交的")
    assert row["score"] == 0.0 and row["submitted"] is False


def test_extra_eval_students_included(ws):
    """批阅里有、名单没传的学生也要给出来（避免丢分）。"""
    _put(ws, "p1", "张三", 88)
    _put(ws, "p1", "编外", 70)
    r = G.grading_scores(ws, CLASS, "p1", students=["张三"])
    assert {x["name"] for x in r["rows"]} == {"张三", "编外"}


def test_missing_pack_errors(ws):
    with pytest.raises(G.GradingScoreError):
        G.grading_scores(ws, CLASS, "nope", students=["张三"])


def test_path_traversal_rejected(ws):
    with pytest.raises(G.GradingScoreError):
        G.list_grading_packs(ws, "../../etc")


def test_rows_merge_with_existing_sources(ws):
    """与 Excel 成绩源**同一套加权聚合**（不新增算法）。"""
    _put(ws, "p1", "张三", 100)
    r = G.grading_scores(ws, CLASS, "p1", students=["张三", "李四"])
    students = [{"name": "张三"}, {"name": "李四"}]
    # 模拟另一列（手工成绩），权重 1
    extra = [{"name": "张三", "score": 60, "weight": 1.0, "source": "exam:期末"},
             {"name": "李四", "score": 80, "weight": 1.0, "source": "exam:期末"}]
    merged = merge_scores(students, r["rows"] + extra)
    # 张三 (100+60)/2 = 80；李四 (0+80)/2 = 40
    assert merged["张三"]["mean"] == 80.0
    assert merged["李四"]["mean"] == 40.0


def test_weight_participates(ws):
    _put(ws, "p1", "张三", 100)
    r = G.grading_scores(ws, CLASS, "p1", students=["张三"])
    rows = r["rows"]
    rows[0]["weight"] = 3.0          # 批阅成绩权重 3
    students = [{"name": "张三"}]
    extra = [{"name": "张三", "score": 40, "weight": 1.0, "source": "exam:期末"}]
    merged = merge_scores(students, rows + extra)
    assert merged["张三"]["mean"] == 85.0    # (100*3 + 40*1)/4

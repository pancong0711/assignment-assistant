"""D168：作业包 roster / 作答名单快照（保证历史可复现）。

教师问题（docs/112-D168 §3.1）：
> 换新作业包时 roster 会变；想批阅之前的作业，roster 会切回原来的吗？这关系到批阅依据的 tag。

修复前：tag 来自前端 plan，roster 一改历史不可复现。
修复后：`roster-tags/<packId>.json` 冻结 + 批阅时**以快照为准**。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from assist.grading import snapshots as S

CLASS = "classes/化工251"
PACK = "homework1"


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    (tmp_path / "classes" / "化工251").mkdir(parents=True)
    return tmp_path


STUDENTS = [
    {"name": "张三", "number": "2023001", "tag": "top"},
    {"name": "李四", "number": "2023002", "tag": "middle"},
]


# ---------------- roster-tags 快照 ----------------

def test_write_and_read_snapshot(ws):
    rep = S.write_tags_snapshot(ws, CLASS, PACK, STUDENTS)
    assert rep["ok"] and rep["count"] == 2 and rep["created"] is True
    got = S.read_tags_snapshot(ws, CLASS, PACK)
    assert got["ok"]
    assert [(s["number"], s["tag"]) for s in got["students"]] == [
        ("2023001", "top"), ("2023002", "middle")]


def test_snapshot_is_frozen_by_default(ws):
    """**关键**：已存在的快照默认不被覆盖（防批阅中途改掉历史依据）。"""
    S.write_tags_snapshot(ws, CLASS, PACK, STUDENTS)
    rep = S.write_tags_snapshot(ws, CLASS, PACK,
                                [{"name": "张三", "number": "2023001", "tag": "middle"}])
    assert rep["ok"] and rep["created"] is False
    assert "已存在" in rep["skipped"]
    got = S.read_tags_snapshot(ws, CLASS, PACK)
    assert len(got["students"]) == 2          # 仍是 2 人，未被 1 人覆盖
    assert got["students"][0]["tag"] == "top"


def test_force_overwrites(ws):
    S.write_tags_snapshot(ws, CLASS, PACK, STUDENTS)
    rep = S.write_tags_snapshot(ws, CLASS, PACK,
                                [{"name": "张三", "number": "2023001", "tag": "middle"}],
                                force=True)
    assert rep["created"] is True
    got = S.read_tags_snapshot(ws, CLASS, PACK)
    assert len(got["students"]) == 1 and got["students"][0]["tag"] == "middle"


def test_empty_roster_refused(ws):
    rep = S.write_tags_snapshot(ws, CLASS, PACK, [])
    assert rep["ok"] is False and "名单为空" in rep["error"]


def test_class_dir_traversal_rejected(ws):
    with pytest.raises(S.SnapshotError):
        S.write_tags_snapshot(ws, "classes/../../etc", PACK, STUDENTS)


def test_bad_pack_id_rejected(ws):
    with pytest.raises(S.SnapshotError):
        S.write_tags_snapshot(ws, CLASS, "../evil", STUDENTS)


def test_tag_counts(ws):
    S.write_tags_snapshot(ws, CLASS, PACK, STUDENTS + [
        {"name": "王五", "number": "2023003", "tag": "top"}])
    assert S.tag_counts(ws, CLASS, PACK) == {"top": 2, "middle": 1}


def test_list_snapshots(ws):
    S.write_tags_snapshot(ws, CLASS, "hw1", STUDENTS)
    S.write_tags_snapshot(ws, CLASS, "hw2", STUDENTS[:1])
    items = S.list_tags_snapshots(ws, CLASS)
    assert [x["packId"] for x in items] == ["hw1", "hw2"]
    assert [x["count"] for x in items] == [2, 1]


# ---------------- 差异检测（快照 vs 当前 roster） ----------------

def test_diff_detects_tag_change(ws):
    from assist.files import roster_io
    S.write_tags_snapshot(ws, CLASS, PACK, STUDENTS)
    roster_io.write_roster(ws, CLASS, [
        {"name": "张三", "number": "2023001", "tag": "middle"},   # tag 变了
        {"name": "李四", "number": "2023002", "tag": "middle"},
    ])
    d = S.diff_against_roster(ws, CLASS, PACK)
    assert d["ok"] and d["changed"] is True
    assert d["tagChanged"] == [{"number": "2023001", "name": "张三",
                                "from": "top", "to": "middle"}]


def test_diff_detects_added_and_removed(ws):
    from assist.files import roster_io
    S.write_tags_snapshot(ws, CLASS, PACK, STUDENTS)
    roster_io.write_roster(ws, CLASS, [STUDENTS[0]])       # 李四移出
    d = S.diff_against_roster(ws, CLASS, PACK)
    assert d["changed"] is True
    assert [x["name"] for x in d["removed"]] == ["李四"]
    assert d["added"] == []


def test_diff_unchanged_when_same(ws):
    from assist.files import roster_io
    S.write_tags_snapshot(ws, CLASS, PACK, STUDENTS)
    roster_io.write_roster(ws, CLASS, STUDENTS)
    d = S.diff_against_roster(ws, CLASS, PACK)
    assert d["ok"] and d["changed"] is False


def test_diff_missing_snapshot(ws):
    assert S.diff_against_roster(ws, CLASS, "nope")["missing"] is True


# ---------------- submissions.json ----------------

def test_write_submissions_counts_images(ws):
    rep = S.write_submissions(ws, CLASS, PACK, [
        {"name": "张三", "number": "2023001", "tag": "top",
         "images": ["1.png", "2.png", "3.png"]}])
    assert rep["ok"] and rep["count"] == 1
    got = S.read_submissions(ws, CLASS, PACK)
    assert got["submitted"][0]["imageCount"] == 3


def test_submissions_records_unrecognized(ws):
    S.write_submissions(ws, CLASS, PACK,
                        [{"name": "张三", "images": ["a.png"]}],
                        unrecognized=["weird-name.png", "  "])
    got = S.read_submissions(ws, CLASS, PACK)
    assert got["unrecognized"] == ["weird-name.png"]


def test_submissions_empty_refused(ws):
    assert S.write_submissions(ws, CLASS, PACK, [])["ok"] is False


# ---------------- 提交率 ----------------

def test_submit_stats_per_tag(ws):
    """提交率 = submissions ÷ roster-tags 快照（分母是"应交"）。"""
    S.write_tags_snapshot(ws, CLASS, PACK, STUDENTS + [
        {"name": "王五", "number": "2023003", "tag": "top"}])
    S.write_submissions(ws, CLASS, PACK, [STUDENTS[0]])      # 只交了张三(top)
    st = S.submit_stats(ws, CLASS, PACK)
    assert st["ok"]
    assert st["byTag"]["top"] == {"expected": 2, "submitted": 1, "rate": 0.5}
    assert st["byTag"]["middle"] == {"expected": 1, "submitted": 0, "rate": 0.0}
    assert st["total"] == {"expected": 3, "submitted": 1, "rate": round(1 / 3, 4)}


def test_submit_stats_needs_snapshot(ws):
    S.write_submissions(ws, CLASS, PACK, [STUDENTS[0]])
    st = S.submit_stats(ws, CLASS, PACK)
    assert st["ok"] is False and "roster 快照" in st["error"]


# ---------------- 批阅集成：按快照锁定 tag ----------------

def test_grade_uses_snapshot_tag_not_live_plan(ws):
    """**核心验收**：快照存在时，批阅用的 tag 以快照为准（不随 plan 变）。"""
    from assist.grading.flow import _write_grade_snapshots
    # 先冻结：张三 = top
    S.write_tags_snapshot(ws, CLASS, PACK, STUDENTS, source=S.SOURCE_RECOMPUTE)
    task = {"class_dir": CLASS, "pack_id": PACK}
    # 这次 plan 里张三变成了 middle（模拟 roster 被改）
    plan = {"packId": PACK, "students": [
        {"name": "张三", "number": "2023001", "tag": "middle",
         "images": ["1.png"], "questions": []}]}
    out = _write_grade_snapshots(ws, task, plan)
    assert out["students"][0]["tag"] == "top", "应被快照锁定为 top"


def test_grade_auto_writes_snapshot_when_missing(ws):
    from assist.grading.flow import _write_grade_snapshots
    task = {"class_dir": CLASS, "pack_id": PACK}
    plan = {"packId": PACK, "students": [
        {"name": "张三", "number": "2023001", "tag": "top", "images": ["1.png"]}]}
    out = _write_grade_snapshots(ws, task, plan)
    assert out["students"][0]["tag"] == "top"
    snap = S.read_tags_snapshot(ws, CLASS, PACK)
    assert snap["ok"] and snap["source"] == S.SOURCE_AUTO_GRADE


def test_grade_writes_submissions(ws):
    from assist.grading.flow import _write_grade_snapshots
    task = {"class_dir": CLASS, "pack_id": PACK}
    plan = {"packId": PACK, "students": [
        {"name": "张三", "number": "2023001", "tag": "top",
         "images": ["1.png", "2.png"]}]}
    _write_grade_snapshots(ws, task, plan)
    sub = S.read_submissions(ws, CLASS, PACK)
    assert sub["ok"]
    assert sub["submitted"][0]["imageCount"] == 2


def test_grade_snapshot_failure_does_not_break_grading(ws):
    """快照写入失败绝不能影响批阅（只告警）。"""
    from assist.grading.flow import _write_grade_snapshots
    task = {"class_dir": "", "pack_id": PACK}      # class_dir 空 → 跳过
    plan = {"packId": PACK, "students": [{"name": "张三", "tag": "top"}]}
    out = _write_grade_snapshots(ws, task, plan)
    assert out["students"][0]["tag"] == "top"

"""D184：审计采用 tag 的 UPSERT 修复。

根因：快照生成较早 / roster 后来变化，导致实际已提交学生不在快照里；
旧 apply_audit_tags() 只 patch 快照已有行，缺失学生直接进 missing 且不写文件。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from assist.grading import tag_audit as T
from assist.grading import snapshots as S
from assist.files import roster_io

CLASS = "classes/化工251"
PACK = "hw-d184"

INNOVATION = "innovation"
TRANSLATION = "translation"


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    return tmp_path


def _roster(ws: Path, students: list[dict]) -> dict:
    return roster_io.write_roster(ws, CLASS, students, pack_id=PACK)


def _snap(ws: Path, students: list[dict]) -> dict:
    return S.write_tags_snapshot(ws, CLASS, PACK, students)


def _read_snap(ws: Path) -> dict:
    return S.read_tags_snapshot(ws, CLASS, PACK)


def _find_row(ws: Path, name: str) -> dict | None:
    snap = _read_snap(ws)
    for s in snap.get("students") or []:
        if str(s.get("name")) == name:
            return s
    return None


def test_apply_upserts_from_roster_when_student_missing_in_snapshot(ws):
    """a. 快照只有甲、roster 有甲乙；对乙 apply translation -> 快照新增乙，previousTag=innovation。"""
    assert _roster(ws, [
        {"name": "甲", "number": "1", "tag": INNOVATION},
        {"name": "乙", "number": "2", "tag": INNOVATION},
    ]).get("ok")
    assert _snap(ws, [{"name": "甲", "number": "1", "tag": INNOVATION}]).get("ok")

    rep = T.apply_audit_tags(ws, class_dir=CLASS, pack_id=PACK,
                             changes=[{"name": "乙", "number": "2", "tag": TRANSLATION}])
    assert rep["ok"] and rep["written"]
    assert [a["name"] for a in rep["applied"]] == ["乙"]

    yi = _find_row(ws, "乙")
    assert yi is not None
    assert yi["tag"] == TRANSLATION
    assert yi["previousTag"] == INNOVATION
    assert yi["number"] == "2"
    assert yi["tagUpdateReason"] == "audit-apply"
    assert any(h["from"] == INNOVATION and h["to"] == TRANSLATION for h in yi.get("tagHistory") or [])

    jia = _find_row(ws, "甲")
    assert jia is not None and jia["tag"] == INNOVATION


def test_apply_upserts_from_change_when_roster_and_snapshot_miss(ws):
    """b. 快照/roster 都没有但 changes 有姓名 -> 插入，previousTag 为空。"""
    assert _roster(ws, [
        {"name": "甲", "number": "1", "tag": INNOVATION},
    ]).get("ok")
    assert _snap(ws, [{"name": "甲", "number": "1", "tag": INNOVATION}]).get("ok")

    rep = T.apply_audit_tags(ws, class_dir=CLASS, pack_id=PACK,
                             changes=[{"name": "乙", "number": "2", "tag": TRANSLATION}])
    assert rep["ok"] and rep["written"]
    yi = _find_row(ws, "乙")
    assert yi is not None
    assert yi["tag"] == TRANSLATION
    assert yi.get("previousTag", "") == ""
    assert yi["number"] == "2"
    hist = yi.get("tagHistory") or []
    assert hist[-1].get("upsert") == "change"


def test_apply_matches_by_number_when_names_differ(ws):
    """c. 快照/roster 姓名不同但 number 一致 -> 按 number 命中并更新。"""
    assert _roster(ws, [
        {"name": "乙", "number": "1", "tag": INNOVATION},
    ]).get("ok")
    assert _snap(ws, [{"name": "甲", "number": "1", "tag": INNOVATION}]).get("ok")

    rep = T.apply_audit_tags(ws, class_dir=CLASS, pack_id=PACK,
                             changes=[{"name": "乙", "number": "1", "tag": TRANSLATION}])
    assert rep["ok"] and rep["written"]
    row = _find_row(ws, "乙")
    assert row is not None
    assert row["tag"] == TRANSLATION
    assert row["number"] == "1"


def test_apply_partial_missing_keeps_applied_and_missing(ws):
    """d. 多学生部分 missing -> 已匹配写入，missing 保留。"""
    assert _roster(ws, [
        {"name": "甲", "number": "1", "tag": INNOVATION},
        {"name": "乙", "number": "2", "tag": INNOVATION},
    ]).get("ok")
    assert _snap(ws, [{"name": "甲", "number": "1", "tag": INNOVATION}]).get("ok")

    rep = T.apply_audit_tags(ws, class_dir=CLASS, pack_id=PACK,
                             changes=[
                                 {"name": "甲", "tag": TRANSLATION},
                                 {"name": "乙", "number": "2", "tag": TRANSLATION},
                                 {"tag": TRANSLATION},  # 无身份 -> missing
                             ])
    assert rep["ok"] and rep["written"]
    assert sorted(a["name"] for a in rep["applied"]) == sorted(["甲", "乙"])
    assert rep["missing"] == ["(无名)"]

    assert _find_row(ws, "甲")["tag"] == TRANSLATION
    assert _find_row(ws, "乙")["tag"] == TRANSLATION


def test_apply_does_not_delete_untouched_students(ws):
    """e. 不删除快照中未参与本次操作的学生。"""
    assert _roster(ws, [
        {"name": "甲", "number": "1", "tag": INNOVATION},
        {"name": "乙", "number": "2", "tag": INNOVATION},
        {"name": "丙", "number": "3", "tag": INNOVATION},
    ]).get("ok")
    assert _snap(ws, [
        {"name": "甲", "number": "1", "tag": INNOVATION},
        {"name": "丙", "number": "3", "tag": INNOVATION},
    ]).get("ok")

    rep = T.apply_audit_tags(ws, class_dir=CLASS, pack_id=PACK,
                             changes=[{"name": "乙", "number": "2", "tag": TRANSLATION}])
    assert rep["ok"] and rep["written"]
    names = {str(s.get("name")) for s in _read_snap(ws).get("students") or []}
    assert names == {"甲", "乙", "丙"}


def test_apply_updates_audit_resolution_for_upserted_student(ws):
    """f. audit 文件存在时，对新插入学生也更新 resolution。"""
    # 构造简单题库 + 转写，让 run_audit 能产出乙的审计行。
    from assist.files.kb_io import write_xlsx
    (ws / "kb").mkdir(parents=True, exist_ok=True)
    write_xlsx(ws / "kb" / "problems.xlsx", {
        "chap": [{"id": i, "content": q, "solution": "略"} for i, q in [
            (1, "质量为 2 kg 的物块以 3 m/s 撞静止物块，完全弹性碰撞，求碰后两物块速度。"),
        ]],
    })
    taskpads = [
        {"id": "pd", "target_tag": INNOVATION, "numbering": "auto",
         "items": [{"kb": "problems", "chap": "chap", "tag": INNOVATION,
                    "ids": ["chap-1"]}]},
        {"id": "pd2", "target_tag": TRANSLATION, "numbering": "auto",
         "items": [{"kb": "problems", "chap": "chap", "tag": TRANSLATION,
                    "ids": ["chap-1"]}]},
    ]
    tr_dir = ws / CLASS / "grading" / PACK / "transcripts"
    tr_dir.mkdir(parents=True, exist_ok=True)
    (tr_dir / "乙.json").write_text(json.dumps({
        "items": [{"no": "1", "printed_question": "质量为 2 kg 的物块以 3 m/s 撞静止物块，完全弹性碰撞，求碰后两物块速度。",
                   "answer": "解：略"}]
    }, ensure_ascii=False), encoding="utf-8")

    assert _roster(ws, [
        {"name": "甲", "number": "1", "tag": INNOVATION},
        {"name": "乙", "number": "2", "tag": INNOVATION},
    ]).get("ok")
    assert _snap(ws, [{"name": "甲", "number": "1", "tag": INNOVATION}]).get("ok")

    audit = T.run_audit(ws, class_dir=CLASS, pack_id=PACK, taskpads=taskpads)
    assert audit["ok"]
    yi_audit = next((s for s in audit["students"] if s["name"] == "乙"), None)
    assert yi_audit is not None

    rep = T.apply_audit_tags(ws, class_dir=CLASS, pack_id=PACK,
                             changes=[{"name": "乙", "number": "2", "tag": TRANSLATION}])
    assert rep["ok"] and rep["written"]

    aud = T.read_audit(ws, class_dir=CLASS, pack_id=PACK)
    yi_row = next((s for s in aud["students"] if s["name"] == "乙"), None)
    assert yi_row is not None
    assert yi_row["resolution"]["to"] == TRANSLATION
    assert yi_row["verdict"] == "match"

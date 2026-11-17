"""D183：批阅 plan 必须按作业包快照 tag 选作业纸/题目。

现场：学生 roster tag=innovation，AI 审计建议/采用 translation。D172 的
`apply_audit_tags()` 只更新 `roster-tags/<packId>.json` 快照，不改
`roster.xlsx`。若 `build_plan()` 只读 roster，重批仍会按 innovation 选错题目，
表现就像“tag 转换失败/已评阅所以不生效”。

本测试只用合成数据，不访问网络或真实学生数据。
"""
from __future__ import annotations

import json
from pathlib import Path

from assist.files import roster_io
from assist.grading import inputs as I
from assist.grading import snapshots as SN

CLASS_DIR = "classes/SynthD183"
PACK = "pack-d183"


def _write_roster(ws: Path, tag: str = "innovation") -> None:
    (ws / "kb").mkdir(exist_ok=True)
    roster_io.write_roster(
        ws, CLASS_DIR,
        [{"name": "学生甲", "number": "001", "tag": tag},
         {"name": "学生乙", "number": "002", "tag": tag}])


def _pads() -> dict:
    return {
        "innovation": {
            "id": "pad-innovation",
            "items": [{"no": "1", "content": "创新题：设计一个实验", "solution": "创新答案"}],
        },
        "translation": {
            "id": "pad-translation",
            "items": [{"no": "1", "content": "翻译题：把这段英文译成中文", "solution": "参考译文"}],
        },
    }


def _plan(ws: Path) -> dict:
    return I.build_plan(
        ws, task_id=PACK, class_dir=CLASS_DIR,
        explicit_pads=_pads(),
        review_students=[
            {"name": "学生甲", "number": "001", "workAnswerId": "wa1", "images": ["/a.jpg"]},
            {"name": "学生乙", "number": "002", "workAnswerId": "wa2", "images": ["/b.jpg"]},
        ],
    )


def test_build_plan_uses_roster_tag_without_snapshot(tmp_path: Path):
    _write_roster(tmp_path, "innovation")
    plan = _plan(tmp_path)
    a = next(s for s in plan["students"] if s["name"] == "学生甲")
    assert a["tag"] == "innovation"
    assert a["padId"] == "pad-innovation"
    assert "创新题" in a["questions"][0]["content"]


def test_build_plan_uses_snapshot_tag_after_audit_apply(tmp_path: Path):
    _write_roster(tmp_path, "innovation")
    SN.write_tags_snapshot(tmp_path, CLASS_DIR, PACK, [
        {"name": "学生甲", "number": "001", "tag": "translation"},
        {"name": "学生乙", "number": "002", "tag": "innovation"},
    ])

    plan = _plan(tmp_path)
    a = next(s for s in plan["students"] if s["name"] == "学生甲")
    b = next(s for s in plan["students"] if s["name"] == "学生乙")
    assert a["tag"] == "translation"
    assert a["padId"] == "pad-translation"
    assert "翻译题" in a["questions"][0]["content"]
    # 未改 tag 的学生仍用原作业纸
    assert b["tag"] == "innovation"
    assert b["padId"] == "pad-innovation"


def test_build_plan_snapshot_matches_number_before_name(tmp_path: Path):
    _write_roster(tmp_path, "innovation")
    SN.write_tags_snapshot(tmp_path, CLASS_DIR, PACK, [
        # 姓名不同但学号一致：学号是快照主键
        {"name": "改名后的学生甲", "number": "001", "tag": "translation"},
    ])
    plan = _plan(tmp_path)
    a = next(s for s in plan["students"] if s["name"] == "学生甲")
    assert a["tag"] == "translation"


def test_students_with_tags_explicit_pack_id(tmp_path: Path):
    _write_roster(tmp_path, "innovation")
    SN.write_tags_snapshot(tmp_path, CLASS_DIR, PACK, [
        {"name": "学生甲", "number": "001", "tag": "translation"},
    ])
    rows = I.students_with_tags(tmp_path, CLASS_DIR, pack_id=PACK)
    assert {r["name"]: r["tag"] for r in rows} == {
        "学生甲": "translation", "学生乙": "innovation"}

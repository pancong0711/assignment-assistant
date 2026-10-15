"""D85 §3：本地批阅草稿存储回归（纯文件，无浏览器）。"""

from pathlib import Path

from assist.xxt.grade_store import (delete_draft, draft_file, read_drafts,
                                    save_draft, student_key)


def test_save_read_merge(tmp_path: Path):
    r = save_draft(tmp_path, "C1", "W1", "学生A", score=100, comment="很好")
    assert r["ok"] and Path(r["file"]).is_file()
    assert r["draft"]["score"] == 100.0
    # 二次更新只改分数，保留批语
    save_draft(tmp_path, "C1", "W1", "学生A", score=90)
    d = read_drafts(tmp_path, "C1", "W1")["学生A"]
    assert d["score"] == 90.0 and d["comment"] == "很好" and d["updatedAt"]


def test_images_and_key_priority(tmp_path: Path):
    save_draft(tmp_path, "C1", "W1", "54761942", score=88,
               images=[{"name": "a.png", "data_b64": "AAA"}])
    d = read_drafts(tmp_path, "C1", "W1")["54761942"]
    assert d["images"][0]["name"] == "a.png"
    assert student_key({"workAnswerId": "54761942", "name": "某人"}) == "54761942"
    assert student_key({"name": "某人"}) == "某人"


def test_reject_bad_ids_and_score(tmp_path: Path):
    assert draft_file(tmp_path, "../x", "W1") is None
    assert save_draft(tmp_path, "C1", "W1", "", score=1)["ok"] is False
    assert save_draft(tmp_path, "C1", "W1", "X", score="abc")["ok"] is False
    assert read_drafts(tmp_path, "nope", "W1") == {}


def test_delete_draft(tmp_path: Path):
    save_draft(tmp_path, "C1", "W1", "X", score=1)
    assert delete_draft(tmp_path, "C1", "W1", "X")["ok"] is True
    assert read_drafts(tmp_path, "C1", "W1") == {}
    assert delete_draft(tmp_path, "C1", "W1", "X")["ok"] is False

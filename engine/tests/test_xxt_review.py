"""D75-1c/d 回归：批阅图片命名 / 目录索引 / 时长清理（纯逻辑）。"""

import json
import os
import time

from assist.xxt import review


def test_image_filename_old_style():
    n = review.image_filename("张三", "示例班", "热力学作业", 3, ".jpg")
    assert n == "张三_示例班+热力学作业_p03.jpg"
    bad = review.image_filename('a/b:c*?"<>|', "班", "作业", 1, ".png")
    assert "/" not in bad and ":" not in bad and bad.endswith("_p01.png")


def test_manifest_roundtrip_and_index(tmp_path):
    d = review.work_dir(tmp_path, "11", "22")
    d.mkdir(parents=True, exist_ok=True)
    (d / review.image_filename("张三", "示例班", "作业A", 1)).write_bytes(b"jpg")
    (d / review.image_filename("张三", "示例班", "作业A", 2)).write_bytes(b"jpg")
    review.write_manifest(tmp_path, "11", "22", {
        "classId": "11", "workId": "22", "courseId": "1",
        "courseName": "物理", "className": "示例班", "workName": "作业A",
        "generated_at": "2026-10-10 12:00:00",
        "students": [{"studentId": "9", "name": "张三", "workAnswerId": "99",
                      "images": ["张三_示例班+作业A_p01.jpg"],
                      "comment": "批语", "per_question_comments": ["题1"], "score": "95"}],
    })
    items = review.list_review_works(tmp_path)
    assert len(items) == 1
    it = items[0]
    assert it["className"] == "示例班" and it["workName"] == "作业A"
    assert it["count"] == 2 and it["students"] == 1
    assert review.read_manifest(tmp_path, "11", "22")["students"][0]["score"] == "95"


def test_safe_image_path_blocks_traversal(tmp_path):
    assert review.safe_work_dir(tmp_path, "../../etc", "1") is None
    assert review.safe_image_path(tmp_path, "11", "22", "../x.jpg") is None


def test_prune_review_by_months(tmp_path):
    old = review.work_dir(tmp_path, "11", "old")
    new = review.work_dir(tmp_path, "11", "new")
    old.mkdir(parents=True); new.mkdir(parents=True)
    (old / "a_p01.jpg").write_bytes(b"x")
    old_ts = time.time() - 200 * 24 * 3600
    os.utime(old, (old_ts, old_ts))
    res = review.prune_review(tmp_path, months=6)
    assert res["removed_count"] == 1
    assert not old.exists() and new.exists()
    assert review.review_stats(tmp_path)["works"] == 0 or not review.work_dir(tmp_path, "11", "old").exists()

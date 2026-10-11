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


def test_prune_review_keeps_manifest(tmp_path):
    old = review.work_dir(tmp_path, "11", "old")
    new = review.work_dir(tmp_path, "11", "new")
    old.mkdir(parents=True); new.mkdir(parents=True)
    (old / "a_p01.jpg").write_bytes(b"x")
    old_ts = time.time() - 200 * 24 * 3600
    os.utime(old, (old_ts, old_ts))
    res = review.prune_review(tmp_path, months=6)
    assert res["removed_count"] == 1 and res["deleted_images"] == 1
    assert old.exists() and (old / "students.json").is_file()   # 删图片、留清单
    assert not (old / "a_p01.jpg").exists()
    assert new.exists()
    purged = review.purge_review_work(tmp_path, "11", "old")
    assert purged["ok"] and not old.exists()


def test_comment_image_filename():
    a = review.comment_image_filename("张三", "示例班", "作业A", 2, ".jpg")
    assert a == "张三_示例班+作业A_comment_p02.jpg"
    b = review.comment_image_filename("张三", "示例班", "作业A", 1, ".png", qidx=3)
    assert b == "张三_示例班+作业A_comment_q3_p01.png"


def test_delete_work_images_keeps_manifest(tmp_path):
    d = review.work_dir(tmp_path, "11", "22"); d.mkdir(parents=True)
    (d / review.image_filename("张三", "示例班", "作业A", 1)).write_bytes(b"a")
    (d / review.comment_image_filename("张三", "示例班", "作业A", 1)).write_bytes(b"c")
    review.write_manifest(tmp_path, "11", "22", {
        "classId": "11", "workId": "22", "className": "示例班", "workName": "作业A",
        "students": [{"name": "张三", "images": ["x.jpg"], "comment_images": ["c.jpg"]}],
    })
    res = review.delete_work_images(tmp_path, "11", "22")
    assert res["ok"] and res["deleted_answer"] == 1 and res["deleted_comment"] == 1
    m = review.read_manifest(tmp_path, "11", "22")
    assert m["images_deleted"] is True and m["students"][0]["images"] == []
    assert m["students"][0]["deleted_images"] == ["x.jpg"]
    assert (d / "students.json").is_file()

"""D75-1 回归：review 列表 HTML 解析（合成 fixture，不依赖真实数据）。"""

import json
import os

from assist.xxt import preview

FIXTURE = """
<ul class="dataBody_td" id="1001" createid="9">
  <li class="dataBody_check"></li>
  <li class="taskBody_name"><div class="py_name" id="name1001">张三</div></li>
  <li class="taskBody_con wid_bf_12">2026-10-01</li>
  <li class="taskBody_con wid_bf_12"><input class="inp80 scoreInput" type="text" value="95"></li>
  <li class="taskBody_con wid_bf_12"><p class="caozuo">
    <a href="javascript:;" data="/mooc2-ans/work/library/review-work?courseid=1&amp;clazzid=2&amp;workId=3">查看</a>
  </p></li>
</ul>
<ul class="dataBody_td" id="1002" createid="9">
  <li class="taskBody_name"><div class="py_name" id="name1002">李四</div></li>
  <li class="taskBody_con wid_bf_12"><input class="inp80 scoreInput" type="text" value=""></li>
</ul>
"""


def test_parse_review_list_rows():
    rows = preview.parse_review_list(FIXTURE)
    assert len(rows) == 2
    a, b = rows
    assert a["name"] == "张三" and a["score"] == "95" and a["graded"] is True
    assert a["status"] == "已批阅"
    assert a["review_path"].startswith("/mooc2-ans/work/library/review-work")
    assert "&" in a["review_path"] and "&amp;" not in a["review_path"]
    assert b["name"] == "李四" and b["score"] == "" and b["graded"] is False
    assert b["status"] == "待批阅"


def test_list_review_archives(tmp_path):
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages" / "v2-review-11-22.html").write_text(FIXTURE, encoding="utf-8")
    items = preview.list_review_archives(tmp_path)
    assert items == [{"classId": "11", "workId": "22",
                      "file": str(tmp_path / "pages" / "v2-review-11-22.html"),
                      "mtime": items[0]["mtime"]}]
    model = preview.preview_students(tmp_path, "11", "22")
    assert model["ok"] and model["count"] == 2 and model["scored"] == 1
    assert model["source"] == "archive"
    miss = preview.preview_students(tmp_path, "99", "99")
    assert miss["ok"] is False


def test_list_review_archives_scans_run_dirs_and_prefers_newest(tmp_path):
    pages = tmp_path / "pages"
    run_dir = pages / "runs" / "xxt-abc"
    run_dir.mkdir(parents=True)
    root_file = pages / "v2-review-11-22.html"
    run_file = run_dir / "v2-review-11-22.html"
    root_file.write_text(FIXTURE.replace("张三", "旧张三"), encoding="utf-8")
    run_file.write_text(FIXTURE.replace("张三", "新张三"), encoding="utf-8")
    os.utime(root_file, (1_700_000_000, 1_700_000_000))
    os.utime(run_file, (1_800_000_000, 1_800_000_000))
    items = preview.list_review_archives(tmp_path)
    assert len(items) == 1
    assert items[0]["file"] == str(run_file)
    model = preview.preview_students(tmp_path, "11", "22")
    assert model["ok"] and model["students"][0]["name"] == "新张三"


def test_preview_students_run_specific(tmp_path):
    pages = tmp_path / "pages" / "runs"
    (pages / "xxt-a").mkdir(parents=True)
    (pages / "xxt-b").mkdir(parents=True)
    (pages / "xxt-a" / "v2-review-11-22.html").write_text(
        FIXTURE.replace("张三", "A生"), encoding="utf-8")
    (pages / "xxt-b" / "v2-review-11-22.html").write_text(
        FIXTURE.replace("张三", "B生"), encoding="utf-8")
    model = preview.preview_students(tmp_path, "11", "22", run_id="xxt-a")
    assert model["ok"] and model["students"][0]["name"] == "A生"


def test_preview_students_manifest_fallback(tmp_path):
    d = tmp_path / "pages" / "review" / "11" / "22"
    d.mkdir(parents=True)
    (d / "students.json").write_text(json.dumps({
        "classId": "11", "workId": "22", "className": "1班", "workName": "作业一",
        "students": [
            {"studentId": "1001", "name": "张三", "score": "", "comment": ""},
            {"studentId": "1002", "name": "李四", "score": "95", "comment": "好"},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    model = preview.preview_students(tmp_path, "11", "22")
    assert model["ok"] and model["source"] == "manifest"
    assert model["count"] == 2 and model["scored"] == 1
    assert [s["name"] for s in model["students"]] == ["张三", "李四"]

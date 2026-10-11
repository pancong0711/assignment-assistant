"""D75-1 回归：review 列表 HTML 解析（合成 fixture，不依赖真实数据）。"""

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
    miss = preview.preview_students(tmp_path, "99", "99")
    assert miss["ok"] is False

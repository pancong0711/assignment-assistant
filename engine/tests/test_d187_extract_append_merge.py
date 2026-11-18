"""D187：追加提取 run 时保留未选中的旧作业元数据。"""
from __future__ import annotations

from assist.xxt.extract_run import merge_work_records


def test_merge_work_records_preserves_unselected_old_work():
    old = [
        {"workId": "w1", "name": "旧作业1", "pending": 3},
        {"workId": "w2", "name": "旧作业2", "pending": 4},
    ]
    new = [
        {"workId": "w2", "name": "旧作业2（刷新）", "pending": 1},
        {"workId": "w3", "name": "新作业3", "pending": 2},
    ]
    out = merge_work_records(old, new)
    by = {x["workId"]: x for x in out}
    assert set(by) == {"w1", "w2", "w3"}
    assert by["w1"]["name"] == "旧作业1"
    assert by["w2"]["name"] == "旧作业2（刷新）"
    assert by["w3"]["name"] == "新作业3"


def test_merge_work_records_empty_and_missing_ids():
    assert merge_work_records(None, None) == []
    out = merge_work_records([{"name": "无 id 旧项"}], [{"name": "无 id 新项"}])
    assert [x["name"] for x in out] == ["无 id 旧项", "无 id 新项"]

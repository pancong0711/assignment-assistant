"""D74-9 回归：全局操作记录 JSONL（纯逻辑，不触网）。"""

import json
import time
from pathlib import Path

from assist.xxt import journal


def test_log_event_writes_jsonl_and_filters(tmp_path):
    journal.log_event("xxt_extract", home=tmp_path, source="pwa",
                      params={"mode": "targets", "classes": 12},
                      result="ok", duration_ms=1234)
    journal.log_event("xxt_extract", home=tmp_path, source="pwa",
                      params={"mode": "all"}, result="fail", error="session dead")
    ev = journal.events(tmp_path)
    assert len(ev) == 2
    assert ev[0]["kind"] == "xxt_extract"
    assert any(e["result"] == "fail" and e["error"] == "session dead" for e in ev)
    assert journal.events(tmp_path, kind="nope") == []


def test_log_event_sanitizes_name_lists(tmp_path):
    journal.log_event("grade_upload", home=tmp_path,
                      params={"unsubmitted_names": ["甲", "乙", "丙"], "classId": "9"})
    ev = journal.events(tmp_path)[0]
    assert ev["params"]["unsubmitted_names"] == "<3 items>"
    assert ev["params"]["classId"] == "9"


def test_prune_removes_old_months(tmp_path):
    d = journal._dir(tmp_path)
    d.mkdir(parents=True, exist_ok=True)
    (d / "2020-01.jsonl").write_text(json.dumps({"ts": "2020-01-01 00:00:00"}) + "\n",
                                     encoding="utf-8")
    removed = journal.prune(tmp_path, months=6)
    assert any("2020-01.jsonl" in x for x in removed)
    assert not (d / "2020-01.jsonl").exists()
    journal.log_event("ping", home=tmp_path)
    assert len(journal.events(tmp_path)) == 1


def test_events_time_range(tmp_path):
    journal.log_event("a", home=tmp_path)
    time.sleep(1.1)
    journal.log_event("b", home=tmp_path)
    ev = journal.events(tmp_path, limit=500)
    assert ev[0]["kind"] == "b"
    # 用未来时间做下界，应为空
    assert journal.events(tmp_path, start="2999-01-01 00:00:00") == []


def test_clear_removes_all(tmp_path):
    journal.log_event("a", home=tmp_path)
    journal.log_event("b", home=tmp_path)
    removed = journal.clear(tmp_path)
    assert removed and journal.events(tmp_path) == []
    assert journal.stats(tmp_path)["files"] == 0

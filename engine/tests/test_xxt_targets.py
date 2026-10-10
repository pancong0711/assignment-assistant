"""D72 targets 回归：勾选清单安全校验（纯函数）。"""

from assist.xxt.targets import sanitize_targets


def test_sanitize_accepts_minimal_selection():
    sel = [{"courseId": "123", "name": "课程甲",
            "classes": [{"classId": "9", "name": "班一"}]}]
    out, err = sanitize_targets(sel)
    assert err is None
    assert out == [{"name": "课程甲", "courseId": "123",
                    "classes": [{"name": "班一", "classId": "9"}]}]


def test_sanitize_rejects_empty_or_non_list():
    assert sanitize_targets(None)[1]
    assert sanitize_targets([])[1]
    assert sanitize_targets([{"courseId": "1", "classes": []}])[1]


def test_sanitize_rejects_bad_ids():
    assert sanitize_targets([{"courseId": "../etc", "classes": [{"classId": "1"}]}])[1]
    assert sanitize_targets([{"courseId": "1", "classes": [{"classId": "x/y"}]}])[1]
    assert sanitize_targets([{"courseId": "1", "classes": ["nope"]}])[1]


def test_sanitize_fills_name_and_truncates():
    out, err = sanitize_targets([{"courseId": "1", "classes": [{"classId": "2", "name": "n" * 200}]}])
    assert err is None
    assert out[0]["name"] == "1"
    assert out[0]["classes"][0]["name"] == "n" * 80


def test_sanitize_skips_course_without_classes():
    out, err = sanitize_targets([
        {"courseId": "1", "classes": []},
        {"courseId": "2", "classes": [{"classId": "3"}]},
    ])
    assert err is None and [c["courseId"] for c in out] == ["2"]


# ============ D74-3：快照归档 / diff / 清理 ============

import json as _json
import os as _os
import time as _time

from assist.xxt import targets as _t


def _snap(ts, courses):
    return {"ok": True, "discovered_at": ts, "courses": courses}


def test_compute_diff_detects_add_remove_rename():
    prev = _snap("2026-10-08 12:00:00", [
        {"name": "课程A", "courseId": "1", "classes": [
            {"name": "一班", "classId": "11"}, {"name": "二班", "classId": "12"}]},
    ])
    cur = _snap("2026-10-10 12:00:00", [
        {"name": "课程A改", "courseId": "1", "classes": [
            {"name": "一班", "classId": "11"}, {"name": "三班", "classId": "13"}]},
        {"name": "课程B", "courseId": "2", "classes": [{"name": "四班", "classId": "21"}]},
    ])
    d = _t.compute_diff(prev, cur)
    assert d["counts"] == {"courses_added": 1, "courses_removed": 0,
                           "classes_added": 2, "classes_removed": 1, "renamed": 1}
    assert {c["courseId"] for c in d["courses_added"]} == {"2"}
    assert {c["classId"] for c in d["classes_added"]} == {"13", "21"}
    assert {c["classId"] for c in d["classes_removed"]} == {"12"}
    assert d["renamed"][0]["old"] == "课程A" and d["renamed"][0]["new"] == "课程A改"


def test_compute_diff_none_without_prev():
    assert _t.compute_diff(None, _snap("t", [])) is None
    assert _t.compute_diff(_snap("t", []), None) is None


def test_archive_and_prune_keeps_last_five(tmp_path):
    path = _t._targets_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    for i in range(7):
        path.write_text(_json.dumps(_snap(f"2026-10-0{i+1} 10:00:00",
                                          [{"name": f"课{i}", "courseId": str(i), "classes": []}])),
                        encoding="utf-8")
        _time.sleep(0.01)
        _t.archive_current(tmp_path, keep=5)
    files = _t.history_files(tmp_path)
    assert len(files) == 5
    # 最新一份是最后一次归档（课6），最旧应是课2
    latest = _json.loads(files[-1].read_text(encoding="utf-8"))
    oldest = _json.loads(files[0].read_text(encoding="utf-8"))
    assert latest["courses"][0]["name"] == "课6"
    assert oldest["courses"][0]["name"] == "课2"


def test_age_seconds_and_targets_view(tmp_path):
    path = _t._targets_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps(_snap(_time.strftime("%Y-%m-%d %H:%M:%S"),
                                      [{"name": "A", "courseId": "1", "classes": []}])),
                    encoding="utf-8")
    view = _t.targets_view(tmp_path)
    assert view["ok"] and view["history_count"] == 0 and view["diff"] is None
    assert view["age_seconds"] is not None and view["age_seconds"] < 60
    assert _t.age_seconds({"discovered_at": "not-a-date"}) is None


def test_clear_history_keeps_current(tmp_path):
    path = _t._targets_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps(_snap("2026-10-10 10:00:00", [])), encoding="utf-8")
    _t.archive_current(tmp_path, keep=5)
    assert len(_t.history_files(tmp_path)) == 1
    removed = _t.clear_history(tmp_path)
    assert len(removed) == 1 and _t.history_files(tmp_path) == []
    assert path.is_file()


def test_sanitize_keeps_valid_works_ids():
    out, err = sanitize_targets([{
        "courseId": "1",
        "classes": [{"classId": "2", "works": ["a1", "b2", "bad id", {"workId": "c3"}]}],
    }])
    assert err is None
    assert out[0]["classes"][0]["works"] == ["a1", "b2", "c3"]

    out2, err2 = sanitize_targets([{"courseId": "1", "classes": [{"classId": "2"}]}])
    assert err2 is None and "works" not in out2[0]["classes"][0]

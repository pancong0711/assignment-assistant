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

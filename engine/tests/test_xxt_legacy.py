"""D73-9 回归：旧 run / targets JSON 规范化导入（纯函数，不触网）。"""

import json

from assist.xxt import legacy


OLD_RUN = {
    "run_id": "xxt-20261008-122317-full",
    "mode": "readonly",
    "ts_start": "2026-10-08 12:23:17",
    "ts_end": "2026-10-08 12:41:00",
    "unknown_top": "drop-me",
    "courses": [{
        "name": "示例课程",
        "courseId": "c1",
        "cpi": "9",
        "classes": [{
            "name": "示例班",
            "classId": "k1",
            "status": "extracted",
            "cpi": "9",
            "roster": {"total": 3},
            "works": [{
                "name": "作业一",
                "workId": "w1",
                "pending": 1, "submitted": 2, "unsubmitted": 1,
                "submitted_names": [{"name": "甲"}],
                "unsubmitted_names": ["乙"],
                "anchor": {"ok": True, "roster_delta": 0},
                "unknown_work": "drop",
            }],
            "unknown_class": "drop",
        }],
    }],
    "failures": [],
}


def test_normalize_run_id_prefers_valid_field():
    assert legacy.normalize_run_id(OLD_RUN) == "xxt-20261008-122317-full"


def test_normalize_run_id_falls_back_to_filename():
    assert legacy.normalize_run_id({}, "xxt-20261008-184915.json") == "xxt-20261008-184915"


def test_normalize_run_id_generates_when_missing():
    rid = legacy.normalize_run_id({"run_id": "bad id!!"})
    assert rid.startswith("xxt-") and " " not in rid
    assert legacy._RUN_ID_RE.match(rid)


def test_normalize_legacy_run_keeps_known_drops_unknown():
    run = legacy.normalize_legacy_run(OLD_RUN)
    assert run["imported"] is True
    assert "unknown_top" not in run
    c = run["courses"][0]
    assert c["courseId"] == "c1" and "unknown_class" not in c
    cl = c["classes"][0]
    assert cl["classId"] == "k1"
    w = cl["works"][0]
    assert w["submitted"] == 2 and w["unsubmitted_names"] == ["乙"]
    assert "unknown_work" not in w
    assert cl["notices"] == [] and cl["notes"] == []


def test_normalize_legacy_run_accepts_targets_schema():
    targets = {"courses": [{"name": "课程", "courseId": "c9",
                            "classes": [{"name": "班", "classId": "k9"}]}]}
    run = legacy.normalize_legacy_run(targets, fallback_id="targets.json")
    assert run["run_id"].startswith("xxt-")
    assert run["courses"][0]["classes"][0]["works"] == []
    assert run["imported"] is True


def test_normalize_legacy_run_rejects_non_run():
    for bad in ([], {}, {"courses": "no"}):
        try:
            legacy.normalize_legacy_run(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"should reject {bad!r}")


def test_import_run_data_writes_and_suffixes(tmp_path):
    r1 = legacy.import_run_data(OLD_RUN, home=tmp_path)
    assert r1["imported"] and r1["classes"] == 1 and r1["works"] == 1
    p1 = tmp_path / "runs" / "xxt-20261008-122317-full.json"
    assert p1.is_file()
    r2 = legacy.import_run_data(OLD_RUN, home=tmp_path)
    assert r2["run_id"] == "xxt-20261008-122317-full-2"
    assert (tmp_path / "runs" / "xxt-20261008-122317-full-2.json").is_file()
    assert json.loads(p1.read_text(encoding="utf-8"))["run_id"] == "xxt-20261008-122317-full"


def test_import_run_file_and_scan(tmp_path):
    src = tmp_path / "xxt-20261008-184915.json"
    src.write_text(json.dumps(OLD_RUN, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "xxt-login-state.json").write_text("{}", encoding="utf-8")
    home = tmp_path / "home"
    files = legacy.scan_legacy_run_files(tmp_path)
    assert src in files and (tmp_path / "xxt-login-state.json") not in files
    r = legacy.import_run_file(src, home=home)
    assert r["out"].endswith("xxt-20261008-122317-full.json")
    assert (home / "runs" / "xxt-20261008-122317-full.json").is_file()

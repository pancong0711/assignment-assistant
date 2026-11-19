"""D210：上传前对照的平台状态做本地缓存，仅在“重新读取平台状态”时刷新。

现场：读平台状态要打开批阅列表并逐生打开批阅页，很慢（几十人 × 数秒）。
期望：打开对照优先用缓存秒开；本地批语/分数变化时用缓存平台快照重新判定并标记 stale；
点「重新读取平台状态」强制刷新；上传后缓存自动失效。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from assist.xxt import upload_preview as UP


def _payload(student="学生甲", score=88, comment="批语", version="v1"):
    return {"student": student, "key": student, "score": score,
            "comment": comment, "images": [],
            "report": {"version": version} if version else {}}


def test_cache_path_layout(tmp_path: Path):
    p = UP.cache_path(tmp_path, "classes/c", "packA", "w1")
    assert p is not None
    assert p.parent == (tmp_path / "classes/c/grading/packA/upload").resolve()
    assert p.name == "preview-w1.json"


def test_cache_path_requires_scope(tmp_path: Path):
    assert UP.cache_path(tmp_path, "", "packA", "w1") is None
    assert UP.cache_path(tmp_path, "classes/c", "", "w1") is None
    assert UP.cache_path(tmp_path, "classes/c", "packA", "") is None


def test_fingerprint_changes_with_local_edits():
    a = UP.payload_fingerprint([_payload(score=88)])
    assert a == UP.payload_fingerprint([_payload(score=88)])
    assert a != UP.payload_fingerprint([_payload(score=90)])
    assert a != UP.payload_fingerprint([_payload(comment="改了批语")])
    assert a != UP.payload_fingerprint([_payload(version="v2")])


def _write_cache(tmp_path, payloads, *, platform_rows, per_student=None, age_sec=0):
    cp = UP.cache_path(tmp_path, "classes/c", "packA", "w1")
    UP.write_cache(cp, course_id="c1", class_id="k1", work_id="w1",
                   task_id="packA", class_dir="classes/c",
                   platform_rows=platform_rows, per_student=per_student or {},
                   fingerprint=UP.payload_fingerprint(payloads))
    data = json.loads(cp.read_text(encoding="utf-8"))
    data["fetchedAt"] = __import__("time").time() - age_sec
    cp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return cp


def test_cache_hit_avoids_opening_browser(tmp_path, monkeypatch):
    payloads = [_payload()]
    _write_cache(tmp_path, payloads,
                 platform_rows=[{"name": "学生甲", "status": "待批阅",
                                 "score": "", "workAnswerId": "wa1"}])

    def boom(*a, **k):
        raise AssertionError("命中缓存时不应启动浏览器")

    import assist.xxt.grade_upload as GU
    monkeypatch.setattr(GU, "_start_browser", boom)
    rep = UP.build_preview(storage="x", course_id="c1", class_id="k1", cpi="0",
                           work_id="w1", payloads=payloads,
                           ws=tmp_path, class_dir="classes/c", task_id="packA")
    assert rep["ok"] is True
    assert rep["cache"]["hit"] is True
    assert rep["cache"]["stale"] is False
    assert rep["rows"][0]["platformStatus"] == "待批阅"


def test_cache_stale_when_local_content_changed(tmp_path, monkeypatch):
    """本地改了分数 → 仍用缓存的平台快照重新判定，并标 stale 提示刷新。"""
    _write_cache(tmp_path, [_payload(score=88)],
                 platform_rows=[{"name": "学生甲", "status": "待批阅",
                                 "score": "", "workAnswerId": "wa1"}])
    import assist.xxt.grade_upload as GU
    monkeypatch.setattr(GU, "_start_browser",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应开浏览器")))
    rep = UP.build_preview(storage="x", course_id="c1", class_id="k1", cpi="0",
                           work_id="w1", payloads=[_payload(score=95)],
                           ws=tmp_path, class_dir="classes/c", task_id="packA")
    assert rep["cache"]["hit"] is True
    assert rep["cache"]["stale"] is True
    assert "重新读取平台状态" in rep["cache"]["hint"]


def test_expired_cache_triggers_live_read(tmp_path, monkeypatch):
    _write_cache(tmp_path, [_payload()],
                 platform_rows=[{"name": "学生甲", "status": "待批阅",
                                 "score": "", "workAnswerId": "wa1"}], age_sec=99999)
    import assist.xxt.grade_upload as GU
    called = {"n": 0}

    def fake_start(storage):
        called["n"] += 1
        return None, None, None, {"ok": False, "error": "no browser"}

    monkeypatch.setattr(GU, "_start_browser", fake_start)
    rep = UP.build_preview(storage="x", course_id="c1", class_id="k1", cpi="0",
                           work_id="w1", payloads=[_payload()],
                           ws=tmp_path, class_dir="classes/c", task_id="packA")
    assert called["n"] == 1, "过期缓存应触发实时读取"
    assert rep["ok"] is False


def test_force_refresh_bypasses_cache(tmp_path, monkeypatch):
    _write_cache(tmp_path, [_payload()],
                 platform_rows=[{"name": "学生甲", "status": "待批阅",
                                 "score": "", "workAnswerId": "wa1"}])
    import assist.xxt.grade_upload as GU
    called = {"n": 0}

    def fake_start(storage):
        called["n"] += 1
        return None, None, None, {"ok": False, "error": "no browser"}

    monkeypatch.setattr(GU, "_start_browser", fake_start)
    UP.build_preview(storage="x", course_id="c1", class_id="k1", cpi="0",
                     work_id="w1", payloads=[_payload()], force_refresh=True,
                     ws=tmp_path, class_dir="classes/c", task_id="packA")
    assert called["n"] == 1


def test_invalidate_cache(tmp_path):
    cp = _write_cache(tmp_path, [_payload()], platform_rows=[])
    assert cp.is_file()
    assert UP.invalidate_cache(tmp_path, "classes/c", "packA", "w1") is True
    assert not cp.is_file()
    assert UP.invalidate_cache(tmp_path, "classes/c", "packA", "w1") is False


def test_corrupt_cache_is_ignored(tmp_path, monkeypatch):
    cp = UP.cache_path(tmp_path, "classes/c", "packA", "w1")
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text("{坏 json", encoding="utf-8")
    assert UP.read_cache(cp) is None


def test_compose_marks_readiness(tmp_path):
    rep = UP.compose_preview(
        payloads=[_payload()],
        platform_rows=[{"name": "学生甲", "status": "待批阅", "score": "",
                        "workAnswerId": "wa1"}])
    assert rep["rows"][0]["readyState"] == "ready"
    assert rep["rows"][0]["submitted"] is True


def test_source_contract_for_d210():
    root = Path(__file__).resolve().parents[1]
    up = (root / "src/assist/xxt/upload_preview.py").read_text(encoding="utf-8")
    serve = (root / "src/assist/serve.py").read_text(encoding="utf-8")
    view = (root.parent / "app/src/components/AiGradingPanel.vue").read_text(encoding="utf-8")
    client = (root.parent / "app/src/lib/engineClient.ts").read_text(encoding="utf-8")
    assert "def cache_path(" in up and "def invalidate_cache(" in up
    assert "DEFAULT_TTL_SEC" in up
    assert "force_refresh" in up
    assert 'payload.get("force")' in serve
    assert "invalidate_cache(ws" in serve
    assert "openUploadPreview(true, { force: true })" in view
    assert "previewCache" in view
    assert "force?: boolean" in client


# ---------------- D210-FIX：状态判定与 decide 同口径 ----------------

def test_decide_recognizes_completed_status_as_reviewed():
    """真实平台返回“已完成/Completed”时，必须走覆盖确认，不能当成未批阅直接覆盖。"""
    from assist.xxt import grade_plan as GP
    for st in ("已批阅", "已完成", "Completed", "Completed（教师提交）", "Reviewed"):
        d = GP.decide(status=st, local_score=88, local_comment="x",
                      platform={"score": 70, "comment": "旧批语"})
        assert d["decision"] == GP.CONFLICT, st
        assert d["needsConfirm"] is True, st


def test_decide_treats_pending_statuses_as_new():
    from assist.xxt import grade_plan as GP
    for st in ("待批阅", "To be reviewed", "Unreview", ""):
        d = GP.decide(status=st, local_score=88, local_comment="x")
        assert d["decision"] == GP.NEW, st

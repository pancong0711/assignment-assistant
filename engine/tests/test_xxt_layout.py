"""D72/D74：run/pages/shots 路径契约 + run 形状校验（D74-6）。"""

import json

from assist.xxt import layout


def _run(rid="xxt-r1"):
    return json.dumps({"run_id": rid, "courses": []}, ensure_ascii=False)


def test_run_json_files_prefers_runs_and_compat_root(tmp_path):
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "xxt-new.json").write_text(_run("xxt-new"), encoding="utf-8")
    (tmp_path / "xxt-old.json").write_text(_run("xxt-old"), encoding="utf-8")
    (tmp_path / "xxt-login-state.json").write_text("{}", encoding="utf-8")
    names = [p.name for p in layout.run_json_files(tmp_path)]
    assert "xxt-new.json" in names
    assert "xxt-old.json" in names
    assert "xxt-login-state.json" not in names


def test_find_run_json_prefers_runs(tmp_path):
    (tmp_path / "runs").mkdir()
    p1 = tmp_path / "runs" / "xxt-1.json"
    p2 = tmp_path / "xxt-1.json"
    p1.write_text(_run("xxt-1"), encoding="utf-8")
    p2.write_text(_run("xxt-1"), encoding="utf-8")
    assert layout.find_run_json("xxt-1", tmp_path) == p1


def test_shot_candidates_new_then_legacy(tmp_path):
    new = layout.shots_dir(tmp_path)
    legacy = tmp_path / "xxt-pages" / "shots"
    new.mkdir(parents=True); legacy.mkdir(parents=True)
    p_new = new / "xxt-r-step01.png"
    p_legacy = legacy / "xxt-r-step02.png"
    p_new.write_bytes(b"png"); p_legacy.write_bytes(b"png")
    assert p_new in layout.shot_candidates("xxt-r", "xxt-r-step01.png", tmp_path)
    assert p_legacy in layout.shot_candidates("xxt-r", "xxt-r-step02.png", tmp_path)


def test_delete_run_artifacts(tmp_path):
    runs = layout.runs_dir(tmp_path); runs.mkdir(parents=True)
    shots = layout.shots_dir(tmp_path); shots.mkdir(parents=True)
    run = runs / "xxt-r1.json"; shot = shots / "xxt-r1-step01.png"
    run.write_text(_run("xxt-r1"), encoding="utf-8"); shot.write_bytes(b"png")
    removed = layout.delete_run_artifacts("xxt-r1", tmp_path)
    assert not run.exists()
    assert not shot.exists()
    assert len(removed) == 2


def test_run_pages_dir_and_delete(tmp_path):
    runs = layout.runs_dir(tmp_path); runs.mkdir(parents=True)
    rp = layout.run_pages_dir("xxt-r2", tmp_path); rp.mkdir(parents=True)
    (rp / "v2-list-1.html").write_text("x", encoding="utf-8")
    (runs / "xxt-r2.json").write_text(_run("xxt-r2"), encoding="utf-8")
    assert layout.run_pages_dir("xxt-r2", tmp_path) == tmp_path / "pages" / "runs" / "xxt-r2"
    removed = layout.delete_run_artifacts("xxt-r2", tmp_path)
    assert not rp.exists() and not (runs / "xxt-r2.json").exists()
    assert any("v2-list-1.html" in x for x in removed)


def test_clear_runs_keeps_session_files(tmp_path):
    runs = layout.runs_dir(tmp_path); runs.mkdir(parents=True)
    (runs / "xxt-r3.json").write_text(_run("xxt-r3"), encoding="utf-8")
    (tmp_path / "xxt-storage.json").write_text("{}", encoding="utf-8")
    (tmp_path / "xxt-login-state.json").write_text("{}", encoding="utf-8")
    res = layout.clear_runs(tmp_path)
    assert res["runs"] == ["xxt-r3"]
    assert not (runs / "xxt-r3.json").exists()
    assert (tmp_path / "xxt-storage.json").exists()
    assert (tmp_path / "xxt-login-state.json").exists()


def test_targets_json_path(tmp_path):
    assert layout.targets_json(tmp_path) == tmp_path / "targets.json"
    assert layout.targets_spec_json(tmp_path) == tmp_path / "targets" / "extract-spec.json"


def test_is_run_shape():
    assert layout.is_run_shape({"run_id": "xxt-1", "courses": []})
    assert not layout.is_run_shape({})
    assert not layout.is_run_shape([])
    assert not layout.is_run_shape({"run_id": "xxt-1"})            # 缺 courses
    assert not layout.is_run_shape({"run_id": "spec", "courses": []})  # run_id 非 xxt-


def test_run_json_files_excludes_targets_spec_and_bad_json(tmp_path):
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "xxt-good.json").write_text(_run("xxt-good"), encoding="utf-8")
    # 旧 spec：有 courses 但没有 run_id，且文件不在 runs/
    (tmp_path / "xxt-extract-targets.json").write_text(
        json.dumps({"courses": [{"courseId": "1", "classes": []}]}), encoding="utf-8")
    (tmp_path / "xxt-broken.json").write_text("{not json", encoding="utf-8")
    names = [p.name for p in layout.run_json_files(tmp_path)]
    assert names == ["xxt-good.json"]
    assert layout.find_run_json("xxt-extract-targets", tmp_path) is None
    assert layout.find_run_json("xxt-broken", tmp_path) is None

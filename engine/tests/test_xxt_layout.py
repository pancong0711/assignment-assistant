"""D72 回归：run/pages/shots 路径契约统一。"""

from assist.xxt import layout


def test_run_json_files_prefers_runs_and_compat_root(tmp_path):
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "xxt-new.json").write_text("{}", encoding="utf-8")
    (tmp_path / "xxt-old.json").write_text("{}", encoding="utf-8")
    (tmp_path / "xxt-login-state.json").write_text("{}", encoding="utf-8")
    names = [p.name for p in layout.run_json_files(tmp_path)]
    assert "xxt-new.json" in names
    assert "xxt-old.json" in names
    assert "xxt-login-state.json" not in names


def test_find_run_json_prefers_runs(tmp_path):
    (tmp_path / "runs").mkdir()
    p1 = tmp_path / "runs" / "xxt-1.json"
    p2 = tmp_path / "xxt-1.json"
    p1.write_text("{}", encoding="utf-8")
    p2.write_text("{}", encoding="utf-8")
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

"""D188：学习通登录页跳转的只读判定 + /xxt/status 最小字段（合成数据）。"""

import json
import os
import time

import assist.serve as serve
from assist.xxt.session import is_login_redirect_url, steps_have_login_redirect


def test_login_redirect_url_detects_passport_and_login():
    assert is_login_redirect_url("https://passport2.chaoxing.com/login?fid=&refer=x")
    assert is_login_redirect_url("https://i.chaoxing.com/login")
    assert is_login_redirect_url("https://login.chaoxing.com/portal")
    assert not is_login_redirect_url("https://i.chaoxing.com/base")
    assert not is_login_redirect_url("https://mooc1.chaoxing.com/work/list")


def test_login_redirect_url_defensive():
    assert not is_login_redirect_url("")
    assert not is_login_redirect_url(None)
    assert not is_login_redirect_url("not a url")


def test_steps_have_login_redirect_only_uses_url():
    assert steps_have_login_redirect([
        {"action": "goto", "url": "https://passport2.chaoxing.com/login?token=secret"},
    ])
    assert not steps_have_login_redirect([
        {"action": "goto", "title": "用户登录", "url": "https://mooc1.chaoxing.com/work"},
    ])
    assert not steps_have_login_redirect(None)
    assert not steps_have_login_redirect(["oops", None, {"url": ""}])


def _write_run(home, steps, run_id="xxt-20261118-101010-abcdef"):
    runs = home / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    path = runs / f"{run_id}.json"
    path.write_text(json.dumps({
        "run_id": run_id,
        "courses": [],
        "failures": [{"scope": "run", "kind": "not_extracted",
                      "detail": "合成失败"}],
        "steps": steps,
    }, ensure_ascii=False), encoding="utf-8")
    return path


def _write_targets(home, steps):
    path = home / "targets.json"
    path.write_text(json.dumps({
        "ok": True,
        "discovered_at": "2026-11-18 10:10:10",
        "courses": [],
        "steps": steps,
    }, ensure_ascii=False), encoding="utf-8")
    return path


def test_status_login_redirect_from_latest_run(tmp_path, monkeypatch):
    monkeypatch.setattr(serve, "_xxt_home", lambda: tmp_path)
    monkeypatch.setattr(serve, "_xxt_session_check_cached",
                        lambda: {"verdict": "alive"})
    run = _write_run(tmp_path, [
        {"action": "goto", "title": "用户登录",
         "url": "https://passport2.chaoxing.com/login?fid=&token=synthetic"},
    ])
    out = serve._xxt_login_redirect({"verdict": "alive"})
    assert out["loginRedirect"] is True
    assert out["loginRedirectTs"] == int(run.stat().st_mtime)
    # 只返回最小字段，不回显 URL/cookie/token
    assert set(out) == {"loginRedirect", "loginRedirectTs"}
    assert "synthetic" not in json.dumps(out)


def test_status_login_redirect_false_for_normal_run(tmp_path, monkeypatch):
    monkeypatch.setattr(serve, "_xxt_home", lambda: tmp_path)
    _write_run(tmp_path, [{"action": "goto", "url": "https://i.chaoxing.com/base"}])
    assert serve._xxt_login_redirect({"verdict": "alive"}) == {
        "loginRedirect": False, "loginRedirectTs": 0}


def test_status_login_redirect_uses_newest_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(serve, "_xxt_home", lambda: tmp_path)
    run = _write_run(tmp_path, [
        {"action": "goto", "url": "https://passport2.chaoxing.com/login"},
    ])
    targets = _write_targets(tmp_path, [
        {"action": "goto", "url": "https://i.chaoxing.com/base"},
    ])
    now = time.time()
    os.utime(run, (now - 10, now - 10))
    os.utime(targets, (now, now))
    # 最新的发现已正常 → 不因旧 run 的登录跳转长期报红
    assert serve._xxt_login_redirect({"verdict": "alive"})["loginRedirect"] is False

    login_targets = _write_targets(tmp_path, [
        {"action": "goto", "title": "用户登录",
         "url": "https://passport2.chaoxing.com/login?x=1"},
    ])
    os.utime(login_targets, (now + 10, now + 10))
    out = serve._xxt_login_redirect({"verdict": "alive"})
    assert out["loginRedirect"] is True
    assert out["loginRedirectTs"] == int(login_targets.stat().st_mtime)


def test_status_login_redirect_from_check_final_url(tmp_path, monkeypatch):
    monkeypatch.setattr(serve, "_xxt_home", lambda: tmp_path)
    out = serve._xxt_login_redirect({
        "verdict": "dead",
        "final_url": "https://passport2.chaoxing.com/login?fid=&token=synthetic",
    })
    assert out["loginRedirect"] is True
    assert out["loginRedirectTs"] > 0
    assert "synthetic" not in json.dumps(out)


def test_status_login_redirect_ignores_successful_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(serve, "_xxt_home", lambda: tmp_path)
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "xxt-20261118-101010-abcdef.json").write_text(json.dumps({
        "run_id": "xxt-20261118-101010-abcdef",
        "courses": [{"courseId": "c1", "classes": [{"classId": "k1"}]}],
        "failures": [],
        "steps": [{"action": "goto", "url": "https://passport2.chaoxing.com/login"},
                  {"action": "goto", "url": "https://mooc1.chaoxing.com/work"}],
    }, ensure_ascii=False), encoding="utf-8")
    assert serve._xxt_login_redirect({"verdict": "alive"}) == {
        "loginRedirect": False, "loginRedirectTs": 0}


def test_status_login_redirect_never_raises_on_bad_files(tmp_path, monkeypatch):
    monkeypatch.setattr(serve, "_xxt_home", lambda: tmp_path)
    (tmp_path / "targets.json").write_text("{bad json", encoding="utf-8")
    assert serve._xxt_login_redirect({"verdict": "alive"}) == {
        "loginRedirect": False, "loginRedirectTs": 0}

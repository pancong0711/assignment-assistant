"""D189：扫码登录成功判定必须基于「本次扫码带来的新会话 cookie」。

现场：教师以前登录过，浏览器残留 _uid；旧实现只看 _uid 存在就判登录成功，
新二维码还没扫就提前退出 → 表现为「扫了没反应/不跳转」。
"""
from __future__ import annotations

import json
from pathlib import Path

import assist.serve as serve
from assist.xxt.session import (cookie_fingerprint, session_cookie_changed,
                                _SESSION_COOKIE_NAMES)


def _ck(**kw):
    return [{"name": k, "value": v} for k, v in kw.items()]


def test_cookie_fingerprint_masks_values():
    fp = cookie_fingerprint(_ck(_uid="secret-value", fid="12345"))
    assert set(fp) == {"_uid", "fid"}
    for v in fp.values():
        assert len(v) == 8 and "secret" not in v


def test_cookie_fingerprint_defensive():
    assert cookie_fingerprint(None) == {}
    assert cookie_fingerprint(["oops", None, {"value": "x"}]) == {}


def test_session_cookie_changed_detects_stale_baseline():
    """旧 _uid 仍在 → 与 baseline 相同 → 不算本次扫码成功。"""
    base = cookie_fingerprint(_ck(_uid="old", fid="1"))
    same = cookie_fingerprint(_ck(_uid="old", fid="1"))
    assert session_cookie_changed(base, same) is False


def test_session_cookie_changed_detects_new_cookie():
    base = cookie_fingerprint(_ck(_uid="old"))
    new = cookie_fingerprint(_ck(_uid="new-value"))
    assert session_cookie_changed(base, new) is True


def test_session_cookie_changed_first_scan_baseline_empty():
    assert session_cookie_changed({}, cookie_fingerprint(_ck(_uid="x"))) is True
    assert session_cookie_changed({}, {}) is False


def test_session_cookie_names_cover_uid():
    assert "_uid" in _SESSION_COOKIE_NAMES and "uid" in _SESSION_COOKIE_NAMES


def test_login_state_readable_and_masked(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(serve, "_xxt_home", lambda: tmp_path)
    (tmp_path / "xxt-login-state.json").write_text(json.dumps({
        "stage": "failed",
        "error": "Timeout 30000ms exceeded (token=abc123)",
        "url": "https://passport2.chaoxing.com/login?token=abc123",
        "cookies": ["_uid", "fid"],
    }), encoding="utf-8")
    (tmp_path / "xxt-qr.png").write_bytes(b"png")
    st = serve._xxt_login_state(tmp_path)
    assert st["stage"] == "failed"
    assert "Timeout" in st["error"]
    assert st["urlHost"] == "passport2.chaoxing.com"
    assert st["qrExists"] is True
    assert set(st["cookies"]) == {"_uid", "fid"}
    # 不返回完整 URL（其 query 可能带票据）
    assert "token=abc123" not in json.dumps(st, ensure_ascii=False)


def test_login_state_missing_is_safe(tmp_path: Path):
    st = serve._xxt_login_state(tmp_path)
    assert st["stage"] == "" and st["qrExists"] is False


def test_login_job_running_detects_single_instance():
    with serve._JOBS_LOCK:
        serve._JOBS["job-test-1"] = {"item": "xxt_login", "status": "running"}
    try:
        assert serve._xxt_login_job_running() == "job-test-1"
    finally:
        with serve._JOBS_LOCK:
            serve._JOBS.pop("job-test-1", None)
    assert serve._xxt_login_job_running() is None


def test_start_scripts_contract_for_d189():
    """源码契约：登录 start 必须做单实例检查、清旧状态，并暴露只读 state 端点。"""
    root = Path(__file__).resolve().parents[2]
    src = (root / "engine/src/assist/serve.py").read_text(encoding="utf-8")
    ses = (root / "engine/src/assist/xxt/session.py").read_text(encoding="utf-8")
    assert "_xxt_login_job_running()" in src
    assert "/xxt/login/state" in src
    assert '"stage": "busy"' in src
    assert "xxt-login-state.json" in src
    assert "def _is_logged_in(page, baseline" in ses
    assert "session_cookie_changed(baseline, current)" in ses


class _Ctx:
    def __init__(self, cookies):
        self._cookies = cookies

    def cookies(self):
        return self._cookies


class _Page:
    def __init__(self, url, cookies):
        self.url = url
        self.context = _Ctx(cookies)


def test_is_logged_in_rejects_stale_uid_on_teaching_host():
    """D189 核心回归：旧 _uid 未变时，教学域页面不得判为本次扫码成功。"""
    from assist.xxt.session import _is_logged_in
    old = cookie_fingerprint(_ck(_uid="stale"))
    # 注意：fid 也属于会话 cookie，基线里必须有，否则“新增 fid”会被判成变化。
    page = _Page("https://i.chaoxing.com/base", _ck(_uid="stale", fid="1"))
    old2 = cookie_fingerprint(_ck(_uid="stale", fid="1"))
    assert _is_logged_in(page, old2) is False


def test_is_logged_in_accepts_new_uid_on_teaching_host():
    from assist.xxt.session import _is_logged_in
    old = cookie_fingerprint(_ck(_uid="stale"))
    page = _Page("https://i.chaoxing.com/base", _ck(_uid="fresh", fid="1"))
    assert _is_logged_in(page, old) is True


def test_is_logged_in_accepts_new_uid_still_on_login_url():
    from assist.xxt.session import _is_logged_in
    old = cookie_fingerprint(_ck(_uid="stale"))
    page = _Page("https://passport2.chaoxing.com/login?fid=0", _ck(_uid="fresh"))
    assert _is_logged_in(page, old) is True

"""D63 T1 回归：xxt 会话体检纯逻辑 + CLI 组接线（不触网、不依赖 playwright）。"""

from click.testing import CliRunner

from assist.cli import cli
from assist.xxt.session import (
    _is_logged_in, _page_alive, default_qr_path, evaluate_verdict, resolve_storage_path, xxt_home,
)


def test_verdict_alive_normal():
    v, reasons = evaluate_verdict("https://i.chaoxing.com/base", login_pwd_input=False)
    assert v == "alive" and reasons == []


def test_verdict_dead_redirect():
    v, reasons = evaluate_verdict(
        "https://passport2.chaoxing.com/login?refer=xxx", login_pwd_input=False)
    assert v == "dead" and any("redirected" in r for r in reasons)


def test_verdict_dead_password():
    v, reasons = evaluate_verdict("https://i.chaoxing.com/base", login_pwd_input=True)
    assert v == "dead" and any("password" in r for r in reasons)


def test_xxt_group_registered():
    """T1 验收：`assist --help` 可见 xxt 组，`xxt check/login --help` 可用（click 接线）。"""
    r = CliRunner().invoke(cli, ["xxt", "--help"])
    assert r.exit_code == 0, r.output
    assert "check" in r.output and "login" in r.output
    r2 = CliRunner().invoke(cli, ["xxt", "check", "--help"])
    assert r2.exit_code == 0, r2.output
    assert "--storage" in r2.output

def test_resolve_storage_explicit_wins(tmp_path):
    p = tmp_path / "custom" / "xxt-storage.json"
    assert resolve_storage_path(p) == p


def test_resolve_storage_env(tmp_path, monkeypatch):
    p = tmp_path / "xxt-storage.json"
    monkeypatch.setenv("XXT_STORAGE", str(p))
    assert resolve_storage_path() == p


def test_default_qr_path_same_dir(tmp_path):
    storage = tmp_path / "runtime" / "xxt-storage.json"
    assert default_qr_path(storage) == tmp_path / "runtime" / "xxt-qr.png"


def test_xxt_home_env_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("XXT_HOME", str(tmp_path))
    assert xxt_home() == tmp_path


def test_cli_default_storage_follows_xxt_home(tmp_path, monkeypatch):
    """D66：CLI 与 serve 必须使用同一 xxt_home/storage 口径。"""
    from assist.xxt.cli import default_storage
    monkeypatch.delenv("XXT_STORAGE", raising=False)
    monkeypatch.setenv("XXT_HOME", str(tmp_path))
    assert default_storage(None) == tmp_path / "xxt-storage.json"


def test_serve_xxt_home_matches_session(tmp_path, monkeypatch):
    """D66：/xxt/qr 的读取根必须与 session 写出口径一致。"""
    from assist.serve import _xxt_home
    monkeypatch.setenv("XXT_HOME", str(tmp_path))
    assert _xxt_home() == xxt_home() == tmp_path

class _FakeContext:
    def __init__(self, cookies):
        self._cookies = cookies

    def cookies(self):
        return self._cookies


class _FakePage:
    def __init__(self, url, cookies):
        self.url = url
        self.context = _FakeContext(cookies)


def test_is_logged_in_chaoxing_host_even_without_cookie():
    """D68：扫码后跳到教学域即判真，避免 cookie 可见时序差异导致不动作。"""
    assert _is_logged_in(_FakePage("https://i.chaoxing.com/base", [])) is True


def test_is_logged_in_login_page_with_uid_is_true():
    """D70：cookie 先判——URL 还在 passport 但 _uid 已出现时也要识别登录。"""
    assert _is_logged_in(
        _FakePage("https://passport2.chaoxing.com/login?fid=&newversion=true",
                  [{"name": "_uid", "value": "x"}])) is True


def test_is_logged_in_login_page_without_uid_stays_false():
    assert _is_logged_in(
        _FakePage("https://passport2.chaoxing.com/login?fid=&newversion=true", [])) is False


def test_is_logged_in_uid_cookie_fallback():
    assert _is_logged_in(
        _FakePage("https://example.chaoxing.com/base", [{"name": "UID", "value": "x"}])) is True


def test_cli_login_post_check_alive_exits_0(tmp_path, monkeypatch):
    import assist.xxt.session as sess
    monkeypatch.setattr(sess, "qr_login", lambda *a, **k: {"verdict": "logged_in"})
    monkeypatch.setattr(sess, "check_session", lambda *a, **k: {"verdict": "alive"})
    r = CliRunner().invoke(cli, ["xxt", "login", "--storage", str(tmp_path / "s.json")])
    assert r.exit_code == 0, r.output


def test_cli_login_post_check_dead_exits_2(tmp_path, monkeypatch):
    """D68：CLI 套壳必须确认 storage JSON 可用，否则 PWA 会显示登录任务失败。"""
    import assist.xxt.session as sess
    monkeypatch.setattr(sess, "qr_login", lambda *a, **k: {"verdict": "logged_in"})
    monkeypatch.setattr(sess, "check_session", lambda *a, **k: {"verdict": "dead"})
    r = CliRunner().invoke(cli, ["xxt", "login", "--storage", str(tmp_path / "s.json")])
    assert r.exit_code == 2, r.output

class _AliveBrowser:
    def is_connected(self):
        return True


class _NavPage:
    def is_closed(self):
        return False

    def evaluate(self, _expr):
        raise RuntimeError(
            "Execution context was destroyed, most likely because of a navigation")


class _DeadBrowser:
    def is_connected(self):
        return False


class _OpenPage:
    def is_closed(self):
        return False

    def evaluate(self, _expr):
        return 1


def test_page_alive_navigation_context_is_not_death():
    ok, err = _page_alive(_AliveBrowser(), _NavPage())
    assert ok is True and err == ""


def test_page_alive_browser_disconnected_is_death():
    ok, err = _page_alive(_DeadBrowser(), _OpenPage())
    assert ok is False and "disconnected" in err


def test_xxt_extract_cli_supports_all():
    from assist.cli import cli
    r = CliRunner().invoke(cli, ["xxt", "extract", "--help"])
    assert r.exit_code == 0, r.output
    assert "--all" in r.output
    # 无 --targets/--all 时应给用法错误，而不是静默什么都不做
    r2 = CliRunner().invoke(cli, ["xxt", "extract"])
    assert r2.exit_code != 0


def test_cli_extract_all_sets_discover(monkeypatch, tmp_path):
    import assist.xxt.extract_run as er
    called = {}

    def fake_run_extract(targets, **kw):
        called["targets"] = targets
        called.update(kw)
        return {"run_id": "xxt-test", "ts_end": "", "failures": [],
                "courses": [], "out": str(tmp_path / "xxt-test.json")}

    monkeypatch.setattr(er, "run_extract", fake_run_extract)
    monkeypatch.setenv("XXT_HOME", str(tmp_path))
    r = CliRunner().invoke(cli, ["xxt", "extract", "--all"])
    assert r.exit_code == 0, r.output
    assert called["targets"] == []
    assert called["discover_all"] is True

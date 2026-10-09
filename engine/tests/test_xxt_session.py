"""D63 T1 回归：xxt 会话体检纯逻辑 + CLI 组接线（不触网、不依赖 playwright）。"""

from click.testing import CliRunner

from assist.cli import cli
from assist.xxt.session import default_qr_path, evaluate_verdict, resolve_storage_path, xxt_home


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

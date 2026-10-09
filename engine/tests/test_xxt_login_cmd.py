"""D68 回归：PWA 扫码登录必须走 CLI 套壳，保证登录后 storage JSON/check_session 行为一致。"""

from pathlib import Path

import assist.serve as serve


def test_xxt_login_cmd_uses_cli_and_explicit_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(serve, "_venv_python", lambda: Path("/tmp/venv-python"))
    cmd = serve._xxt_login_cmd(tmp_path)
    assert cmd[:4] == ["/tmp/venv-python", "-m", "assist.cli", "xxt"]
    assert cmd[4] == "login"
    assert str(tmp_path / "xxt-storage.json") in cmd
    assert str(tmp_path / "xxt-qr.png") in cmd

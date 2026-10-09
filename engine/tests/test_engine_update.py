"""D65-P4：引擎版本检测纯逻辑回归（不触网）。"""

import json
from types import SimpleNamespace

from assist import engine_update as eu


def _write_local(tmp_path, meta):
    p = tmp_path / "_engine" / "engine-version.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(meta), encoding="utf-8")


def test_update_available_when_commit_differs(monkeypatch, tmp_path):
    _write_local(tmp_path, {"engine_version": "0.1.0", "commit": "aaa111"})
    monkeypatch.setattr(eu, "remote_version", lambda: {"engine_version": "0.1.0", "commit": "bbb222"})
    info = eu.check_engine_update(tmp_path)
    assert info["ok"] is True
    assert info["update_available"] is True


def test_no_update_when_commit_same(monkeypatch, tmp_path):
    _write_local(tmp_path, {"engine_version": "0.1.0", "commit": "same123"})
    monkeypatch.setattr(eu, "remote_version", lambda: {"engine_version": "0.1.0", "commit": "same123"})
    info = eu.check_engine_update(tmp_path)
    assert info["ok"] is True
    assert info["update_available"] is False


def test_missing_local_marker_marks_one_time_update(monkeypatch, tmp_path):
    monkeypatch.setattr(eu, "remote_version", lambda: {"engine_version": "0.1.0", "commit": "remote456"})
    info = eu.check_engine_update(tmp_path)
    assert info["ok"] is True
    assert info["update_available"] is True


def test_remote_unreachable_does_not_raise(monkeypatch, tmp_path):
    def boom():
        raise RuntimeError("pages unreachable")
    monkeypatch.setattr(eu, "remote_version", boom)
    info = eu.check_engine_update(tmp_path)
    assert info["ok"] is False
    assert info["update_available"] is None
    assert "pages unreachable" in info["error"]


def test_update_engine_noop_when_latest(monkeypatch, tmp_path):
    monkeypatch.setattr(eu, "check_engine_update", lambda ws: {
        "ok": True, "update_available": False, "remote": {}, "local": {}, "error": "",
    })
    lines: list[str] = []
    rc = eu.update_engine(tmp_path, lines.append)
    assert rc == 0
    assert any("最新" in line for line in lines)


def test_engine_cli_group_registered():
    from click.testing import CliRunner
    from assist.cli import cli
    r = CliRunner().invoke(cli, ["engine", "--help"])
    assert r.exit_code == 0, r.output
    assert "version" in r.output and "update" in r.output


def test_dep_install_commands_uv_uses_env_index_and_pip_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(eu.shutil, "which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr(eu, "_venv_python", lambda ws: "/tmp/venv-python")
    monkeypatch.setenv("UV_DEFAULT_INDEX", "https://mirror.example/simple")
    cmds = eu._dep_install_commands(tmp_path, tmp_path / "_engine" / "engine")
    assert len(cmds) == 2
    assert cmds[0][:4] == ["uv", "pip", "install", "-e"]
    assert "--cache-dir" in cmds[0]
    assert "--index-url" not in cmds[0]          # 新版 uv 已弃用显式 --index-url
    assert cmds[1][:4] == ["/tmp/venv-python", "-m", "pip", "install"]
    assert "-i" in cmds[1] and "https://mirror.example/simple" in cmds[1]


def test_install_engine_editable_falls_back_pip(monkeypatch, tmp_path, ):
    monkeypatch.setattr(eu, "_dep_install_commands",
                        lambda ws, engine_dir: [["uv", "fail"], ["pip", "ok"]])

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd == ["uv", "fail"]:
            return SimpleNamespace(returncode=2, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="installed", stderr="")

    monkeypatch.setattr(eu.subprocess, "run", fake_run)
    lines: list[str] = []
    assert eu._install_engine_editable(tmp_path, tmp_path / "engine", lines.append) == 0
    assert calls == [["uv", "fail"], ["pip", "ok"]]
    assert any("uv 安装失败，已用 venv pip 回退成功" in line for line in lines)

"""D65-P4：引擎版本检测纯逻辑回归（不触网）。"""

import json

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

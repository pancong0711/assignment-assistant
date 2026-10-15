"""D83-5.0：serve workspace 一致性 —— 白名单写端与 CLI 读端必须同一目录。

回归：`serve --workspace X` 但 ASSIST_WORKSPACE 未设时，_xxt_env 曾用 find_workspace(None)
解析到别处，导致「PWA 勾选班级 → 写 X 白名单；CLI work-create → 读别处空白名单 → 误拒」。
"""

import os
from pathlib import Path

import pytest

from assist.xxt.allowlist import is_allowed, write_allowlist
from assist.xxt.work import validate_work_target


def _mk_ws(tmp: Path) -> Path:
    (tmp / "kb").mkdir(parents=True, exist_ok=True)
    return tmp


def test_serve_ws_used_by_xxt_env(monkeypatch, tmp_path: Path):
    import assist.serve as serve

    ws = _mk_ws(tmp_path / "ws_explicit")
    serve._set_serve_ws(ws)
    try:
        # 即便环境里 ASSIST_WORKSPACE 指向别处，_ws() 仍返回 serve 的实际 workspace
        monkeypatch.setenv("ASSIST_WORKSPACE", str(tmp_path / "other"))
        assert serve._ws() == ws.resolve()
        env = serve._xxt_env(tmp_path / "xxt-home")
        assert env["ASSIST_WORKSPACE"] == str(ws.resolve())
    finally:
        serve._SERVE_WS = None


def test_validate_work_target_honors_env_workspace(monkeypatch, tmp_path: Path):
    """CLI 子进程不传 ws 时，find_workspace(None) 必须经 ASSIST_WORKSPACE 命中同一白名单。"""
    ws = _mk_ws(tmp_path / "ws")
    write_allowlist(ws, [{"courseId": "236685449", "classId": "81657984", "name": "默认班级"}])
    monkeypatch.setenv("ASSIST_WORKSPACE", str(ws))
    assert is_allowed("236685449", "81657984") is True
    assert validate_work_target("236685449", "81657984") is None
    # 未在白名单的班仍拒绝，且拒绝信息回显实际白名单文件与条目
    err = validate_work_target("111111", "222222")
    assert err and "白名单" in err and str(ws / "settings.local.json") in err


def test_validate_work_target_ws_mismatch_is_surfaced(monkeypatch, tmp_path: Path):
    """workspace 不同 → 拒绝信息里能看到实际读取的白名单路径（便于排查）。"""
    ws_a = _mk_ws(tmp_path / "a")
    ws_b = _mk_ws(tmp_path / "b")
    write_allowlist(ws_a, [{"courseId": "1", "classId": "2", "name": "A班"}])
    # 显式 ws_b（空白名单）读取 → 应拒绝并回显 ws_b 的文件路径
    err = validate_work_target("1", "2", ws_b)
    assert err and str(ws_b / "settings.local.json") in err
    # 显式 ws_a → 通过
    assert validate_work_target("1", "2", ws_a) is None


def test_create_work_rejects_non_whitelisted_before_session(tmp_path: Path, monkeypatch):
    """D83-7：create_work 先做白名单校验（传 ws），非白名单直接拒，不触网。"""
    from assist.xxt.work import create_work
    ws = _mk_ws(tmp_path / "cws")
    # 空白名单 → 任何班都拒
    out = create_work(ws / "storage.json", "1", "2", "0", "T", "<p>x</p>", "0", [], ws)
    assert out["ok"] is False and "白名单" in out["error"]


def test_create_work_attachment_path_guard(tmp_path: Path, monkeypatch):
    """D83-7：附件路径经 safe_attachment_path 过滤；越界/非法扩展名 → 拒绝整次创建。"""
    from assist.xxt.allowlist import write_allowlist
    from assist.xxt.work import create_work
    ws = _mk_ws(tmp_path / "aws")
    write_allowlist(ws, [{"courseId": "9", "classId": "8", "name": "班"}])
    evil = tmp_path / "evil.exe"; evil.write_bytes(b"MZ")
    out = create_work(ws / "storage.json", "9", "8", "0", "T", "<p>x</p>", "0", [str(evil)], ws)
    assert out["ok"] is False and "附件被拒绝" in out["error"]

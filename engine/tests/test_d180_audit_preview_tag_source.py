"""D180：/xxt/preview/students 带 classDir+taskId 时优先读 roster-tags 快照补 tag。

验收点：
- roster=innovation、快照=translation、带 classDir+taskId → 返回 translation；
- 只有 classDir、无 taskId → 返回 roster 的 innovation；
- 带 taskId 但快照缺失 → 回落 roster；
- 快照损坏 → 回落 roster，不报 500；
- 学号优先、姓名兜底；学生不在快照中按姓名回落 roster；
- 端到端：apply_audit_tags 写快照后，preview 立即读到新 tag；
- 既有 /xxt/preview/students 行为不回归。

全部使用合成数据；禁止真实学生数据/网络。
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import pytest

from assist.files import roster_io
from assist.grading import snapshots as SN
from assist.grading import tag_audit as TA


CLASS_DIR = "classes/SynthC1"
PACK = "pack-d180"


@pytest.fixture(autouse=True)
def _isolate_serve_state():
    """隔离 D180 测试对 serve/xxt 全局状态的修改，防止泄漏给 d130/d172。"""
    from assist import serve as S
    from assist.xxt.session import bind_workspace, bound_workspace

    prev_ws = S.Handler.ws
    prev_token = S.Handler.token
    prev_bound = bound_workspace()
    prev_xxt_home = os.environ.get("XXT_HOME")
    try:
        yield
    finally:
        S.Handler.ws = prev_ws
        S.Handler.token = prev_token
        bind_workspace(prev_bound)
        if prev_xxt_home is None:
            os.environ.pop("XXT_HOME", None)
        else:
            os.environ["XXT_HOME"] = prev_xxt_home


@contextmanager
def _server(ws: Path):
    """启动一个临时 serve 实例，绑定 XXT_HOME 到 ws 下，退出时清理环境变量。"""
    from assist import serve as S

    S.Handler.ws = ws
    S.Handler.token = ""
    home = ws / ".runtime" / "xxt"
    os.environ["XXT_HOME"] = str(home)
    s0 = socket.socket()
    s0.bind(("127.0.0.1", 0))
    port = s0.getsockname()[1]
    s0.close()
    httpd = S.ThreadingHTTPServer(("127.0.0.1", port), S.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.2)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        os.environ.pop("XXT_HOME", None)


def _jget(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read().decode())


def _write_roster(ws: Path, tag: str = "innovation"):
    (ws / "kb").mkdir(exist_ok=True)
    roster_io.write_roster(
        ws, CLASS_DIR,
        [{"name": "学生甲", "number": "001", "tag": tag},
         {"name": "学生乙", "number": "002", "tag": tag}])


def _write_snapshot(ws: Path, pack: str, rows):
    SN.write_tags_snapshot(ws, CLASS_DIR, pack, rows)


def _write_review_archive(ws: Path, students=None):
    """在 XXT_HOME 下写 review 列表 HTML 存档。"""
    home = ws / ".runtime" / "xxt"
    pages = home / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    if students is None:
        students = [("学生甲", "001"), ("学生乙", "002")]
    html = "".join(
        f'<ul class="dataBody_td"><div class="py_name">{name}</div>'
        f'<div id="{sid}"></div></ul>'
        for name, sid in students
    )
    (pages / "v2-review-cid1-wid1.html").write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------
# 核心场景
# ---------------------------------------------------------------------------
def test_preview_tag_prefers_snapshot_when_classdir_and_taskid(tmp_path: Path):
    """roster=innovation，快照=translation，带 classDir+taskId → translation。"""
    ws = tmp_path
    _write_roster(ws, "innovation")
    _write_snapshot(ws, PACK, [
        {"name": "学生甲", "number": "001", "tag": "translation"},
        {"name": "学生乙", "number": "002", "tag": "translation"},
    ])
    _write_review_archive(ws)

    with _server(ws) as base:
        q = urllib.parse.urlencode({"classDir": CLASS_DIR, "taskId": PACK})
        o = _jget(f"{base}/xxt/preview/students/cid1/wid1?{q}")
        assert o["ok"] is True
        tags = {s["name"]: s["tag"] for s in o["students"]}
        assert tags == {"学生甲": "translation", "学生乙": "translation"}


def test_preview_tag_uses_roster_when_no_taskid(tmp_path: Path):
    """只有 classDir、无 taskId → 返回 roster 的 innovation。"""
    ws = tmp_path
    _write_roster(ws, "innovation")
    _write_snapshot(ws, PACK, [
        {"name": "学生甲", "number": "001", "tag": "translation"},
    ])
    _write_review_archive(ws)

    with _server(ws) as base:
        q = urllib.parse.urlencode({"classDir": CLASS_DIR})
        o = _jget(f"{base}/xxt/preview/students/cid1/wid1?{q}")
        assert o["ok"] is True
        tags = {s["name"]: s["tag"] for s in o["students"]}
        assert tags == {"学生甲": "innovation", "学生乙": "innovation"}


def test_preview_tag_falls_back_when_snapshot_missing(tmp_path: Path):
    """带 taskId 但快照缺失 → 回落 roster，不报 500。"""
    ws = tmp_path
    _write_roster(ws, "innovation")
    _write_review_archive(ws)

    with _server(ws) as base:
        q = urllib.parse.urlencode({"classDir": CLASS_DIR, "taskId": PACK})
        o = _jget(f"{base}/xxt/preview/students/cid1/wid1?{q}")
        assert o["ok"] is True
        tags = {s["name"]: s["tag"] for s in o["students"]}
        assert tags == {"学生甲": "innovation", "学生乙": "innovation"}


def test_preview_tag_falls_back_when_snapshot_corrupt(tmp_path: Path):
    """快照 JSON 损坏 → 回落 roster，不报 500。"""
    ws = tmp_path
    _write_roster(ws, "innovation")
    snap_path = Path(SN.tags_snapshot_path(ws, CLASS_DIR, PACK))
    snap_path.parent.mkdir(parents=True, exist_ok=True)
    snap_path.write_text("not-json {", encoding="utf-8")
    _write_review_archive(ws)

    with _server(ws) as base:
        q = urllib.parse.urlencode({"classDir": CLASS_DIR, "taskId": PACK})
        o = _jget(f"{base}/xxt/preview/students/cid1/wid1?{q}")
        assert o["ok"] is True
        tags = {s["name"]: s["tag"] for s in o["students"]}
        assert tags == {"学生甲": "innovation", "学生乙": "innovation"}


def test_preview_tag_matches_by_number_first(tmp_path: Path):
    """学号优先于姓名：快照按学号命中时，即使姓名在 roster 中不同也使用快照 tag。"""
    ws = tmp_path
    (ws / "kb").mkdir(exist_ok=True)
    roster_io.write_roster(
        ws, CLASS_DIR,
        [{"name": "学生甲", "number": "001", "tag": "innovation"}])
    _write_snapshot(ws, PACK, [
        {"name": "另一姓名", "number": "001", "tag": "translation"},
    ])
    _write_review_archive(ws, students=[("学生甲", "001")])

    with _server(ws) as base:
        q = urllib.parse.urlencode({"classDir": CLASS_DIR, "taskId": PACK})
        o = _jget(f"{base}/xxt/preview/students/cid1/wid1?{q}")
        assert o["ok"] is True
        assert len(o["students"]) == 1
        assert o["students"][0]["tag"] == "translation"


def test_preview_tag_falls_back_per_student_not_in_snapshot(tmp_path: Path):
    """快照只覆盖部分学生，其余学生按姓名回落 roster。"""
    ws = tmp_path
    _write_roster(ws, "innovation")
    _write_snapshot(ws, PACK, [
        {"name": "学生甲", "number": "001", "tag": "translation"},
    ])
    _write_review_archive(ws)

    with _server(ws) as base:
        q = urllib.parse.urlencode({"classDir": CLASS_DIR, "taskId": PACK})
        o = _jget(f"{base}/xxt/preview/students/cid1/wid1?{q}")
        assert o["ok"] is True
        tags = {s["name"]: s["tag"] for s in o["students"]}
        assert tags["学生甲"] == "translation"
        assert tags["学生乙"] == "innovation"


# ---------------------------------------------------------------------------
# 端到端：apply_audit_tags → preview
# ---------------------------------------------------------------------------
def test_preview_tag_after_audit_apply_uses_snapshot(tmp_path: Path):
    """端到端：apply_audit_tags 写快照后，preview 立即读到新 tag。"""
    ws = tmp_path
    _write_roster(ws, "innovation")
    _write_snapshot(ws, PACK, [
        {"name": "学生甲", "number": "001", "tag": "innovation"},
        {"name": "学生乙", "number": "002", "tag": "innovation"},
    ])
    _write_review_archive(ws)

    rep = TA.apply_audit_tags(
        ws, class_dir=CLASS_DIR, pack_id=PACK,
        changes=[{"name": "学生甲", "tag": "translation"}])
    assert rep["ok"] is True

    with _server(ws) as base:
        q = urllib.parse.urlencode({"classDir": CLASS_DIR, "taskId": PACK})
        o = _jget(f"{base}/xxt/preview/students/cid1/wid1?{q}")
        assert o["ok"] is True
        tags = {s["name"]: s["tag"] for s in o["students"]}
        assert tags["学生甲"] == "translation"
        assert tags["学生乙"] == "innovation"


# ---------------------------------------------------------------------------
# 既有行为不回归
# ---------------------------------------------------------------------------
def test_preview_students_still_returns_students_without_classdir(tmp_path: Path):
    """不带 classDir 时，/xxt/preview/students 仍能返回学生列表（只是不补 tag）。"""
    ws = tmp_path
    _write_review_archive(ws)

    with _server(ws) as base:
        o = _jget(f"{base}/xxt/preview/students/cid1/wid1")
        assert o["ok"] is True
        names = {s["name"] for s in o["students"]}
        assert names == {"学生甲", "学生乙"}


def test_preview_students_keeps_existing_shape(tmp_path: Path):
    """带 classDir 时原有字段（count、scored、source）不丢失。"""
    ws = tmp_path
    _write_roster(ws, "innovation")
    _write_review_archive(ws)

    with _server(ws) as base:
        q = urllib.parse.urlencode({"classDir": CLASS_DIR})
        o = _jget(f"{base}/xxt/preview/students/cid1/wid1?{q}")
        assert o["ok"] is True
        assert o["count"] == 2
        assert "students" in o
        assert "source" in o
        assert isinstance(o.get("draftScopes"), list)

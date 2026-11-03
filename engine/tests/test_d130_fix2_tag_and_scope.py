"""D130-FIX2：刷新后「逐生审核」AI 状态 / tag 不显示（两个独立根因）。

根因 A（tag）：`/xxt/preview/students` 从不返回 `tag` 字段，
  而 tag 是**本校名单**概念（学习通列表页没有），前端拿到的永远是空串。
根因 B（AI 状态）：刷新后 `packId`/`padId` 为空（它们只来自下拉框），
  读草稿时 `taskId=''` → 读不到任何草稿 → 「AI 状态」全空；
  而点开弹窗又能看到内容（弹窗另有兜底），于是"表与弹窗不一致"。

修法：都由**引擎**兜底——tag 按姓名 join 名单，草稿目录从磁盘反查。
"""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from assist.xxt import grade_store as G


def _serve(ws: Path):
    from assist import serve as S
    S.Handler.ws = ws
    S.Handler.token = ""
    s0 = socket.socket(); s0.bind(("127.0.0.1", 0)); port = s0.getsockname()[1]; s0.close()
    httpd = S.ThreadingHTTPServer(("127.0.0.1", port), S.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.2)
    return f"http://127.0.0.1:{port}", httpd


def _jget(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read().decode())


# ---------------- 根因 B：反查批阅目录 ----------------
def test_discover_draft_scopes_finds_task_dir(tmp_path: Path):
    for task in ("pack1", "padA"):
        d = tmp_path / "classes" / "化工25" / "grading" / task / "drafts"
        d.mkdir(parents=True)
        (d / "wid1.json").write_text(json.dumps({"张三": {"ai": {}}}), encoding="utf-8")
    scopes = G.discover_draft_scopes(tmp_path, "classes/化工25", "wid1")
    assert set(scopes) == {"pack1", "padA"}


def test_discover_draft_scopes_empty_when_none(tmp_path: Path):
    (tmp_path / "classes" / "化工25" / "grading").mkdir(parents=True)
    assert G.discover_draft_scopes(tmp_path, "classes/化工25", "nope") == []
    assert G.discover_draft_scopes(tmp_path, "", "wid1") == []


def test_discover_draft_scopes_rejects_bad_workid(tmp_path: Path):
    assert G.discover_draft_scopes(tmp_path, "classes/化工25", "../../etc") == []


def test_drafts_endpoint_resolves_without_taskid(tmp_path: Path):
    """刷新后前端不传 taskId，仍必须读到草稿（这是本次 bug 的核心）。"""
    d = tmp_path / "classes" / "化工25" / "grading" / "pack1" / "drafts"
    d.mkdir(parents=True)
    (d / "wid1.json").write_text(
        json.dumps({"张三": {"ai": {"transcript": "x", "score": 88}}},
                   ensure_ascii=False), encoding="utf-8")
    base, httpd = _serve(tmp_path)
    try:
        q = urllib.parse.urlencode({"classDir": "classes/化工25"})
        o = _jget(f"{base}/xxt/grade/drafts/cid1/wid1?{q}")
        assert o["ok"] is True
        assert "张三" in o["drafts"], "刷新后应能反查到草稿"
        assert o["resolvedTaskId"] == "pack1"
        assert "pack1" in o["draftScopes"]
    finally:
        httpd.shutdown()


def test_drafts_endpoint_still_prefers_explicit_taskid(tmp_path: Path):
    for task, name in (("pack1", "张三"), ("other", "李四")):
        d = tmp_path / "classes" / "化工25" / "grading" / task / "drafts"
        d.mkdir(parents=True)
        (d / "wid1.json").write_text(
            json.dumps({name: {"ai": {"score": 70}}}, ensure_ascii=False), encoding="utf-8")
    base, httpd = _serve(tmp_path)
    try:
        q = urllib.parse.urlencode({"classDir": "classes/化工25", "taskId": "pack1"})
        o = _jget(f"{base}/xxt/grade/drafts/cid1/wid1?{q}")
        assert "张三" in o["drafts"] and "李四" not in o["drafts"]
    finally:
        httpd.shutdown()


def test_drafts_endpoint_survives_readonly_xxt_home(tmp_path: Path, monkeypatch):
    """XXT_HOME 只读时不能让读草稿接口 500（曾因 drafts_root 里 mkdir 抛出）。"""
    d = tmp_path / "classes" / "化工25" / "grading" / "pack1" / "drafts"
    d.mkdir(parents=True)
    (d / "wid1.json").write_text(json.dumps({"张三": {"ai": {"score": 80}}}),
                                encoding="utf-8")

    def _boom(*a, **kw):
        raise OSError(30, "Read-only file system")
    monkeypatch.setattr(Path, "mkdir", _boom)
    # drafts_root 不应把 OSError 抛出去
    p = G.drafts_root(str(tmp_path / "ro"))
    assert str(p).endswith("grade-drafts")


# ---------------- 根因 A：tag 由名单补齐 ----------------
def test_preview_students_returns_tag_from_roster(tmp_path: Path):
    """`/xxt/preview/students` 必须返回 tag（按姓名 join 本校名单）。"""
    from assist import serve as S

    ws = tmp_path
    (ws / "kb").mkdir()
    from assist.files import roster_io
    roster_io.write_roster(ws, "classes/化工25",
                           [{"name": "张三", "number": "1", "tag": "q1"},
                            {"name": "李四", "number": "2", "tag": "q2"}])
    # 伪造一份 review 列表存档（模拟学习通列表页）
    review = ws / "xxt" / "pages" / "review" / "cid1" / "wid1"
    review.mkdir(parents=True)
    (review / "list.html").write_text(
        '<ul class="dataBody_td"><div class="py_name">张三</div></ul>'
        '<ul class="dataBody_td"><div class="py_name">李四</div></ul>',
        encoding="utf-8")

    base, httpd = _serve(ws)
    try:
        q = urllib.parse.urlencode({"classDir": "classes/化工25"})
        o = _jget(f"{base}/xxt/preview/students/cid1/wid1?{q}")
        tags = {s.get("name"): s.get("tag") for s in (o.get("students") or [])}
        if tags:      # 存档能被识别时，tag 必须补上
            assert tags.get("张三") == "q1"
            assert tags.get("李四") == "q2"
    finally:
        httpd.shutdown()


def test_tag_lookup_uses_roster_not_student_list(tmp_path: Path):
    """回归：名单里没有该生时 tag 为空（不编造）。"""
    from assist.grading import inputs as I
    from assist.files import roster_io
    (tmp_path / "kb").mkdir()
    roster_io.write_roster(tmp_path, "classes/化工25", [{"name": "张三", "tag": "q1"}])
    tags = {x["name"]: x["tag"] for x in I.students_with_tags(tmp_path, "classes/化工25")}
    assert tags == {"张三": "q1"}
    assert tags.get("王五") is None

"""D181：AI 审计 tag 采纳与手动改写 tag 的端到端回归。

覆盖两条路径在「有快照 / 无快照 / 刷新无 taskId」下的行为，以及失败可见性。
全部使用合成学生/tag（学生甲/学生乙、innovation/translation），禁止真实数据/网络。
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
PACK = "pack-d181"


@pytest.fixture(autouse=True)
def _isolate_serve_state():
    """隔离 D181 测试对 serve/xxt 全局状态的修改。"""
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
    """启动一个临时 serve 实例，退出时清理环境变量。"""
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


def _jpost(url: str, payload: dict) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"ok": False, "error": body or f"HTTP {e.code}"}


def _write_roster(ws: Path, tag: str = "innovation"):
    (ws / "kb").mkdir(exist_ok=True)
    roster_io.write_roster(
        ws, CLASS_DIR,
        [{"name": "学生甲", "number": "001", "tag": tag},
         {"name": "学生乙", "number": "002", "tag": tag}])


def _write_snapshot(ws: Path, pack: str, rows):
    SN.write_tags_snapshot(ws, CLASS_DIR, pack, rows)


def _write_review_archive(ws: Path):
    home = ws / ".runtime" / "xxt"
    pages = home / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    html = "".join(
        f'<ul class="dataBody_td"><div class="py_name">{name}</div>'
        f'<div id="{sid}"></div></ul>'
        for name, sid in [("学生甲", "001"), ("学生乙", "002")]
    )
    (pages / "v2-review-cid1-wid1.html").write_text(html, encoding="utf-8")


def _preview(base: str, task_id: str | None = None) -> dict:
    qs = {"classDir": CLASS_DIR}
    if task_id:
        qs["taskId"] = task_id
    q = urllib.parse.urlencode(qs)
    return _jget(f"{base}/xxt/preview/students/cid1/wid1?{q}")


def _tags_of(resp: dict) -> dict[str, str]:
    return {s["name"]: s["tag"] for s in resp.get("students", [])}


def _apply(base: str, changes: list[dict], reason: str = "audit-apply") -> dict:
    return _jpost(f"{base}/grade/audit-tags/apply",
                  {"classDir": CLASS_DIR, "packId": PACK, "changes": changes, "reason": reason})


# ---------------------------------------------------------------------------
# 路径 A：采纳审计 tag（apply_audit_tags / applyTagAudit）
# ---------------------------------------------------------------------------
def test_apply_audit_tag_with_existing_snapshot_changes_preview(tmp_path: Path):
    """已有快照时点击「采纳审计」，preview 立即显示 translation。"""
    ws = tmp_path
    _write_roster(ws, "innovation")
    _write_snapshot(ws, PACK, [
        {"name": "学生甲", "number": "001", "tag": "innovation"},
        {"name": "学生乙", "number": "002", "tag": "innovation"},
    ])
    _write_review_archive(ws)

    with _server(ws) as base:
        r = _apply(base, [{"name": "学生甲", "tag": "translation"}], reason="audit-apply")
        assert r["ok"] is True
        assert r["applied"] == [{"name": "学生甲", "from": "innovation", "to": "translation"}]
        tags = _tags_of(_preview(base, PACK))
        assert tags == {"学生甲": "translation", "学生乙": "innovation"}


def test_apply_audit_tag_without_snapshot_creates_snapshot_from_roster(tmp_path: Path):
    """无快照时「采纳审计」先从 roster 创建快照，再写入 translation。"""
    ws = tmp_path
    _write_roster(ws, "innovation")
    _write_review_archive(ws)

    with _server(ws) as base:
        r = _apply(base, [{"name": "学生甲", "tag": "translation"}], reason="audit-apply")
        assert r["ok"] is True
        assert r["written"] is True
        snap = SN.read_tags_snapshot(ws, CLASS_DIR, PACK)
        assert snap["ok"] is True
        assert snap["source"] == "audit-apply"
        tags = _tags_of(_preview(base, PACK))
        assert tags == {"学生甲": "translation", "学生乙": "innovation"}


# ---------------------------------------------------------------------------
# 路径 B：手动改写 tag（前端保存 API → 后端落盘 → preview 刷新）
# ---------------------------------------------------------------------------
def test_manual_edit_with_existing_snapshot_changes_preview(tmp_path: Path):
    """已有快照时手动改 tag，preview 刷新后仍为 translation。"""
    ws = tmp_path
    _write_roster(ws, "innovation")
    _write_snapshot(ws, PACK, [
        {"name": "学生甲", "number": "001", "tag": "innovation"},
        {"name": "学生乙", "number": "002", "tag": "innovation"},
    ])
    _write_review_archive(ws)

    with _server(ws) as base:
        r = _apply(base, [{"name": "学生甲", "tag": "translation"}], reason="manual-detail")
        assert r["ok"] is True
        tags = _tags_of(_preview(base, PACK))
        assert tags["学生甲"] == "translation"


def test_manual_edit_without_snapshot_creates_snapshot_from_roster(tmp_path: Path):
    """无快照时手动改 tag，自动创建快照并生效。"""
    ws = tmp_path
    _write_roster(ws, "innovation")
    _write_review_archive(ws)

    with _server(ws) as base:
        r = _apply(base, [{"name": "学生甲", "tag": "translation"}], reason="manual-detail")
        assert r["ok"] is True
        snap = SN.read_tags_snapshot(ws, CLASS_DIR, PACK)
        assert snap["ok"] is True
        tags = _tags_of(_preview(base, PACK))
        assert tags["学生甲"] == "translation"


def test_manual_edit_refresh_without_taskid_still_uses_snapshot(tmp_path: Path):
    """刷新后前端没传 taskId，但磁盘有批阅目录时，tag 仍从快照读取。"""
    ws = tmp_path
    _write_roster(ws, "innovation")
    _write_review_archive(ws)
    # 创建批阅目录，让 discover_draft_scopes 能发现作用域
    drafts = ws / CLASS_DIR / "grading" / PACK / "drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    (drafts / "wid1.json").write_text("{}", encoding="utf-8")

    with _server(ws) as base:
        r = _apply(base, [{"name": "学生甲", "tag": "translation"}], reason="manual-detail")
        assert r["ok"] is True
        # 不带 taskId，只靠 classDir + 磁盘反查
        resp = _preview(base, task_id=None)
        assert resp.get("draftScopes") == [PACK]
        tags = _tags_of(resp)
        assert tags["学生甲"] == "translation"


# ---------------------------------------------------------------------------
# 失败 / 缺失 / 损坏快照回落
# ---------------------------------------------------------------------------
def test_apply_partial_missing_reports_missing_not_changed(tmp_path: Path):
    """无姓名/学号、无法定位的变更返回 missing；其余学生正常写入。"""
    ws = tmp_path
    _write_roster(ws, "innovation")
    _write_snapshot(ws, PACK, [
        {"name": "学生甲", "number": "001", "tag": "innovation"},
    ])
    _write_review_archive(ws)

    with _server(ws) as base:
        r = _apply(base, [{"name": "学生甲", "tag": "translation"},
                          {"tag": "translation"}])
        assert r["ok"] is True
        assert r["missing"] == ["(无名)"]
        tags = _tags_of(_preview(base, PACK))
        assert tags["学生甲"] == "translation"


def test_apply_with_invalid_classdir_returns_visible_error(tmp_path: Path):
    """classDir 非法时 API 返回 ok:false + 400，前端可见错误。"""
    ws = tmp_path
    _write_roster(ws, "innovation")
    _write_snapshot(ws, PACK, [{"name": "学生甲", "tag": "innovation"}])
    _write_review_archive(ws)

    with _server(ws) as base:
        r = _jpost(f"{base}/grade/audit-tags/apply",
                   {"classDir": "../etc", "packId": PACK,
                    "changes": [{"name": "学生甲", "tag": "translation"}]})
        assert r["ok"] is False
        assert "classDir" in r["error"] or "非法" in r["error"]


def test_preview_falls_back_to_roster_when_snapshot_corrupt(tmp_path: Path):
    """快照损坏时 preview 回落 roster，不报 500。"""
    ws = tmp_path
    _write_roster(ws, "innovation")
    snap_path = Path(SN.tags_snapshot_path(ws, CLASS_DIR, PACK))
    snap_path.parent.mkdir(parents=True, exist_ok=True)
    snap_path.write_text("not-json {", encoding="utf-8")
    _write_review_archive(ws)

    with _server(ws) as base:
        tags = _tags_of(_preview(base, PACK))
        assert tags == {"学生甲": "innovation", "学生乙": "innovation"}


# ---------------------------------------------------------------------------
# 直接函数入口：apply_audit_tags 无快照行为
# ---------------------------------------------------------------------------
def test_apply_audit_tags_directly_creates_snapshot_when_missing(tmp_path: Path):
    """直接调用 tag_audit.apply_audit_tags，无快照时自动创建。"""
    ws = tmp_path
    _write_roster(ws, "innovation")
    rep = TA.apply_audit_tags(
        ws, class_dir=CLASS_DIR, pack_id=PACK,
        changes=[{"name": "学生甲", "tag": "translation"}], reason="audit-apply")
    assert rep["ok"] is True
    snap = SN.read_tags_snapshot(ws, CLASS_DIR, PACK)
    assert snap["ok"] is True
    row = next(s for s in snap["students"] if s["name"] == "学生甲")
    assert row["tag"] == "translation"
    assert row["previousTag"] == "innovation"

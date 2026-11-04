"""D134-T3：资料上传 + 文件管理（`materials.files` L0 / `materials.remove` L2）。

安全口径（docs/83 §4 T3a / §6）：
1. 只允许白名单扩展名（不收 .exe/.sh/.zip）；
2. 只写 `_source/`，**同名不覆盖**（自动 `-2`）；
3. 文件名清洗，拒绝路径穿越（`../`）；
4. 单文件大小上限；
5. `remove` **移入 `_source/_trash/`，不真删**（教师原件唯一真源）；
6. 工具注册：`materials.files`=L0、`materials.remove`=L2（必须教师确认）。
"""
from __future__ import annotations

import base64
import json

import pytest

from assist.atopia import registry as R
from assist.atopia import runner as RN
from assist.files import materials as M


@pytest.fixture()
def ws(tmp_path):
    d = tmp_path / "ws"
    d.mkdir()
    return d


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _upload(name: str, content: bytes = b"hello"):
    return {"name": name, "data_b64": _b64(content)}


# ---------------- 上传白名单 ----------------
def test_upload_accepts_allowed_ext(ws):
    rep = M.save_uploads(ws, "chap04", [_upload("lecture01.pptx", b"PK\x03\x04abc")])
    assert rep["ok"] is True
    assert len(rep["saved"]) == 1
    assert (ws / "materials" / "chap04" / "_source" / "lecture01.pptx").is_file()
    assert rep["skipped"] == []


def test_upload_rejects_dangerous_ext(ws):
    for bad in ("evil.exe", "run.sh", "payload.zip", "noext"):
        rep = M.save_uploads(ws, "chap04", [_upload(bad)])
        assert rep["saved"] == [], bad
        assert rep["skipped"], bad
        assert not (ws / "materials" / "chap04" / "_source" / bad).exists()


def test_upload_does_not_overwrite_same_name(ws):
    M.save_uploads(ws, "chap04", [_upload("a.pdf", b"first")])
    rep = M.save_uploads(ws, "chap04", [_upload("a.pdf", b"second")])
    src = ws / "materials" / "chap04" / "_source"
    assert (src / "a.pdf").read_bytes() == b"first"      # 原件不被替换
    assert (src / "a-2.pdf").read_bytes() == b"second"
    assert rep["saved"][0]["renamed"] is True


def test_upload_rejects_size_over_limit(ws):
    big = b"x" * (M.UPLOAD_MAX_BYTES + 1)
    rep = M.save_uploads(ws, "chap04", [{"name": "big.pdf", "data_b64": _b64(big)}])
    assert rep["saved"] == []
    assert "上限" in rep["skipped"][0]["reason"]


def test_upload_sanitizes_path_traversal(ws):
    rep = M.save_uploads(ws, "chap04", [_upload("../../evil.pdf", b"x")])
    assert len(rep["saved"]) == 1
    # 只保留文件名，不写出 _source/
    p = ws / "materials" / "chap04" / "_source" / "evil.pdf"
    assert p.is_file()
    assert not (ws / "evil.pdf").exists()
    assert not (ws / "materials" / "evil.pdf").exists()


def test_upload_writes_only_source(ws):
    M.save_uploads(ws, "chap04", [_upload("a.pdf", b"x")])
    d = ws / "materials" / "chap04"
    assert (d / "_source" / "a.pdf").is_file()
    # 不产出生效清单（确认必须教师做）
    assert not (d / M.KNOW_MD).exists()
    assert not (d / M.KNOW_AI).exists()


def test_upload_invalid_chap_rejected(ws):
    with pytest.raises(M.MaterialsError):
        M.save_uploads(ws, "../etc", [_upload("a.pdf")])


# ---------------- files（L0） ----------------
def test_files_lists_source_with_sha(ws):
    M.save_uploads(ws, "chap04", [_upload("a.pdf", b"abc"), _upload("b.png", b"img")])
    rows = M.files_of(ws, "chap04")
    assert {r["name"] for r in rows} == {"a.pdf", "b.png"}
    for r in rows:
        assert len(r["sha256"]) == 64
        assert r["kind"] in ("pdf", "image")
        assert r["dir"] == "_source"


def test_files_empty_when_no_source(ws):
    (ws / "materials" / "chap04" / "_source").mkdir(parents=True)
    assert M.files_of(ws, "chap04") == []


# ---------------- remove（L2，移入回收站） ----------------
def test_remove_moves_to_trash_not_delete(ws):
    M.save_uploads(ws, "chap04", [_upload("a.pdf", b"abc")])
    rep = M.remove_source(ws, "chap04", "a.pdf")
    assert rep["ok"] is True
    src = ws / "materials" / "chap04" / "_source"
    assert not (src / "a.pdf").exists()
    assert (src / "_trash" / "a.pdf").read_bytes() == b"abc"    # 内容仍在
    assert "_trash" in rep["to"]


def test_remove_second_time_gets_numbered(ws):
    M.save_uploads(ws, "chap04", [_upload("a.pdf", b"1")])
    M.remove_source(ws, "chap04", "a.pdf")
    M.save_uploads(ws, "chap04", [_upload("a.pdf", b"2")])
    rep = M.remove_source(ws, "chap04", "a.pdf")
    src = ws / "materials" / "chap04" / "_source"
    assert (src / "_trash" / "a.pdf").read_bytes() == b"1"
    assert (src / "_trash" / "a-2.pdf").read_bytes() == b"2"


def test_remove_rejects_outside_source(ws):
    with pytest.raises(M.MaterialsError):
        M.remove_source(ws, "chap04", "../../../etc/passwd")


def test_remove_missing_file_errors(ws):
    with pytest.raises(M.MaterialsError):
        M.remove_source(ws, "chap04", "nope.pdf")


def test_remove_shows_in_files_with_trash(ws):
    M.save_uploads(ws, "chap04", [_upload("a.pdf", b"abc")])
    M.remove_source(ws, "chap04", "a.pdf")
    rows = M.files_of(ws, "chap04", include_trash=True)
    assert any(r["dir"] == "_source/_trash" and r["name"] == "a.pdf" for r in rows)


# ---------------- 工具注册与权限 ----------------
def test_tools_registered_with_levels(ws):
    names = {t.name: t.level for t in R.BUILTIN_TOOLS}
    assert names["materials.files"] == "L0"
    assert names["materials.remove"] == "L2"


def test_materials_files_tool_runs_without_confirm(ws):
    M.save_uploads(ws, "chap04", [_upload("a.pdf", b"abc")])
    r = RN.run_tool(ws, "materials.files", {"chap": "chap04"})
    assert r["ok"] is True
    assert "a.pdf" in r["stdout"]


def test_materials_remove_tool_requires_confirmation(ws):
    M.save_uploads(ws, "chap04", [_upload("a.pdf", b"abc")])
    from assist.atopia.registry import ToolDenied
    with pytest.raises(ToolDenied):
        RN.run_tool(ws, "materials.remove", {"chap": "chap04", "file": "a.pdf"})
    # 未确认时**没有动文件**
    assert (ws / "materials" / "chap04" / "_source" / "a.pdf").is_file()


def test_materials_remove_tool_with_confirm(ws):
    M.save_uploads(ws, "chap04", [_upload("a.pdf", b"abc")])
    r = RN.run_tool(ws, "materials.remove", {"chap": "chap04", "file": "a.pdf"},
                    confirmed_by="teacher:test")
    assert r["ok"] is True
    assert (ws / "materials" / "chap04" / "_source" / "_trash" / "a.pdf").is_file()


def test_remove_tool_cannot_escape_workspace(ws):
    """参数不得把命令指向 workspace 之外（路径穿越在 CLI 层被拒）。"""
    M.save_uploads(ws, "chap04", [_upload("a.pdf", b"abc")])
    r = RN.run_tool(ws, "materials.remove",
                    {"chap": "chap04", "file": "../../secret.pdf"},
                    confirmed_by="teacher:test")
    assert r["ok"] is False


# ---------------- D135：从回收站恢复（与 remove 对称） ----------------
def test_restore_moves_back(ws):
    M.save_uploads(ws, "chap04", [_upload("a.pdf", b"abc")])
    M.remove_source(ws, "chap04", "a.pdf")
    rep = M.restore_source(ws, "chap04", "a.pdf")
    src = ws / "materials" / "chap04" / "_source"
    assert rep["ok"] is True
    assert (src / "a.pdf").read_bytes() == b"abc"
    assert not (src / "_trash" / "a.pdf").exists()


def test_restore_accepts_trash_prefix(ws):
    M.save_uploads(ws, "chap04", [_upload("a.pdf", b"abc")])
    M.remove_source(ws, "chap04", "a.pdf")
    M.restore_source(ws, "chap04", "_trash/a.pdf")
    assert (ws / "materials" / "chap04" / "_source" / "a.pdf").is_file()


def test_restore_does_not_overwrite_existing(ws):
    """恢复时目标同名已存在 → 自动 -2（教师原件永不被静默替换）。"""
    M.save_uploads(ws, "chap04", [_upload("a.pdf", b"old")])
    M.remove_source(ws, "chap04", "a.pdf")
    M.save_uploads(ws, "chap04", [_upload("a.pdf", b"new")])
    rep = M.restore_source(ws, "chap04", "a.pdf")
    src = ws / "materials" / "chap04" / "_source"
    assert (src / "a.pdf").read_bytes() == b"new"
    assert (src / "a-2.pdf").read_bytes() == b"old"
    assert rep["renamed"] is True


def test_restore_missing_errors(ws):
    with pytest.raises(M.MaterialsError):
        M.restore_source(ws, "chap04", "nope.pdf")


def test_restore_rejects_outside_trash(ws):
    with pytest.raises(M.MaterialsError):
        M.restore_source(ws, "chap04", "../../../etc/passwd")


def test_restore_tool_is_l2_and_requires_confirm(ws):
    names = {t.name: t.level for t in R.BUILTIN_TOOLS}
    assert names["materials.restore"] == "L2"
    M.save_uploads(ws, "chap04", [_upload("a.pdf", b"abc")])
    M.remove_source(ws, "chap04", "a.pdf")
    from assist.atopia.registry import ToolDenied
    with pytest.raises(ToolDenied):
        RN.run_tool(ws, "materials.restore", {"chap": "chap04", "file": "a.pdf"})
    r = RN.run_tool(ws, "materials.restore", {"chap": "chap04", "file": "a.pdf"},
                    confirmed_by="teacher:test")
    assert r["ok"] is True
    assert (ws / "materials" / "chap04" / "_source" / "a.pdf").is_file()

"""D148：Atopia 通用只读文件能力（fs.ls / fs.read / fs.search）。

教师诉求：让 AI 找某题参考答案时，它应该"先找到文档、再打开查看"。

安全：路径限 workspace、硬屏蔽 secrets/.runtime/.git、只读、有上限。
"""
from __future__ import annotations

import json

import pytest

from assist.atopia import fsview as F
from assist.atopia import registry as R
from assist.atopia import runner as RN


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "kb" / "solutions").mkdir(parents=True)
    (tmp_path / "kb" / "solutions" / "chap04-01.json").write_text(
        json.dumps({"qid": "chap04-01", "versions": [{"text": "动量守恒 $p=mv$"}]},
                   ensure_ascii=False), encoding="utf-8")
    (tmp_path / "settings.local.secrets.json").write_text('{"k":"sk-xxx"}', encoding="utf-8")
    (tmp_path / ".runtime").mkdir()
    (tmp_path / ".runtime" / "junk.txt").write_text("x", encoding="utf-8")
    return tmp_path


# ---------------- 基本能力 ----------------
def test_ls(ws):
    r = F.ls(ws, "kb")
    names = {e["name"] for e in r["entries"]}
    assert "solutions" in names


def test_read(ws):
    r = F.read(ws, "kb/solutions/chap04-01.json")
    assert "动量守恒" in r["text"]


def test_search_finds_answer(ws):
    """教师场景：AI 先搜到文件，再打开查看。"""
    r = F.search(ws, "动量守恒")
    assert r["count"] >= 1
    assert r["hits"][0]["file"].endswith("chap04-01.json")


# ---------------- 安全 ----------------
def test_blocked_secrets(ws):
    with pytest.raises(F.FSViewError) as ei:
        F.read(ws, "settings.local.secrets.json")
    assert "敏感" in str(ei.value)


def test_blocked_runtime(ws):
    with pytest.raises(F.FSViewError):
        F.read(ws, ".runtime/junk.txt")


def test_blocked_outside_workspace(ws):
    with pytest.raises(F.FSViewError):
        F.read(ws, "../../etc/passwd")


def test_secrets_not_listed(ws):
    r = F.ls(ws, ".")
    assert not any("secrets" in e["name"] for e in r["entries"])


def test_search_skips_secrets(ws):
    r = F.search(ws, "sk-xxx")
    assert r["count"] == 0


def test_binary_rejected(ws):
    p = ws / "kb" / "fig.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
    with pytest.raises(F.FSViewError) as ei:
        F.read(ws, "kb/fig.png")
    assert "二进制" in str(ei.value)


def test_read_truncated(ws):
    big = ws / "big.txt"
    big.write_text("\n".join(f"line{i}" for i in range(500)), encoding="utf-8")
    r = F.read(ws, "big.txt", lines=10)
    assert r["lines"] == 10 and r["truncated"] is True


# ---------------- 工具注册 / 占位符传参 ----------------
def test_tools_registered_as_l0():
    lv = {t.name: t.level for t in R.BUILTIN_TOOLS}
    for n in ("fs.ls", "fs.read", "fs.search"):
        assert lv[n] == "L0", n


def test_placeholder_arg_builds_argv():
    """D148 修复：`{query}` 占位符此前因正则写成双反斜杠而**完全失效**。"""
    t = R.get_tool("fs.search")
    argv = R.build_argv(t, {"query": "动量守恒"})
    assert argv == ["fs", "search", "动量守恒"]


def test_fs_search_via_runner(ws):
    r = RN.run_tool(ws, "fs.search", {"query": "动量守恒"})
    assert r["ok"] is True
    assert "chap04-01.json" in r["stdout"]


def test_fs_read_via_runner_blocks_secrets(ws):
    r = RN.run_tool(ws, "fs.read", {"path": "settings.local.secrets.json"})
    assert r["ok"] is False
    assert "敏感" in (r["stderr"] or "")


def test_fs_read_rejects_non_ws_path_arg(ws):
    """参数层的 path_in_ws 校验也必须拦住越界。"""
    from assist.atopia.registry import ToolDenied
    with pytest.raises(ToolDenied):
        RN.run_tool(ws, "fs.read", {"path": "/etc/passwd"})

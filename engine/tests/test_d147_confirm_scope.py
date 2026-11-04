"""D147：L2 确认必须**精确到"哪个工具 + 哪些参数"**（安全修复）。

漏洞（实测可复现）：`/atopia/ask` 的 `_confirm()` 只看 `confirmed === true`。
教师为 `materials.confirm` 点了确认后，同一次请求里模型改请求 `kb.vocab.add`
（或任意其它 L2 工具）→ **同样被自动放行并真的执行了**（journal 有记录），
违背 D132「L2 必须教师**逐次**确认」。

修复后：请求必须带 `confirmedTool`（+ 可选 `confirmedArgs`），
后端只放行**完全一致**的那一次调用；其余 L2 一律拒绝。
"""
from __future__ import annotations

import json

import pytest

from assist.atopia import agent as AG


class FakeLLM:
    """按脚本依次请求工具；从不支持原生 tools（走 JSON 指令协议）。"""

    evaluation_model = "fake"
    session_id = ""

    def __init__(self, tools: list[tuple[str, dict]]):
        self.queue = list(tools)

    def set_session_id(self, sid):
        self.session_id = str(sid or "")

    def chat_with_tools(self, messages, tools, **kw):
        from assist.grading.llm import LLMAPIError
        raise LLMAPIError("400 tools is not supported by this model")

    def tool_calls_of(self, data):
        return []

    def chat(self, **kw):
        if self.queue:
            name, args = self.queue.pop(0)
            return json.dumps({"action": "tool", "tool": name, "args": args})
        return '{"action":"final","answer":"done"}'


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "kb").mkdir()
    return tmp_path


def _make_confirm(ws):
    """构造一个"只认指定工具+参数"的 confirm，模拟修复后的服务端逻辑。"""
    def _confirm(tool_name, args, *, confirmed_tool, confirmed_args=None):
        if confirmed_tool != tool_name:
            return ""
        if confirmed_args is not None and \
                json.dumps(args, sort_keys=True) != json.dumps(confirmed_args, sort_keys=True):
            return ""
        return "teacher:pwa"
    return _confirm


def test_confirm_only_allows_the_confirmed_tool(ws):
    """教师确认 A，模型却请求 B → B 必须被拒绝。"""
    seen = []
    c = FakeLLM([("materials.confirm", {"chap": "chap04"}),
                 ("kb.vocab.add", {"term": "坏"})])
    held = {"tool": "materials.confirm", "args": {"chap": "chap04"}}

    def confirm(tool_name, args):
        if held["tool"] != tool_name:
            return ""
        if json.dumps(args, sort_keys=True) != json.dumps(held["args"], sort_keys=True):
            return ""
        return "teacher:pwa"

    rep = AG.run_session_auto(c, ws, "x", confirm=confirm, max_turns=4)
    for s in rep.get("steps") or []:
        if s.get("action") == "tool":
            seen.append((s.get("tool"), bool(s.get("denied"))))
    assert ("materials.confirm", False) in seen
    # 第二个工具被拒绝 → 会话中止
    assert rep["ok"] is False, "确认了 A 却放行了 B"


def test_confirm_matching_arguments_allowed(ws):
    """工具名与参数都一致 → 正常执行（不误伤）。"""
    held = {"tool": "kb.vocab.add", "args": {"term": "动量守恒"}}

    def confirm(tool_name, args):
        if held["tool"] != tool_name:
            return ""
        if json.dumps(args, sort_keys=True) != json.dumps(held["args"], sort_keys=True):
            return ""
        return "teacher:pwa"

    c = FakeLLM([("kb.vocab.add", {"term": "动量守恒"})])
    rep = AG.run_session_auto(c, ws, "x", confirm=confirm, max_turns=3)
    assert rep["ok"] is True
    assert any(s.get("tool") == "kb.vocab.add" and s.get("ok") for s in rep["steps"])


def test_confirm_args_mismatch_rejected(ws):
    """同名工具但**参数不同**（如 chap04 → chap09）也必须拒绝。"""
    held = {"tool": "materials.confirm", "args": {"chap": "chap04"}}

    def confirm(tool_name, args):
        if tool_name != held["tool"]:
            return ""
        if json.dumps(args, sort_keys=True) != json.dumps(held["args"], sort_keys=True):
            return ""
        return "teacher:pwa"

    c = FakeLLM([("materials.confirm", {"chap": "chap09"})])
    rep = AG.run_session_auto(c, ws, "x", confirm=confirm, max_turns=3)
    assert rep["ok"] is False


# ---------------- 直接验证 serve 里的**真实实现** ----------------
def test_serve_confirm_rejects_other_tool():
    from assist.serve import make_atopia_confirm
    c = make_atopia_confirm(confirmed=True, confirmed_tool="materials.confirm",
                            confirmed_args={"chap": "chap04"})
    assert c("materials.confirm", {"chap": "chap04"}) == "teacher:pwa"
    assert c("kb.write", {"input": "x"}) == ""       # ← 漏洞所在：必须拒绝


def test_serve_confirm_requires_tool_name():
    """带 confirmed 却没指明工具 → 盲确认，必须拒绝。"""
    from assist.serve import make_atopia_confirm
    c = make_atopia_confirm(confirmed=True, confirmed_tool="")
    assert c("kb.write", {}) == ""


def test_serve_confirm_rejects_arg_mismatch():
    from assist.serve import make_atopia_confirm
    c = make_atopia_confirm(confirmed=True, confirmed_tool="materials.confirm",
                            confirmed_args={"chap": "chap04"})
    assert c("materials.confirm", {"chap": "chap09"}) == ""


def test_serve_confirm_without_flag():
    from assist.serve import make_atopia_confirm
    c = make_atopia_confirm(confirmed=False, confirmed_tool="materials.confirm")
    assert c("materials.confirm", {}) == ""


def test_serve_confirm_legacy_client_without_args():
    """老客户端只传工具名（不传参数）→ 仍按工具名放行（向后兼容）。"""
    from assist.serve import make_atopia_confirm
    c = make_atopia_confirm(confirmed=True, confirmed_tool="materials.confirm")
    assert c("materials.confirm", {"chap": "x"}) == "teacher:pwa"

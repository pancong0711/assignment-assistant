"""D135：Atopia 原生 `tools` 协议（OpenAI 兼容 function calling）+ 自动降级。

**安全红线**：原生与 JSON 指令协议最终都调 `RN.run_tool()`，
因此 L3 拒绝 / L2 必须教师确认 / 参数白名单 / 护栏**完全一致**。
原生只是"模型怎么表达意图"更规范，**不是绕过审批的通道**。
"""
from __future__ import annotations

import json

import pytest

from assist.atopia import agent as AG
from assist.atopia import limits as L
from assist.atopia import registry as R


class FakeClient:
    """模拟 OpenAI 兼容客户端：按脚本依次返回响应。"""

    def __init__(self, replies: list[dict], *, raise_on_tools: Exception | None = None):
        self.replies = list(replies)
        self.calls: list[dict] = []
        self.raise_on_tools = raise_on_tools

    def chat_with_tools(self, messages, tools, **kw):
        self.calls.append({"messages": messages, "tools": tools, **kw})
        if self.raise_on_tools is not None:
            raise self.raise_on_tools
        return self.replies.pop(0) if self.replies else self._final("（无后续）")

    def tool_calls_of(self, data):
        return [c for c in (data.get("tool_calls") or []) if isinstance(c, dict)]

    # 降级路径用
    def chat(self, system_prompt, user_text, **kw):
        self.calls.append({"json_mode": True, "user_text": user_text})
        return json.dumps({"action": "final", "answer": "降级后的回答"})

    def _final(self, text):
        return {"tool_calls": [], "choices": [{"message": {"content": text}}]}


def _call(name: str, args: dict, cid: str = "c1") -> dict:
    return {"tool_calls": [{"id": cid, "type": "function",
                            "function": {"name": name,
                                         "arguments": json.dumps(args, ensure_ascii=False)}}],
            "choices": [{"message": {"content": None, "tool_calls": [
                {"id": cid, "type": "function",
                 "function": {"name": name, "arguments": json.dumps(args)}}]}}]}


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "kb").mkdir()
    return tmp_path


# ---------------- 工具清单 ----------------
def test_payload_names_have_no_dots(ws):
    """OpenAI 函数名不允许点号 → 转换后必须仍能还原成登记的工具 id。"""
    payload = AG.build_tools_payload(R.effective_tools(ws))
    names = [p["function"]["name"] for p in payload]
    assert all("." not in n for n in names)
    tools = R.effective_tools(ws)
    assert AG._name_from_function("kb__stats", tools) == "kb.stats"


def test_payload_excludes_l3(ws):
    payload = AG.build_tools_payload([t for t in R.effective_tools(ws) if t.level != "L3"])
    names = {p["function"]["name"] for p in payload}
    assert "engine__update" not in names
    assert "kb__stats" in names


# ---------------- 正常路径 ----------------
def test_native_final_answer(ws):
    c = FakeClient([FakeClient([])._final("你好")])
    rep = AG.run_session_native(c, ws, "打个招呼")
    assert rep["ok"] is True and rep["answer"] == "你好"
    assert rep["protocol"] == "native"
    assert c.calls and c.calls[0]["tools"]


def test_native_runs_l0_tool(ws):
    c = FakeClient([_call("kb__stats", {}), FakeClient([])._final("已完成")])
    rep = AG.run_session_native(c, ws, "统计题库")
    assert rep["ok"] is True
    assert rep["steps"][0]["tool"] == "kb.stats"
    assert rep["steps"][0].get("status") in ("ok", "error")   # 真执行了


# ---------------- 安全：L3 拒绝 ----------------
def test_native_l3_denied(ws):
    c = FakeClient([_call("engine__update", {})])
    rep = AG.run_session_native(c, ws, "升级引擎")
    assert rep["ok"] is False
    assert "未登记" in rep["error"] or "L3" in rep["error"]


# ---------------- 安全：L2 需确认 ----------------
def test_native_l2_requires_confirm_channel(ws):
    c = FakeClient([_call("materials__confirm", {"chap": "chap04"})])
    rep = AG.run_session_native(c, ws, "确认知识点")
    assert rep["ok"] is False
    assert "L2" in rep["error"] or "教师确认" in rep["error"]


def test_native_l2_denied_by_teacher(ws):
    c = FakeClient([_call("materials__confirm", {"chap": "chap04"})])
    rep = AG.run_session_native(c, ws, "确认知识点", confirm=lambda n, a: "")
    assert rep["ok"] is False
    assert "未确认" in rep["error"]


def test_native_l2_confirmed_is_audited(ws, monkeypatch):
    seen = {}

    def fake_run(ws_, name, args, **kw):
        seen.update({"name": name, "args": args, "confirmed_by": kw.get("confirmed_by")})
        return {"ok": True, "status": "ok", "exit": 0, "ms": 1,
                "stdout": "done", "stderr": ""}

    monkeypatch.setattr(AG.RN, "run_tool", fake_run)
    c = FakeClient([_call("materials__confirm", {"chap": "chap04"}),
                    FakeClient([])._final("好了")])
    rep = AG.run_session_native(c, ws, "确认知识点",
                                confirm=lambda n, a: "teacher:test")
    assert rep["ok"] is True
    assert seen["name"] == "materials.confirm"
    assert seen["confirmed_by"] == "teacher:test"


def test_native_unknown_tool_denied(ws):
    c = FakeClient([_call("rm__rf", {})])
    rep = AG.run_session_native(c, ws, "删库")
    assert rep["ok"] is False
    assert "未登记" in rep["error"]


def test_native_param_injection_rejected(ws, monkeypatch):
    """参数里塞 `--workspace` 之类仍由 validate_args 拦（原生不放松）。"""
    c = FakeClient([_call("kb__stats", {"evil": "x"}), FakeClient([])._final("x")])
    rep = AG.run_session_native(c, ws, "统计")
    # 未登记参数 → ToolDenied
    assert rep["ok"] is False
    assert rep["steps"][0].get("denied") is True


# ---------------- 自动降级 ----------------
def test_auto_degrades_when_provider_lacks_tools(ws):
    class E(Exception):
        pass
    c = FakeClient([], raise_on_tools=E("400 tools not supported by this model"))
    rep = AG.run_session_auto(c, ws, "做个任务")
    assert rep["ok"] is True
    assert rep["protocol"] == "json"
    assert rep["degraded"] is True
    assert rep["answer"] == "降级后的回答"


def test_auto_does_not_swallow_unrelated_errors(ws):
    """网络/鉴权故障**不得**被当成"不支持 tools"而静默换协议。"""
    class E(Exception):
        pass
    c = FakeClient([], raise_on_tools=E("401 invalid api key"))
    with pytest.raises(E):
        AG.run_session_auto(c, ws, "做个任务")


def test_auto_prefer_json(ws):
    c = FakeClient([])
    rep = AG.run_session_auto(c, ws, "任务", prefer="json")
    assert rep["protocol"] == "json"
    assert any(x.get("json_mode") for x in c.calls)


def test_limits_still_enforced_native(ws):
    """护栏在原生路径同样生效（超出调用次数即中止）。"""
    L.write_limits(ws, {"maxCallsPerSession": 1})
    sess = L.Session(session_id="t", limits=L.read_limits(ws))
    c = FakeClient([_call("kb__stats", {}, "c1"),
                    _call("kb__stats", {}, "c2"),
                    FakeClient([])._final("x")])
    rep = AG.run_session_native(c, ws, "反复统计", session=sess)
    assert rep["ok"] is False
    assert any(s.get("limit") for s in rep["steps"])


def test_auto_degrades_only_on_tool_protocol_signals(ws):
    """降级判定必须"工具相关 + 不支持"同时命中（防误伤 401/网络错误）。"""
    from assist.atopia.agent import _FATAL_HINTS, _TOOL_HINTS, _UNSUPPORTED_HINTS
    # 必须能识别的真实降级场景
    msg = "400 invalid_request_error: tools is not supported by this model"
    assert any(h in msg for h in _TOOL_HINTS)
    assert any(h in msg for h in _UNSUPPORTED_HINTS)
    # 明确不能降级的场景
    for bad in ("401 invalid api key", "connection timeout", "quota exceeded"):
        assert any(h in bad for h in _FATAL_HINTS), bad

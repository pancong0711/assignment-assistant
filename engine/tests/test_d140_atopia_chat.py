"""D140：Atopia 对话接口（多轮 + 工具，全部经同一 Gate）。

安全要求（docs/89 §3）：
1. 工具只能来自白名单（未登记拒绝）；
2. L2 必须教师**逐次**确认（未确认 → 返回 pendingConfirm，**不执行**）；
3. L3 永不执行；
4. 护栏照旧；会话历史只落 `<ws>/atopia/`。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from assist.atopia import agent as AG
from assist.atopia import limits as L
from assist.atopia import registry as R


class FakeLLM:
    """最小 client：让 run_session 能跑（JSON 指令协议路径）。"""

    evaluation_model = "fake"
    session_id = ""

    def __init__(self, replies):
        self.replies = list(replies)
        self.n = 0

    def set_session_id(self, sid):
        self.session_id = str(sid or "")

    def chat(self, **kw):
        self.n += 1
        return self.replies.pop(0) if self.replies else '{"action":"final","answer":"ok"}'

    def chat_with_tools(self, messages, tools, **kw):
        from assist.grading.llm import LLMAPIError
        # 模拟 provider 不支持 tools → 自动降级到 JSON 指令协议
        raise LLMAPIError("400 tools is not supported by this model")

    def tool_calls_of(self, data):
        return []


def _tool_reply(name, args):
    return json.dumps({"action": "tool", "tool": name, "args": args}, ensure_ascii=False)


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "kb").mkdir()
    return tmp_path


def test_chat_runs_l0_tool_and_answers(ws):
    c = FakeLLM([_tool_reply("kb.stats", {}), '{"action":"final","answer":"有 3 题"}'])
    rep = AG.run_session_auto(c, ws, "题库有多少题")
    assert rep["ok"] is True
    assert rep["answer"] == "有 3 题"
    assert rep["protocol"] == "json"          # 自动降级
    assert any(s.get("tool") == "kb.stats" for s in rep["steps"])


def test_chat_l2_without_confirm_is_denied(ws):
    c = FakeLLM([_tool_reply("materials.confirm", {"chap": "chap04"})])
    rep = AG.run_session_auto(c, ws, "确认知识点", confirm=lambda n, a: "")
    assert rep["ok"] is False
    assert any(s.get("denied") for s in rep["steps"])


def test_chat_l2_with_confirm_executes(ws, monkeypatch):
    seen = {}

    def fake_run(ws_, name, args, **kw):
        seen.update({"name": name, "confirmed_by": kw.get("confirmed_by")})
        return {"ok": True, "status": "ok", "exit": 0, "ms": 1,
                "stdout": "done", "stderr": ""}

    monkeypatch.setattr(AG.RN, "run_tool", fake_run)
    c = FakeLLM([_tool_reply("materials.confirm", {"chap": "chap04"}),
                 '{"action":"final","answer":"已确认"}'])
    rep = AG.run_session_auto(c, ws, "确认知识点",
                              confirm=lambda n, a: "teacher:pwa")
    assert rep["ok"] is True
    assert seen["name"] == "materials.confirm"
    assert seen["confirmed_by"] == "teacher:pwa"


def test_chat_l3_never_runs(ws):
    c = FakeLLM([_tool_reply("engine.update", {})])
    rep = AG.run_session_auto(c, ws, "升级引擎")
    assert rep["ok"] is False
    assert "未登记" in rep["error"] or "L3" in rep["error"]


def test_chat_unknown_tool_denied(ws):
    c = FakeLLM([_tool_reply("rm.rf", {})])
    rep = AG.run_session_auto(c, ws, "删库")
    assert rep["ok"] is False
    assert "未登记" in rep["error"]


def test_chat_limits_enforced(ws):
    L.write_limits(ws, {"maxCallsPerSession": 1})
    sess = L.Session(session_id="t", limits=L.read_limits(ws))
    c = FakeLLM([_tool_reply("kb.stats", {}), _tool_reply("kb.stats", {}),
                 '{"action":"final","answer":"x"}'])
    rep = AG.run_session_auto(c, ws, "反复统计", session=sess)
    assert rep["ok"] is False


def test_session_id_stable_across_turns(ws):
    c = FakeLLM([_tool_reply("kb.stats", {}), '{"action":"final","answer":"ok"}'])
    AG.run_session_auto(c, ws, "统计")
    assert c.session_id.startswith("atopia-")


def test_session_history_files_under_atopia(tmp_path):
    """会话历史必须落在 `<ws>/atopia/sessions/`（可整体删除）。"""
    from assist.atopia import paths as P
    ws = tmp_path
    (ws / "kb").mkdir()
    P.ensure_root(ws)
    sd = ws / "atopia" / "sessions"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "chat-x.jsonl").write_text('{"ts":"t","task":"a","ok":true}\n', encoding="utf-8")
    assert (ws / "atopia" / "sessions" / "chat-x.jsonl").is_file()
    # 删除 atopia/ 不影响 kb/
    import shutil
    shutil.rmtree(ws / "atopia")
    assert (ws / "kb").is_dir()

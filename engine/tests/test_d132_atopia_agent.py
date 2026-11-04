"""D132(P3-3)：LLM function calling 会话（T16），**降级路径不比原生宽松**。

核心安全断言（docs/81 §6）：
- 模型请求 L3 → 拒绝；
- 模型请求未登记工具 → 拒绝；
- L2 没有确认通道 / 教师拒绝 → 拒绝；
- L2 教师同意 → 执行，且 journal 记 confirmed_by；
- 护栏在会话内生效；
- 模型不按 JSON 格式回复 → 当最终回答，**不猜测意图执行工具**。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from assist.atopia import agent as AG
from assist.atopia import limits as L
from assist.atopia import runner as RN


class _Client:
    """假 LLM：按脚本依次返回回复；记录收到的 user_text。"""
    evaluation_model = "fake"

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.i = 0
        self.seen: list[str] = []

    def chat(self, *, system_prompt, user_text, model=None, **kw):
        self.seen.append(user_text)
        r = self.replies[min(self.i, len(self.replies) - 1)]
        self.i += 1
        return r


def _tool_call(name: str, args: dict | None = None) -> str:
    return json.dumps({"action": "tool", "tool": name, "args": args or {},
                       "why": "test"}, ensure_ascii=False)


def _final(answer: str = "done") -> str:
    return json.dumps({"action": "final", "answer": answer}, ensure_ascii=False)


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    (tmp_path / "kb").mkdir()
    return tmp_path


# ---------------- 安全：L3 / 未登记 ----------------
def test_l3_request_denied(ws: Path):
    r = AG.run_session(_Client([_tool_call("migrate.apply")]), ws, "清理")
    assert r["ok"] is False
    assert "L3" in r["error"]
    assert r["steps"][-1].get("denied") is True


def test_unregistered_tool_denied(ws: Path):
    r = AG.run_session(_Client([_tool_call("rm -rf /")]), ws, "x")
    assert r["ok"] is False and "未登记" in r["error"]


def test_no_journal_written_for_denied_call(ws: Path):
    AG.run_session(_Client([_tool_call("migrate.apply")]), ws, "x")
    assert RN.read_journal(ws) == []


# ---------------- 安全：L2 确认 ----------------
def test_l2_without_confirm_channel_denied(ws: Path):
    r = AG.run_session(_Client([_tool_call("rules.reset")]), ws, "恢复默认")
    assert r["ok"] is False and "确认" in r["error"]


def test_l2_teacher_declines(ws: Path):
    r = AG.run_session(_Client([_tool_call("rules.reset")]), ws, "恢复默认",
                       confirm=lambda n, a: "")
    assert r["ok"] is False and "未确认" in r["error"]


def test_l2_teacher_approves_and_runs(ws: Path):
    r = AG.run_session(_Client([_tool_call("rules.reset"), _final("已恢复")]),
                       ws, "恢复默认", confirm=lambda n, a: "teacher:click")
    assert r["ok"] is True and r["answer"] == "已恢复"
    assert r["steps"][0]["ok"] is True
    rec = RN.read_journal(ws)[-1]
    assert rec["tool"] == "rules.reset" and rec["confirmed_by"] == "teacher:click"


def test_l2_confirm_receives_name_and_args(ws: Path):
    seen: list[tuple] = []

    def confirm(name, args):
        seen.append((name, args))
        return "teacher:ok"

    AG.run_session(_Client([_tool_call("rules.set",
                                       {"path": "global.briefProcessDeduct",
                                        "value": "7"}), _final()]),
                   ws, "改规则", confirm=confirm)
    assert seen[0][0] == "rules.set"
    assert seen[0][1]["path"] == "global.briefProcessDeduct"


# ---------------- L0/L1 直接执行 ----------------
def test_l0_executes_without_confirm(ws: Path):
    r = AG.run_session(_Client([_tool_call("rules.summary", {"kind": "qa"}),
                                _final("好了")]), ws, "看 qa 规则")
    assert r["ok"] is True
    assert r["steps"][0]["ok"] is True
    assert "评阅范式：qa" in r["steps"][0]["out"]


def test_second_turn_sees_tool_result(ws: Path):
    """工具结果必须回喂给模型（否则多轮等于瞎跑）。"""
    c = _Client([_tool_call("rules.summary", {"kind": "qa"}), _final()])
    AG.run_session(c, ws, "看规则")
    assert "评阅范式：qa" in c.seen[-1]


# ---------------- 护栏 ----------------
def test_limit_exceeded_stops_session(ws: Path):
    (ws / "atopia").mkdir()
    (ws / "atopia" / "limits.json").write_text(
        json.dumps({"maxCallsPerSession": 1}), encoding="utf-8")
    sess = L.Session("s", L.read_limits(ws))
    r = AG.run_session(_Client([_tool_call("rules.show"), _tool_call("rules.show")]),
                       ws, "看两次", session=sess)
    assert r["ok"] is False
    assert "上限" in str(r.get("error"))


# ---------------- 健壮性 ----------------
def test_non_json_reply_is_treated_as_answer(ws: Path):
    """模型不按格式回复 → 当最终回答，**不得**猜测意图去执行工具。"""
    r = AG.run_session(_Client(["我觉得应该先看题库统计"]), ws, "x")
    assert r["ok"] is True and "题库统计" in r["answer"]
    assert RN.read_journal(ws) == []


def test_fenced_json_reply_parsed(ws: Path):
    fenced = "```json\n" + _tool_call("rules.show") + "\n```"
    r = AG.run_session(_Client([fenced, _final("ok")]), ws, "x")
    assert r["ok"] is True and r["steps"][0]["tool"] == "rules.show"


def test_max_turns_stops(ws: Path):
    r = AG.run_session(_Client([_tool_call("rules.show")]), ws, "一直看",
                       max_turns=2)
    assert r["ok"] is False and "最大轮数" in r["error"]


def test_model_failure_reported(ws: Path):
    class Bad:
        evaluation_model = "x"

        def chat(self, **kw):
            raise RuntimeError("网络挂了")
    r = AG.run_session(Bad(), ws, "x")
    assert r["ok"] is False and "网络挂了" in r["error"]


# ---------------- 扩展提级同样生效（降级路径不绕过） ----------------
def test_extension_raised_level_also_requires_confirm(ws: Path):
    d = ws / "extensions" / "tools"
    d.mkdir(parents=True)
    (d / "a.json").write_text(json.dumps({"name": "rules.show", "level": "L2"}),
                              encoding="utf-8")
    r = AG.run_session(_Client([_tool_call("rules.show")]), ws, "看规则")
    assert r["ok"] is False and "确认" in r["error"]

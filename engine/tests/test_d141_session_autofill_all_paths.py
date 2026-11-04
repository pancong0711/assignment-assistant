"""D141：**所有** LLM 调用点在 opencode-go 上都必须能带上会话头。

背景（教师实际踩到两次）：
- 第一次：只保存 provider 没分配 stage → 静默回落（D139 已修）；
- 第二次：`kb ai-solve --with-rubric` 报 `failed: 1`，根因是
  **`solve._client()` 构造的 LLMClient 没设 session**，而 `{session}` 占位
  此前"缺就报错" → 所有漏设的调用点直接 400。

本测试锁死：不论哪个调用点、是否显式设 session，
**发出的请求都必须带 `x-opencode-session`**，且同一批里每题各自独立。
"""
from __future__ import annotations

import json
import shutil

import httpx
import pytest

from assist.grading import providers as P
from assist.grading.llm import LLMClient

GO_URL = "https://opencode.ai/inference/go/openai/v1"


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "kb").mkdir()
    P.save_provider(tmp_path, "oc", base_url=GO_URL, api_key="k", model="m",
                    headers={"x-opencode-session": "{session}"})
    P.set_stage(tmp_path, "evaluation", provider="oc", model="m")
    P.set_stage(tmp_path, "transcription", provider="oc", model="m")
    return tmp_path


def _capture(monkeypatch, content="ok"):
    seen: list[dict] = []

    class R:
        status_code = 200
        text = "{}"

        def json(self2):
            return {"choices": [{"message": {"content": content}}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen.append({"url": url, "headers": dict(headers or {})})
        return R()

    monkeypatch.setattr(httpx, "post", fake_post)
    return seen


def test_solve_client_sends_session(ws, monkeypatch):
    """`kb ai-solve` 的客户端（此前漏设 session → failed: 1）。"""
    from assist.grading import solve as S
    seen = _capture(monkeypatch)
    c, _m = S._client(ws)
    c.chat("s", "u")
    assert seen[0]["headers"].get("x-opencode-session")


def test_solve_batch_uses_one_session_per_question(ws, monkeypatch):
    """批量作答：**每题一个 session**（并发下不能共享可变 session_id）。"""
    from assist.grading import solve as S
    payload = json.dumps({"reference_solution": "解",
                          "rubric_points": [{"point": "p", "weight": 1}],
                          "knowledge": [], "diagram": {"required": False,
                                                       "description": ""}})
    seen = _capture(monkeypatch, content=payload)
    rep = S.solve_targets(ws, [
        {"id": "q1", "content": "c", "kb": "problems", "chap": "chap04"},
        {"id": "q2", "content": "c", "kb": "problems", "chap": "chap04"},
    ], apply=False, dry_run=False, with_rubric=True, concurrency=2)
    sids = [h["headers"].get("x-opencode-session") for h in seen]
    assert all(sids), "有请求没带会话头"
    assert len(set(sids)) == 2, f"应每题一个 session，实际 {sids}"
    assert rep["failed"] == 0


def test_rubric_client_sends_session(ws, monkeypatch):
    """`rules generate` 用的 `_rubric_client`。"""
    from assist.cli import _rubric_client
    seen = _capture(monkeypatch)
    _rubric_client(ws).chat("s", "u")
    assert seen[0]["headers"].get("x-opencode-session")


def test_materials_suggest_client_sends_session(ws, monkeypatch):
    from assist.files import materials as M
    d = M.ensure_chap(ws, "chap04")
    (d / "_source" / "plan.md").write_text("动量守恒", encoding="utf-8")
    M.extract_chap(ws, "chap04")
    seen = _capture(monkeypatch, content=json.dumps({
        "knowledge": [{"term": "动量守恒", "importance": "core", "topic": "动量定理"}],
        "logic": [], "notes": ""}))
    M.suggest_knowledge(LLMClient(ws=ws), ws, "chap04")
    assert seen[0]["headers"].get("x-opencode-session")


def test_plain_provider_gets_no_session_header(ws, monkeypatch):
    """**没有**配 headers 的 provider 不得凭空多出 session 头（不能误伤）。"""
    ws2 = ws.parent / "ws2"
    (ws2 / "kb").mkdir(parents=True)
    P.save_provider(ws2, "ali", base_url="https://dashscope.example/v1",
                    api_key="k", model="qwen")
    P.set_stage(ws2, "evaluation", provider="ali", model="qwen")
    seen = _capture(monkeypatch)
    LLMClient(ws=ws2).chat("s", "u")
    assert "x-opencode-session" not in {k.lower() for k in seen[0]["headers"]}

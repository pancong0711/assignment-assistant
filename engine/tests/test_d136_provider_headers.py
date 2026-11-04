"""D136：provider 级自定义请求头（opencode-go 的 `x-opencode-session`）+ 会话粒度。

背景（docs/86 §1）：opencode 的 `/go` 路由要求每个**对话**带稳定的
`x-opencode-session`，并用**自有 user agent** 标识客户端。

安全红线：
1. 只允许 `x-*` 与 `user-agent`；**禁止** `Authorization`/`Host`/`Cookie` 等
   （否则改配置即可劫持鉴权/路由）；
2. **其它 provider 不配 headers 时，请求头与改动前一致**（不能被这次改动波及）；
3. 配了 `{session}` 占位但没传 session → 报可读错误，**不发请求**。
"""
from __future__ import annotations

import httpx
import pytest

from assist.grading import providers as P
from assist.grading.llm import LLMClient, LLMConfigError, _error_hint


# ---------------- 白名单 ----------------
def test_allows_x_custom_and_user_agent():
    h, errs = P.validate_headers({"x-opencode-session": "{session}",
                                  "User-Agent": "assignment-assistant/0.1.0"})
    assert errs == []
    assert h["x-opencode-session"] == "{session}"
    assert h["User-Agent"] == "assignment-assistant/0.1.0"


@pytest.mark.parametrize("bad", ["Authorization", "host", "Cookie", "Content-Type",
                                 "x-api-key", "Proxy-Authorization"])
def test_rejects_sensitive_headers(bad):
    h, errs = P.validate_headers({bad: "x"})
    assert h == {}
    assert errs and "禁止" in errs[0]


def test_rejects_non_x_headers():
    h, errs = P.validate_headers({"X-Custom": "1", "referer": "x"})
    assert "X-Custom" in h            # x-* 允许（大小写不敏感语义，原样保留）
    assert errs and "referer" in errs[0]


def test_rejects_control_chars_and_long_values():
    _, e1 = P.validate_headers({"x-a": "bad\x01value"})
    assert e1
    _, e2 = P.validate_headers({"x-a": "y" * 600})
    assert e2


# ---------------- 默认 UA / session 注入 ----------------
def test_default_user_agent_is_not_httpx():
    c = LLMClient(settings={"base_url": "https://x/v1", "api_key": "k", "model": "m"})
    h = c._headers_for("k", {})
    assert h["User-Agent"].startswith("assignment-assistant/")
    assert "httpx" not in h["User-Agent"].lower()


def test_session_placeholder_substituted():
    c = LLMClient(settings={"base_url": "https://x/v1", "api_key": "k", "model": "m",
                            "headers": {"x-opencode-session": "{session}"}})
    c.set_session_id("abc123")
    h = c._headers_for("k", {})
    assert h["x-opencode-session"] == "abc123"


def test_missing_session_raises_config_error():
    c = LLMClient(settings={"base_url": "https://x/v1", "api_key": "k", "model": "m",
                            "headers": {"x-opencode-session": "{session}"}})
    with pytest.raises(LLMConfigError) as ei:
        c._headers_for("k", {})
    assert "x-opencode-session" in str(ei.value)


def test_plain_provider_headers_unchanged():
    """**关键回归**：不配 headers 的 provider，请求头必须与改动前逐字节一致。

    只多一个 User-Agent（官方要求客户端标识自己），其余完全相同。
    """
    c = LLMClient(settings={"base_url": "https://x/v1", "api_key": "k", "model": "m"})
    h = c._headers_for("k", {})
    assert h["Authorization"] == "Bearer k"
    assert h["Content-Type"] == "application/json"
    assert set(h) == {"Authorization", "Content-Type", "User-Agent"}
    assert c.session_id == ""


# ---------------- 真实 HTTP 请求（不打外网） ----------------
def _capture(monkeypatch):
    seen = {}

    class R:
        status_code = 200
        text = "{}"

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["url"] = url
        seen["headers"] = dict(headers or {})
        seen["payload"] = json
        return R()

    monkeypatch.setattr(httpx, "post", fake_post)
    return seen


def test_request_sends_session_header(monkeypatch):
    seen = _capture(monkeypatch)
    c = LLMClient(settings={"base_url": "https://opencode.example/go/openai/v1",
                            "api_key": "k", "model": "m",
                            "headers": {"x-opencode-session": "{session}"}})
    c.set_session_id("sess-1")
    c.chat("sys", "hi")
    assert seen["headers"]["x-opencode-session"] == "sess-1"
    assert seen["headers"]["Authorization"] == "Bearer k"


def test_request_omits_session_when_not_configured(monkeypatch):
    seen = _capture(monkeypatch)
    c = LLMClient(settings={"base_url": "https://dashscope.example/v1",
                            "api_key": "k", "model": "m"})
    c.chat("sys", "hi")
    assert "x-opencode-session" not in seen["headers"]


def test_missing_session_does_not_send_request(monkeypatch):
    called = {"n": 0}

    def fake_post(*a, **k):
        called["n"] += 1
        raise AssertionError("不该发请求")

    monkeypatch.setattr(httpx, "post", fake_post)
    c = LLMClient(settings={"base_url": "https://x/v1", "api_key": "k", "model": "m",
                            "headers": {"x-opencode-session": "{session}"}})
    with pytest.raises(LLMConfigError):
        c.chat("sys", "hi")
    assert called["n"] == 0


# ---------------- provider=- 修复 / 错误提示 ----------------
def test_error_message_has_real_provider(monkeypatch):
    class R:
        status_code = 400
        text = '{"error":{"message":"bad"}}'

        def json(self):
            return {}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: R())
    c = LLMClient(settings={"base_url": "https://x/v1", "api_key": "k", "model": "m",
                            "provider": "opencode-go"})
    with pytest.raises(Exception) as ei:
        c.chat("sys", "hi")
    assert "provider=opencode-go" in str(ei.value)


def test_error_hint_for_missing_session():
    body = ('{"type":"error","error":{"type":"MissingSessionID",'
            '"message":"Request is missing x-opencode-session"}}')
    hint = _error_hint(body)
    assert "x-opencode-session" in hint


def test_error_hint_for_unavailable_model():
    hint = _error_hint('{"error":{"message":"Model is unavailable."}}')
    assert "模型" in hint


def test_error_hint_empty_for_unknown():
    assert _error_hint('{"error":{"type":"weird"}}') == ""


# ---------------- save_provider 写入口 ----------------
def test_save_provider_rejects_bad_headers(tmp_path):
    (tmp_path / "kb").mkdir()
    rep = P.save_provider(tmp_path, "oc", base_url="https://x/v1",
                          headers={"Authorization": "Bearer evil"})
    assert rep["ok"] is False
    assert "Authorization" in rep["error"]


def test_save_provider_persists_allowed_headers(tmp_path):
    (tmp_path / "kb").mkdir()
    rep = P.save_provider(tmp_path, "oc", base_url="https://x/v1",
                          api_key="k", headers={"x-opencode-session": "{session}"},
                          user_agent="assignment-assistant/test")
    assert rep["ok"] is True
    got = P.get_provider(tmp_path, "oc")
    assert got["headers"]["x-opencode-session"] == "{session}"
    assert got["user_agent"] == "assignment-assistant/test"


# ---------------- 会话粒度（docs/86 §2） ----------------
def test_playground_session_is_stable_within_client(tmp_path):
    """一次 playground 会话 = 一个对话 → 同一 client 的多轮用**同一个** session。"""
    from assist.playground import ask as A
    (tmp_path / "kb").mkdir()
    P.save_provider(tmp_path, "oc", base_url="https://x/v1", api_key="k",
                    model="m", headers={"x-opencode-session": "{session}"})
    c1, _ = A._client(tmp_path, "oc", "m")
    c2, _ = A._client(tmp_path, "oc", "m")
    assert c1.session_id and c1.session_id.startswith("playground-")
    assert c1.session_id != c2.session_id      # 不同会话 → 不同 id
    # 同一 client 反复请求时 id 不变（prompt 缓存可命中）
    sid = c1.session_id
    h1 = c1._headers_for("k", {})
    h2 = c1._headers_for("k", {})
    assert h1["x-opencode-session"] == h2["x-opencode-session"] == sid


def test_atopia_session_stable_across_turns(tmp_path):
    (tmp_path / "kb").mkdir()

    class FakeClient:
        """模拟多轮：第一轮请求工具，第二轮给最终回答。"""

        def __init__(self):
            self.session_id = ""
            self.seen: list[str] = []
            self.n = 0

        def set_session_id(self, sid):
            self.session_id = str(sid or "")

        def chat(self, **kw):
            self.seen.append(self.session_id)
            self.n += 1
            if self.n == 1:
                return '{"action":"tool","tool":"kb.stats","args":{}}'
            return '{"action":"final","answer":"done"}'

    from assist.atopia import agent as AG
    c = FakeClient()
    rep = AG.run_session(c, tmp_path, "统计", max_turns=4)
    assert rep["ok"] is True
    assert c.session_id.startswith("atopia-")
    assert len(set(c.seen)) == 1            # 多轮复用同一个 id
    assert c.seen[0] == c.session_id


def test_atopia_keeps_caller_session_if_preset(tmp_path):
    (tmp_path / "kb").mkdir()

    class FakeClient:
        def __init__(self):
            self.session_id = "caller-fixed"

        def set_session_id(self, sid):
            self.session_id = str(sid or "")

        def chat(self, **kw):
            return '{"action":"final","answer":"ok"}'

    from assist.atopia import agent as AG
    c = FakeClient()
    AG.run_session(c, tmp_path, "x", max_turns=2)
    assert c.session_id == "caller-fixed"


def test_batch_grading_session_is_per_assignment(tmp_path):
    """批量批阅：**每份作业一个** session（不是全局一个，也不是每次请求换）。"""
    from assist.grading.flow import _session_per_student

    class C:
        session_id = ""

        def set_session_id(self, sid):
            self.session_id = str(sid)

    d = tmp_path / "transcripts"
    d.mkdir()
    (d / "张三.json").write_text("{}", encoding="utf-8")
    c = C()
    _session_per_student(c, {"transcripts_dir": d})
    assert c.session_id == "grade-张三"      # 单份 → 用学生名

    (d / "李四.json").write_text("{}", encoding="utf-8")
    c2 = C()
    _session_per_student(c2, {"transcripts_dir": d})
    assert c2.session_id == "grade-batch2"   # 多份 → 批次标识


# ---------------- CLI `llm provider --header` ----------------
def test_cli_sets_and_lists_headers(tmp_path):
    from click.testing import CliRunner

    from assist.cli import cli
    r = CliRunner().invoke(cli, [
        "llm", "provider", "--action", "set", "--name", "oc",
        "--base-url", "https://opencode.ai/inference/go/openai/v1",
        "--header", "x-opencode-session={session}",
        "--user-agent", "assignment-assistant/test", "-w", str(tmp_path)])
    assert r.exit_code == 0, r.output
    got = P.get_provider(tmp_path, "oc")
    assert got["headers"]["x-opencode-session"] == "{session}"
    assert got["user_agent"] == "assignment-assistant/test"


def test_cli_rejects_header_without_equals(tmp_path):
    from click.testing import CliRunner

    from assist.cli import cli
    r = CliRunner().invoke(cli, [
        "llm", "provider", "--action", "set", "--name", "oc",
        "--header", "x-broken", "-w", str(tmp_path)])
    assert r.exit_code != 0
    assert "name=value" in r.output


def test_cli_rejects_forbidden_header(tmp_path):
    from click.testing import CliRunner

    from assist.cli import cli
    r = CliRunner().invoke(cli, [
        "llm", "provider", "--action", "set", "--name", "oc",
        "--header", "Authorization=Bearer evil", "-w", str(tmp_path)])
    assert r.exit_code == 2
    assert "Authorization" in r.output

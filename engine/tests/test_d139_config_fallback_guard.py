"""D139：修复「配了 provider 却没分配 stage → 静默回落到旧单层配置」。

现象（教师实际遇到）：以为配好了 opencode-go，实际请求发往了旧单层 base_url，
且 provider 上的 `headers`（x-opencode-session）**完全被绕过**，
报错里的端点与配置对不上，极难排查。

修复口径：**配置类错误必须报出来**，不得静默回落。
"""
from __future__ import annotations

import pytest

from assist.grading import providers as P
from assist.grading.llm import LLMClient, LLMConfigError


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "kb").mkdir()
    return tmp_path


def _add(ws, name="opencode-go", **kw):
    return P.save_provider(ws, name,
                           base_url="https://opencode.ai/inference/go/openai/v1",
                           api_key="k", model="deepseek-chat",
                           headers={"x-opencode-session": "{session}"}, **kw)


def test_provider_without_stage_raises(ws):
    """有 provider 但没分配 stage → **明确报错**（不再静默回落）。"""
    _add(ws)
    with pytest.raises(LLMConfigError) as ei:
        LLMClient(ws=ws)
    msg = str(ei.value)
    assert "还没有为任何一段分配 provider" in msg
    assert "assist llm provider --action stage" in msg


def test_provider_with_stage_keeps_headers(ws):
    _add(ws)
    P.set_stage(ws, "evaluation", provider="opencode-go", model="deepseek-chat")
    c = LLMClient(ws=ws)
    c.set_session_id("s1")
    ep = c._step_endpoint("evaluation")
    h = c._headers_for("k", ep)
    assert ep["base_url"].endswith("/go/openai/v1")
    assert h["x-opencode-session"] == "s1"


def test_stage_with_name_but_empty_provider_counts_as_unset(ws):
    """stage 存在但 provider 名为空 → 同样视为"未分配"。"""
    _add(ws)
    P.set_stage(ws, "evaluation", provider="", model="")
    with pytest.raises(LLMConfigError):
        LLMClient(ws=ws)


def test_no_provider_still_falls_back_to_flat_config(ws):
    """**没有**任何 provider 时，旧单层配置路径必须照常可用（不误伤）。"""
    import json
    (ws / "settings.local.json").write_text(json.dumps({
        "llm": {"base_url": "https://legacy.example/v1", "api_key": "k2", "model": "m2"}
    }), encoding="utf-8")
    c = LLMClient(ws=ws)
    assert c.base_url == "https://legacy.example/v1"
    assert c.api_key == "k2"

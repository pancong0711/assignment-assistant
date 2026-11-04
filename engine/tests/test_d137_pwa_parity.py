"""D137：PWA ↔ CLI 对齐的引擎侧接口。

覆盖三块（docs/87 §1）：
- A1 provider `headers` / `user_agent` 可经 HTTP 写入（白名单仍由引擎强校验）；
- B1 Atopia 护栏可经 HTTP 修改（受 HARD_CAPS 硬顶约束）；
- A2 资料抽取 / AI 建议预览 / 确认生效（**confirm 必须显式传入**）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from assist.grading import providers as P
from assist.atopia import limits as L
from assist.files import materials as M


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "kb").mkdir()
    return tmp_path


# ---------------- A1 provider 请求头（HTTP 等价路径） ----------------
def test_provider_headers_saved_via_save_provider(ws):
    rep = P.save_provider(ws, "oc", base_url="https://opencode.ai/inference/go/openai/v1",
                          api_key="k", headers={"x-opencode-session": "{session}"},
                          user_agent="assignment-assistant/test")
    assert rep["ok"] is True
    got = P.get_provider(ws, "oc")
    assert got["headers"]["x-opencode-session"] == "{session}"
    assert got["user_agent"] == "assignment-assistant/test"


def test_provider_headers_reject_authorization_via_api(ws):
    rep = P.save_provider(ws, "oc", base_url="https://x/v1",
                          headers={"Authorization": "Bearer evil"})
    assert rep["ok"] is False
    assert "Authorization" in rep["error"]
    # 不得写入
    assert not (P.get_provider(ws, "oc") or {}).get("headers")


def test_provider_headers_reload_survives(ws):
    """PWA 重载后仍能看到已配置的请求头（不能只在内存）。"""
    P.save_provider(ws, "oc", base_url="https://x/v1",
                    headers={"x-opencode-session": "{session}"})
    listed = {p["name"]: p for p in P.list_providers(ws)}
    assert listed["oc"]["headers"]["x-opencode-session"] == "{session}"


# ---------------- B1 Atopia 护栏 ----------------
def test_limits_writable(ws):
    rep = L.write_limits(ws, {"maxCallsPerSession": 60})
    assert rep["ok"] is True
    assert L.read_limits(ws)["maxCallsPerSession"] == 60


def test_limits_reject_over_hard_cap(ws):
    cap = L.HARD_CAPS["maxCallsPerSession"]
    rep = L.write_limits(ws, {"maxCallsPerSession": cap + 1})
    assert rep["ok"] is False
    assert "硬顶" in rep["error"]
    assert L.read_limits(ws)["maxCallsPerSession"] == L.DEFAULTS["maxCallsPerSession"]


def test_limits_reject_unknown_key(ws):
    rep = L.write_limits(ws, {"nope": 1})
    assert rep["ok"] is False
    assert "未知项" in rep["error"]


# ---------------- A2 资料三动作 ----------------
def _write_source(ws, chap, text="第4章 动量守恒：完全弹性碰撞"):
    d = M.ensure_chap(ws, chap)
    (d / "_source" / "plan.md").write_text(text, encoding="utf-8")
    return d


def test_extract_chap(ws):
    _write_source(ws, "chap04")
    rep = M.extract_chap(ws, "chap04")
    assert rep["ok"] is True
    assert (M.chap_dir(ws, "chap04") / M.INDEX).is_file()


def test_confirm_requires_ai_suggest_file(ws):
    M.ensure_chap(ws, "chap04")
    with pytest.raises(M.MaterialsError):
        M.confirm_knowledge(ws, "chap04")


def test_confirm_creates_md_and_does_not_overwrite(ws):
    d = _write_source(ws, "chap04")
    (d / M.KNOW_AI).write_text(json.dumps({
        "chap": "chap04",
        "knowledge": [{"term": "动量守恒", "aliases": [], "importance": "core",
                       "evidence": "第1页"}],
        "logic": [], "generatedAt": "2026-10-31"}, ensure_ascii=False), encoding="utf-8")
    rep = M.confirm_knowledge(ws, "chap04")
    assert rep.get("ok") is not False
    md = (d / M.KNOW_MD).read_text(encoding="utf-8")
    assert "动量守恒" in md
    # 第二次确认：默认**不覆盖**已有 .md（返回 ok=False，不是抛异常）
    rep2 = M.confirm_knowledge(ws, "chap04")
    assert rep2["ok"] is False
    assert "已存在" in rep2["error"]
    assert (d / M.KNOW_MD).read_text(encoding="utf-8") == md     # 内容未被改动


def test_confirm_force_overwrites(ws):
    d = _write_source(ws, "chap04")
    (d / M.KNOW_AI).write_text(json.dumps({
        "chap": "chap04",
        "knowledge": [{"term": "动量守恒", "aliases": [], "importance": "core"}],
        "logic": []}, ensure_ascii=False), encoding="utf-8")
    M.confirm_knowledge(ws, "chap04")
    (d / M.KNOW_AI).write_text(json.dumps({
        "chap": "chap04",
        "knowledge": [{"term": "角动量守恒", "aliases": [], "importance": "core"}],
        "logic": []}, ensure_ascii=False), encoding="utf-8")
    rep = M.confirm_knowledge(ws, "chap04", force=True)
    md = (d / M.KNOW_MD).read_text(encoding="utf-8")
    assert "角动量守恒" in md
    assert rep.get("ok") is not False


def test_render_knowledge_md_for_preview(ws):
    """确认弹窗用的全文预览与最终写入**同一渲染函数**（不会"看到的≠生效的"）。"""
    data = {"chap": "chap04",
            "knowledge": [{"term": "动量守恒", "aliases": ["动量守恒定律"],
                           "importance": "core", "evidence": "第1页"}],
            "logic": []}
    preview = M.render_knowledge_md(data)
    assert "动量守恒" in preview and "动量守恒定律" in preview

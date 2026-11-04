"""D164：Atopia 工作区（上传/解析）+ 复制到课堂资料。

三层目录隔离（关键安全边界）：
    materials/<特征名>/_source/     教师原件（AI 只读，D131）
    atopia/work/<特征名>/_upload/   教师交给 Atopia 的临时文件
    atopia/work/<特征名>/_parsed/   Atopia 解析产物
"""
from __future__ import annotations

import base64
import json

import pytest

from assist.atopia import work as W
from assist.files import materials as M


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "kb").mkdir()
    return tmp_path


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def test_upload_goes_to_atopia_work_not_materials(ws):
    """**核心**：上传落 `atopia/work/`，不碰 `materials/`。"""
    r = W.save_uploads(ws, "26C1", [{"name": "plan.md", "data_b64": _b64("动量守恒")}])
    assert r["saved"]
    assert (ws / "atopia" / "work" / "26C1" / "_upload" / "plan.md").is_file()
    assert not (ws / "materials" / "26C1" / "_source" / "plan.md").exists()


def test_upload_does_not_overwrite(ws):
    W.save_uploads(ws, "26C1", [{"name": "a.md", "data_b64": _b64("v1")}])
    r = W.save_uploads(ws, "26C1", [{"name": "a.md", "data_b64": _b64("v2")}])
    up = ws / "atopia" / "work" / "26C1" / "_upload"
    assert (up / "a.md").read_text(encoding="utf-8") == "v1"
    assert (up / "a-2.md").read_text(encoding="utf-8") == "v2"
    assert r["saved"][0]["name"] == "a-2.md"


def test_upload_rejects_bad_ext(ws):
    r = W.save_uploads(ws, "26C1", [{"name": "x.exe", "data_b64": _b64("MZ")}])
    assert r["saved"] == [] and r["skipped"]


def test_illegal_feature_rejected(ws):
    with pytest.raises(W.WorkError):
        W.feature_dir(ws, "../etc")


def test_read_upload_text(ws):
    W.save_uploads(ws, "26C1", [{"name": "p.md", "data_b64": _b64("第4章 动量守恒")}])
    t = W.read_upload_text(ws, "26C1")
    assert "动量守恒" in t["text"]
    assert t["files"] == ["p.md"]


def test_save_and_read_parsed(ws):
    data = {"knowledge": [{"term": "动量守恒", "topic": "动量定理"}], "logic": []}
    r = W.save_parsed(ws, "26C1", data)
    assert r["ok"]
    back = W.read_parsed(ws, "26C1", "26C1.json")
    assert back["knowledge"][0]["term"] == "动量守恒"


def test_list_features(ws):
    W.ensure_feature(ws, "26C1")
    W.ensure_feature(ws, "26C2")
    assert W.list_features(ws) == ["26C1", "26C2"]


def test_copy_to_materials_is_separate_step(ws):
    """复制到课堂资料后才写 materials（与 atopia 工作区物理隔离）。"""
    data = {"knowledge": [{"term": "角动量守恒", "topic": "角动量",
                           "importance": "core", "aliases": []}], "logic": []}
    W.save_parsed(ws, "26C1", data)
    # 复制前 materials 里没有
    assert not (ws / "materials" / "26C1" / M.KNOW_MD).exists()
    d = M.ensure_chap(ws, "26C1")
    md = M.render_knowledge_md({**data, "chap": "26C1"})
    (d / M.KNOW_MD).write_text(md, encoding="utf-8")
    assert (d / M.KNOW_MD).is_file()
    assert "角动量守恒" in M.read_knowledge_md(ws, "26C1")


def test_copied_manifest_feeds_summary(ws):
    """复制后的清单能被 summary 批阅读到（D155 关联链）。"""
    from assist.grading import evaluate as EV
    data = {"knowledge": [{"term": "动量守恒", "topic": "动量定理",
                           "importance": "core", "aliases": []}], "logic": []}
    d = M.ensure_chap(ws, "26C1")
    (d / M.KNOW_MD).write_text(M.render_knowledge_md({**data, "chap": "26C1"}),
                               encoding="utf-8")
    item = {"序号": "1", "kind": "summary", "chap": "26C1", "feature": "26C1",
            "content": "总结", "tag": "summary"}
    p = EV.build_user_prompt([item], "作答", "张三", ws=ws)
    assert "动量守恒" in p

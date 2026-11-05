"""D166：AI 再整理知识点（归一 / 合并 / 拆分），**必须教师逐题确认**。

口径（docs/109 §2.3、§5）：
1. `pinned_by=human` 默认跳过；
2. 词表术语优先，词表外保留并标记；
3. 不自动改答案文本里的【知识点】行。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from assist.grading import related_tidy as RT
from assist.grading import rubric as RB


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    from assist.files import kb_io
    (tmp_path / "kb").mkdir(parents=True, exist_ok=True)
    kb_io.write_chapters_preserving(tmp_path / "kb" / "qa.xlsx", {"chap01": [
        {"id": "c1", "content": "库仑定律题", "related": "库仑定律律,库仑定律"},
        {"id": "c2", "content": "场强题", "related": ""},
    ]})
    return tmp_path


class _FakeClient:
    def __init__(self, reply: dict):
        self.reply = reply

    def chat(self, **kw):
        return json.dumps(self.reply, ensure_ascii=False)


def test_diff_computed_before_and_after():
    d = RT.build_diff(["库仑定律律", "库仑定律"], ["库仑定律"])
    assert d["added"] == []
    assert set(d["removed"]) == {"库仑定律律"}
    assert d["changed"] is True


def test_no_change_reports_unchanged():
    d = RT.build_diff(["库仑定律"], ["库仑定律"])
    assert d["changed"] is False


def test_tidy_produces_suggestions_without_writing(ws):
    """关键：整理阶段**只产出建议**，不落盘。"""
    client = _FakeClient({"items": [
        {"qid": "chap01-c1", "terms": ["库仑定律"], "merged_from": ["库仑定律律"],
         "dropped": [], "note": "合并同义写法"}]})
    rep = RT.tidy_related(client, ws, kind="qa", chap="chap01")
    assert rep["ok"] is True
    assert rep["returned"] == 1
    item = rep["items"][0]
    assert item["diff"]["after"] == ["库仑定律"]
    assert "库仑定律律" in item["diff"]["removed"]
    # 没有写盘：xlsx 里还是旧值
    from assist.files import kb_io
    row = kb_io.read_xlsx(ws / "kb" / "qa.xlsx", ws / "kb")["chap01"][0]
    assert "库仑定律律" in row["related"]


def test_tidy_skips_human_pinned(ws):
    RB.set_meta(ws, "qa", "chap01", "chap01-c1", {"pinned_by": "human"})
    client = _FakeClient({"items": []})
    rep = RT.tidy_related(client, ws, kind="qa", chap="chap01")
    assert any("教师已锁定" in s["reason"] for s in rep["skipped"])


def test_tidy_force_includes_pinned(ws):
    RB.set_meta(ws, "qa", "chap01", "chap01-c1", {"pinned_by": "human"})
    client = _FakeClient({"items": [
        {"qid": "chap01-c1", "terms": ["库仑定律"], "note": "强制"}]})
    rep = RT.tidy_related(client, ws, kind="qa", chap="chap01", force=True)
    assert rep["returned"] == 1


def test_apply_tidy_writes_version_and_keeps_history(ws):
    rep = RT.apply_tidy(ws, [{"qid": "chap01-c1", "kb": "qa", "chap": "chap01",
                             "terms": ["库仑定律"], "note": "AI 再整理"}])
    assert rep["ok"] and rep["written"] == 1
    got = RB.get_related(ws, kb="qa", chap="chap01", qid="chap01-c1")
    assert got["terms"] == ["库仑定律"]
    assert len(got["versions"]) == 1
    assert got["versions"][0]["note"] == "AI 再整理"


def test_prompt_mentions_merge_and_vocab():
    p = RT.build_tidy_prompt([{"qid": "c1", "content": "题", "terms": ["A"]}],
                             ["库仑定律"])
    assert "同义合并" in p
    assert "受控词表" in p
    assert "库仑定律" in p


def test_collect_targets_filters_by_kind_and_chap(ws):
    from assist.files import kb_io
    kb_data = kb_io.read_kb(ws / "kb")
    got = RT.collect_targets(ws, kb_data, kind="qa", chap="chap01")
    assert len(got["todo"]) == 2
    got2 = RT.collect_targets(ws, kb_data, kind="problems", chap="chap01")
    assert got2["todo"] == []

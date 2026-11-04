"""D138：知识点两层分类（章 → 主题 → 术语），**不做 parent/child**。

口径（docs/88）：
- `chapter` 已有（题库章），新增 `topic`（章内的"块"）；
- 无 topic 时**退回按章/扁平**，不报错、不丢术语；
- 旧格式 md（无 `###` 分节）必须仍能正确解析（向后兼容）。
"""
from __future__ import annotations

import json

import pytest

from assist.files import materials as M
from assist.grading import teacher_report as TR
from assist.grading import trend as TD
from assist.grading import vocab as V


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "kb").mkdir()
    return tmp_path


# ---------------- 词表：topic 读写 ----------------
def test_add_term_with_topic(ws):
    V.add_term(ws, "完全弹性碰撞", topic="碰撞问题", chapter="chap04")
    t = {x["term"]: x for x in V.load_vocab(ws)["terms"]}["完全弹性碰撞"]
    assert t["topic"] == "碰撞问题"
    assert t["chapter"] == "chap04"


def test_topic_preserved_when_not_passed(ws):
    """不传 topic 不能清空已有归类（与 aliases 同口径）。"""
    V.add_term(ws, "动量守恒", topic="动量定理")
    V.add_term(ws, "动量守恒", aliases=["动量守恒定律"])
    t = {x["term"]: x for x in V.load_vocab(ws)["terms"]}["动量守恒"]
    assert t["topic"] == "动量定理"
    assert t["aliases"] == ["动量守恒定律"]


def test_topic_can_be_cleared_explicitly(ws):
    V.add_term(ws, "动量守恒", topic="动量定理")
    V.add_term(ws, "动量守恒", topic="")
    t = {x["term"]: x for x in V.load_vocab(ws)["terms"]}["动量守恒"]
    assert t["topic"] == ""


def test_old_vocab_without_topic_loads(ws):
    """旧词表（无 topic 字段）必须照常可用。"""
    (ws / "knowledge-terms.json").write_text(json.dumps({
        "version": 1,
        "terms": [{"term": "动量守恒", "source": "human", "aliases": [],
                   "chapter": "chap04", "count": 2}]}), encoding="utf-8")
    v = V.load_vocab(ws)
    assert v["terms"][0]["term"] == "动量守恒"


# ---------------- 清单渲染：按主题分节 ----------------
def _data(**kw):
    base = {"chap": "chap04", "knowledge": [
        {"term": "动量守恒", "aliases": [], "importance": "core",
         "topic": "动量定理", "evidence": "第1页"},
        {"term": "完全弹性碰撞", "aliases": ["弹性碰撞"], "importance": "core",
         "topic": "碰撞问题", "evidence": "第2页"},
        {"term": "冲量", "aliases": [], "importance": "supporting", "topic": "动量定理"},
        {"term": "未归类", "aliases": [], "importance": "supporting"}], "logic": []}
    base.update(kw)
    return base


def test_render_groups_by_topic():
    md = M.render_knowledge_md(_data())
    assert "### 动量定理" in md and "### 碰撞问题" in md
    assert "### 其他" in md          # 无 topic 归入「其他」
    assert "未归类" in md             # 且**不丢**


def test_render_without_any_topic_keeps_old_format():
    d = _data(knowledge=[{"term": "动量守恒", "aliases": [], "importance": "core",
                          "evidence": "第1页"}])
    md = M.render_knowledge_md(d)
    assert "###" not in md            # 旧格式（无小节）
    assert "动量守恒" in md


# ---------------- 解析：新旧格式都行 ----------------
def test_knowledge_terms_new_format(ws):
    d = M.ensure_chap(ws, "chap04")
    (d / M.KNOW_MD).write_text(
        "# t\n## 核心知识点（必考）\n### 动量定理\n- **动量守恒** —— _第1页_\n"
        "## 逻辑关系\n- 动量定理 → 动量守恒\n", encoding="utf-8")
    terms = M.knowledge_terms(ws, "chap04")
    assert terms == ["动量守恒"]      # `###` 标题与 `A → B` 都不算术语


def test_knowledge_terms_old_format(ws):
    d = M.ensure_chap(ws, "chap04")
    (d / M.KNOW_MD).write_text(
        "# t\n## 核心知识点\n- **动量守恒** —— _第1页_\n- 完全弹性碰撞\n"
        "## 逻辑关系\n- A → B\n", encoding="utf-8")
    assert M.knowledge_terms(ws, "chap04") == ["动量守恒", "完全弹性碰撞"]


def test_knowledge_topics_new_format(ws):
    d = M.ensure_chap(ws, "chap04")
    (d / M.KNOW_MD).write_text(
        "# t\n## 核心知识点\n### 动量定理\n- 动量守恒\n### 碰撞问题\n- 完全弹性碰撞\n",
        encoding="utf-8")
    assert M.knowledge_topics(ws, "chap04") == {
        "动量定理": ["动量守恒"], "碰撞问题": ["完全弹性碰撞"]}


def test_knowledge_topics_old_format_falls_back_to_other(ws):
    d = M.ensure_chap(ws, "chap04")
    (d / M.KNOW_MD).write_text("# t\n## 核心知识点\n- 动量守恒\n", encoding="utf-8")
    assert M.knowledge_topics(ws, "chap04") == {"其他": ["动量守恒"]}


# ---------------- 教师报告按主题分组 ----------------
def _rec(student, terms):
    return {"student": student, "total_score": 80,
            "analysis": {"questions": [{"id": 1, "errors": [
                {"knowledge": [t], "confidence": "high"} for t in terms]}]}}


def test_teacher_report_groups_by_topic():
    recs = [_rec("张三", ["动量守恒", "完全弹性碰撞"]), _rec("李四", ["动量守恒"])]
    st = TR.analyze(recs, topics={"动量守恒": "动量定理", "完全弹性碰撞": "碰撞问题"})
    assert [g["topic"] for g in st["byTopic"]] == ["动量定理", "碰撞问题"]
    assert st["byTopic"][0]["items"][0]["term"] == "动量守恒"


def test_teacher_report_flat_when_no_topics():
    recs = [_rec("张三", ["动量守恒"])]
    st = TR.analyze(recs)                      # 不传 topics = 旧行为
    assert st["byTopic"] == []
    assert st["knowledge_errors"][0]["topic"] == ""


def test_teacher_report_md_grouped():
    recs = [_rec("张三", ["动量守恒", "完全弹性碰撞"])]
    st = TR.analyze(recs, topics={"动量守恒": "动量定理", "完全弹性碰撞": "碰撞问题"})
    md = TR.render_md(st)
    assert "📚 动量定理" in md and "📚 碰撞问题" in md


def test_load_topic_map_from_materials(ws):
    d = M.ensure_chap(ws, "chap04")
    (d / M.KNOW_MD).write_text(
        "# t\n## 核心知识点\n### 动量定理\n- 动量守恒\n### 其他\n- 未归类\n",
        encoding="utf-8")
    mp = TR.load_topic_map(ws)
    assert mp == {"动量守恒": "动量定理"}      # 「其他」不入映射


def test_load_topic_map_missing_returns_empty(ws):
    assert TR.load_topic_map(ws) == {}


# ---------------- 趋势报告按主题分组 ----------------
def _put(root, pack, student, terms, ts):
    d = root / "classes" / "化工25" / "grading" / pack / "evaluations"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{student}.json").write_text(json.dumps({
        "student": student, "timestamp": ts,
        "analysis": {"questions": [{"id": 1, "errors": [
            {"knowledge": [t], "confidence": "high"} for t in terms]}]}},
        ensure_ascii=False), encoding="utf-8")


def test_trend_groups_by_topic(ws):
    """两个主题才分组渲染（单组时按主题分级没意义，直接用扁平列表）。"""
    _put(ws, "p1", "张三", ["动量守恒", "完全弹性碰撞"], "2026-10-01")
    _put(ws, "p2", "张三", ["动量守恒", "完全弹性碰撞"], "2026-10-10")
    st = TD.analyze(ws, "classes/化工25",
                    topics={"动量守恒": "动量定理", "完全弹性碰撞": "碰撞问题"})
    assert [g["topic"] for g in st["byTopic"]] == ["动量定理", "碰撞问题"]
    md = TD.render_md(st)
    assert "📚 动量定理" in md and "📚 碰撞问题" in md


def test_trend_single_topic_stays_flat(ws):
    """只有一个主题时不分组（避免"多一层标题没有任何信息量"）。"""
    _put(ws, "p1", "张三", ["动量守恒"], "2026-10-01")
    _put(ws, "p2", "张三", ["动量守恒"], "2026-10-10")
    st = TD.analyze(ws, "classes/化工25", topics={"动量守恒": "动量定理"})
    assert st["byTopic"][0]["topic"] == "动量定理"
    assert "📚" not in TD.render_md(st)


def test_trend_flat_when_no_topics(ws):
    _put(ws, "p1", "张三", ["动量守恒"], "2026-10-01")
    _put(ws, "p2", "张三", ["动量守恒"], "2026-10-10")
    st = TD.analyze(ws, "classes/化工25")
    assert st["byTopic"] == []
    assert st["recurring"][0]["term"] == "动量守恒"


# ---------------- 工具注册 ----------------
def test_set_topic_tool_is_l2():
    from assist.atopia import registry as R
    names = {t.name: t.level for t in R.BUILTIN_TOOLS}
    assert names["kb.vocab.set-topic"] == "L2"

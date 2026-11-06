"""D171：批阅三键语义 + 结果落草稿 + 抄写题计分。

教师反馈（docs/116-D171）：
> 完整批阅其实是重新批阅覆盖的意思……应该叫「转写+批阅」。
> 需要转写、批阅、转写+批阅三个键，再加一个「强制重做」勾选。

> 点开审核没有看到 AI 批语，也没有打分……状态还是已转写。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from assist.grading import evaluate as E


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    return tmp_path


def _run(ws, q: dict, kind: str = "copy"):
    a = {"student": "x", "questions": [{"id": "1", "kind": kind, "confidence": "high",
                                        "correct_points": [], "errors": [],
                                        "has_diagram": True, **q}]}
    return E.score_from_analysis(a, ws=ws)


# ---------------- T3：抄写题 topicMatch 计分 ----------------

def test_copy_topic_match_full_marks(ws):
    """主题相符 + 字数充足 → 满分。"""
    r = _run(ws, {"topic_match": "match", "answer_chars": 200})
    assert r["total_score"] == 100


def test_copy_topic_mismatch_deducts(ws):
    """主题不符 → 扣 topicMismatchDeduct（默认 20）。"""
    r = _run(ws, {"topic_match": "mismatch", "answer_chars": 200})
    assert r["total_score"] == 80
    assert any("主题不符" in d for d in r["deductions"])


def test_copy_topic_partial_deducts_half(ws):
    r = _run(ws, {"topic_match": "partial", "answer_chars": 200})
    assert r["total_score"] == 90


def test_copy_short_answer_deducts(ws):
    """字数 < 50% → −10；50%~100% → −5。"""
    assert _run(ws, {"topic_match": "match", "answer_chars": 30})["total_score"] == 90
    assert _run(ws, {"topic_match": "match", "answer_chars": 60})["total_score"] == 95


def test_copy_ignores_errors(ws):
    """**核心**：抄写题**不读 errors** —— 转录失真导致的"逻辑错误"不能扣分。"""
    a = {"student": "x", "questions": [{
        "id": "1", "kind": "copy", "confidence": "high",
        "correct_points": [], "has_diagram": True,
        "topic_match": "match", "answer_chars": 200,
        "errors": [{"description": "推导错误", "knowledge": ["库仑定律"]}]}]}
    r = E.score_from_analysis(a, ws=ws)
    assert r["total_score"] == 100, f"抄写题不应因逻辑错误扣分：{r['deductions']}"


def test_copy_rule_is_configurable(ws):
    """字数下限与扣分可在规则里改（教师要在界面上调）。

    注意：单题扣分仍受**全局 perQuestionCap**（默认 20）封顶——
    这里把 cap 放宽，只验证"取值来自规则"这件事。
    """
    from assist.grading import rules as R
    data = R.read_rules(ws)
    data["types"]["copy"]["minChars"] = 50
    data["types"]["copy"]["topicMismatchDeduct"] = 30
    data["global"]["perQuestionCap"] = 50
    data["global"]["briefProcessDeduct"] = 0
    assert R.write_rules(ws, data)["ok"]
    assert _run(ws, {"topic_match": "mismatch", "answer_chars": 100})["total_score"] == 70


def test_copy_deduct_capped_by_global_cap(ws):
    """单题扣分受全局 perQuestionCap 封顶（既有规则，不是 bug）。"""
    from assist.grading import rules as R
    data = R.read_rules(ws)
    data["types"]["copy"]["topicMismatchDeduct"] = 60     # 想扣 60
    assert R.write_rules(ws, data)["ok"]
    r = _run(ws, {"topic_match": "mismatch", "answer_chars": 100})
    assert r["total_score"] >= 100 - 25, f"应被单题上限拦住：{r['deductions']}"


# ---------------- T2：评阅结果必须落草稿 ----------------

def test_persist_evaluations_skips_without_workid(tmp_path: Path):
    """缺 workId 时要**明确说明**跳过原因（不能静默）。"""
    from assist.grading.flow import _persist_evaluations_to_drafts
    rep = _persist_evaluations_to_drafts(tmp_path, {}, {"classId": "c1"}, {})
    assert "skipped" in rep and "workId" in rep["skipped"]


def test_persist_evaluations_works(tmp_path: Path):
    """有完整 plan 时，评阅产物应写进草稿库（PWA 状态判定的数据源）。"""
    from assist.files import kb_io  # noqa: F401 —— 确保依赖可用
    from assist.grading import flow as F
    from assist.xxt import grade_store as G

    class_dir = "classes/A"
    task_id = "hw1"
    base = tmp_path / class_dir / "grading" / task_id
    (base / "evaluations").mkdir(parents=True)
    (base / "transcripts").mkdir(parents=True)
    (base / "evaluations" / "张三.json").write_text(
        '{"student":"张三","total_score":88,"feedback_md":"批语正文","tag":"top"}',
        encoding="utf-8")
    (base / "transcripts" / "张三.json").write_text('{"student":"张三"}', encoding="utf-8")
    plan = {"classId": "c1", "workId": "w1", "classDir": class_dir,
            "packId": task_id, "students": [{"name": "张三", "tag": "top"}]}
    task = {"id": task_id, "class_dir": class_dir}
    rep = F._persist_evaluations_to_drafts(tmp_path, task, plan, {"report_kind": "ai"})
    assert rep.get("ok"), f"落草稿失败：{rep}"
    assert rep["count"] >= 1


def test_persist_evaluations_reports_error_on_bad_dir(tmp_path: Path):
    """写失败必须返回 error（供 journal 记录），不能吞掉。"""
    from assist.grading.flow import _persist_evaluations_to_drafts
    rep = _persist_evaluations_to_drafts(
        tmp_path, {}, {"classId": "c1", "workId": "w1",
                       "classDir": "classes/不存在", "packId": "x"}, {})
    assert rep.get("error") or rep.get("ok") is False

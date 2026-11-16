"""D176：题目类型（kind）必须贯通「plan → 提示词 → 算分」。

教师提问：
  1. translation 通常不需要画示意图 —— 检查提示词；
  2. 批阅是否**按题目类型**（把该题题干+答案 + 学生转写一起发给模型）？
     并提醒：**作业纸类型**与**题目类型**可能混淆（一张作业纸里可能混多种题型）。

发现的真实缺陷：
  `flow._plan_items_for()` 只透传 序号/content/solution/tag，**丢掉了每题的 kind/kb**
  → ① 提示词只按**作业纸 tag** 注入题型指令（混题型作业纸全用错范式）；
    ② 算分只在模型自报的 `q.kind` 里找（schema 不强制）→ 缺失即一律 problems，
       翻译题被按「每错 −5」算（实测 −20，而 translation 规则实际只 −5）。
"""
from __future__ import annotations

import pytest

from assist.grading import flow
from assist.grading.evaluate import build_user_prompt, score_from_analysis
from assist.grading.prompts import format_questions


def _plan():
    """一张 tag=qa 的作业纸里**混**了三种题型（正是教师担心的场景）。"""
    return {"students": [{"name": "张三", "tag": "qa", "questions": [
        {"no": "1", "content": "求加速度", "solution": "a=F/m",
         "kind": "problems", "kb": "problems", "related": "牛顿第二定律"},
        {"no": "2", "content": "把这段英文译成中文", "solution": "参考译文",
         "kind": "translation", "kb": "translation", "related": ""},
        {"no": "3", "content": "抄写以下公式", "solution": "原文",
         "kind": "copy", "kb": "copy", "related": ""},
    ]}]}


# ---------------- 1) plan → items：kind 不得丢失 ----------------

def test_plan_items_keep_per_question_kind():
    items = flow._plan_items_for({"plan": _plan()}, "张三")
    assert [it["kind"] for it in items] == ["problems", "translation", "copy"]
    assert [it["kb"] for it in items] == ["problems", "translation", "copy"]
    # tag 仍保留，但只是"作业纸级"信息，不能当题型
    assert all(it["tag"] == "qa" for it in items)
    assert items[0]["related"] == "牛顿第二定律"


def test_plan_items_keep_kind_even_when_tag_differs():
    """作业纸 tag=qa，但题目 kind=translation → 以题目 kind 为准。"""
    items = flow._plan_items_for({"plan": _plan()}, "张三")
    assert items[1]["tag"] == "qa" and items[1]["kind"] == "translation"


# ---------------- 2) 提示词：逐题标注题型 + 注入所有涉及题型的指令 ----------------

def test_prompt_marks_kind_per_question():
    p = format_questions(flow._plan_items_for({"plan": _plan()}, "张三"))
    assert "第 1 题【题型：计算/推导题】" in p
    assert "第 2 题【题型：翻译题】" in p
    assert "第 3 题【题型：抄写题】" in p
    assert "每题的题型以该题标注为准" in p


def test_prompt_injects_each_kind_instruction_for_mixed_sheet():
    items = flow._plan_items_for({"plan": _plan()}, "张三")
    prompt = build_user_prompt(items, "学生转写内容", "张三", ws=None)
    assert "【翻译题输出要求】" in prompt
    assert "【抄写题输出要求】" in prompt
    assert "【计算/推导题输出要求】" in prompt
    # 题干与参考答案都要进提示词（教师问的第 2 点）
    assert "把这段英文译成中文" in prompt and "参考译文" in prompt
    assert "学生转写内容" in prompt


def test_prompt_labels_kind_on_each_question_block():
    """生产路径（build_user_prompt）逐题给出「评阅范式」，模型才知道哪题用哪套规则。

    这正是教师问的"是否按题目类型批阅"：题干 + 参考答案 + 学生转写一起发给模型，
    且**逐题**标明题型。
    """
    items = flow._plan_items_for({"plan": _plan()}, "张三")
    prompt = build_user_prompt(items, "学生转写", "张三", ws=None)
    assert "评阅范式: problems" in prompt
    assert "评阅范式: translation" in prompt
    assert "评阅范式: copy" in prompt
    # 每题的题干与参考答案都必须在
    assert "求加速度" in prompt and "a=F/m" in prompt
    assert "把这段英文译成中文" in prompt and "参考译文" in prompt
    assert "抄写以下公式" in prompt and "原文" in prompt


def test_prompt_does_not_treat_worksheet_tag_as_kind():
    """只有 tag、没有任何 kind/kb 时才兜底用 tag；有 kind 时必须用 kind。"""
    items = [{"序号": 1, "content": "x", "kind": "translation", "tag": "qa"}]
    prompt = build_user_prompt(items, "y", ws=None)
    assert "【翻译题输出要求】" in prompt
    assert "【问答题输出要求】" not in prompt


# ---------------- 3) 算分：模型不报 kind 也要按题目 kind ----------------

def _analysis(kind_in_q: bool, qid: str = "1"):
    q = {"id": qid, "reasoning": {"status": "ok", "note": "n"}, "correct_points": [],
         "errors": [{"step": "s", "description": "译文错误", "guidance": "g",
                     "evidence": "e", "confidence": "high", "why": "w"}] * 4,
         "confidence": "high", "has_diagram": True,
         "relevance": "irrelevant", "answer_chars": 5}
    if kind_in_q:
        q["kind"] = "translation"
    return {"question_match": {"status": True, "match": True}, "questions": [q],
            "has_signature": True, "summary": "", "guidance": "",
            "strengths": [], "weaknesses": []}


@pytest.mark.parametrize("kind_in_q", [True, False])
def test_translation_scored_by_translation_rule_without_model_kind(kind_in_q):
    """模型报不报 kind 都必须走 translation 规则（此前缺 kind → 按 problems 扣 20）。"""
    items = flow._plan_items_for({"plan": _plan()}, "张三")[1:2]   # 只留翻译题（序号=2）
    r = score_from_analysis(_analysis(kind_in_q, qid="2"), items=items, ws=None)
    assert r["per_question_rules"][0]["kind"] == "translation"
    assert r["per_question_rules"][0]["rules"] == ["translation"]
    assert r["total_score"] == 95, r["deductions"]      # −5，而不是 problems 的 −20


# ---------------- 4) 示意图：翻译/抄写题不要求画图 ----------------

def test_translation_hint_says_no_diagram_needed():
    from assist.grading.prompts import kind_output_hint
    h = kind_output_hint("translation")
    assert "has_diagram" in h and "一律填 true" in h
    assert "不要求画" in h


def test_copy_hint_says_no_diagram_needed():
    from assist.grading.prompts import kind_output_hint
    h = kind_output_hint("copy")
    assert "has_diagram" in h and "一律填 true" in h


def test_analysis_prompt_scopes_diagram_to_required_questions():
    from assist.grading import evaluate as EV
    p = EV.ANALYSIS_PROMPT
    assert "只在题目要求画图时才判定" in p
    assert "翻译题" in p and "不要求画图" in p
    assert "题目没要求画图 → `has_diagram` 一律填 `true`" in p


def test_report_does_not_tell_translation_student_to_draw_diagram():
    """翻译题即使 has_diagram=false，也不该在报告里提示"缺少示意图"。"""
    from assist.grading.evaluate import build_feedback_md
    a = _analysis(True)
    a["questions"][0]["has_diagram"] = False
    md = build_feedback_md({"total_score": 95, "deductions": [], "analysis": a}, "张三")
    assert "缺少示意图" not in md

    a2 = _analysis(False)
    a2["questions"][0]["kind"] = "qa"
    a2["questions"][0]["has_diagram"] = False
    md2 = build_feedback_md({"total_score": 95, "deductions": [], "analysis": a2}, "张三")
    assert "缺少示意图" in md2      # 问答题仍要提示

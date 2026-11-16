"""D174：翻译题批阅放宽为「基本完成度」判据。

教师原话（第 19 轮反馈）：
  「translation 的批阅提示词可能有些过于严格了，这部分我们主要看学生有没有翻译
    和回答基本问题，如果翻译完全不对则扣 5 分，如果没有回答问题则扣 5 分，
    如果字数少于题目描述，则扣 10 分。」

背景：旧实现 translation 走通用 `lengthBased`（基准 = 题长×3，<80% 扣 5、<50% 扣 10，
与题目无关扣 20），且提示词要求「检查翻译是否准确、术语使用是否正确」——
文学作品翻译没有唯一标准答案，逐词比对准确性会误伤学生。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from assist.grading import evaluate as EV
from assist.grading import rules as R


def _q(qid=1, *, kind="translation", answer_chars=None, relevance=None,
       question_answered=None, answer_text="", errors=(), reasoning="ok",
       required_chars=None):
    q = {"id": qid, "reasoning": {"status": reasoning, "note": "n"},
         "correct_points": [], "errors": list(errors), "confidence": "high",
         "has_diagram": True, "kind": kind, "answer_text": answer_text}
    if answer_chars is not None:
        q["answer_chars"] = answer_chars
    if relevance is not None:
        q["relevance"] = relevance
    if question_answered is not None:
        q["question_answered"] = question_answered
    if required_chars is not None:
        q["required_chars"] = required_chars
    return q


def _analysis(questions):
    return {"question_match": {"status": True, "match": True},
            "questions": questions, "has_signature": True, "summary": "",
            "guidance": "", "strengths": [], "weaknesses": []}


def _err():
    return {"step": "s", "description": "译文用词不准", "guidance": "想一想该词的含义",
            "evidence": "e", "confidence": "high", "why": "w"}


# ---------------- 默认规则 ----------------

def test_default_mode_is_dedicated_translation():
    t = R.DEFAULT_RULES["types"]["translation"]
    assert t["mode"] == "translation"
    assert "translation" in R.VALID_MODES
    assert t["translationWrongDeduct"] == 5
    assert t["questionAnsweredDeduct"] == 5
    assert t["shortAnswerDeduct"] == 10


def test_rule_summary_mentions_lenient_deductions():
    s = R.rule_summary(None, "translation")
    assert "翻译完全不对" in s and "−5" in s
    assert "没有回答" in s
    assert "−10" in s
    assert "不逐词比对" in s


# ---------------- 计分 ----------------

def test_good_translation_gets_full_marks(tmp_path: Path):
    """译文有个别用词不准（errors 有内容）也不扣分。"""
    a = _analysis([_q(answer_chars=200, relevance="relevant", question_answered=True,
                      errors=[_err(), _err()])])
    r = EV.score_from_analysis(a, ws=None)
    assert r["total_score"] == 100, r["deductions"]
    assert any("转为启发式提问" in d for d in r["deductions"]) is False  # 只写进明细


def test_translation_completely_wrong_deducts_5():
    a = _analysis([_q(answer_chars=200, relevance="irrelevant")])
    r = EV.score_from_analysis(a, ws=None)
    assert r["total_score"] == 95, r["deductions"]
    assert any("翻译完全不对" in d for d in r["deductions"])


def test_question_not_answered_deducts_5():
    a = _analysis([_q(answer_chars=200, relevance="relevant", question_answered=False)])
    r = EV.score_from_analysis(a, ws=None)
    assert r["total_score"] == 95, r["deductions"]
    assert any("没有回答" in d for d in r["deductions"])


def test_short_answer_deducts_10_once(tmp_path: Path):
    """字数不足只扣一次 10 分（不再按 8 折/5 折分档、也不受题长倍数影响）。"""
    a = _analysis([_q(answer_chars=12, relevance="relevant", question_answered=True,
                      required_chars=100)])
    r = EV.score_from_analysis(a, ws=None)
    assert r["total_score"] == 90, r["deductions"]
    assert any("题目要求 100 字" in d for d in r["deductions"])


def test_short_answer_uses_transcript_text_when_chars_missing():
    """模型没报字数时以转写原文重算。"""
    a = _analysis([_q(answer_chars=None, answer_text="短", relevance="relevant",
                      required_chars=100)])
    r = EV.score_from_analysis(a, ws=None)
    assert r["total_score"] == 90, r["deductions"]


def test_no_required_chars_means_no_length_deduction():
    """题目没规定字数（required_chars 缺省）→ 不按长度扣分。"""
    a = _analysis([_q(answer_chars=5, relevance="relevant", question_answered=True)])
    r = EV.score_from_analysis(a, ws=None)
    assert r["total_score"] == 100, r["deductions"]


def test_three_penalties_can_coexist_capped():
    """三项可叠加，但单题扣分仍受全局 perQuestionCap（20）封顶。"""
    a = _analysis([_q(answer_chars=5, relevance="irrelevant", question_answered=False,
                      required_chars=100)])
    r = EV.score_from_analysis(a, ws=None)
    assert r["total_score"] == 80, r["deductions"]   # 5+5+10 = 20


# ---------------- 提示词 ----------------

def test_prompt_only_asks_completion_questions():
    from assist.grading.prompts import kind_output_hint, tag_instruction
    h = kind_output_hint("translation")
    assert "question_answered" in h
    assert "答案" not in h and "完全不对" in h
    t = tag_instruction("translation")
    assert "不要" in t and "准确性" in t


def test_schema_has_question_answered():
    from assist.grading.prompts import EVALUATION_SCHEMA
    props = (EVALUATION_SCHEMA["json_schema"]["schema"]["properties"]["questions"]
             ["items"]["properties"])
    assert props["question_answered"]["type"] == "boolean"

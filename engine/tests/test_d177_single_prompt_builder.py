"""D177：评阅提示词只能有**一份**实现（合并 evaluate/prompts 两套）。

背景：此前有两个构建器各自演进：
  - `evaluate.build_user_prompt`   —— 生产主路径（evaluate_student 用）
  - `prompts.build_evaluate_prompt` —— 批量接口（llm_batch 用）
两者在「题型标注 / 先判题目 / 严谨性要求」上口径漂移，D176 的 kind 丢失问题
就部分源于此。现在两者都委托给唯一实现 `prompts.build_grade_prompt`。
"""
from __future__ import annotations

import inspect

import pytest

from assist.grading import evaluate as EV
from assist.grading import prompts as PR


def _items():
    return [
        {"序号": "1", "content": "求加速度", "solution": "a=F/m",
         "kind": "problems", "kb": "problems", "tag": "qa", "related": "牛顿第二定律"},
        {"序号": "2", "content": "把英文译成中文", "solution": "参考译文",
         "kind": "translation", "kb": "translation", "tag": "qa"},
    ]


# ---------------- 1) 只有一个实现：两个入口都委托 ----------------

def test_evaluate_build_user_prompt_delegates():
    src = inspect.getsource(EV.build_user_prompt)
    assert "build_grade_prompt" in src, "evaluate.build_user_prompt 必须委托给 build_grade_prompt"
    # 不得再自己拼装提示词（不得出现旧的逐题渲染逻辑）
    assert "【作业纸题目】" not in src, "提示词拼装逻辑不应残留第二份"


def test_prompts_build_evaluate_prompt_delegates():
    src = inspect.getsource(PR.build_evaluate_prompt)
    assert "build_grade_prompt" in src, "build_evaluate_prompt 必须委托给 build_grade_prompt"
    assert "【作业纸题目】" not in src


def test_kinds_of_is_single_source():
    src = inspect.getsource(EV._kinds_of)
    assert "kinds_of_items" in src, "_kinds_of 必须委托给 prompts.kinds_of_items"


# ---------------- 2) 两条路径产出同一份提示词（同输入同输出） ----------------

def test_two_entry_points_produce_identical_prompt():
    items = _items()
    a = EV.build_user_prompt(items, "学生作答内容", "张三", ws=None)
    # build_evaluate_prompt 的 questions 用 no/kind，且不带 student
    b = PR.build_evaluate_prompt(
        questions=[{"no": "1", "content": "求加速度", "solution": "a=F/m",
                    "kind": "problems", "kb": "problems", "tag": "qa", "related": "牛顿第二定律"},
                   {"no": "2", "content": "把英文译成中文", "solution": "参考译文",
                    "kind": "translation", "kb": "translation", "tag": "qa"}],
        markdown_text="学生作答内容", tag="")
    # 唯一差异应只有"学生："行
    assert a.replace("学生：张三\n\n", "") == b


# ---------------- 3) 合并后关键能力不丢 ----------------

def test_unified_prompt_contains_all_critical_blocks():
    p = EV.build_user_prompt(_items(), "学生作答", "张三", ws=None)
    assert "学生：张三" in p
    assert "【作业纸题目】" in p
    assert "评阅范式: problems" in p and "评阅范式: translation" in p
    assert "参考答案/解题要点" in p and "a=F/m" in p and "参考译文" in p
    assert "【第一步：先判断题目是否对应】" in p
    assert "【学生转写（含题目与作答）】" in p
    assert "严谨性要求" in p                      # EVIDENCE_INSTRUCTION
    assert "【翻译题输出要求】" in p and "【计算/推导题输出要求】" in p


def test_missing_questions_yields_explicit_notice():
    p = PR.build_evaluate_prompt(questions=[], markdown_text="x", tag="")
    assert "【缺少作业纸题目】" in p
    assert "请你先自行判断题目" not in p          # 不得让模型自己猜题


def test_worksheet_tag_hint_is_subordinate_to_question_kind():
    """作业纸 tag 的提示必须声明"与题目级冲突时以题目级为准"。"""
    p = PR.build_evaluate_prompt(
        questions=[{"no": "1", "content": "把英文译成中文", "kind": "translation"}],
        markdown_text="x", tag="copy")
    assert "[作业纸级提示]" in p
    assert "以题目级为准" in p


def test_normalize_prompt_items_accepts_both_field_styles():
    got = PR.normalize_prompt_items([
        {"no": 1, "content": "a", "kb": "translation"},        # prompts 风格
        {"序号": 2, "content": "b", "kind": "copy"},           # plan 风格
        {"content": "c"},                                       # 无编号
    ])
    assert [x["序号"] for x in got] == [1, 2, 3]
    assert [x["kind"] for x in got] == ["translation", "copy", "problems"]

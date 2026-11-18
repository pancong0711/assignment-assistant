"""D186：summary 题目提示与评阅口径适度放宽。

教师要求：
- summary 题干提示应列主要概念/定理/定律、定义/公式、示意图与概念关系；
- 题干中的斜杠 “/” 表示“或”，定义文字与公式不要求同时出现；
- 不要求列全所有概念/定理/定律，课程本身没有定理/定律时不应误判；
- summary 题要求画出示意图；
- 评阅尺度适当放宽，不额外增加扣分项。
"""
from __future__ import annotations

from pathlib import Path

from assist.grading import evaluate as EV
from assist.grading import prompts as PR
from assist.grading import rules as R
from assist.paper import compose as C


def test_summary_question_content_is_updated():
    expected = (
        "请总结课堂内容，并画出示意图。（提示：列出主要概念/定理/定律，"
        "包括定义/公式、示意图等，指出概念之间的关系，如xx求导/积分可得到xxx。）"
    )
    assert C.SUMMARY_CONTENT == expected
    app_src = Path(__file__).resolve().parents[2] / "app" / "src" / "lib" / "taskpad.ts"
    text = app_src.read_text(encoding="utf-8")
    assert expected in text


def test_summary_analysis_prompt_is_lenient():
    p = EV.ANALYSIS_PROMPT
    assert "主要概念/定理/定律" in p
    assert "定义或公式" in p
    assert "“/”表示“或”" in p
    assert "不要求列全" in p
    assert "没有定理/定律时不要因此判错" in p
    assert "是否按题目要求画出示意图" in p


def test_summary_output_hint_lenient_keys():
    h = PR.KIND_OUTPUT_SCHEMA_HINT["summary"]
    assert "定义文字或公式任一即可" in h
    assert "不要求同时写文字定义和公式" in h
    assert "不要求列全" in h
    assert "课程内容本身没有定理或定律" in h
    assert "不单独增加新的扣分项" in h
    assert "未画才判 false" in h


def test_summary_fallback_and_material_blocks_are_lenient():
    fb = PR.summary_fallback_block({
        "enabled": True, "minChars": 120, "minCharsDeduct": 5,
        "requireKnowledgeSummary": True, "requireFormulaOrDerivation": True,
        "requireDiagram": "if_question_has",
    })
    assert "不要求列全" in fb
    assert "二者其一即可" in fb
    assert "不要求文字定义与公式同时出现" in fb
    assert "明确要求画出" in fb

    mb = PR.summary_knowledge_block(["动量守恒", "弹性碰撞"])
    assert "主要概念/定理/定律" in mb
    assert "不要求二者都写" in mb
    assert "不单独增加扣分项" in mb


def test_summary_rule_focus_is_lenient():
    s = R.rule_summary(None, "summary")
    assert "不要求列全" in s
    assert "“/”表示或" in s
    assert "不因课程本身没有定理/定律而苛求" in s

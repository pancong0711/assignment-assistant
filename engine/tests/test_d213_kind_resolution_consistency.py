"""D213：题库(kind)解析在“提示词”和“算分”两处必须一致。

现场：tag=innovation 的学生，innovation 题被按 problems 逐错扣分（太严）。
根因：plan.json 旧版题目只有 tag、没有 kind/kb；
  - 提示词：kind > kb > tag → 注入 innovation 规则（模型把逻辑问题写成启发式提问）
  - 算分  ：kind > kb > q.kind > problems → **没有 tag 回退** → 回落 problems，
            把“启发式提问”当成“错误”每处 −5。
"""
from __future__ import annotations

from pathlib import Path

from assist.grading import rules as R
from assist.grading.evaluate import score_from_analysis
from assist.grading.prompts import build_grade_prompt, normalize_prompt_items


def _analysis(errors=None, chars=300):
    return {"questions": [{"id": 1, "relevance": "relevant", "answer_chars": chars,
                           "errors": errors or []}], "has_signature": True}


LOGIC_ERRORS = [{"type": "logic", "description": "推导不严谨", "confidence": "high"},
                {"type": "logic", "description": "假设不成立", "confidence": "high"}]


# ---------------- 1) 解析口径统一 ----------------

def test_resolve_item_kind_priority():
    assert R.resolve_item_kind({"kind": "innovation"}) == ("innovation", "item.kind")
    assert R.resolve_item_kind({"kb": "innovation"}) == ("innovation", "item.kb")
    assert R.resolve_item_kind({"tag": "innovation"}) == ("innovation", "item.tag")
    assert R.resolve_item_kind({}, {"kind": "translation"}) == ("translation", "model")
    assert R.resolve_item_kind({}) == ("problems", "fallback")


def test_resolve_item_kind_aliases():
    assert R.resolve_item_kind({"kb": "copyonly"})[0] == "copy"


def test_prompt_items_use_same_resolution():
    items = normalize_prompt_items([{"tag": "innovation", "content": "x"}])
    assert items[0]["kind"] == "innovation"


# ---------------- 2) 核心回归：tag-only 的 innovation 题不得按 problems 扣 ----------

def test_innovation_by_tag_only_is_lenient():
    r = score_from_analysis(_analysis(LOGIC_ERRORS),
                            items=[{"序号": 1, "tag": "innovation",
                                    "content": "创新题：设计实验"}])
    assert r["total_score"] == 100, r["deductions"]
    rule = r["per_question_rules"][0]
    assert rule["kind"] == "innovation"
    assert rule["kindSource"] == "item.tag"


def test_innovation_by_kb_is_lenient():
    r = score_from_analysis(_analysis(LOGIC_ERRORS),
                            items=[{"序号": 1, "kb": "innovation", "content": "x"}])
    assert r["total_score"] == 100


def test_unknown_source_falls_back_to_problems_and_is_flagged():
    r = score_from_analysis(_analysis(LOGIC_ERRORS), items=[{"序号": 1, "content": "x"}])
    assert r["total_score"] == 90            # problems 每错 −5 × 2
    rule = r["per_question_rules"][0]
    assert rule["kind"] == "problems" and rule["kindSource"] == "fallback"
    assert r["kind_fallback_questions"] == [1]


def test_mixed_worksheet_applies_per_question_rules():
    """同一份作业纸：innovation 题宽松、problems 题严格。"""
    analysis = {"questions": [
        {"id": 1, "relevance": "relevant", "answer_chars": 300,
         "errors": [{"type": "logic", "description": "x", "confidence": "high"}]},
        {"id": 2, "relevance": "relevant", "answer_chars": 300,
         "errors": [{"type": "logic", "description": "y", "confidence": "high"}]},
    ], "has_signature": True}
    items = [
        {"序号": 1, "kb": "innovation", "content": "创新题"},
        {"序号": 2, "kb": "problems", "content": "计算题"},
    ]
    r = score_from_analysis(analysis, items=items)
    by_id = {x["id"]: x for x in r["per_question_rules"]}
    assert by_id[1]["kind"] == "innovation" and by_id[1]["deduct"] == 0
    assert by_id[2]["kind"] == "problems" and by_id[2]["deduct"] == 5


# ---------------- 3) 提示词：规则按题注入 ----------------

def test_prompt_injects_per_kind_rules_and_labels():
    items = [{"序号": 1, "kb": "innovation", "content": "创新题：设计实验"},
             {"序号": 2, "kb": "problems", "content": "计算题：求速度"}]
    p = build_grade_prompt(items, "学生转写……", student="学生甲")
    assert "【评阅范式：innovation】" in p
    assert "【评阅范式：problems】" in p
    assert "来源: innovation；评阅范式: innovation" in p
    assert "来源: problems；评阅范式: problems" in p
    assert "逻辑错误本身不额外扣分" in p


def test_prompt_contains_question_solution_and_transcript():
    items = [{"序号": 1, "kb": "problems", "content": "题干ABC",
              "solution": "参考答案XYZ", "related": "动能定理"}]
    p = build_grade_prompt(items, "学生作答ZZZ", student="学生甲")
    assert "题干ABC" in p and "参考答案XYZ" in p
    assert "学生作答ZZZ" in p
    assert "动能定理" in p


# ---------------- 4) plan 旧数据补 kind ----------------

def test_plan_items_enriched_from_questions_by_tag():
    from assist.grading.flow import _plan_items_for
    ctx = {"plan": {
        "students": [{"name": "学生甲", "tag": "innovation",
                      "questions": [{"no": "1", "content": "创新题"}]}],
        "questionsByTag": {"innovation": [
            {"no": "1", "kb": "innovation", "kind": "innovation", "related": "熵"}]},
    }}
    items = _plan_items_for(ctx, "学生甲")
    assert items[0]["kind"] == "innovation"
    assert items[0]["kb"] == "innovation"
    assert items[0]["related"] == "熵"


def test_plan_items_prefer_own_kind_when_present():
    from assist.grading.flow import _plan_items_for
    ctx = {"plan": {
        "students": [{"name": "学生甲", "tag": "innovation",
                      "questions": [{"no": "1", "kind": "problems", "kb": "problems"}]}],
        "questionsByTag": {"innovation": [{"no": "1", "kind": "innovation"}]},
    }}
    items = _plan_items_for(ctx, "学生甲")
    assert items[0]["kind"] == "problems"


def test_source_contract_for_d213():
    root = Path(__file__).resolve().parents[1]
    rules = (root / "src/assist/grading/rules.py").read_text(encoding="utf-8")
    prompts = (root / "src/assist/grading/prompts.py").read_text(encoding="utf-8")
    evaluate = (root / "src/assist/grading/evaluate.py").read_text(encoding="utf-8")
    flow = (root / "src/assist/grading/flow.py").read_text(encoding="utf-8")
    assert "def resolve_item_kind(" in rules
    assert "resolve_item_kind(d)" in prompts
    assert "resolve_item_kind(it, q)" in evaluate
    assert "kindSource" in evaluate
    assert "kind_fallback_questions" in evaluate
    assert "_kb_by_no" in flow


def test_report_warns_about_kind_fallback():
    from assist.grading.report import _rule_source_md
    md = _rule_source_md({
        "per_question_rules": [{"id": 1, "kind": "problems", "kindSource": "fallback",
                                "source": "problems", "rules": ["errorCount"], "deduct": 5}],
        "kind_fallback_questions": [1],
    })
    text = "\n".join(md)
    assert "未识别题库来源" in text
    assert "重批" in text

"""D216：批阅前置「程序对齐」——用 Python 判断学生做的是哪份卷（0 token）。

约定（教师 2026-11-20 拍板）：
- mismatch 仅警告、仍出分；
- unknown 沿用现有审计判定；
- 不做新增按钮；
- 对齐结果写进 plan/evaluation/drafts，PWA 与草稿版报告可见。
"""
from __future__ import annotations

import json
from pathlib import Path

from assist.grading import align as A
from assist.grading import tag_audit as TA


INNOV = {"padId": "pad-innov", "tag": "innovation", "questions": [
    {"no": "1", "stem": "设计一个实验验证动量守恒，要求说明器材与步骤", "kb": "innovation"},
    {"no": "2", "stem": "说明你的实验误差来源与改进方法", "kb": "innovation"}]}
PROB = {"padId": "pad-prob", "tag": "problems", "questions": [
    {"no": "1", "stem": "质量为2kg的物体受10N力，求加速度大小", "kb": "problems"},
    {"no": "2", "stem": "求3秒后的速度与位移", "kb": "problems"}]}
PAPERS = [INNOV, PROB]


def _tr(*questions):
    return {"items": [{"no": str(i + 1), "printed_question": q}
                      for i, q in enumerate(questions)]}


TR_INNOV = _tr("设计实验验证动量守恒，说明器材与步骤",
               "说明你的实验误差来源与改进方法")


# ---------------- 1) 三态判定 ----------------

def test_match_when_roster_tag_matches_content():
    r = A.align_student(TR_INNOV, PAPERS, roster_tag="innovation")
    assert r["verdict"] == "match"
    assert r["coverage"] >= 0.6
    assert r["padId"] == "pad-innov"
    assert all(m["kb"] == "innovation" for m in r["questionMap"])


def test_mismatch_warns_but_still_selects_current_tag_pad():
    """核心：mismatch 只警告、仍出分——padId 仍是当前 tag 的卷。"""
    r = A.align_student(TR_INNOV, PAPERS, roster_tag="problems")
    assert r["verdict"] == "mismatch"
    assert r["bestTag"] == "innovation"
    assert r["padId"] == "pad-prob"          # 批阅仍用当前 tag 的卷
    assert "建议核对 tag" in r["reason"] or "建议" in r["reason"]


def test_unknown_when_no_questions_in_transcript():
    r = A.align_student({"markdown": ""}, PAPERS, roster_tag="innovation")
    assert r["verdict"] == "unknown"
    assert "没有可用的题目块" in r["reason"]


def test_unknown_when_papers_missing():
    r = A.align_student(TR_INNOV, [], roster_tag="innovation")
    assert r["verdict"] == "unknown"


def test_align_is_readonly_evidence():
    r = A.align_student(TR_INNOV, PAPERS, roster_tag="innovation")
    assert r["source"] == "align-python"
    # 不包含任何“权威写回”字段
    assert "tagApplied" not in r and "write" not in r


def test_question_map_carries_kb_per_question():
    r = A.align_student(TR_INNOV, PAPERS, roster_tag="innovation")
    assert {m["kb"] for m in r["questionMap"]} == {"innovation"}


def test_summarize_counts():
    rows = {"甲": {"verdict": "match"}, "乙": {"verdict": "mismatch"},
            "丙": {"verdict": "unknown"}, "丁": {}}
    s = A.summarize(rows)
    assert s["total"] == 4 and s["match"] == 1 and s["mismatch"] == 1
    assert s["unknown"] == 2


# ---------------- 2) 阈值可调（并入 tagAudit） ----------------

def test_thresholds_come_from_rules_cfg():
    from assist.grading.rules import DEFAULT_RULES, global_rules
    ta = DEFAULT_RULES["tagAudit"]
    assert "coverageMin" in ta and "worksheetMarginMin" in ta
    assert "matchScore" in ta and "alignMinChars" in ta
    g = global_rules(None)
    assert g is not None


def test_strict_threshold_makes_unknown():
    """阈值可调：把 margin 门槛提高到超过实际差值 → unknown（沿用现状口径）。"""
    # 把“单题算匹配”的门槛提到 0.99 → 只有完全一致的题才算，覆盖率降到 0.5
    r = A.align_student(TR_INNOV, PAPERS, roster_tag="innovation",
                        cfg={"tagAudit": {"matchScore": 0.99}})
    assert r["verdict"] == "unknown"
    assert r["coverage"] < 0.6


def test_invalid_threshold_falls_back_to_default():
    c = A._cfg({"tagAudit": {"coverageMin": 9.9}})
    assert c["coverageMin"] == 0.6


# ---------------- 3) 提示词：match 省 token ----------------

def test_prompt_match_replaces_compare_block():
    from assist.grading.prompts import build_grade_prompt
    items = [{"序号": 1, "kb": "innovation", "content": "创新题：设计实验", "solution": "参考"}]
    p_match = build_grade_prompt(items, "转写", student="甲",
                                 align={"verdict": "match", "coverage": 0.9})
    p_none = build_grade_prompt(items, "转写", student="甲")
    assert "第一步：先判断题目是否对应" not in p_match
    assert "题目已由程序核对" in p_match
    assert len(p_match) < len(p_none)
    # 题目与参考答案不能被漏掉
    assert "创新题：设计实验" in p_match and "参考" in p_match


def test_prompt_mismatch_keeps_compare_block_and_adds_hint():
    from assist.grading.prompts import build_grade_prompt
    items = [{"序号": 1, "kb": "problems", "content": "计算题"}]
    p = build_grade_prompt(items, "转写", student="甲",
                           align={"verdict": "mismatch", "reason": "更像 innovation 卷",
                                  "bestTag": "innovation"})
    assert "第一步：先判断题目是否对应" in p
    assert "程序对齐提示" in p


# ---------------- 4) 算分用对齐给出的 kb ----------------

def test_scoring_uses_align_kb():
    from assist.grading.evaluate import score_from_analysis
    analysis = {"questions": [{"id": 1, "relevance": "relevant", "answer_chars": 300,
                "errors": [{"type": "logic", "description": "x", "confidence": "high"}]}],
                "has_signature": True}
    items = [{"序号": 1, "content": "创新题", "kb": "innovation", "_kindSource": "align"}]
    r = score_from_analysis(analysis, items=items)
    rule = r["per_question_rules"][0]
    assert rule["kind"] == "innovation"
    assert rule["kindSource"] == "align"
    assert r["total_score"] == 100


# ---------------- 5) 草稿层与报告可见 ----------------

def test_drafts_persist_align_fields():
    src = (Path(__file__).resolve().parents[1] / "src/assist/grading/drafts.py").read_text(
        encoding="utf-8")
    assert '"align"' in src and '"question_match"' in src
    assert '"per_question_rules"' in src


def test_draft_report_renders_align_and_rules():
    from assist.grading.report import _mode_report_md
    md, _kind = _mode_report_md(
        student="学生甲",
        ai={"score": 88, "comment": "批语",
            "align": {"verdict": "mismatch", "reason": "更像 innovation 卷"},
            "per_question_rules": [{"id": 1, "kind": "innovation",
                                    "source": "innovation", "rules": ["lengthBased"],
                                    "deduct": 0}],
            "kind_fallback_questions": []},
        human={}, human_mode="none", revision={}, revised=False)
    assert "题目存在差异" in md
    assert "评分依据" in md
    assert "innovation" in md


def test_plan_carries_papers_with_kb():
    src = (Path(__file__).resolve().parents[1] / "src/assist/grading/inputs.py").read_text(
        encoding="utf-8")
    assert '"papers": papers' in src
    assert "papers_from_taskpads" in src
    assert "def papers_for_plan(" in src


def test_flow_aligns_before_grade():
    src = (Path(__file__).resolve().parents[1] / "src/assist/grading/flow.py").read_text(
        encoding="utf-8")
    assert "align_student(" in src
    assert 'ctx.setdefault("align", {})' in src
    assert "align=align" in src


# ---------------- 6) 端到端：对齐 → 提示词 → 算分 → 评阅 JSON ----------------

class _FakeClient:
    evaluation_model = "fake-eval"

    def __init__(self, analysis):
        self.analysis = analysis

    def chat(self, *, system_prompt, user_text, model=None, temperature=0.2, **kw):
        self.last_prompt = user_text
        return json.dumps(self.analysis, ensure_ascii=False)


def _e2e(tmp_path, *, roster_tag, analysis, items, transcript_items, align=None):
    from assist.grading.evaluate import evaluate_student
    tp = tmp_path / "学生甲.json"
    tp.write_text(json.dumps({"student": "学生甲", "model": "fake",
                              "items": transcript_items}, ensure_ascii=False),
                  encoding="utf-8")
    client = _FakeClient(analysis)
    out = evaluate_student(client, tp, items, tmp_path / "eval", ws=tmp_path,
                           align=align)
    return client, json.loads(out.read_text(encoding="utf-8"))


def test_e2e_align_match_shrinks_prompt_and_records_align(tmp_path):
    al = A.align_student(TR_INNOV, PAPERS, roster_tag="innovation")
    analysis = {"questions": [{"id": 1, "relevance": "relevant", "answer_chars": 300,
                               "errors": []}], "has_signature": True}
    items = [{"序号": 1, "content": INNOV["questions"][0]["stem"],
              "kb": "innovation", "kind": "innovation"}]
    client, res = _e2e(tmp_path, roster_tag="innovation", analysis=analysis,
                       items=items,
                       transcript_items=[{"no": "1",
                                          "printed_question": "设计实验验证动量守恒，说明器材与步骤",
                                          "answer": "x" * 300}],
                       align=al)
    assert "第一步：先判断题目是否对应" not in client.last_prompt
    assert "题目已由程序核对" in client.last_prompt
    assert res["align"]["verdict"] == "match"
    assert res["question_match"]["source"] == "align-python"
    assert res["question_match"]["status"] is True


def test_e2e_align_mismatch_still_scores(tmp_path):
    """mismatch 仅警告、仍出分：结果有分数，verdict/question_match 标不一致。"""
    al = A.align_student(TR_INNOV, PAPERS, roster_tag="problems")
    analysis = {"questions": [{"id": 1, "relevance": "relevant", "answer_chars": 300,
                               "errors": [{"type": "logic", "description": "x",
                                           "confidence": "high"}]}],
                "has_signature": True}
    items = [{"序号": 1, "content": PROB["questions"][0]["stem"],
              "kb": "problems", "kind": "problems"}]
    _client, res = _e2e(tmp_path, roster_tag="problems", analysis=analysis,
                        items=items,
                        transcript_items=[{"no": "1",
                                           "printed_question": "设计实验验证动量守恒，说明器材与步骤",
                                           "answer": "y" * 300}],
                        align=al)
    assert res["align"]["verdict"] == "mismatch"
    assert isinstance(res["total_score"], (int, float))   # 仍出分
    assert res["question_match"]["status"] is False


def test_e2e_align_kb_marks_kind_source(tmp_path):
    """对齐给出 kb → 算分 kindSource=align，innovation 题不被按 problems 扣。"""
    al = {"verdict": "match", "coverage": 0.9,
          "questionMap": [{"padNo": "1", "kb": "innovation", "score": 0.95}]}
    analysis = {"questions": [{"id": 1, "relevance": "relevant", "answer_chars": 300,
                               "errors": [{"type": "logic", "description": "x",
                                           "confidence": "high"}]}],
                "has_signature": True}
    items = [{"序号": 1, "content": "创新题", "kind": "", "kb": ""}]
    _client, res = _e2e(tmp_path, roster_tag="innovation", analysis=analysis,
                        items=items,
                        transcript_items=[{"no": "1", "printed_question": "创新题",
                                           "answer": "z" * 300}],
                        align=al)
    rule = res["per_question_rules"][0]
    assert rule["kind"] == "innovation"
    assert rule["kindSource"] == "align"
    assert res["total_score"] == 100

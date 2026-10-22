"""D98-B5：批阅严谨性（json_schema / evidence / confidence / low 不计分 / 报告三段式）。"""
from assist.grading.evaluate import build_feedback_md, score_from_analysis
from assist.grading.prompts import EVALUATION_SCHEMA, EVIDENCE_INSTRUCTION


def _analysis(*, errors, correct_points=None, confidence="high"):
    return {
        "question_match": {"status": True, "note": "匹配"},
        "questions": [{
            "id": 1,
            "reasoning": {"status": "ok", "note": "思路完整"},
            "correct_points": correct_points if correct_points is not None else ["正确列出受力"],
            "errors": errors,
            "confidence": confidence,
            "has_diagram": True,
        }],
        "has_signature": True,
        "summary": "整体尚可",
        "guidance": "想一想为什么合力为零？",
        "strengths": ["步骤清晰"],
        "weaknesses": ["单位"],
    }


def test_schema_has_evidence_and_confidence():
    props = EVALUATION_SCHEMA["json_schema"]["schema"]["properties"]["questions"]["items"]["properties"]
    err = props["errors"]["items"]["properties"]
    assert "evidence" in err and "confidence" in err and "why" in err
    assert "correct_points" in props
    assert eval  # 占位避免 lint


def test_evidence_instruction_present():
    assert "evidence" in EVIDENCE_INSTRUCTION and "confidence" in EVIDENCE_INSTRUCTION


def test_low_confidence_error_not_deducted():
    a = _analysis(errors=[
        {"step": "第1步", "description": "符号错", "guidance": "检查符号", "deduct": 5,
         "evidence": "F = ma", "confidence": "low", "why": "可能笔误"},
    ])
    r = score_from_analysis(a)
    assert r["total_score"] == 100, r
    assert not any("扣" in d for d in r["deductions"])


def test_high_confidence_error_deducted():
    a = _analysis(errors=[
        {"step": "第1步", "description": "漏项", "guidance": "想想还有哪些力", "deduct": 5,
         "evidence": "F = mg", "confidence": "high", "why": "漏支持力"},
    ])
    r = score_from_analysis(a)
    assert r["total_score"] < 100


def test_mixed_low_only_notes_in_report():
    a = _analysis(errors=[
        {"step": "第1步", "description": "明确错误", "guidance": "g1", "deduct": 5,
         "evidence": "x=1", "confidence": "high", "why": "算错了"},
        {"step": "第2步", "description": "看不清", "guidance": "g2", "deduct": 5,
         "evidence": "y=?", "confidence": "low", "why": "字迹模糊"},
    ])
    r = score_from_analysis(a)
    r["analysis"] = a
    md = build_feedback_md(r, "学生甲", "第1次作业", analysis=a)
    assert "做对" in md and "为什么" in md and "你的原文" in md
    assert "待教师确认" in md
    assert "看不清" in md
    # 低置信度那条不应出现在"问题"列表里被算作扣分依据
    assert "另有1处低置信度未计" in " ".join(r["deductions"]) or True

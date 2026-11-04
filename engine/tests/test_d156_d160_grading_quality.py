"""D156–D160：批阅正确性与质量的一组修复。

- D156：`--students` 必须**同时**过滤评阅（此前只过滤转写 → 出现"批张紫涵却报张松"）；
- D157：逐生补批**强制重跑**（否则已有转写/评阅会被跳过，表现为"两次结果一样"）；
- D158：批阅 system prompt 重写（要求 evidence/why/correct_points）；
- D159：批阅"信息量不足"检测；
- D160：转写加 response_format schema + 结构校验 + 降级回退。
"""
from __future__ import annotations

import json

import pytest

from assist.grading import evaluate as EV
from assist.grading import prompts as PR


# ---------------- D156：评阅按 students 过滤 ----------------
def test_only_students_helper():
    from assist.grading.flow import _only_students
    assert _only_students({"only_students": ["张三"]}) == {"张三"}
    assert _only_students({}) == set()


def test_evaluate_skips_students_outside_list(tmp_path, monkeypatch):
    """评阅阶段只处理指定学生（张松不应被评阅）。"""
    from assist.grading import flow as F
    tr = tmp_path / "transcripts"; tr.mkdir()
    ev = tmp_path / "evaluations"; ev.mkdir()
    for name in ("张紫涵", "张松"):
        (tr / f"{name}.json").write_text(json.dumps({"student": name, "items": []}),
                                        encoding="utf-8")
    called = []
    monkeypatch.setattr(F, "evaluate_student",
                        lambda client, tf, items, out, **kw: called.append(tf.stem) or tf)
    ctx = {"items": [{"序号": "1", "content": "题"}], "task": {}, "transcripts_dir": tr,
           "plan": None, "only_students": ["张紫涵"], "force": True,
           "journal": tmp_path / "j.jsonl", "run_id": "r1", "ws": tmp_path,
           "diag": tmp_path / "d.jsonl", "evaluations_dir": ev}
    F._run_evaluate(ctx, object(), ev)
    assert called == ["张紫涵"], f"只应评阅指定学生，实际：{called}"


def test_evaluate_skips_existing_without_force(tmp_path, monkeypatch):
    """D157：已有评阅结果且未强制 → 跳过（不重复花额度）。"""
    from assist.grading import flow as F
    tr = tmp_path / "transcripts"; tr.mkdir()
    ev = tmp_path / "evaluations"; ev.mkdir()
    (tr / "张三.json").write_text("{}", encoding="utf-8")
    (ev / "张三.json").write_text('{"student":"张三"}', encoding="utf-8")
    called = []
    monkeypatch.setattr(F, "evaluate_student",
                        lambda *a, **k: called.append(1) or a[1])
    ctx = {"items": [], "task": {}, "transcripts_dir": tr, "plan": None,
           "only_students": [], "force": False, "journal": tmp_path / "j.jsonl",
           "run_id": "r", "ws": tmp_path, "diag": tmp_path / "d.jsonl"}
    F._run_evaluate(ctx, object(), ev)
    assert called == [], "未强制重跑时不应重新评阅"


def test_evaluate_reruns_with_force(tmp_path, monkeypatch):
    from assist.grading import flow as F
    tr = tmp_path / "transcripts"; tr.mkdir()
    ev = tmp_path / "evaluations"; ev.mkdir()
    (tr / "张三.json").write_text("{}", encoding="utf-8")
    (ev / "张三.json").write_text('{"student":"张三"}', encoding="utf-8")
    called = []
    monkeypatch.setattr(F, "evaluate_student",
                        lambda *a, **k: called.append(1) or a[1])
    ctx = {"items": [], "task": {}, "transcripts_dir": tr, "plan": None,
           "only_students": [], "force": True, "journal": tmp_path / "j.jsonl",
           "run_id": "r", "ws": tmp_path, "diag": tmp_path / "d.jsonl"}
    F._run_evaluate(ctx, object(), ev)
    assert called == [1], "强制重跑时必须重新评阅"


# ---------------- D158：批阅提示词要求 ----------------
def test_analysis_prompt_requires_evidence_and_why():
    p = EV.ANALYSIS_PROMPT
    assert "evidence" in p and "逐字" in p
    assert "物理原理" in p or "物理依据" in p
    assert "correct_points" in p
    assert "苏格拉底" in p or "追问" in p


def test_analysis_prompt_has_quality_selfcheck():
    assert "质量自查" in EV.ANALYSIS_PROMPT


def test_deduct_no_longer_required_in_schema():
    """D158：分数由系统算，schema 不应再强制模型自报 deduct。"""
    schema = PR.EVALUATION_SCHEMA["json_schema"]["schema"]
    err_req = (schema["properties"]["questions"]["items"]["properties"]
               ["errors"]["items"]["required"])
    assert "deduct" not in err_req


def test_analyze_default_max_tokens_raised():
    import inspect
    sig = inspect.signature(EV.analyze)
    assert sig.parameters["max_tokens"].default >= 12288


# ---------------- D159：信息量检测 ----------------
def test_thin_questions_detects_empty_review():
    a = {"questions": [
        {"id": "1", "correct_points": [], "errors": [],
         "reasoning": {"note": "好"}},
        {"id": "2", "correct_points": ["列式正确"], "errors": [],
         "reasoning": {"note": ""}},
    ]}
    assert EV.thin_questions(a) == ["1"]


def test_thin_questions_empty_when_detailed():
    a = {"questions": [{"id": "1", "correct_points": ["a"], "errors": [],
                        "reasoning": {"note": ""}}]}
    assert EV.thin_questions(a) == []


# ---------------- D160：转写 schema + 校验 ----------------
def test_transcription_schema_exists():
    assert PR.TRANSCRIPTION_SCHEMA["json_schema"]["name"] == "transcription"


def test_validate_transcription_ok():
    assert PR.validate_transcription({
        "items": [{"no": "1", "answer": "答", "printed_question": "",
                   "diagrams": []}],
        "unmatched_notes": "", "quality": {"handwriting": "工整",
                                           "clarity": "清晰", "organization": "整洁"},
    }) == []


def test_validate_transcription_rejects_empty_items():
    errs = PR.validate_transcription({"items": [], "quality": {}})
    assert any("items" in e for e in errs)


def test_validate_transcription_accepts_legacy_markdown():
    """旧格式（v1）仍兼容——不能因为加校验就破坏历史数据。"""
    assert PR.validate_transcription({"markdown": "内容", "quality": {}}) == []


def test_chat_with_images_accepts_response_format():
    import inspect
    from assist.grading.llm import LLMClient
    sig = inspect.signature(LLMClient.chat_with_images)
    assert "response_format" in sig.parameters

"""D234：补交/迟交由程序校验提交状态并扣 5 分，并进入批阅报告。"""
from __future__ import annotations

import json
from pathlib import Path

from assist.grading import inputs as I
from assist.grading.drafts import build_draft_report
from assist.grading.evaluate import (
    build_result_from_analysis,
    evaluate_student,
    is_late_submission,
    score_from_analysis,
)
from assist.grading.report import build_report_md
from assist.roster.grading_scores import grading_scores


def _analysis():
    return {
        "question_match": {"status": True, "match": True, "note": ""},
        "questions": [{
            "id": 1,
            "reasoning": {"status": "ok", "note": "思路完整"},
            "correct_points": ["正确"],
            "errors": [],
            "confidence": "high",
            "has_diagram": True,
        }],
        "has_signature": True,
        "summary": "整体尚可",
        "guidance": "继续保持",
        "strengths": ["步骤清晰"],
        "weaknesses": [],
    }


class _FakeClient:
    evaluation_model = "fake-eval"

    def __init__(self, analysis):
        self.analysis = analysis

    def chat(self, *, system_prompt, user_text, model=None, temperature=0.2, **kw):
        return json.dumps(self.analysis, ensure_ascii=False)


def test_is_late_submission_only_uses_explicit_status():
    assert is_late_submission("补交")
    assert is_late_submission("已完成（补交）")
    assert is_late_submission("迟交")
    assert is_late_submission("overdue / late")
    assert not is_late_submission("已批阅")
    assert not is_late_submission("待批阅")
    assert not is_late_submission("Completed（教师提交）")
    assert not is_late_submission("")


def test_score_from_analysis_applies_five_point_penalty_once():
    normal = score_from_analysis(_analysis(), submission_status="已批阅")
    assert normal["total_score"] == 100
    assert normal["submission"] == {"status": "已批阅", "late": False}
    assert normal["score_adjustments"] == []

    late = score_from_analysis(_analysis(), submission_status="补交")
    assert late["academic_score"] == 100
    assert late["total_score"] == 95
    assert late["submission"] == {"status": "补交", "late": True}
    assert late["score_adjustments"] == [{
        "kind": "late-submission", "deduct": 5.0, "status": "补交",
        "reason": "平台提交状态为补交/迟交",
    }]
    assert any("补交/迟交" in x and "−5" in x for x in late["deductions"])


def test_batch_reflow_path_also_applies_late_penalty():
    r = build_result_from_analysis(_analysis(), student="张三",
                                   submission_status="补交")
    assert r["academic_score"] == 100
    assert r["total_score"] == 95
    assert r["submission"]["late"] is True


def test_late_penalty_is_applied_after_academic_floor(tmp_path: Path):
    """学术分已到 floor=40 时，补交仍是额外的 5 分，而不是被 floor 吞掉。"""
    (tmp_path / "grading-rules.json").write_text(json.dumps({
        "version": 1,
        "global": {"floor": 40, "lateSubmissionDeduct": 5},
        "types": {},
    }, ensure_ascii=False), encoding="utf-8")
    r = score_from_analysis({"questions": [], "has_signature": True},
                            ws=tmp_path, submission_status="补交")
    assert r["academic_score"] == 40
    assert r["total_score"] == 35


def test_read_review_students_keeps_platform_status(tmp_path: Path, monkeypatch):
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    (review_dir / "students.json").write_text(json.dumps({
        "students": [{
            "name": "张三", "workAnswerId": "wa1", "status": "补交",
            "images": [], "score": "",
        }]
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(I, "review_dir_for", lambda class_id, work_id: review_dir)
    _, rows = I.read_review_students("C", "W")
    assert rows[0]["status"] == "补交"


def test_build_plan_propagates_submission_status(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(I, "students_with_tags",
                        lambda ws, class_dir, pack_id="": [
                            {"name": "张三", "number": "1", "tag": "qa"}])
    # 本测试只验证状态透传，不需要真实作业纸展开（也避免拉入渲染依赖）。
    monkeypatch.setattr(I, "pads_by_tag",
                        lambda *a, **k: {"qa": {"padId": "", "questions": []}})
    monkeypatch.setattr(I, "_norm_tag", lambda t: str(t or "").strip().lower())
    plan = I.build_plan(
        tmp_path, task_id="p1", class_dir="classes/A", review_students=[{
            "name": "张三", "workAnswerId": "wa1", "status": "补交",
            "images": ["/tmp/x.jpg"],
        }], explicit_pads={})
    stu = plan["students"][0]
    assert stu["submissionStatus"] == "补交"
    assert stu["lateSubmission"] is True


def test_flow_passes_plan_submission_status_to_evaluate(tmp_path: Path, monkeypatch):
    from assist.grading import flow as F

    tr_dir = tmp_path / "transcripts"
    ev_dir = tmp_path / "evals"
    tr_dir.mkdir()
    (tr_dir / "张三.json").write_text(json.dumps({
        "student": "张三", "items": [{"no": "1", "answer": "答1"}],
    }, ensure_ascii=False), encoding="utf-8")
    seen = {}

    def _fake_evaluate(client, transcript_file, items, evaluations_dir, **kwargs):
        seen.update(kwargs)
        return evaluations_dir / "张三.json"

    monkeypatch.setattr(F, "evaluate_student", _fake_evaluate)
    ctx = {
        "items": [{"序号": 1, "content": "题1", "kind": "problems"}],
        "task": {"grade": {"models": {}}},
        "transcripts_dir": tr_dir,
        "plan": {"students": [{
            "name": "张三", "tag": "problems",
            "questions": [{"no": "1", "content": "题1", "kind": "problems"}],
            "submissionStatus": "补交",
        }]},
        "ws": tmp_path,
        "force": False,
        "only_students": [],
    }
    F._run_evaluate(ctx, object(), ev_dir)
    assert seen["submission_status"] == "补交"


def test_evaluate_student_writes_adjustment_and_report_mentions_it(tmp_path: Path):
    transcript = tmp_path / "张三.json"
    transcript.write_text(json.dumps({
        "student": "张三", "model": "fake-tr",
        "items": [{"no": "1", "printed_question": "题1", "answer": "答1"}],
    }, ensure_ascii=False), encoding="utf-8")
    items = [{"序号": 1, "content": "题1", "kind": "problems", "kb": "problems"}]
    out = evaluate_student(_FakeClient(_analysis()), transcript, items,
                           tmp_path / "eval", ws=tmp_path,
                           submission_status="补交")
    ev = json.loads(out.read_text(encoding="utf-8"))
    assert ev["academic_score"] == 100
    assert ev["total_score"] == 95
    assert ev["submission"]["late"] is True
    assert "**平台状态：** 补交" in ev["feedback_md"]
    assert "程序按提交状态扣分" in ev["feedback_md"]

    md = build_report_md(transcript, out)
    assert "**平台状态：** 补交" in md
    assert "程序已按提交状态自动扣分" in md
    assert "−5" in md

    # PWA 实际生成报告走 build_draft_report；草稿 ai 套必须带同样字段。
    draft_md, _ = build_draft_report({
        "student": "张三", "humanMode": "none", "human": {},
        "ai": {
            "score": ev["total_score"], "comment": "批语",
            "submission": ev["submission"],
            "score_adjustments": ev["score_adjustments"],
        },
    })
    assert "**平台状态：** 补交" in draft_md
    assert "程序已按提交状态自动扣分" in draft_md


def test_grading_score_source_uses_adjusted_score_and_exposes_status(tmp_path: Path):
    ev_dir = tmp_path / "classes" / "A" / "grading" / "p1" / "evaluations"
    ev_dir.mkdir(parents=True)
    (ev_dir / "张三.json").write_text(json.dumps({
        "student": "张三", "total_score": 95, "academic_score": 100,
        "submission": {"status": "补交", "late": True},
        "score_adjustments": [{"kind": "late-submission", "deduct": 5.0}],
    }, ensure_ascii=False), encoding="utf-8")
    rep = grading_scores(tmp_path, "classes/A", "p1", students=["张三"])
    row = rep["rows"][0]
    assert row["score"] == 95
    assert row["submissionStatus"] == "补交"
    assert row["lateSubmission"] is True
    assert row["academicScore"] == 100

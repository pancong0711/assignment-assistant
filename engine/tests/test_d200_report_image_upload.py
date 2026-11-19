"""D200：上传“报告图 + 分数”即可，不应因批语文本为空被判“批语为空”。

现场：对照表显示「8 名可上传；48 名已提交但批语为空」，但教师确认全部学生都有
AI 批语与批阅报告（含人工修改）。根因：就绪判定只看 `comment` 文本，
**完全忽略报告图**；而教师的工作流本来就是“上传报告图 + 打分”，
报告图里已经是排版好的批语，不需要再单独上传原始批语文本。
"""
from __future__ import annotations

import json
from pathlib import Path

from assist.xxt import grade_plan as GP


def _row(name, status="待批阅", wa="wa1"):
    return {"name": name, "status": status, "workAnswerId": wa, "review_path": "review-work"}


def _payload(name, *, comment="", score=None, images=None, version=""):
    return {"student": name, "comment": comment, "score": score,
            "images": images or [],
            "report": {"version": version} if version else {}}


IMG = [{"name": "a-report.png", "data_b64": "AAA"}]


def test_report_image_makes_student_ready_without_comment():
    """核心回归：有报告图、无批语文本 → 必须 ready（旧实现是 no-comment）。"""
    rep = GP.upload_readiness(platform_rows=[_row("学生甲")],
                              payloads=[_payload("学生甲", score=88, images=IMG,
                                                 version="ab12cd")])
    row = rep["rows"][0]
    assert row["state"] == GP.READY
    assert row["hasImage"] is True and row["hasComment"] is False
    assert row["uploadMode"] == "report-only"
    assert rep["ready"] == ["学生甲"]
    assert rep["noReport"] == []


def test_comment_only_still_ready():
    rep = GP.upload_readiness(platform_rows=[_row("学生甲")],
                              payloads=[_payload("学生甲", comment="批语", score=80)])
    row = rep["rows"][0]
    assert row["state"] == GP.READY and row["uploadMode"] == "text"


def test_score_only_still_ready():
    rep = GP.upload_readiness(platform_rows=[_row("学生甲")],
                              payloads=[_payload("学生甲", score=80)])
    assert rep["rows"][0]["state"] == GP.READY


def test_nothing_uploadable_is_no_report():
    rep = GP.upload_readiness(platform_rows=[_row("学生甲")],
                              payloads=[_payload("学生甲")])
    row = rep["rows"][0]
    assert row["state"] == GP.NO_REPORT
    assert "生成批阅报告" in row["reason"]
    assert rep["noReport"] == ["学生甲"]


def test_empty_comment_but_ready_is_reported_separately():
    """“批语文本为空”不再阻断上传，只在预览里单独提示（走报告图模式）。"""
    rep = GP.upload_readiness(
        platform_rows=[_row("学生甲"), _row("学生乙")],
        payloads=[_payload("学生甲", score=88, images=IMG),
                  _payload("学生乙", comment="有批语", score=80)])
    assert rep["ready"] == ["学生甲", "学生乙"]
    assert rep["emptyComment"] == ["学生甲"]
    assert rep["noReport"] == []


def test_hint_does_not_claim_missing_comments():
    rep = GP.upload_readiness(platform_rows=[_row("学生甲")],
                              payloads=[_payload("学生甲", score=88, images=IMG)])
    assert "批语为空" not in rep["hint"]
    assert "报告图" in rep["hint"]


def test_unsubmitted_still_never_ready():
    rep = GP.upload_readiness(platform_rows=[_row("学生甲", status="未交")],
                              payloads=[_payload("学生甲", score=88, images=IMG)])
    assert rep["rows"][0]["state"] == GP.NOT_SUBMITTED
    assert rep["ready"] == []


# ---------------- evaluations 兜底 ----------------

def test_enrich_payloads_fills_comment_and_score_from_evaluations(tmp_path: Path):
    from assist.xxt.grade_upload import enrich_payloads_from_evaluations
    ws = tmp_path / "ws"
    ev = ws / "classes/c/grading/p/evaluations"
    ev.mkdir(parents=True)
    (ev / "学生甲.json").write_text(json.dumps({
        "student": "学生甲", "total_score": 91,
        "feedback_md": "AI 批语：思路清晰"}, ensure_ascii=False), encoding="utf-8")
    payloads = [_payload("学生甲")]
    out = enrich_payloads_from_evaluations(payloads, ws, class_dir="classes/c",
                                           task_id="p")
    assert out[0]["comment"] == "AI 批语：思路清晰"
    assert out[0]["score"] == 91.0
    assert set(out[0]["filledFromEvaluations"]) == {"comment", "score"}


def test_enrich_payloads_does_not_overwrite_existing(tmp_path: Path):
    from assist.xxt.grade_upload import enrich_payloads_from_evaluations
    ws = tmp_path / "ws"
    ev = ws / "classes/c/grading/p/evaluations"
    ev.mkdir(parents=True)
    (ev / "学生甲.json").write_text(json.dumps({
        "student": "学生甲", "total_score": 91, "feedback_md": "AI"},
        ensure_ascii=False), encoding="utf-8")
    out = enrich_payloads_from_evaluations(
        [_payload("学生甲", comment="人工批语", score=88)], ws,
        class_dir="classes/c", task_id="p")
    assert out[0]["comment"] == "人工批语"
    assert out[0]["score"] == 88


def test_enrich_payloads_is_safe_without_evaluations(tmp_path: Path):
    from assist.xxt.grade_upload import enrich_payloads_from_evaluations
    payloads = [_payload("学生甲", comment="x")]
    out = enrich_payloads_from_evaluations(payloads, tmp_path, class_dir="classes/c",
                                           task_id="p")
    assert out == payloads


# ---------------- 源码契约 ----------------

def test_source_contract_for_d200():
    root = Path(__file__).resolve().parents[1]
    plan = (root / "src/assist/xxt/grade_plan.py").read_text(encoding="utf-8")
    cli = (root / "src/assist/xxt/cli.py").read_text(encoding="utf-8")
    serve = (root / "src/assist/serve.py").read_text(encoding="utf-8")
    assert "NO_REPORT" in plan
    assert "hasImage" in plan and "uploadMode" in plan
    assert "--report-only" in cli
    assert "enrich_payloads_from_evaluations" in cli
    assert "enrich_payloads_from_evaluations" in serve
    assert 'payload.get("reportOnly")' in serve
    # 旧代码里两个不存在的 helper 已被真实解析替代（只允许出现在注释里）
    import re as _re
    assert not _re.search(r"write_upload_manifest\(ws, _resolve_class_dir\(\)", cli)
    assert "write_upload_manifest(ws, cd_scope, tid_scope" in cli

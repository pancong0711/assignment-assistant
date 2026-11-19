"""D196：只上传**已提交**学生的批阅报告；批语缺失要提醒先去批阅。

教师诉求：
1. 只上传已提交学生的批阅报告；未提交学生不需要上传；
2. 已提交但批语/报告没生成的，要提醒去批阅/AI 批阅；
3. 支持逐生上传（更易定位问题、单人失败不影响他人）。
"""
from __future__ import annotations

import json
from pathlib import Path

from assist.xxt import grade_plan as GP


def _row(name, status="待批阅", wa="wa-1", path="review-work"):
    return {"name": name, "status": status, "workAnswerId": wa, "review_path": path}


def _payload(name, comment="批语内容", score=88, version="ab12cd"):
    return {"student": name, "comment": comment, "score": score,
            "report": {"version": version} if version else {}}


# ---------------- 已提交判定 ----------------

def test_is_submitted_true_for_mark_list_rows():
    assert GP.is_submitted(_row("学生甲", "已批阅")) is True
    assert GP.is_submitted(_row("学生乙", "待批阅")) is True


def test_is_submitted_false_for_unsubmitted_status():
    assert GP.is_submitted(_row("学生丙", "未交")) is False
    assert GP.is_submitted(_row("学生丁", "未提交")) is False
    assert GP.is_submitted({}) is False


def test_is_submitted_explicit_flag():
    assert GP.is_submitted({"name": "甲", "submitted": False}) is False


# ---------------- 就绪分类 ----------------

def test_upload_readiness_buckets():
    platform = [_row("学生甲", "待批阅"), _row("学生乙", "待批阅"),
                _row("学生丙", "已批阅")]
    payloads = [_payload("学生甲", comment="有批语"),
                # D200：批语空且无分数/报告图 → 没有可上传内容
                _payload("学生乙", comment="", score=None),
                ]                                       # 学生丙无草稿
    rep = GP.upload_readiness(platform_rows=platform, payloads=payloads)
    assert rep["ready"] == ["学生甲"]
    assert rep["noReport"] == ["学生乙"]
    assert rep["noDraft"] == ["学生丙"]
    assert rep["summary"][GP.NO_REPORT] == 1
    # 兼容字段：noComment 指向“没有可上传内容”
    assert rep["noComment"] == ["学生乙"]


def test_unsubmitted_students_never_ready():
    platform = [_row("学生甲", "未交"), _row("学生乙", "未提交")]
    payloads = [_payload("学生甲"), _payload("学生乙")]
    rep = GP.upload_readiness(platform_rows=platform, payloads=payloads)
    assert rep["ready"] == []
    assert sorted(rep["notSubmitted"]) == ["学生乙", "学生甲"]


def test_local_draft_not_in_platform_list_is_not_submitted():
    """本地有草稿但平台清单没有 → 视为未提交，不上传。"""
    rep = GP.upload_readiness(platform_rows=[_row("学生甲")],
                              payloads=[_payload("学生甲"), _payload("学生乙")])
    assert rep["ready"] == ["学生甲"]
    assert "学生乙" in rep["notSubmitted"]


def test_readiness_hint_mentions_missing_content():
    """D200：提示改为“没有报告图/批语/分数”，不再说“批语为空”。"""
    rep = GP.upload_readiness(platform_rows=[_row("学生甲"), _row("学生乙")],
                              payloads=[_payload("学生甲"),
                                        _payload("学生乙", comment="", score=None)])
    assert "没有报告图/批语/分数" in rep["hint"]
    assert "批语为空" not in rep["hint"]


def test_upload_readiness_handles_empty_inputs():
    rep = GP.upload_readiness(platform_rows=None, payloads=None)
    assert rep["ok"] is True and rep["rows"] == []


def test_ready_requires_comment_not_report():
    """批语齐全即可上传（报告没生成不算阻塞，但会被标 hasReport=False）。"""
    rep = GP.upload_readiness(platform_rows=[_row("学生甲")],
                              payloads=[_payload("学生甲", comment="有", version="")])
    assert rep["ready"] == ["学生甲"]
    assert rep["rows"][0]["hasReport"] is False


# ---------------- 上传路径的防御性拦截 ----------------

def test_upload_grade_blocks_unsubmitted_and_empty_comment():
    src = (Path(__file__).resolve().parents[1] / "src/assist/xxt/grade_upload.py").read_text(
        encoding="utf-8")
    assert "grade_plan.NOT_SUBMITTED" in src
    assert "grade_plan.NO_COMMENT" in src
    assert "该学生批语为空，请先批阅" in src
    assert "needsReview" in src


def test_source_contract_for_d196():
    root = Path(__file__).resolve().parents[1]
    preview = (root / "src/assist/xxt/upload_preview.py").read_text(encoding="utf-8")
    serve = (root / "src/assist/serve.py").read_text(encoding="utf-8")
    assert "upload_readiness(" in preview
    assert '"readiness": readiness' in preview
    assert "needComment" in preview
    # 逐生上传复用现有 /xxt/grade/upload 的 student 参数
    body = serve.split('u.path == "/xxt/grade/upload"')[1][:2000]
    assert 'payload.get("student")' in body

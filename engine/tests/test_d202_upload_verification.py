"""D202：上传显示“成功”但学习通其实没批阅、也没分数。

现场：点「上传」显示已上传，重新读取平台状态也显示已上传，
但平台仍是未批阅、无分数。

根因：`upload_grade()` 的 `ok` 只等价于“点到了 markAction(1) 按钮”，
**从不核验平台是否真的保存**；分数若没写进输入框，点提交也只是空提交。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from assist.xxt import grade_upload as GU


# ---------------- 提交后核验（纯逻辑，替身页面） ----------------

def _patch_rows(monkeypatch, rows):
    monkeypatch.setattr(GU, "_open_mark_list", lambda *a, **k: "url")
    monkeypatch.setattr(GU, "_students_from_mark_list", lambda page: rows)


def test_verified_ok_when_reviewed_and_score_matches(monkeypatch):
    _patch_rows(monkeypatch, [{"name": "韩冰月", "status": "已批阅",
                               "score": "90", "workAnswerId": "wa1"}])
    rep = GU.verify_submission(object(), "c", "k", "w", student="韩冰月",
                               work_answer_id="wa1", expect_score=90)
    assert rep["ok"] is True
    assert rep["status"] == "已批阅" and rep["score"] == "90"


def test_not_verified_when_status_still_pending(monkeypatch):
    """核心回归：状态仍是“待批阅”必须判失败，而不是报成功。"""
    _patch_rows(monkeypatch, [{"name": "韩冰月", "status": "待批阅",
                               "score": "", "workAnswerId": "wa1"}])
    rep = GU.verify_submission(object(), "c", "k", "w", student="韩冰月",
                               work_answer_id="wa1", expect_score=90)
    assert rep["ok"] is False
    assert "仍为「待批阅」" in rep["error"]


def test_not_verified_when_score_mismatch(monkeypatch):
    _patch_rows(monkeypatch, [{"name": "韩冰月", "status": "已批阅",
                               "score": "60", "workAnswerId": "wa1"}])
    rep = GU.verify_submission(object(), "c", "k", "w", student="韩冰月",
                               work_answer_id="wa1", expect_score=90)
    assert rep["ok"] is False
    assert "不一致" in rep["error"]


def test_verified_ok_without_expected_score(monkeypatch):
    _patch_rows(monkeypatch, [{"name": "学生甲", "status": "已批阅",
                               "score": "", "workAnswerId": "wa1"}])
    rep = GU.verify_submission(object(), "c", "k", "w", student="学生甲",
                               work_answer_id="wa1", expect_score=None)
    assert rep["ok"] is True


def test_not_verified_when_student_missing(monkeypatch):
    _patch_rows(monkeypatch, [])
    rep = GU.verify_submission(object(), "c", "k", "w", student="韩冰月",
                               work_answer_id="wa1", expect_score=90)
    assert rep["ok"] is False
    assert "未在批阅列表找到学生" in rep["error"]


def test_verify_survives_list_read_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("页面崩了")
    monkeypatch.setattr(GU, "_open_mark_list", boom)
    rep = GU.verify_submission(object(), "c", "k", "w", student="学生甲")
    assert rep["ok"] is False
    assert "重新读取批阅列表失败" in rep["error"]


def test_verify_falls_back_to_name_when_workanswerid_missing(monkeypatch):
    _patch_rows(monkeypatch, [{"name": "学生乙", "status": "已批阅",
                               "score": "88", "workAnswerId": ""}])
    rep = GU.verify_submission(object(), "c", "k", "w", student="学生乙",
                               work_answer_id="wa-missing", expect_score=88)
    assert rep["ok"] is True


# ---------------- 源码契约 ----------------

def test_upload_grade_requires_verification_before_ok():
    src = (Path(__file__).resolve().parents[1] / "src/assist/xxt/grade_upload.py").read_text(
        encoding="utf-8")
    body = src.split("        if send:")[1].split('status": "dry-run-filled')[0]
    assert "verify_submission(" in body, '提交后未核验平台状态'
    assert 'result["ok"] = bool(clicked and ver.get("ok"))' in body, \
        'ok 仍未与核验结果绑定'
    assert "unverified" in body, '未区分“点了按钮但没保存”'
    # 提交前分数校验
    assert "分数未成功写入页面" in src
    assert "score-not-filled" in src


def test_marks_include_score_field():
    src = (Path(__file__).resolve().parents[1] / "src/assist/xxt/extractor.py").read_text(
        encoding="utf-8")
    assert "score: sc" in src or '"score": sc' in src
    up = (Path(__file__).resolve().parents[1] / "src/assist/xxt/grade_upload.py").read_text(
        encoding="utf-8")
    assert '"score": str(r.get("score") or "").strip()' in up


def test_fill_scores_blurs_inputs():
    src = (Path(__file__).resolve().parents[1] / "src/assist/xxt/marking.py").read_text(
        encoding="utf-8")
    assert "inp.blur()" in src
    assert "KeyboardEvent('keyup'" in src

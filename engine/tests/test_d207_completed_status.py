"""D207：真实平台提交后的状态是 "Completed（教师提交）"，不是“已批阅”/“Reviewed”。

实测（docs/149-D206）：真实批阅列表行文本为
    学生名 学号 Completed（教师提交） 时间 View return
旧解析只认“已批阅/Reviewed/Unreview”，于是 status 读成空串 →
核验只能靠分数兜底；而分数在“只改分未提交”时也会被平台保存 →
存在把“未真正提交”误判为成功的风险。

修复后：状态解析与核验都识别 Completed / 完成 / 教师提交，
核验不再依赖分数兜底。
"""
from __future__ import annotations

from pathlib import Path

from assist.xxt import grade_upload as GU


def _patch_rows(monkeypatch, rows):
    monkeypatch.setattr(GU, "_open_mark_list", lambda *a, **k: "url")
    monkeypatch.setattr(GU, "_students_from_mark_list", lambda page: rows)


def test_completed_counts_as_reviewed(monkeypatch):
    _patch_rows(monkeypatch, [{"name": "学生甲", "status": "Completed（教师提交）",
                               "score": "100", "workAnswerId": "wa1"}])
    rep = GU.verify_submission(object(), "c", "k", "w", student="学生甲",
                               work_answer_id="wa1", expect_score=100)
    assert rep["ok"] is True
    assert rep["status"] == "Completed（教师提交）"
    assert not rep.get("note")          # 不再走“状态为空仅凭分数”的兜底


def test_completed_english_counts_as_reviewed(monkeypatch):
    _patch_rows(monkeypatch, [{"name": "学生甲", "status": "Completed",
                               "score": "88", "workAnswerId": "wa1"}])
    rep = GU.verify_submission(object(), "c", "k", "w", student="学生甲",
                               work_answer_id="wa1", expect_score=88)
    assert rep["ok"] is True


def test_completed_but_score_mismatch_fails(monkeypatch):
    _patch_rows(monkeypatch, [{"name": "学生甲", "status": "Completed（教师提交）",
                               "score": "100", "workAnswerId": "wa1"}])
    rep = GU.verify_submission(object(), "c", "k", "w", student="学生甲",
                               work_answer_id="wa1", expect_score=77)
    assert rep["ok"] is False
    assert "不一致" in rep["error"]


def test_unreview_still_fails_even_with_matching_score(monkeypatch):
    """关键：状态明确未批阅时，分数一致也不能算成功（防“只改分未提交”假成功）。"""
    _patch_rows(monkeypatch, [{"name": "学生甲", "status": "Unreview",
                               "score": "100", "workAnswerId": "wa1"}])
    rep = GU.verify_submission(object(), "c", "k", "w", student="学生甲",
                               work_answer_id="wa1", expect_score=100)
    assert rep["ok"] is False
    assert "仍为「Unreview」" in rep["error"]


def test_pending_chinese_still_fails(monkeypatch):
    _patch_rows(monkeypatch, [{"name": "学生甲", "status": "待批阅",
                               "score": "100", "workAnswerId": "wa1"}])
    rep = GU.verify_submission(object(), "c", "k", "w", student="学生甲",
                               work_answer_id="wa1", expect_score=100)
    assert rep["ok"] is False


def test_source_contract_for_d207():
    root = Path(__file__).resolve().parents[1]
    js = (root / "src/assist/xxt/extractor.py").read_text(encoding="utf-8")
    up = (root / "src/assist/xxt/grade_upload.py").read_text(encoding="utf-8")
    assert "Completed" in js and "教师提交" in js, '列表状态解析未覆盖 Completed（教师提交）'
    assert "completed" in up.lower(), '核验未识别 completed'
    assert "pending" in up, '核验未区分“明确未批阅”'

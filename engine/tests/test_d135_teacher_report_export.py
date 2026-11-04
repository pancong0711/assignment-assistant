"""D135：教师总结报告导出 PNG / PDF（复用学生报告 Playwright 链路）。

口径：
- 导图是**附加能力**：浏览器不可用时返回 None，**不得**让报告生成失败；
- PDF 由**长图**贴入单页（宽固定 A4、高按比例），重排版会让"看到的≠导出的"；
- 默认（不传参数）行为与 D126-B 完全一致（不导图）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from assist.grading import teacher_report as T


@pytest.fixture()
def ev(tmp_path):
    d = tmp_path / "evaluations"
    d.mkdir()
    for stu, terms in (("张三", ["动量守恒"]), ("李四", ["动量守恒", "完全弹性碰撞"])):
        (d / f"{stu}.json").write_text(json.dumps({
            "student": stu, "total_score": 80,
            "analysis": {"questions": [{"id": 1, "errors": [
                {"knowledge": [t], "description": f"{t}错", "confidence": "high"}
                for t in terms]}]},
            "per_question_scores": [80],
            "per_question_rules": [{"id": 1, "kind": "problems", "deduct": 5}],
        }, ensure_ascii=False), encoding="utf-8")
    return d


def test_default_does_not_export_images(ev, tmp_path):
    """默认不导图：保持 D126-B 既有行为（避免每次批阅都启动浏览器）。"""
    rep = T.generate(ev, tmp_path / "reports")
    assert rep["png"] is None and rep["pdf"] is None
    assert (tmp_path / "reports" / "_teacher_report.md").is_file()


def test_export_png_returns_none_without_browser(ev, tmp_path, monkeypatch):
    """浏览器不可用 → 返回 None，**不抛**（导图不能让报告生成失败）。"""
    import assist.grading.report as R
    monkeypatch.setattr(R, "render_report_png",
                        lambda *a, **k: None)
    rep = T.generate(ev, tmp_path / "reports", render_png=True)
    assert rep["ok"] is True
    assert rep["png"] is None
    assert (tmp_path / "reports" / "_teacher_report.md").is_file()


def test_export_png_swallows_exceptions(ev, tmp_path, monkeypatch):
    import assist.grading.report as R

    def boom(*a, **k):
        raise RuntimeError("chromium crashed")
    monkeypatch.setattr(R, "render_report_png", boom)
    rep = T.generate(ev, tmp_path / "reports", render_png=True)
    assert rep["ok"] is True and rep["png"] is None


def test_export_pdf_needs_png(ev, tmp_path, monkeypatch):
    """没有 PNG 时不该尝试出 PDF（PDF 由长图贴入）。"""
    import assist.grading.report as R
    monkeypatch.setattr(R, "render_report_png", lambda *a, **k: None)
    rep = T.generate(ev, tmp_path / "reports", render_pdf=True)
    assert rep["pdf"] is None


def test_teacher_kind_label_is_explicit():
    """教师报告必须一眼看出"只给教师"（不能和学生报告混淆）。"""
    from assist.grading.report import KIND_LABEL, report_html
    assert KIND_LABEL["teacher"] == "教师总结报告（只给教师）"
    html = report_html("# 教师总结报告\n\n内容", kind="teacher", title="T")
    assert "教师总结报告（只给教师）" in html


def test_teacher_html_contains_tables(ev, tmp_path):
    from assist.grading.report import report_html
    rep = T.generate(ev, tmp_path / "reports")
    md = Path(rep["md"]).read_text(encoding="utf-8")
    html = report_html(md, kind="teacher", title="第4次作业")
    assert "动量守恒" in html
    assert "<table" in html

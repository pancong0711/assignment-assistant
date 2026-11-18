"""D195：报告范围与重复学生（现场：只部分学生出报告、表格出现重复姓名）。

现场：教师忘记勾选班级/作业包就点「一键生成」，之后又勾选再点一次 →
表格里多出很多姓名且部分重复；只有部分学生有报告，其余（表格有行）没报告。

根因：
1. 报告只按**草稿**生成；平台名单里有行但没草稿的学生本来就出不了报告，
   而界面没有说明 → 看起来“只生成了一部分”；
2. 同一学生在草稿里可能有**两个键**（workAnswerId + 姓名，历史遗留）→
   旧实现按 key 遍历：同一人生成两份报告、写同一个 `<学生>.png` 互相覆盖、
   版本索引重复，前端表格也出现重复。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from assist.grading import drafts as D
from assist.grading import report_versions as RV
from assist.xxt import grade_store

CLASS_DIR = "classes/化工25"
CLASS_ID = "1001"
WORK_ID = "w1"
TASK_ID = "packA"


def _seed(home, ws, key: str, student: str, score: float, comment: str,
          human: "dict | None" = None):
    grade_store.save_draft_sets(home, CLASS_ID, WORK_ID, key,
                                ai={"score": score, "comment": comment},
                                human=human, student=student,
                                ws=ws, class_dir=CLASS_DIR, task_id=TASK_ID)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    home = tmp_path / "xxt"
    (ws / CLASS_DIR).mkdir(parents=True)
    home.mkdir(parents=True)
    _seed(home, ws, "学生甲", "学生甲", 90, "甲批语")
    _seed(home, ws, "学生乙", "学生乙", 80, "乙批语")
    monkeypatch.setattr("assist.grading.report.html_to_png",
                        lambda html, out_path, **kw: _fake_png(out_path))
    return ws, home


def _fake_png(out_path):
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"PNG")
    return p


def _render(ws, home, **kw):
    return D.render_reports_from_drafts(
        ws, class_id=CLASS_ID, work_id=WORK_ID, task_id=TASK_ID,
        class_dir=CLASS_DIR, home=home, **kw)


def test_duplicate_draft_keys_produce_single_report(env):
    """同一学生两个草稿键 → 只生成一份报告（不再同名互相覆盖）。"""
    ws, home = env
    _seed(home, ws, "wa_9001", "学生甲", 88, "甲的另一个键")
    rep = _render(ws, home)
    names = [x["student"] for x in rep["reports"]]
    assert names.count("学生甲") == 1
    assert sorted(names) == ["学生乙", "学生甲"]


def test_duplicate_keys_all_receive_report_backwrite(env):
    """合并后报告要回写到该学生的**所有**草稿键，否则表格按另一键读不到。"""
    ws, home = env
    _seed(home, ws, "wa_9001", "学生甲", 88, "甲的另一个键")
    _render(ws, home)
    data = grade_store.read_drafts(home, CLASS_ID, WORK_ID, ws=ws,
                                   class_dir=CLASS_DIR, task_id=TASK_ID)
    for key in ("学生甲", "wa_9001"):
        assert (data[key].get("human") or {}).get("report"), f"{key} 未回写报告版本"


def test_richer_draft_wins_when_merging(env):
    """合并取更完整的那份：人工套已使用 > 只有 AI 分。"""
    ws, home = env
    _seed(home, ws, "wa_9002", "学生甲", 70, "旧 AI",
          human={"used": True, "score": 95, "comment": "教师改过"})
    _render(ws, home)
    md = (ws / CLASS_DIR / "grading" / TASK_ID / "reports" / "学生甲.md").read_text(
        encoding="utf-8")
    assert "95" in md


def test_scope_report_lists_missing_drafts(env):
    """平台名单里有、但没草稿的学生必须被点出来（否则“只生成一部分”无从解释）。"""
    ws, home = env
    rep = D.report_scope_report(ws, class_id=CLASS_ID, work_id=WORK_ID,
                                task_id=TASK_ID, class_dir=CLASS_DIR, home=home,
                                students=["学生甲", "学生乙", "学生丙"])
    assert rep["studentCount"] == 2
    assert rep["missingDraft"] == ["学生丙"]
    assert rep["draftCount"] == 2


def test_scope_report_detects_duplicate_keys(env):
    ws, home = env
    _seed(home, ws, "wa_9003", "学生甲", 88, "甲另一键")
    rep = D.report_scope_report(ws, class_id=CLASS_ID, work_id=WORK_ID,
                                task_id=TASK_ID, class_dir=CLASS_DIR, home=home,
                                students=["学生甲", "学生乙"])
    assert "学生甲" in rep["duplicateKeys"]
    assert len(rep["duplicateKeys"]["学生甲"]) == 2


def test_scope_report_without_student_list_is_safe(env):
    ws, home = env
    rep = D.report_scope_report(ws, class_id=CLASS_ID, work_id=WORK_ID,
                                task_id=TASK_ID, class_dir=CLASS_DIR, home=home)
    assert rep["ok"] is True
    assert rep["missingDraft"] == [] and rep["notInList"] == []


def test_cleanup_reports_removes_non_roster(env, tmp_path):
    ws, home = env
    _render(ws, home)
    reports = ws / CLASS_DIR / "grading" / TASK_ID / "reports"
    (reports / "学生丙.md").write_text("残留", encoding="utf-8")
    rep = RV.cleanup_reports(reports, keep_students=["学生甲", "学生乙"], dry_run=True)
    assert rep["count"] == 1 and (reports / "学生丙.md").is_file()  # dry-run 不删
    rep2 = RV.cleanup_reports(reports, keep_students=["学生甲", "学生乙"], dry_run=False)
    assert rep2["count"] == 1 and not (reports / "学生丙.md").exists()
    assert (reports / "学生甲.md").is_file()   # 名单内保留


def test_cleanup_keeps_history_of_kept_students(env):
    ws, home = env
    _render(ws, home)
    reports = ws / CLASS_DIR / "grading" / TASK_ID / "reports"
    assert (reports / RV.VERSIONS_DIR / "学生甲").is_dir()
    RV.cleanup_reports(reports, keep_students=["学生甲", "学生乙"], dry_run=False)
    assert (reports / RV.VERSIONS_DIR / "学生甲").is_dir()


def test_source_contract_for_d195():
    root = Path(__file__).resolve().parents[1]
    drafts = (root / "src/assist/grading/drafts.py").read_text(encoding="utf-8")
    serve = (root / "src/assist/serve.py").read_text(encoding="utf-8")
    assert "def report_scope_report(" in drafts
    assert "def _draft_richness(" in drafts
    assert "merged_keys" in drafts or "sibling_keys" in drafts
    assert "scopeOnly" in serve
    assert '"/xxt/grade/report-cleanup"' in serve

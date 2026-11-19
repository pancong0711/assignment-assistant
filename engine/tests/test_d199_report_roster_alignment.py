"""D199：报告版本必须以**逐生审核名单**为基准（57 人），不是另一份名单（53 人）。

现场：逐生审核显示 57 名学生、作答图也是 57 份，但「报告版本」只有 53。
根因（两个）：
1. 草稿若没有 `student` 字段，报告会用 `wa_2001` 之类的**草稿键**当学生名 →
   版本索引里不是姓名，按名单过滤时“少了几个人”；
2. 版本面板只列“索引里有的学生”，没有按名单补齐“未生成”的人 → 数字天然对不上。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from assist.grading import drafts as D
from assist.grading import report_versions as RV
from assist.xxt import grade_store

CLASS_DIR = "classes/c"
CLASS_ID = "1001"
WORK_ID = "w1"
TASK_ID = "p"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    home = tmp_path / "xxt"
    (ws / CLASS_DIR).mkdir(parents=True)
    home.mkdir(parents=True)
    # 学生甲：草稿写了 student；学生乙：草稿**没写** student（历史遗留）
    grade_store.save_draft_sets(home, CLASS_ID, WORK_ID, "学生甲",
                                ai={"score": 90, "comment": "甲"}, student="学生甲",
                                ws=ws, class_dir=CLASS_DIR, task_id=TASK_ID)
    grade_store.save_draft_sets(home, CLASS_ID, WORK_ID, "wa_2001",
                                ai={"score": 80, "comment": "乙"}, student="",
                                ws=ws, class_dir=CLASS_DIR, task_id=TASK_ID)
    monkeypatch.setattr("assist.grading.report.html_to_png",
                        lambda html, out, **kw: _png(out))
    monkeypatch.setattr(D, "student_name_map",
                        lambda *a, **k: {"wa_2001": "学生乙"})
    return ws, home


def _png(out):
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"PNG")
    return p


def test_report_uses_student_name_not_draft_key(env):
    ws, home = env
    rep = D.render_reports_from_drafts(
        ws, class_id=CLASS_ID, work_id=WORK_ID, task_id=TASK_ID,
        class_dir=CLASS_DIR, home=home)
    assert sorted(x["student"] for x in rep["reports"]) == ["学生乙", "学生甲"]
    reports = ws / CLASS_DIR / "grading" / TASK_ID / "reports"
    assert (reports / "学生乙.md").is_file()
    assert not (reports / "wa_2001.md").exists()


def test_version_index_records_student_name(env):
    ws, home = env
    D.render_reports_from_drafts(ws, class_id=CLASS_ID, work_id=WORK_ID,
                                 task_id=TASK_ID, class_dir=CLASS_DIR, home=home)
    reports = ws / CLASS_DIR / "grading" / TASK_ID / "reports"
    names = {x["student"] for x in RV.read_index(reports)["items"]}
    assert names == {"学生甲", "学生乙"}


def test_draft_student_field_backfilled(env):
    ws, home = env
    D.render_reports_from_drafts(ws, class_id=CLASS_ID, work_id=WORK_ID,
                                 task_id=TASK_ID, class_dir=CLASS_DIR, home=home)
    data = grade_store.read_drafts(home, CLASS_ID, WORK_ID, ws=ws,
                                   class_dir=CLASS_DIR, task_id=TASK_ID)
    assert data["wa_2001"]["student"] == "学生乙"


def test_student_name_map_uses_plan():
    m = D.student_name_map("/tmp/ws", class_id="c", work_id="w",
                           plan={"students": [{"name": "学生甲", "workAnswerId": "wa1"}]})
    assert m["wa1"] == "学生甲"


def test_student_name_map_ignores_incomplete_rows():
    m = D.student_name_map("/tmp/ws", class_id="c", work_id="w",
                           plan={"students": [{"name": "", "workAnswerId": "wa1"},
                                              {"name": "学生乙", "workAnswerId": ""},
                                              {"name": "学生丙", "workAnswerId": "wa3"}]})
    assert m == {"wa3": "学生丙"}


def test_source_contract_for_d199():
    root = Path(__file__).resolve().parents[1]
    drafts = (root / "src/assist/grading/drafts.py").read_text(encoding="utf-8")
    serve = (root / "src/assist/serve.py").read_text(encoding="utf-8")
    assert "def student_name_map(" in drafts
    assert "name_map.get(str(k))" in drafts
    assert '"student": stu' in drafts
    # 版本视图按名单补齐 + key→姓名归一
    assert '"roster": roster' in serve
    assert '"missingReport": missing' in serve
    assert "key_to_name" in serve
    assert "studentRaw" in serve

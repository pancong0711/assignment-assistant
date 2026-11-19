"""D211：逐生上传重复学生 + 覆盖原报告。

现场：
1) 逐生上传里同一学生出现两次、报告版本一致、本地分数不同；点上传实际传了两张报告图；
2) 上传前对照显示“共 112 人”，刚好 56×2（班级实为 56 人）；
3) 「重新读取平台状态」不显示平台分数；
4) 需要“覆盖”功能：删除平台上原报告图，换上新报告图与新分数。

根因：
- 同一学生在草稿里有**两个键**（workAnswerId + 姓名）→ drafts_to_payloads 产出两条；
- 覆盖模式下 UEditor 会把新图**追加**到旧图后（不清空原批语）。
"""
from __future__ import annotations

from pathlib import Path

from assist.xxt import grade_plan as GP
from assist.xxt.grade_upload import (dedupe_payloads_by_student, drafts_to_payloads)
from assist.xxt import upload_preview as UP


def _draft(score, comment="批语", human=None, hm="none"):
    return {"student": "学生甲", "ai": {"score": score, "comment": comment},
            "human": human or {}, "humanMode": hm}


# ---------------- 1) 去重 ----------------

def test_drafts_to_payloads_dedupes_same_student():
    drafts = {"wa_101": _draft(88), "学生甲": _draft(95, human={"used": True, "score": 95},
                                                    hm="replace")}
    ps = drafts_to_payloads(drafts)
    assert len(ps) == 1
    assert ps[0]["score"] == 95          # 人工套优先
    assert set(ps[0]["draftKeys"]) == {"wa_101", "学生甲"}


def test_dedupe_keeps_report_version_from_either_key():
    payloads = [
        {"student": "学生甲", "key": "wa_1", "score": 88, "comment": "x", "images": [],
         "report": {}},
        {"student": "学生甲", "key": "学生甲", "score": 88, "comment": "x", "images": [],
         "report": {"version": "v9"}},
    ]
    out = dedupe_payloads_by_student(payloads)
    assert len(out) == 1
    assert out[0]["report"]["version"] == "v9"


def test_dedupe_keeps_different_students():
    payloads = [{"student": "学生甲", "key": "a"}, {"student": "学生乙", "key": "b"}]
    assert len(dedupe_payloads_by_student(payloads)) == 2


def test_preview_compose_has_one_row_per_student():
    payloads = dedupe_payloads_by_student([
        {"student": "学生甲", "key": "wa_1", "score": 88, "comment": "x", "images": []},
        {"student": "学生甲", "key": "学生甲", "score": 95, "comment": "x", "images": []},
    ])
    rep = UP.compose_preview(
        payloads=payloads,
        platform_rows=[{"name": "学生甲", "status": "待批阅", "score": "", "workAnswerId": "wa1"}])
    assert len(rep["rows"]) == 1


# ---------------- 2) 平台分数读取状态 ----------------

def test_platform_score_unknown_flagged():
    rep = UP.compose_preview(
        payloads=[{"student": "学生甲", "key": "wa1", "score": 88, "comment": "x", "images": []}],
        platform_rows=[{"name": "学生甲", "status": "已完成", "score": "", "workAnswerId": "wa1"}])
    r = rep["rows"][0]
    assert r["platformScore"] is None
    assert r.get("platformScoreUnknown") is True


def test_platform_read_error_surfaced():
    rep = UP.compose_preview(
        payloads=[{"student": "学生甲", "key": "wa1", "score": 88, "comment": "x", "images": []}],
        platform_rows=[{"name": "学生甲", "status": "已完成", "score": "", "workAnswerId": "wa1"}],
        read_errors={"学生甲": "Timeout 30000ms"})
    r = rep["rows"][0]
    assert "Timeout" in r["platformReadError"]


def test_reviewed_status_prefers_snapshot_score():
    rep = UP.compose_preview(
        payloads=[{"student": "学生甲", "key": "wa1", "score": 95, "comment": "x", "images": []}],
        platform_rows=[{"name": "学生甲", "status": "已完成", "score": "88", "workAnswerId": "wa1"}],
        per_student={"学生甲": {"score": 88.0, "commentLength": 10}})
    assert rep["rows"][0]["platformScore"] == 88.0


# ---------------- 3) 覆盖模式 ----------------

def test_upload_grade_supports_overwrite_flag():
    src = (Path(__file__).resolve().parents[1] / "src/assist/xxt/grade_upload.py").read_text(
        encoding="utf-8")
    assert "overwrite: bool = False" in src
    assert 'step = "清空原批语"' in src
    assert "set_comment_html(page, \"\")" in src
    assert "if comment_images and not overwrite:" in src
    assert "if overwrite:" in src and "force = True" in src


def test_cli_and_serve_support_overwrite():
    root = Path(__file__).resolve().parents[1]
    cli = (root / "src/assist/xxt/cli.py").read_text(encoding="utf-8")
    serve = (root / "src/assist/serve.py").read_text(encoding="utf-8")
    assert '"--overwrite"' in cli
    assert "overwrite=bool(overwrite)" in cli
    assert 'args += ["--overwrite"]' in serve


def test_frontend_has_overwrite_button():
    repo = Path(__file__).resolve().parents[2]
    view = (repo / "app/src/components/AiGradingPanel.vue").read_text(encoding="utf-8")
    client = (repo / "app/src/lib/engineClient.ts").read_text(encoding="utf-8")
    assert "overwrite?: boolean" in client
    assert "@click=\"uploadOneStudent(r, { overwrite: true })\"" in view
    assert ">覆盖</button>" in view
    assert "将清空平台上该生的原批语/原报告图" in view

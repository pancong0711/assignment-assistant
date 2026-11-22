"""D217：疑似错卷「照常批阅 + 上传前默认拦截」。

教师拍板（方案 C）：
- 批阅仍出分（mismatch 标记，不阻断）；
- 上传前对照默认把疑似错卷标为 align-mismatch，不计入可上传；
- 批量/引擎默认跳过，需显式 allowMismatch 才传；
- 逐生审核行内提示“改 tag 后重批”。
"""
from __future__ import annotations

from pathlib import Path

from assist.xxt import grade_plan as GP


def _row(name="学生甲", status="待批阅", wa="wa1"):
    return {"name": name, "status": status, "workAnswerId": wa, "review_path": "x"}


def _payload(name="学生甲", *, align=None, comment="批语", score=88, images=None):
    return {"student": name, "key": name, "score": score, "comment": comment,
            "images": images or [], "align": align or {}}


IMG = [{"name": "r.png", "data_b64": "AAA"}]


# ---------------- 1) 就绪态 ----------------

def test_mismatch_becomes_align_mismatch_state():
    rep = GP.upload_readiness(
        platform_rows=[_row()],
        payloads=[_payload(align={"verdict": "mismatch", "bestTag": "innovation"},
                           images=IMG)])
    r = rep["rows"][0]
    assert r["state"] == GP.ALIGN_MISMATCH
    assert "默认不上传" in r["reason"]
    assert "innovation" in r["reason"]
    assert rep["ready"] == []
    assert rep["alignMismatch"] == ["学生甲"]


def test_match_or_unknown_still_ready():
    for v in ("match", "unknown", ""):
        rep = GP.upload_readiness(platform_rows=[_row()],
                                  payloads=[_payload(align={"verdict": v}, images=IMG)])
        assert rep["rows"][0]["state"] == GP.READY, v


def test_not_submitted_takes_priority_over_mismatch():
    rep = GP.upload_readiness(
        platform_rows=[_row(status="未交")],
        payloads=[_payload(align={"verdict": "mismatch"})])
    assert rep["rows"][0]["state"] == GP.NOT_SUBMITTED


def test_summary_counts_mismatch():
    rep = GP.upload_readiness(
        platform_rows=[_row("甲"), _row("乙")],
        payloads=[_payload("甲", align={"verdict": "mismatch"}, images=IMG),
                  _payload("乙", images=IMG)])
    assert rep["summary"][GP.ALIGN_MISMATCH] == 1
    assert rep["summary"][GP.READY] == 1
    assert "疑似错卷" in rep["hint"]


# ---------------- 2) 引擎兜底：默认跳过 ----------------

def test_cli_skips_mismatch_by_default():
    src = (Path(__file__).resolve().parents[1] / "src/assist/xxt/cli.py").read_text(
        encoding="utf-8")
    assert '"--allow-mismatch"' in src
    assert "skippedMismatch" in src
    assert "已默认跳过上传" in src


def test_serve_forwards_allow_mismatch():
    src = (Path(__file__).resolve().parents[1] / "src/assist/serve.py").read_text(
        encoding="utf-8")
    assert 'payload.get("allowMismatch")' in src
    assert '"--allow-mismatch"' in src


def test_payload_carries_align():
    src = (Path(__file__).resolve().parents[1] / "src/assist/xxt/grade_upload.py").read_text(
        encoding="utf-8")
    assert '"align": ((d.get("ai") or {}).get("align") or {})' in src


# ---------------- 3) 前端 ----------------

def test_frontend_guards_mismatch():
    repo = Path(__file__).resolve().parents[2]
    view = (repo / "app/src/components/AiGradingPanel.vue").read_text(encoding="utf-8")
    client = (repo / "app/src/lib/engineClient.ts").read_text(encoding="utf-8")
    assert "uploadIncludeMismatch" in view
    assert "疑似错卷·暂不上传" in view
    assert "包含疑似错卷" in view
    assert "allowMismatch" in view and "allowMismatch?: boolean" in client
    assert "疑似错卷（默认不上传）" in view
    assert "改 tag 后点「转写+批阅」重批" in view
    # 批量上传：默认排除
    assert "if (r.readyState === 'align-mismatch') return uploadIncludeMismatch.value" in view

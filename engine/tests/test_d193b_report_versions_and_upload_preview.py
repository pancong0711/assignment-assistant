"""D193 §2/§3：已批阅三态对照 + 报告内容哈希版本。

只用合成数据（学生甲/学生乙），不启动浏览器、不读真实作业。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from assist.grading import report_versions as RV
from assist.xxt import grade_plan as GP


# ---------------- §2 三态对照 ----------------

def test_decide_new_when_not_reviewed():
    d = GP.decide(status="未批阅", local_score=88, local_comment="写得好")
    assert d["decision"] == GP.NEW and d["upload"] is True
    assert d["needsConfirm"] is False


def test_decide_unchanged_when_same_score_and_comment():
    md = "<p>学生甲：思路清晰</p>"
    d = GP.decide(status="已批阅", local_score=88, local_comment=md,
                  platform={"score": 88, "comment": "学生甲：思路清晰"})
    assert d["decision"] == GP.UNCHANGED and d["upload"] is False


def test_decide_conflict_requires_confirm():
    d = GP.decide(status="已批阅", local_score=92, local_comment="新批语",
                  platform={"score": 88, "comment": "旧批语"})
    assert d["decision"] == GP.CONFLICT
    assert d["needsConfirm"] is True and d["upload"] is False
    assert "92" in d["reason"] or "→" in d["reason"]


def test_decide_conflict_with_force_uploads():
    d = GP.decide(status="已批阅", local_score=92, local_comment="新批语",
                  platform={"score": 88, "comment": "旧批语"}, force=True)
    assert d["decision"] == GP.CONFLICT
    assert d["upload"] is True and d["needsConfirm"] is False
    assert d["platformBefore"]["score"] == 88


def test_decide_skipped_when_no_local_content():
    d = GP.decide(status="未批阅", local_score=None, local_comment="")
    assert d["decision"] == GP.SKIPPED and d["upload"] is False


def test_decide_only_score_changed_is_conflict():
    d = GP.decide(status="已批阅", local_score=90, local_comment="同一段批语",
                  platform={"score": 80, "comment": "同一段批语"})
    assert d["decision"] == GP.CONFLICT


def test_decide_only_comment_changed_is_conflict():
    d = GP.decide(status="已批阅", local_score=80, local_comment="新批语",
                  platform={"score": 80, "comment": "旧批语"})
    assert d["decision"] == GP.CONFLICT


@pytest.mark.parametrize("raw,expected", [
    ("<p>a</p><p>b</p>", "a\nb"),
    ("<div>a&nbsp;b</div>", "a b"),
    ("<p>10 &amp; 20</p>", "10 & 20"),
    ("<script>x()</script><p>ok</p>", "ok"),
    ("", ""),
])
def test_text_of_normalizes_html(raw, expected):
    assert GP.text_of(raw) == expected


def test_same_score_tolerance_and_none():
    assert GP.same_score(88, "88.0") is True
    assert GP.same_score(88.004, 88.0) is True
    assert GP.same_score(88.02, 88.0) is False
    assert GP.same_score(None, None) is True
    assert GP.same_score(None, 1) is False


def test_platform_snapshot_never_keeps_full_text_contract():
    snap = GP.platform_snapshot({"score": "85", "comment": "<p>很长</p>",
                                 "commentImages": "2"})
    assert snap["score"] == 85.0
    assert snap["commentLength"] == 2
    assert snap["commentImages"] == 2


def test_summarize_five_buckets():
    reps = [
        {"student": "学生甲", "ok": True, "decision": GP.NEW},
        {"student": "学生乙", "ok": True, "decision": GP.UNCHANGED},
        {"student": "学生丙", "ok": False, "decision": GP.CONFLICT},
        {"student": "学生丁", "ok": False},
        {"student": "学生戊", "ok": False, "decision": GP.SKIPPED},
    ]
    s = GP.summarize(reps)
    assert s["applied"] == ["学生甲"]
    assert s["unchanged"] == ["学生乙"]
    assert s["conflict"] == ["学生丙"]
    assert s["failed"] == ["学生丁"]
    assert s["skipped"] == ["学生戊"]
    assert s["ok"] is False


# ---------------- §3 报告版本 ----------------

def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_digest_is_content_stable_and_short():
    a = RV.content_digest("# 报告\n内容")
    b = RV.content_digest("# 报告\n内容")
    c = RV.content_digest("# 报告\n内容2")
    assert a == b and a != c and len(a) == 6


def test_record_creates_version_and_history(tmp_path: Path):
    reports = tmp_path / "reports"
    md1 = "# 学生甲 报告\n初版"
    png1 = _write(reports / "学生甲.png", "PNG1")
    r1 = RV.record(reports, "学生甲", md1, kind="ai", score=88,
                   reason="三键", files=[png1])
    assert r1["changed"] is True
    assert r1["tag"].endswith(r1["version"])
    hist = RV.history(reports, "学生甲")
    assert len(hist) == 1 and hist[0]["version"] == r1["version"]
    # 历史文件真的落盘
    vdir = reports / RV.VERSIONS_DIR / "学生甲"
    assert any(p.name.startswith(r1["tag"]) for p in vdir.iterdir())


def test_record_idempotent_for_same_content(tmp_path: Path):
    reports = tmp_path / "reports"
    md = "# 同一份"
    png = _write(reports / "学生甲.png", "PNG")
    RV.record(reports, "学生甲", md, files=[png])
    r2 = RV.record(reports, "学生甲", md, files=[png])
    assert r2["changed"] is False
    assert len(RV.history(reports, "学生甲")) == 1


def test_record_new_version_keeps_old(tmp_path: Path):
    reports = tmp_path / "reports"
    png = _write(reports / "学生甲.png", "PNG1")
    r1 = RV.record(reports, "学生甲", "v1", files=[png])
    png.write_text("PNG2", encoding="utf-8")
    r2 = RV.record(reports, "学生甲", "v2", files=[png])
    assert r1["version"] != r2["version"]
    hist = RV.history(reports, "学生甲")
    assert len(hist) == 2
    assert RV.latest_entry(reports, "student") is None
    assert RV.latest_entry(reports, "学生甲")["version"] == r2["version"]


def test_index_is_readable_json_and_trimmed(tmp_path: Path):
    reports = tmp_path / "reports"
    png = _write(reports / "学生甲.png", "x")
    for i in range(5):
        RV.record(reports, "学生甲", f"v{i}", files=[png])
    idx = json.loads((reports / RV.VERSIONS_DIR / RV.INDEX_NAME).read_text(encoding="utf-8"))
    assert len(idx["items"]) == 5


def test_history_isolated_per_student(tmp_path: Path):
    reports = tmp_path / "reports"
    png = _write(reports / "x.png", "x")
    RV.record(reports, "学生甲", "a", files=[png])
    RV.record(reports, "学生乙", "b", files=[png])
    assert len(RV.history(reports, "学生甲")) == 1
    assert len(RV.history(reports, "学生乙")) == 1


def test_safe_stem_keeps_chinese_and_strips_bad_chars():
    assert RV.safe_stem("学生甲") == "学生甲"
    assert "/" not in RV.safe_stem("a/b")
    assert RV.safe_stem("") == "student"


def test_record_survives_corrupt_index(tmp_path: Path):
    reports = tmp_path / "reports"
    d = reports / RV.VERSIONS_DIR
    d.mkdir(parents=True, exist_ok=True)
    (d / RV.INDEX_NAME).write_text("{坏 json", encoding="utf-8")
    r = RV.record(reports, "学生甲", "md", files=[])
    assert r["changed"] is True
    assert len(RV.history(reports, "学生甲")) == 1


def test_version_tag_format():
    tag = RV.version_tag(1700000000, "ab12cd")
    assert len(tag.split("-")[0]) == 8 and tag.endswith("ab12cd")


# ---------------- 源码契约 ----------------

def test_source_contract_for_d193b():
    root = Path(__file__).resolve().parents[1]
    drafts = (root / "src/assist/grading/drafts.py").read_text(encoding="utf-8")
    upload = (root / "src/assist/xxt/grade_upload.py").read_text(encoding="utf-8")
    serve = (root / "src/assist/serve.py").read_text(encoding="utf-8")
    assert "report_versions.record(" in drafts
    assert 'human_patch["report"] = {' in drafts
    assert '"version": ver["version"]' in drafts
    assert "decide(status=" in upload and "platform_snapshot(" in upload
    assert "draft_report_version" in upload
    assert '"/xxt/grade/report-versions"' in serve
    assert '"/xxt/grade/upload-preview"' in serve

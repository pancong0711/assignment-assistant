"""D135：跨多次作业的知识点趋势（同一知识点是否反复出错）。

口径（docs/84 §2）：
- 作业序列 = **同一 class_dir 下**、按**评阅时间升序**的作业包序列；
- 只统计 `errors[].knowledge[]`（低置信度不计，与计分口径一致）；
- 在 ≥2 次作业出现的知识点 → `recurring`（含逐次轨迹与改善/持续判定）；
- 纯统计不调 LLM；只给教师。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from assist.grading import trend as T


def _ev(root: Path, pack: str, records: list[dict]) -> Path:
    d = root / "classes" / "化工25" / "grading" / pack / "evaluations"
    d.mkdir(parents=True, exist_ok=True)
    for r in records:
        (d / f"{r['student']}.json").write_text(
            json.dumps(r, ensure_ascii=False), encoding="utf-8")
    return d


def _rec(student: str, terms: list[str], ts: str, conf: str = "high") -> dict:
    return {"student": student, "timestamp": ts,
            "analysis": {"questions": [{"id": 1, "errors": [
                {"knowledge": [t], "description": f"{t} 错", "confidence": conf}
                for t in terms]}]}}


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "kb").mkdir()
    return tmp_path


# ---------------- 序列发现 ----------------
def test_sequence_sorted_by_timestamp_not_name(ws):
    """序列必须按**评阅时间**排，而不是按包名（pack9 可能早于 pack1）。"""
    _ev(ws, "packZ", [_rec("张三", ["动量守恒"], "2026-10-01 10:00")])
    _ev(ws, "packA", [_rec("张三", ["动量守恒"], "2026-10-20 10:00")])
    seq = T.discover_sequence(ws, "classes/化工25")
    assert [p["packId"] for p in seq] == ["packZ", "packA"]


def test_sequence_skips_packs_without_evaluations(ws):
    _ev(ws, "p1", [_rec("张三", ["动量守恒"], "2026-10-01 10:00")])
    (ws / "classes" / "化工25" / "grading" / "p2" / "evaluations").mkdir(parents=True)
    seq = T.discover_sequence(ws, "classes/化工25")
    assert [p["packId"] for p in seq] == ["p1"]


def test_sequence_missing_class_returns_empty(ws):
    assert T.discover_sequence(ws, "classes/不存在") == []


def test_eval_time_falls_back_to_mtime(ws):
    d = _ev(ws, "p1", [{"student": "张三", "analysis": {"questions": []}}])
    (d / "张三.json").write_text(json.dumps({"student": "张三",
                                             "analysis": {"questions": []}}),
                                 encoding="utf-8")
    seq = T.discover_sequence(ws, "classes/化工25")
    assert seq[0]["at"]          # 没有 timestamp 时用文件 mtime


# ---------------- 反复出错 ----------------
def test_recurring_term_across_two_packs(ws):
    _ev(ws, "p1", [_rec("张三", ["动量守恒"], "2026-10-01 10:00"),
                   _rec("李四", ["动量守恒"], "2026-10-01 10:00")])
    _ev(ws, "p2", [_rec("张三", ["动量守恒"], "2026-10-10 10:00")])
    st = T.analyze(ws, "classes/化工25")
    assert st["summary"]["recurring"] == 1
    r = st["recurring"][0]
    assert r["term"] == "动量守恒"
    assert r["packs"] == 2
    assert [p["packId"] for p in r["trail"]] == ["p1", "p2"]
    assert r["peakStudents"] == 2


def test_one_off_not_recurring(ws):
    _ev(ws, "p1", [_rec("张三", ["唯一错点"], "2026-10-01 10:00")])
    _ev(ws, "p2", [_rec("张三", ["别的"], "2026-10-10 10:00")])
    st = T.analyze(ws, "classes/化工25")
    assert st["recurring"] == []
    assert {x["term"] for x in st["oneOff"]} == {"唯一错点", "别的"}


def test_improving_vs_persisting(ws):
    # A：p1 两人都错(100%) → p2 一人错(50%) 改善
    # B：p1 一人错(50%) → p2 两人都错(100%) 持续
    _ev(ws, "p1", [_rec("张三", ["A", "B"], "2026-10-01"),
                   _rec("李四", ["A"], "2026-10-01")])
    _ev(ws, "p2", [_rec("张三", ["A", "B"], "2026-10-10"),
                   _rec("李四", ["B"], "2026-10-10")])
    st = T.analyze(ws, "classes/化工25")
    by = {r["term"]: r for r in st["recurring"]}
    assert by["A"]["improving"] is True and by["A"]["persisting"] is False
    assert by["B"]["persisting"] is True and by["B"]["improving"] is False


def test_low_confidence_excluded(ws):
    """低置信度与计分口径一致：不计入趋势。"""
    _ev(ws, "p1", [_rec("张三", ["X"], "2026-10-01", conf="low")])
    _ev(ws, "p2", [_rec("张三", ["X"], "2026-10-10", conf="low")])
    st = T.analyze(ws, "classes/化工25")
    assert st["recurring"] == [] and st["oneOff"] == []


def test_min_recur_threshold(ws):
    _ev(ws, "p1", [_rec("张三", ["X"], "2026-10-01")])
    _ev(ws, "p2", [_rec("张三", ["X"], "2026-10-10")])
    assert T.analyze(ws, "classes/化工25", min_recur=2)["summary"]["recurring"] == 1
    assert T.analyze(ws, "classes/化工25", min_recur=3)["summary"]["recurring"] == 0


def test_empty_class_no_crash(ws):
    st = T.analyze(ws, "classes/空班")
    assert st["ok"] is True and st["sequence"] == [] and st["recurring"] == []


# ---------------- 渲染/落盘 ----------------
def test_render_md_contains_trail_and_disclaimer(ws):
    _ev(ws, "p1", [_rec("张三", ["动量守恒"], "2026-10-01 10:00")])
    _ev(ws, "p2", [_rec("张三", ["动量守恒"], "2026-10-10 10:00")])
    rep = T.generate(ws, "classes/化工25")
    md = rep["markdown"]
    assert "反复出错的知识点" in md and "动量守恒" in md
    assert "仍在持续" in md
    assert "只给教师" in md and "不发给学生" in md


def test_generate_writes_files(ws, tmp_path):
    _ev(ws, "p1", [_rec("张三", ["X"], "2026-10-01")])
    _ev(ws, "p2", [_rec("张三", ["X"], "2026-10-10")])
    out = tmp_path / "out"
    rep = T.generate(ws, "classes/化工25", out)
    assert (out / "trend.md").is_file() and (out / "trend.json").is_file()
    assert len(rep["written"]) == 2


def test_pack_name_from_packs_index(ws):
    from assist.packs import save_pack
    save_pack(ws, "p1", {"name": "第4次作业"})
    _ev(ws, "p1", [_rec("张三", ["X"], "2026-10-01")])
    seq = T.discover_sequence(ws, "classes/化工25")
    assert seq[0]["name"] == "第4次作业"

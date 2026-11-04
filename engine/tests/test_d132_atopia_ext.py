"""D132(P3-2)：扩展覆盖（rules/ 词表）+ 护栏写接口 + 升级不触碰 extensions。

覆盖 docs/81 §8：
5. 护栏超限可读拒绝；
6. extensions/ 覆盖生效，且只能更严；
7. 升级不触碰 extensions/（快照比对）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from assist.atopia import extensions as E
from assist.atopia import limits as L


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    (tmp_path / "kb").mkdir()
    return tmp_path


# ---------------- 扩展：评阅规则覆盖 ----------------
def test_rules_override_applies(ws: Path):
    from assist.grading import rules as R
    assert R.type_rules(ws, "qa")["perMissingPointDeduct"] == 5
    E.ensure(ws)
    (ws / "extensions" / "rules" / "grading-rules.json").write_text(
        json.dumps({"types": {"qa": {"perMissingPointDeduct": 13}}}), encoding="utf-8")
    assert R.type_rules(ws, "qa")["perMissingPointDeduct"] == 13
    # 未覆盖的字段保持内置
    assert R.type_rules(ws, "qa")["mode"] == "missingPoints"


def test_rules_override_cannot_change_algorithm(ws: Path):
    """算法名（mode）是只读项：扩展改了要让计分与提示词保持一致，不允许。"""
    from assist.grading import rules as R
    E.ensure(ws)
    (ws / "extensions" / "rules" / "grading-rules.json").write_text(
        json.dumps({"types": {"qa": {"mode": "errorCount"}}}), encoding="utf-8")
    assert R.type_rules(ws, "qa")["mode"] == "missingPoints"


def test_rules_override_broken_file_falls_back(ws: Path):
    from assist.grading import rules as R
    E.ensure(ws)
    (ws / "extensions" / "rules" / "grading-rules.json").write_text(
        "{not json", encoding="utf-8")
    assert R.type_rules(ws, "qa")["perMissingPointDeduct"] == 5


def test_rules_override_does_not_block_default_file(ws: Path):
    """扩展存在时，规则文件仍应"缺失即写默认"（既有语义不能被扩展改变）。"""
    from assist.grading import rules as R
    E.ensure(ws)
    (ws / "extensions" / "rules" / "grading-rules.json").write_text(
        json.dumps({"types": {"qa": {"perMissingPointDeduct": 13}}}), encoding="utf-8")
    assert not (ws / "grading-rules.json").exists()
    R.read_rules(ws)
    assert (ws / "grading-rules.json").is_file()


# ---------------- 扩展：词表覆盖 ----------------
def test_vocab_override_merges_terms(ws: Path):
    from assist.grading import vocab as V
    V.add_term(ws, "动量守恒", aliases=["动量守恒定律"])
    E.ensure(ws)
    (ws / "extensions" / "knowledge-terms.json").write_text(
        json.dumps({"terms": [{"term": "完全弹性碰撞", "source": "human"}]},
                   ensure_ascii=False), encoding="utf-8")
    terms = {t["term"] for t in V.load_vocab(ws)["terms"]}
    assert {"动量守恒", "完全弹性碰撞"} <= terms
    assert V.canonical(V.load_vocab(ws), "动量守恒定律") == "动量守恒"


def test_vocab_override_wins_on_same_term(ws: Path):
    from assist.grading import vocab as V
    V.add_term(ws, "惯性", aliases=["旧别名"])
    E.ensure(ws)
    (ws / "extensions" / "knowledge-terms.json").write_text(
        json.dumps({"terms": [{"term": "惯性", "aliases": ["新别名"]}]},
                   ensure_ascii=False), encoding="utf-8")
    hit = next(t for t in V.load_vocab(ws)["terms"] if t["term"] == "惯性")
    assert hit["aliases"] == ["新别名"]


# ---------------- 护栏写接口 ----------------
def test_write_limits_ok_and_persisted(ws: Path):
    rep = L.write_limits(ws, {"maxCallsPerSession": 60})
    assert rep["ok"] and L.read_limits(ws)["maxCallsPerSession"] == 60
    assert (ws / "atopia" / "limits.json").is_file()


def test_write_limits_rejects_over_hard_cap(ws: Path):
    rep = L.write_limits(ws, {"maxCallsPerSession": 999999})
    assert rep["ok"] is False
    assert "硬顶" in rep["error"]
    assert L.read_limits(ws)["maxCallsPerSession"] == L.DEFAULTS["maxCallsPerSession"]


def test_write_limits_rejects_unknown_and_nonpositive(ws: Path):
    assert L.write_limits(ws, {"bogus": 1})["ok"] is False
    assert L.write_limits(ws, {"maxCallsPerSession": 0})["ok"] is False
    assert L.write_limits(ws, {"maxCallsPerSession": "abc"})["ok"] is False


def test_write_limits_journaled(ws: Path):
    L.write_limits(ws, {"callTimeoutSeconds": 90})
    jl = (ws / "atopia" / "journal.jsonl").read_text(encoding="utf-8")
    assert "limits.write" in jl and "90" in jl


# ---------------- 升级不触碰 extensions ----------------
def test_snapshot_and_untouched(ws: Path):
    E.ensure(ws)
    f = ws / "extensions" / "rules" / "grading-rules.json"
    f.write_text(json.dumps({"types": {"qa": {"perMissingPointDeduct": 9}}}),
                 encoding="utf-8")
    before = E.snapshot(ws)
    assert "rules/grading-rules.json" in before
    # 模拟"升级流程"：读取扩展、生成内置文件——**不得改动扩展**
    from assist.grading import rules as R
    R.read_rules(ws)
    R.type_rules(ws, "qa")
    after = E.snapshot(ws)
    assert E.assert_untouched(before, after) == []


def test_assert_untouched_detects_modification(ws: Path):
    E.ensure(ws)
    f = ws / "extensions" / "tools" / "a.json"
    f.write_text('{"name":"kb.stats","level":"L2"}', encoding="utf-8")
    before = E.snapshot(ws)
    f.write_text('{"name":"kb.stats","level":"L3"}', encoding="utf-8")
    problems = E.assert_untouched(before, E.snapshot(ws))
    assert problems and "被修改" in problems[0]


def test_assert_untouched_detects_deletion(ws: Path):
    E.ensure(ws)
    f = ws / "extensions" / "tools" / "a.json"
    f.write_text("{}", encoding="utf-8")
    before = E.snapshot(ws)
    f.unlink()
    assert any("被删除" in p for p in E.assert_untouched(before, E.snapshot(ws)))


def test_ensure_does_not_clobber_existing(ws: Path):
    E.ensure(ws)
    f = ws / "extensions" / "rules" / "grading-rules.json"
    f.write_text('{"x": 1}', encoding="utf-8")
    E.ensure(ws)
    assert f.read_text(encoding="utf-8") == '{"x": 1}'

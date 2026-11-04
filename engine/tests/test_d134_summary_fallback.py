"""D134-T4/T5：`summary` 题双轨评阅（资料口径 / 保底口径）。

用户诉求（原名）："如果不使用实时的课堂教学内容，可否安排一个批阅 summary 题目的
托底方法？比如只让 llm 判断转写内容里面是否有知识点总结、公式推导、示意图画制、
以及合理的回答内容长度等。"

锁定口径（docs/83 §4 T4/T5）：
1. 有 `知识点清单.md` → 资料口径，`summary_basis="materials"`，**不叠加**保底口径；
2. 无资料 → 保底口径，`summary_basis="heuristic"`：
   - 四维判定（知识点总结 / 公式推导 / 示意图 / 长度）；
   - **缺项不扣分**（没资料就没资格判漏了什么）；
   - 唯一可扣：**总结过于简略**（字数按转写原文重算，不信模型自报）；
3. 无资料时**禁止编造** `knowledge_missing`；
4. `rubric_enabled(summary)` 仅在有已确认资料时为 True（否则让模型编造"本章该讲什么"）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from assist.grading import evaluate as EV
from assist.grading import prompts as PR
from assist.grading import rules as R


@pytest.fixture()
def ws(tmp_path):
    d = tmp_path / "ws"
    d.mkdir()
    return d


def _summary_item(**kw):
    it = {"序号": "2", "kind": "summary", "chap": "chap04",
          "content": "请总结本堂课的主要内容。", "tag": "summary"}
    it.update(kw)
    return it


def _analysis(**q):
    base = {"id": "2", "reasoning": {"status": "ok", "note": ""},
            "correct_points": [], "errors": [], "confidence": "high",
            "has_diagram": True}
    base.update(q)
    return {"questions": [base], "summary": "", "guidance": "",
            "strengths": [], "weaknesses": []}


# ---------------- 保底口径：prompt ----------------
def test_fallback_block_requires_heuristic_basis(ws):
    fb = R.summary_fallback(ws)
    assert fb["enabled"] is True
    block = PR.summary_fallback_block(fb)
    assert "heuristic" in block
    assert "知识点" in block and "公式" in block and "示意图" in block
    assert "长度" in block


def test_prompt_without_materials_uses_fallback(ws):
    p = EV.build_user_prompt([_summary_item()], "学生作答……", "张三", ws=ws)
    assert "通用保底标准" in p
    assert "heuristic" in p


def test_prompt_with_materials_uses_materials_basis(ws):
    from assist.files import materials as M
    d = M.ensure_chap(ws, "chap04")
    (d / M.KNOW_MD).write_text("## 核心知识点\n- 动量守恒\n- 冲量定理\n", encoding="utf-8")

    p = EV.build_user_prompt([_summary_item()], "学生作答……", "张三", ws=ws)
    assert "本堂课应掌握的知识点" in p
    assert '`summary_basis` 必须填 `"materials"`' in p
    # **不叠加**保底口径（避免双重扣分）
    assert "通用保底标准" not in p


def test_fallback_disabled_reverts_to_old_behavior(ws):
    """把 fallback.enabled 关掉 → 行为与 D130 完全一致（prompt 不含保底段）。"""
    data = R.read_rules(ws)
    data["types"]["summary"]["fallback"]["enabled"] = False
    R.write_rules(ws, data)
    assert R.summary_fallback(ws) == {}
    p = EV.build_user_prompt([_summary_item()], "学生作答……", "张三", ws=ws)
    assert "通用保底标准" not in p


# ---------------- 保底口径：计分 ----------------
def test_heuristic_missing_items_do_not_deduct(ws):
    """保底模式下缺三项（知识点/公式/示意图）**不扣分**。"""
    item = _summary_item()
    a = _analysis(covered={"知识点与概念": False, "重要公式及推导": False, "示意图": False},
                  summary_basis="heuristic", answer_chars=400)
    r = EV.score_from_analysis(a, items=[item], ws=ws)
    assert "未完成" not in " ".join(r["deductions"])
    assert r["total_score"] == 100


def test_heuristic_too_short_deducts(ws):
    """保底模式唯一可扣：总结过于简略（<minChars）。"""
    item = _summary_item()
    fb = R.summary_fallback(ws)
    a = _analysis(covered={"知识点与概念": True, "重要公式及推导": True, "示意图": True},
                  summary_basis="heuristic",
                  answer_chars=max(0, fb["minChars"] - 50))
    r = EV.score_from_analysis(a, items=[item], ws=ws)
    assert any("过于简略" in d for d in r["deductions"])
    assert r["total_score"] == 100 - fb["minCharsDeduct"]


def test_heuristic_uses_transcript_chars_not_model_claim(ws):
    """字数以转写原文重算：模型自报很长，但原文很短 → 仍判过简。"""
    item = _summary_item()
    fb = R.summary_fallback(ws)
    a = _analysis(covered={"知识点与概念": True, "重要公式及推导": True, "示意图": True},
                  summary_basis="heuristic", answer_chars=9999,   # 模型撒谎
                  answer_text="只写了一句。")
    r = EV.score_from_analysis(a, items=[item], ws=ws)
    assert any("过于简略" in d for d in r["deductions"])


def test_materials_basis_still_deducts_missing_items(ws):
    """资料口径：缺项照常扣（这是原有 D130 行为，不能被保底口径放松）。"""
    item = _summary_item()
    a = _analysis(covered={"知识点与概念": False, "重要公式及推导": True, "示意图": True},
                  summary_basis="materials", answer_chars=400)
    r = EV.score_from_analysis(a, items=[item], ws=ws)
    assert any("未完成" in d for d in r["deductions"])
    assert r["total_score"] < 100


# ---------------- 降级可见 ----------------
def test_summary_basis_recorded_in_result(ws, tmp_path):
    a = _analysis(summary_basis="heuristic")
    r = EV.build_result_from_analysis(a, student="张三", items=[_summary_item()], ws=ws)
    assert r.get("summary_basis") == "heuristic"


def test_feedback_md_explains_heuristic(ws):
    a = _analysis(summary_basis="heuristic")
    r = EV.build_result_from_analysis(a, student="张三", items=[_summary_item()], ws=ws)
    md = r["feedback_md"]
    assert "通用标准" in md
    assert "不判断漏掉了哪些具体知识点" in md


def test_feedback_md_not_added_when_materials(ws):
    a = _analysis(summary_basis="materials")
    r = EV.build_result_from_analysis(a, student="张三", items=[_summary_item()], ws=ws)
    assert "关于总结题" not in r["feedback_md"]


# ---------------- T5：要点生成门槛 ----------------
def test_rubric_disabled_for_summary_without_materials(ws):
    assert R.rubric_enabled(ws, "summary", chap="chap04") is False


def test_rubric_enabled_for_summary_with_materials(ws):
    from assist.files import materials as M
    d = M.ensure_chap(ws, "chap04")
    (d / M.KNOW_MD).write_text("## 核心知识点\n- 动量守恒\n", encoding="utf-8")
    assert R.rubric_enabled(ws, "summary", chap="chap04") is True


def test_copy_still_never_generates_rubric(ws):
    assert R.rubric_enabled(ws, "copy") is False


def test_fallback_config_validation(ws):
    data = R.read_rules(ws)
    data["types"]["summary"]["fallback"]["minChars"] = -5
    errs = R.validate_rules(data)
    assert any("fallback.minChars" in e for e in errs)


def test_default_fallback_is_conservative(ws):
    """默认必须保守：缺项扣 0，只对过简扣 5。"""
    fb = R.summary_fallback(ws)
    assert fb["missingItemDeduct"] == 0
    assert fb["minCharsDeduct"] == 5
    assert fb["minChars"] > 0


# ---------------- T5c：CLI 门槛提示 ----------------
def test_rules_generate_summary_without_materials_points_to_materials(ws):
    """无资料时 `rules generate --kind summary` **明确指引**去整理资料，不静默产出。"""
    from click.testing import CliRunner

    from assist.cli import cli
    r = CliRunner().invoke(cli, ["rules", "generate", "--kind", "summary",
                                 "--chap", "chap04", "-w", str(ws)])
    assert r.exit_code == 0
    out = json.loads(r.output)
    assert out["skipped"] is True
    assert "howTo" in out and any("materials confirm" in x for x in out["howTo"])
    assert "保底口径" in out["fallback"]


def test_rules_generate_summary_requires_chap(ws):
    from click.testing import CliRunner

    from assist.cli import cli
    r = CliRunner().invoke(cli, ["rules", "generate", "--kind", "summary",
                                 "-w", str(ws)])
    assert r.exit_code != 0
    assert "--chap" in r.output


def test_ai_solve_summary_skips_rubric_without_materials(ws, monkeypatch):
    """`kb ai-solve --with-rubric` 在 summary 上同样遵循资料门槛（两个入口同口径）。"""
    from click.testing import CliRunner

    from assist import cli as CLI
    captured = {}

    def fake_solve(ws_, targets, **kw):
        captured.update(kw)
        return {"ok": True, "written": []}

    monkeypatch.setattr("assist.grading.solve.list_targets",
                        lambda *a, **k: [{"qid": "1", "content": "x", "chap": "chap04"}])
    monkeypatch.setattr("assist.grading.solve.solve_targets", fake_solve)
    r = CliRunner().invoke(CLI.cli, ["kb", "ai-solve", "--kb-kind", "summary",
                                     "--chap", "chap04", "--with-rubric",
                                     "--apply", "-w", str(ws)])
    # 无论 solve 是否被调，都不得带 with_rubric=True
    assert captured.get("with_rubric", False) is False

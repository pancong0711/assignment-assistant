"""D144：删除规则卡里的「为本题型生成 AI 评阅要点」开关。

为什么删（教师指出）：
1. 它挂在「**评阅规则卡**」里，但**批阅根本不读它** —— 批阅读的是
   `mode` / 扣分数值 / `checklist`。放在评阅规则里天然误导；
2. 它与「⑦ 题库 AI 作答 → 同时生成评阅要点」是**两个入口、两套规则**
   （后者只对 copy/summary 受限，前者对所有题型生效），容易让人困惑；
3. 规则卡应当只回答"**怎么扣分**"，生成不生成要点与扣分无关。

改为**代码口径**（不需要教师配置）：
- `copy`：永不自动生成（以原文为唯一依据），需要时显式 `--force`；
- `summary`：仅当本章有已确认的 `知识点清单.md`；
- 其它：允许。
"""
from __future__ import annotations

import pytest

from assist.grading import rules as R


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "kb").mkdir()
    return tmp_path


def test_field_absent_from_defaults():
    for kind, cfg in (R.DEFAULT_RULES.get("types") or {}).items():
        assert "generateRubric" not in cfg, f"默认规则 types.{kind} 仍含 generateRubric"


def test_legacy_config_with_field_is_tolerated(ws):
    """旧配置里残留该字段时**不报错**（向后兼容），但也不再生效。"""
    data = R.read_rules(ws)
    data["types"]["qa"]["generateRubric"] = True
    errs = R.validate_rules(data)
    assert not any("generateRubric" in e for e in errs)


def test_grading_does_not_read_the_field(ws):
    """**核心断言**：改这个字段不影响批阅计分。

    构造两套配置（字段 True / False），同一份 analysis 的扣分必须完全一致。
    """
    from assist.grading import evaluate as EV

    item = {"序号": "1", "kind": "qa", "content": "题", "tag": "qa"}
    analysis = {"questions": [{
        "id": "1", "reasoning": {"status": "ok"},
        "correct_points": [], "has_diagram": True, "confidence": "high",
        "key_points": [{"point": "要点A", "answered": False, "evidence": ""}],
    }]}
    results = []
    for flag in (True, False):
        data = R.read_rules(ws)
        data["types"]["qa"]["generateRubric"] = flag
        R.write_rules(ws, data)
        results.append(EV.score_from_analysis(analysis, items=[item], ws=ws)["total_score"])
    assert results[0] == results[1], f"批阅计分被该字段影响：{results}"


def test_copy_never_generates(ws):
    assert R.rubric_enabled(ws, "copy") is False


def test_other_kinds_allowed(ws):
    for k in ("problems", "qa", "distinguish", "innovation", "translation"):
        assert R.rubric_enabled(ws, k) is True, k


def test_summary_needs_confirmed_materials(ws):
    assert R.rubric_enabled(ws, "summary", chap="chap04") is False
    from assist.files import materials as M
    d = M.ensure_chap(ws, "chap04")
    (d / M.KNOW_MD).write_text("## 核心知识点\n- 动量守恒\n", encoding="utf-8")
    assert R.rubric_enabled(ws, "summary", chap="chap04") is True

"""D151：提示词模板扩展到 5 类 system prompt（可改/可存/可删）。

关键口径：
- **不选模板 = 内置默认**（与改动前完全一致，有测试锁定）；
- 各类**互相隔离**（evaluate 的默认不可被 ai-solve 的派生影响）；
- 内置模板不可删。
"""
from __future__ import annotations

import pytest

from assist.files import prompts as P


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "kb").mkdir()
    return tmp_path


def test_all_categories_exist(ws):
    assert set(P.CATEGORIES) >= {"ai-solve", "transcribe", "evaluate",
                                 "solve", "rubric", "termnorm"}


def test_empty_template_falls_back_to_builtin(ws):
    """**核心**：默认模板内容为空 → 用代码内置（不选=现状）。"""
    assert P.system_prompt(ws, "evaluate", "BUILTIN") == "BUILTIN"
    assert P.system_prompt(ws, "rubric", "BUILTIN") == "BUILTIN"


def test_custom_template_overrides(ws):
    """显式设为默认后才覆盖（新建模板不会自动抢默认）。"""
    P.save_template(ws, pid="mine", name="我的", text="CUSTOM", make_default=True,
                    category="evaluate")
    assert P.system_prompt(ws, "evaluate", "BUILTIN") == "CUSTOM"


def test_new_template_does_not_steal_default(ws):
    """**安全**：新建模板不自动成为默认（避免误改全局行为）。"""
    P.save_template(ws, pid="mine", name="我的", text="CUSTOM", category="evaluate")
    assert P.system_prompt(ws, "evaluate", "BUILTIN") == "BUILTIN"


def test_categories_are_isolated(ws):
    """evaluate 设了默认，不能影响 rubric / solve。"""
    P.save_template(ws, pid="mine", name="x", text="EVAL", make_default=True,
                    category="evaluate")
    assert P.system_prompt(ws, "evaluate", "B") == "EVAL"
    assert P.system_prompt(ws, "rubric", "B") == "B"
    assert P.system_prompt(ws, "solve", "B") == "B"


def test_list_per_category(ws):
    P.save_template(ws, pid="e1", name="E1", text="X", category="evaluate")
    assert "e1" in [t["id"] for t in P.list_templates(ws, "evaluate")]
    assert "e1" not in [t["id"] for t in P.list_templates(ws, "rubric")]


def test_builtin_not_deletable(ws):
    r = P.delete_template(ws, "standard", category="evaluate")
    assert r["ok"] is False
    assert "内置" in r["error"]


def test_delete_custom_ok(ws):
    P.save_template(ws, pid="tmp1", name="T", text="X", category="solve")
    assert P.delete_template(ws, "tmp1", category="solve")["ok"] is True


def test_set_default_clears_others_in_same_category(ws):
    P.save_template(ws, pid="a", name="A", text="A", make_default=True, category="rubric")
    P.save_template(ws, pid="b", name="B", text="B", make_default=True, category="rubric")
    items = {t["id"]: t for t in P.list_templates(ws, "rubric")}
    assert items["b"]["default"] is True
    assert items["a"]["default"] is False


def test_unknown_category_falls_back(ws):
    """未知类别不能炸（回落内置）。"""
    assert P.system_prompt(ws, "nope", "B") == "B"


def test_ai_solve_category_still_works(ws):
    """原有 ai-solve（作答要求片段）不受影响。"""
    tpl = P.default_template(ws, "ai-solve")
    assert tpl and tpl.get("text")

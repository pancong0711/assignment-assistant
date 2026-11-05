"""D168-B6：工具面治理 + 权限收紧。

教师关切（docs/113-D169 §2）：
> 给 atopia 准备越来越多的工具，可能导致后面使用的时候出现错误，
> 我觉得有必要对这些工具做优化，一定要写好注释/说明等。

安全模型（§1.3）：
> AI 只能写 `atopia/**`；kb/materials 的写入只能由引擎执行（教师确认后）。
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from assist.atopia import registry as R


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    (tmp_path / "kb").mkdir()
    return tmp_path


# ---------------- 权限收紧 ----------------

@pytest.mark.parametrize("name", [
    "kb.write",                     # 直接覆盖题库
    "kb.tag-knowledge.apply",       # 直接改写知识点
    "kb.check-knowledge.apply",     # 直接改写术语
])
def test_dangerous_kb_writes_are_l3(name):
    """**核心安全验收**：AI 不得直接写生效数据（题库 xlsx）。"""
    assert R.get_tool(name).level == R.L3


def test_l3_cannot_be_lowered_by_extension(ws):
    """扩展只能升不能降——L3 必须保持 L3。"""
    from assist.atopia import paths as P
    d = P.extensions_dir(ws) / "tools"
    d.mkdir(parents=True, exist_ok=True)
    (d / "x.json").write_text('{"name": "kb.write", "level": "L0"}', encoding="utf-8")
    assert R.effective_tool(ws, "kb.write").level == R.L3


def test_suggest_kb_is_safe_alternative():
    """有安全的替代路径：写建议文件（不改题库）。"""
    t = R.get_tool("atopia.suggest-kb")
    assert t.level == R.L2
    assert t.group == "atopia"
    assert "不改题库" in t.when


# ---------------- 分组暴露 ----------------

def test_every_tool_has_group_and_when():
    """每个工具都必须有分组和「何时用」说明（给模型看的）。"""
    for t in R.BUILTIN_TOOLS:
        assert t.group in R.GROUPS, f"{t.name} 分组非法：{t.group}"
        assert t.when.strip(), f"{t.name} 缺少 when 说明"
        assert len(t.when) >= 8, f"{t.name} 的 when 太短，不足以指导模型"


def test_tools_by_group_narrows_choice(ws):
    """分组后选择空间显著变小（31 → 个位数）。"""
    all_tools = R.tools_by_group(ws, None)
    kb_only = R.tools_by_group(ws, ["kb"])
    assert len(all_tools) == len(R.BUILTIN_TOOLS)
    assert 0 < len(kb_only) < len(all_tools) / 2
    assert all(t.group == "kb" for t in kb_only)


def test_tools_by_group_multiple(ws):
    got = R.tools_by_group(ws, ["kb", "fs"])
    assert {t.group for t in got} == {"kb", "fs"}


def test_group_summary_covers_all(ws):
    rep = R.group_summary(ws)
    assert sum(rep["groups"].values()) == len(R.BUILTIN_TOOLS)
    assert rep["labels"]


# ---------------- 工具说明（给模型） ----------------

def test_tool_list_text_uses_when(ws):
    """工具清单给模型看的是 `when`（何时用），不是 summary（这是什么）。"""
    from assist.atopia import agent
    tools = [t for t in R.tools_by_group(ws, ["fs"]) if t.level != R.L3]
    text = agent._tool_list_text(tools)
    assert tools[0].when in text


def test_l3_tools_hidden_from_model(ws):
    from assist.atopia import agent
    tools = R.tools_by_group(ws, None)
    usable = [t for t in tools if t.level != R.L3]
    text = agent._tool_list_text(usable)
    assert "kb.write" not in text


# ---------------- 建议写（安全替代） ----------------

def test_save_suggest_writes_to_atopia_only(ws):
    from assist.atopia import work as W
    W.ensure_feature(ws, "26C1")
    rep = W.save_suggest(ws, "26C1", {"changes": [
        {"qid": "chap04-c1", "related": "库仑定律", "reason": "补全"}]})
    assert rep["ok"] and rep["count"] == 1
    assert Path(rep["file"]).is_relative_to(ws / "atopia")
    # **不动题库**
    assert not (ws / "kb" / "qa.xlsx").exists()


def test_save_suggest_refuses_empty(ws):
    from assist.atopia import work as W
    W.ensure_feature(ws, "26C1")
    with pytest.raises(W.WorkError):
        W.save_suggest(ws, "26C1", {"changes": []})


def test_list_suggests(ws):
    from assist.atopia import work as W
    W.ensure_feature(ws, "26C1")
    W.save_suggest(ws, "26C1", {"changes": [{"qid": "x"}]})
    items = W.list_suggests(ws, "26C1")
    assert len(items) == 1 and items[0]["status"] == "pending"


# ---------------- 只读接口必须在 do_GET ----------------

def test_readonly_routes_are_in_do_get():
    """**回归**：只读 GET 接口放错到 do_POST 会静默 302 到 Pages。

    D151 的 /prompts/templates 与 D168-B6 的 /atopia/tool-groups 都踩过这个坑。
    """
    from assist import serve as S
    src = inspect.getsource(S.Handler)
    i_get = src.index("def do_GET(")
    for route in ('"/prompts/templates"', '"/atopia/tool-groups"',
                  '"/kb/examples"', '"/analysis/error'):
        idx = src.index(route)
        assert idx > i_get, f"{route} 必须在 do_GET 中（前端用 GET 调用）"

"""D168-B3：知识点分析可视化（组合份额算法 + 出图 + 依赖缺失可读提示）。

教师质疑（docs/113-D169 §4.1）：
> 这些包其实不进到我们的 engine 里，只是作为一个依赖包，需要用户下载，
> 引用这些包应该不会大幅增加 engine 的大小吧？有现成的工具直接用不是很方便吗？

→ 教师判断正确，已改用 matplotlib/networkx（`[viz]` optional extra）。
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from assist.grading import viz


def _rec(student, questions, tag="top"):
    return {"student": student, "tag": tag, "analysis": {"questions": [
        {"id": qid, "errors": [{"knowledge": k} for k in ks]} for qid, ks in questions]}}


@pytest.fixture()
def recs():
    return [_rec("s1", [("1", ["A", "B"]), ("2", ["A", "B"]), ("3", ["B", "C"])])]


# ---------------- 组合份额（移植 2508，去 pandas） ----------------

def test_share_sums_to_one(recs):
    sh = viz.cooccurrence_share(recs, n=2)
    assert sh["total"] == 3
    total = sum(sh["combos"].values())
    # 题1/2 各 1 组 C(2,2)=1；题3 C(2,2)=1 → T=3
    assert sh["T"] == 3
    assert math.isclose(total, 1.0, rel_tol=1e-6)


def test_share_values(recs):
    sh = viz.cooccurrence_share(recs, n=2)
    assert math.isclose(sh["combos"][("A", "B")], 2 / 3, rel_tol=1e-6)
    assert math.isclose(sh["combos"][("B", "C")], 1 / 3, rel_tol=1e-6)


def test_node_edge_hierarchy_identity(recs):
    """层级恒等式：Σ_{e∋w} E(e) = (n−1)·V(w)（2508 口径）。"""
    V, E, _sh = viz.node_edge_potential(recs, n=2)
    for w in V:
        total_e = sum(v for (a, b), v in E.items() if w in (a, b))
        assert math.isclose(total_e, (2 - 1) * V[w], rel_tol=1e-6), f"{w} 不满足恒等式"


def test_empty_records():
    assert viz.cooccurrence_share([])["total"] == 0
    assert viz.node_edge_potential([])[0] == {}


def test_region_partition_groups_coupled(recs):
    part = viz.region_partition(recs, n=2)["partition"]
    assert part["A"] == part["B"], "强耦合的 A/B 应同区"


def test_alias_merge_applies():
    vocab = {"terms": [{"term": "动量守恒", "aliases": ["动量守恒定律"]}]}
    recs = [_rec("s1", [("1", ["动量守恒", "动量守恒定律"])])]
    sh = viz.cooccurrence_share(recs, n=2, vocab=vocab)
    # 归并后同题只剩 1 个术语 → 无组合
    assert sh["combos"] == {}


# ---------------- 依赖探测（可读提示） ----------------

def test_available_reports_hint_when_missing(monkeypatch):
    """依赖缺失时给**可读提示**，不是 ImportError 堆栈（docs/113 §4.4）。"""
    import builtins
    real = builtins.__import__

    def fake(name, *a, **kw):
        if name in ("matplotlib", "networkx"):
            raise ImportError("No module named " + name)
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake)
    out = viz.available()
    assert out["ok"] is False
    assert set(out["missing"]) == {"matplotlib", "networkx"}
    assert "pip install -e engine[viz]" in out["hint"]


# ---------------- 出图（有依赖时） ----------------

@pytest.fixture()
def has_viz():
    return viz.available()["ok"]


def test_bar_chart_created(tmp_path, has_viz):
    if not has_viz:
        pytest.skip("未安装 matplotlib")
    items = [{"term": "A", "rate": 1.5}, {"term": "B", "rate": 0.5}]
    out = viz.bar_error_rates(items, tmp_path / "bar.png")
    assert out.is_file() and out.stat().st_size > 1000


def test_bar_chart_refuses_empty(tmp_path, has_viz):
    if not has_viz:
        pytest.skip("未安装 matplotlib")
    with pytest.raises(viz.VizUnavailable):
        viz.bar_error_rates([], tmp_path / "x.png")


def test_network_chart_created(tmp_path, has_viz):
    if not has_viz:
        pytest.skip("未安装 matplotlib")
    recs = [_rec("s1", [("1", ["A", "B"]), ("2", ["A", "B"]), ("3", ["B", "C"])]),
            _rec("s2", [("1", ["A", "B"]), ("2", ["B", "C"])])]
    out = viz.cooccurrence_network(recs, tmp_path / "net.png",
                                   rates={"A": 1.0, "B": 2.0, "C": 0.5})
    assert out.is_file() and out.stat().st_size > 1000


def test_network_chart_refuses_no_edges(tmp_path, has_viz):
    if not has_viz:
        pytest.skip("未安装 matplotlib")
    with pytest.raises(viz.VizUnavailable):
        viz.cooccurrence_network([_rec("s1", [("1", ["A"])])], tmp_path / "x.png")

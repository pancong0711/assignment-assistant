"""D168 §2：知识点共现（含 tag 拆分 + 归一化关联 + 自然聚类）。

教师口径：
- 每个 tag **各画一张**共现图（top/middle 错法不同，混算会糊）；
- 归一化关联 = P(共现) / ∏P(单项)（2508 口径，我们现有朴素版缺这个）；
- 不做章节层级，用共现做**自然聚类**。
"""
from __future__ import annotations

from assist.grading import cooccurrence as C


def _rec(student, tag, questions):
    return {"student": student, "tag": tag,
            "analysis": {"questions": [
                {"id": qid, "errors": [{"knowledge": k} for k in ks]}
                for qid, ks in questions]}}


def test_occurrence_prob():
    recs = [_rec("s1", "top", [("1", [["A"]]), ("2", [["A", "B"]])])]
    r = C.occurrence_prob(recs)
    assert r["total"] == 2
    assert r["terms"]["A"] == {"questions": 2, "rate": 1.0}
    assert r["terms"]["B"] == {"questions": 1, "rate": 0.5}


def test_pair_cooccurrence_rate():
    """共现率 = 同题内同时出现的题数 / 总题数。"""
    recs = [_rec("s1", "top", [
        ("1", [["A", "B"]]),
        ("2", [["A", "B"]]),
        ("3", [["A"]]),
    ])]
    co = C.cooccurrence(recs, n=2)
    assert co["total"] == 3
    ab = next(c for c in co["combos"] if set(c["terms"]) == {"A", "B"})
    assert ab["count"] == 2
    assert ab["rate"] == round(2 / 3, 4)


def test_association_below_one_when_independent():
    """关联 = P(AB)/(P(A)P(B))；独立时接近 1。"""
    recs = [_rec("s1", "t", [
        ("1", [["A", "B"]]),
        ("2", [["A"]]),
        ("3", [["B"]]),
        ("4", [["C"]]),
    ])]
    co = C.cooccurrence(recs, n=2)
    ab = next(c for c in co["combos"] if set(c["terms"]) == {"A", "B"})
    # P(A)=0.5, P(B)=0.5, P(AB)=0.25 → 0.25/0.25 = 1.0
    assert ab["association"] == 1.0


def test_association_above_one_when_coupled():
    """A、B 总在同题 → 关联 > 1（比随机更常同现）。"""
    recs = [_rec("s1", "t", [
        ("1", [["A", "B"]]),
        ("2", [["A", "B"]]),
        ("3", [["A", "B"]]),
        ("4", [["A"]]),
        ("5", [["B"]]),
        ("6", [["C"]]),
    ])]
    co = C.cooccurrence(recs, n=2)
    ab = next(c for c in co["combos"] if set(c["terms"]) == {"A", "B"})
    # P(A)=4/6, P(B)=4/6, P(AB)=3/6 → (0.5)/((2/3)^2)=1.125
    assert ab["association"] == 1.125


def test_tag_split_gives_separate_graphs():
    """**核心验收**：不同 tag 的共现图必须独立。"""
    recs = [
        _rec("s1", "top", [("1", [["A", "B"]])]),
        _rec("s2", "middle", [("1", [["C", "D"]])]),
    ]
    r = C.by_tag(recs, n=2)
    assert r["tags"] == ["middle", "top"]
    top_terms = {t for c in r["byTag"]["top"]["combos"] for t in c["terms"]}
    mid_terms = {t for c in r["byTag"]["middle"]["combos"] for t in c["terms"]}
    assert top_terms == {"A", "B"}
    assert mid_terms == {"C", "D"}
    assert not (top_terms & mid_terms)


def test_tag_filter_leaves_only_that_tag():
    recs = [
        _rec("s1", "top", [("1", [["A", "B"]])]),
        _rec("s2", "middle", [("1", [["A", "C"]])]),
    ]
    co = C.cooccurrence(recs, n=2, tag="top")
    terms = {t for c in co["combos"] for t in c["terms"]}
    assert terms == {"A", "B"}


def test_alias_merge_in_cooccurrence():
    vocab = {"terms": [{"term": "动量守恒", "aliases": ["动量守恒定律"]}]}
    recs = [_rec("s1", "top", [("1", [["动量守恒", "动量守恒定律"]])])]
    co = C.cooccurrence(recs, n=2, vocab=vocab)
    # 归并后同一题只剩 1 个术语 → 无 2 元组合
    assert co["combos"] == []


def test_empty_records():
    assert C.cooccurrence([]) == {"total": 0, "combos": []}
    assert C.by_tag([])["overall"]["total"] == 0


def test_natural_clusters_group_coupled_terms():
    """自然聚类：强耦合的术语归为一类（不依赖章节）。"""
    recs = [_rec("s1", "t", [
        ("1", [["A", "B"]]),
        ("2", [["A", "B"]]),
        ("3", [["C", "D"]]),
        ("4", [["C", "D"]]),
    ])]
    cl = C.natural_clusters(recs, n=2)
    members = [set(c["members"]) for c in cl["clusters"]]
    assert {"A", "B"} in members
    assert {"C", "D"} in members


def test_clusters_exclude_singletons():
    recs = [_rec("s1", "t", [("1", [["A", "B"]]), ("2", [["Z"]])])]
    cl = C.natural_clusters(recs, n=2)
    all_members = {m for c in cl["clusters"] for m in c["members"]}
    assert "Z" not in all_members, "孤立点不应单独成类"

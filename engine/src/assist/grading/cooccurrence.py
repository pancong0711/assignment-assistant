"""cooccurrence.py — D168 §2：知识点共现（含 tag 拆分 + 归一化关联）。

## 两套共现图（教师提出，docs/112-D168 §2.1）

| | 标准共现图 | 作答共现图（本模块） |
|---|---|---|
| 数据源 | 例题知识点 | 批阅 `errors[].knowledge[]` |
| 含义 | 老师怎么教 | 学生怎么错 |

## tag 必须拆开（§2.2）

教师原话：
> 每一个 tag 其实也对应一个知识点共现图……对于 tag 来讲，是要拆开的。

理由：top 错"高阶综合应用"、middle 错"基础概念混淆"，混算会糊成一团。

## 口径（沿用 2508，docs/110 §1）

- 分析单元 = **一道题**（同一题内多个知识点同时出错 = 共现）；
- 共现率 `P = 含该组合的题数 / 总题数`；
- **归一化关联** `= P(共现) / ∏P(单项)` —— 衡量"比随机同时出现强多少"。
  这是现有 `teacher_report` 朴素版**缺的**（它只数同时出错的人数）。
"""
from __future__ import annotations

from collections import Counter
from itertools import combinations


def _term_question_map(records: "list[dict]", *, tag: str = "") -> dict:
    """题号 → 该题内出错的知识点集合（可按 tag 过滤学生）。"""
    q2terms: dict[str, set[str]] = {}
    for r in records or []:
        if not isinstance(r, dict):
            continue
        if tag and str(r.get("tag") or "").strip() != tag:
            continue
        for q in ((r.get("analysis") or {}).get("questions") or []):
            if not isinstance(q, dict):
                continue
            qid = str(q.get("id") or "?")
            for e in (q.get("errors") or []):
                if not isinstance(e, dict):
                    continue
                if str(e.get("confidence") or "high").lower() == "low":
                    continue
                from .error_stats import _terms_of
                for t in _terms_of(e.get("knowledge")):
                    q2terms.setdefault(qid, set()).add(t)
    return q2terms


def occurrence_prob(records: "list[dict]", *, tag: str = "") -> dict:
    """一阶：每个知识点在多少比例的题里出错（供词云/热度）。"""
    q2 = _term_question_map(records, tag=tag)
    total = len(q2)
    if not total:
        return {"total": 0, "terms": {}}
    cnt = Counter()
    for terms in q2.values():
        for t in terms:
            cnt[t] += 1
    return {"total": total,
            "terms": {t: {"questions": c, "rate": round(c / total, 4)}
                      for t, c in cnt.items()}}


def cooccurrence(records: "list[dict]", *, n: int = 2, tag: str = "",
                 vocab: dict | None = None) -> dict:
    """n 元共现 + 归一化关联（docs/112-D168 §2）。

    返回 `{"total": 题数, "combos": [{terms, count, rate, association}]}`。
    `association` = 共现率 / ∏单项概率（>1 表示比随机更常同时出现）。
    """
    q2 = _term_question_map(records, tag=tag)
    total = len(q2)
    if not total:
        return {"total": 0, "combos": []}
    if vocab is not None:
        from .vocab import normalize_terms
        q2 = {k: set(normalize_terms(sorted(v), vocab)[0]) for k, v in q2.items()}
    single = Counter()
    combos = Counter()
    for terms in q2.values():
        ordered = sorted(terms)
        for t in ordered:
            single[t] += 1
        if len(ordered) < n:
            continue
        for c in combinations(ordered, n):
            combos[c] += 1
    out = []
    for combo, c in combos.items():
        rate = c / total
        # 归一化关联 = P(组合) / ∏P(单项)
        # （此前写成"rate 逐个除"——每除一次又把 total 乘回去，结果恒为 1.0，是个真 bug）
        denom = 1.0
        for t in combo:
            denom *= (single[t] / total)
        assoc = (rate / denom) if denom > 0 else 0.0
        out.append({"terms": list(combo), "count": c, "rate": round(rate, 4),
                    "association": round(assoc, 3)})
    out.sort(key=lambda x: (-x["association"], -x["count"]))
    return {"total": total, "combos": out}


def by_tag(records: "list[dict]", *, n: int = 2, vocab: dict | None = None) -> dict:
    """按 tag **各画一张**共现图（教师 §1.3.1 要求）。

    返回 {"overall": {...}, "byTag": {tag: {...}}}。
    """
    tags = sorted({str(r.get("tag") or "").strip()
                   for r in (records or []) if isinstance(r, dict)
                   and str(r.get("tag") or "").strip()})
    return {"overall": cooccurrence(records, n=n, vocab=vocab),
            "byTag": {t: cooccurrence(records, n=n, tag=t, vocab=vocab) for t in tags},
            "tags": tags}


# ---------------- 自然聚类（教师："不想做章节级别"） ----------------

def natural_clusters(records: "list[dict]", *, n: int = 2,
                     vocab: dict | None = None, min_edge: float = 0.0) -> dict:
    """基于共现关联做**自然聚类**（不依赖章节层级）。

    教师原话（docs/112-D168 §2.3/§3.4）：
    > 我们不想做章节级别，而是通过知识点共现情况做自然聚类分析，可以按类来查看，也可以查看全局。

    实现：取 n 元共现里 `association > 1`（比随机更常同现）的边建图，
    做**连通分量**聚类（轻量；2508 的 louvain 在 B3 引入可视化时再对拍）。

    返回 {"clusters": [{"id", "members", "size"}], "edges": [...]}。
    """
    co = cooccurrence(records, n=n, vocab=vocab)
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    edges = []
    for c in co["combos"]:
        if c["association"] <= 1.0 and c["count"] < 2:
            continue
        if len(c["terms"]) < 2:
            continue
        a, b = c["terms"][0], c["terms"][1]
        union(a, b)
        edges.append({"a": a, "b": b, "count": c["count"],
                      "association": c["association"]})
    groups: dict[str, list[str]] = {}
    for term in list(parent):
        groups.setdefault(find(term), []).append(term)
    clusters = []
    for i, (_, members) in enumerate(sorted(groups.items(),
                                            key=lambda kv: -len(kv[1])), start=1):
        if len(members) < 2:      # 孤立点不单独成类
            continue
        clusters.append({"id": f"c{i}", "members": sorted(members),
                         "size": len(members)})
    return {"clusters": clusters, "edges": edges, "totalQuestions": co["total"]}

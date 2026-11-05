"""viz.py — D168-B3：知识点分析可视化（PNG）。

## 设计（docs/113-D169 §4）

教师质疑得对：matplotlib **不会**让引擎体积暴涨（源码 zip 不变，依赖由用户下载）。
所以**直接用现成工具**，不手写渲染。

**分工铁律**（docs/113-D169 §5.3）：
- 引擎**算数 + 出图**（Python，`[viz]` optional extra）；
- 前端只 `<img src=...>` 显示，**不重写算法**；
- 将来要"点节点看明细"时：引擎算 x/y 坐标 → 前端画 SVG（**算法仍在 Python**）。

## 与 2508 的关系（docs/110-D167）

移植其**组合份额体系**（`cooccurrence_share` / `node_edge_potential`），
但**去掉 pandas**（引擎"去 pandas"原则），输入改用本项目的数据结构。

## 依赖缺失时的行为

`matplotlib` 未安装时**不抛 ImportError 堆栈**，返回可读错误：
「请重新运行 start.sh 安装依赖（或 pip install -e engine[viz]）」。
这是 docs/113-D169 §4.4 的要求——教师看不懂 import 异常。
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from loguru import logger

# 中文字体偏好（与 2508 同口径；缺失时回退默认字体并告警）
_CJK_FONTS = ["Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Zen Hei",
              "Microsoft YaHei", "SimHei", "PingFang SC", "DejaVu Sans"]


class VizUnavailable(RuntimeError):
    """可视化依赖未安装（可读错误，供 PWA 直接展示）。"""


def _import_plt():
    try:
        import matplotlib
        matplotlib.use("Agg")            # 无显示器环境（服务器/CLI）
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm
        from matplotlib import rcParams
    except ImportError as exc:  # noqa: BLE001
        raise VizUnavailable(
            "缺少可视化依赖（matplotlib/networkx）。请重新运行 start.sh / start.bat 安装依赖，"
            "或手动执行：pip install -e engine[viz]。原始错误：" + str(exc)) from None
    # 中文字体：能选到 CJK 就选，否则保持默认（中文会显示成方块，但图形仍可用）
    try:
        available = {f.name for f in fm.fontManager.ttflist}
        picked = [f for f in _CJK_FONTS if f in available]
        if picked:
            rcParams["font.sans-serif"] = picked + ["DejaVu Sans"]
        else:
            logger.warning("[可视化] 未找到中文字体，图中中文可能显示为方块")
        rcParams["axes.unicode_minus"] = False
    except Exception:  # noqa: BLE001 —— 字体配置失败不影响出图
        pass
    return plt


# ---------------- 组合份额计算（移植 2508，去 pandas） ----------------

def cooccurrence_share(records: "list[dict]", *, n: int = 2,
                       vocab: dict | None = None) -> dict:
    """组合份额：P_X = c_X / Σ_题 C(N_k, n)（组合级概率，Σ=1）。

    与 2508 `cooccurrence_share()` 同口径（docs/110 §1），
    输入换成我们的 `evaluations` 记录列表。
    """
    from .cooccurrence import _term_question_map
    q2 = _term_question_map(records)
    if vocab is not None:
        from .vocab import normalize_terms
        q2 = {k: set(normalize_terms(sorted(v), vocab)[0]) for k, v in q2.items()}
    total = len(q2)
    if not total:
        return {"total": 0, "combos": {}, "single": {}}
    single = Counter()
    cnt: Counter = Counter()
    T = 0
    for terms in q2.values():
        ordered = sorted(terms)
        for t in ordered:
            single[t] += 1
        if len(ordered) < n:
            continue
        T += math.comb(len(ordered), n)
        for c in combinations(ordered, n):
            cnt[c] += 1
    combos = {c: (k / T if T else 0.0) for c, k in cnt.items()}
    return {"total": total, "combos": combos, "counts": dict(cnt), "T": T,
            "single": {t: single[t] / total for t in single}}


def node_edge_potential(records: "list[dict]", *, n: int = 2,
                        vocab: dict | None = None) -> "tuple[dict, dict, dict]":
    """节点/边关联势（超图投影）。

    - V(w) = Σ_{X∋w} P_X；
    - E(w1,w2) = Σ_{X⊇{w1,w2}} P_X（2 阶时 E 即该组合份额）；
    - 层级恒等式：Σ_{e∋w} E(e) = (n−1)·V(w)。
    """
    sh = cooccurrence_share(records, n=n, vocab=vocab)
    V: dict[str, float] = defaultdict(float)
    E: dict[tuple[str, str], float] = defaultdict(float)
    for combo, P in sh["combos"].items():
        for w in combo:
            V[w] += P
        for i in range(len(combo)):
            for j in range(i + 1, len(combo)):
                E[tuple(sorted((combo[i], combo[j])))] += P
    return dict(V), dict(E), sh


def region_partition(records: "list[dict]", *, n: int = 2, max_edges: int = 80,
                     vocab: dict | None = None) -> dict:
    """社区划分（{术语: 区域号}），用于共现图的"圆圈聚类"。

    2508 用 louvain；这里用 **networkx 的 louvain**（同样 seed 固定，结果可复现）。
    单点社区并入 E 联系最强的区域（与 2508 一致，docs/110 §1）。
    """
    try:
        import networkx as nx
        from networkx.algorithms import community as nxcomm
    except ImportError as exc:  # noqa: BLE001
        raise VizUnavailable(f"缺少 networkx：{exc}") from None
    _V, E, sh = node_edge_potential(records, n=n, vocab=vocab)
    G = nx.Graph()
    for (a, b), w in sorted(E.items(), key=lambda kv: -kv[1])[:max_edges]:
        G.add_edge(a, b, weight=float(w))
    if G.number_of_nodes() == 0:
        return {"partition": {}, "E": E, "V": _V}
    comps = [set(c) for c in nxcomm.louvain_communities(G, weight="weight", seed=42) if c]

    def e_to(w: str, comp: set) -> float:
        return sum(E.get(tuple(sorted((w, o))), 0.0) for o in comp)

    changed = True
    while changed and len(comps) > 1:
        changed = False
        for c in [x for x in comps if len(x) == 1]:
            w = next(iter(c))
            best = max((x for x in comps if x is not c), key=lambda x: e_to(w, x),
                       default=None)
            if best is not None and e_to(w, best) > 0:
                best |= c
                comps.remove(c)
                changed = True
    part: dict[str, int] = {}
    for i, c in enumerate(sorted(comps, key=lambda x: -len(x)), start=1):
        for w in c:
            part[w] = i
    return {"partition": part, "E": E, "V": _V, "clusters": comps}


# ---------------- 出图 ----------------

def _loss_color(rate: float, vmax: float) -> "tuple[float, float, float, float]":
    """失误率 → 颜色（红高绿低，与 2508 词云/网络节点同语义）。"""
    import matplotlib.colors as mcolors
    t = 0.0 if vmax <= 0 else max(0.0, min(1.0, rate / vmax))
    return mcolors.to_rgba(plt_cmap()(t))


_CMAP = None


def plt_cmap():
    global _CMAP
    if _CMAP is None:
        import matplotlib
        _CMAP = matplotlib.colormaps.get_cmap("RdYlGn_r")
    return _CMAP


def bar_error_rates(items: "list[dict]", out: Path, *, title: str = "知识点加权失误率",
                    top: int = 20) -> Path:
    """横向条形图：失误率排行（唯一渲染入口，前端只显示图片）。"""
    plt = _import_plt()
    rows = sorted([x for x in (items or []) if float(x.get("rate") or 0) > 0],
                  key=lambda x: -float(x.get("rate") or 0))[:top]
    if not rows:
        raise VizUnavailable("没有失误数据，无法出图")
    labels = [str(r.get("term") or "") for r in rows][::-1]
    vals = [float(r.get("rate") or 0) for r in rows][::-1]
    fig, ax = plt.subplots(figsize=(8, max(3, 0.38 * len(rows) + 1.2)), dpi=140)
    bars = ax.barh(labels, vals, color=[_loss_color(v, max(vals)) for v in vals])
    ax.set_xlabel("加权失误率（次/人）")
    ax.set_title(title)
    for b, v in zip(bars, vals):
        ax.text(b.get_width(), b.get_y() + b.get_height() / 2, f" {v:.2f}",
                va="center", fontsize=8)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)
    return out


def cooccurrence_network(records: "list[dict]", out: Path, *, n: int = 2,
                         title: str = "", vocab: dict | None = None,
                         max_edges: int = 40,
                         rates: "dict[str, float] | None" = None) -> Path:
    """共现网络图：节点=知识点（颜色=失误率），边=关联势（粗细=强度），圆圈=社区。

    简化为 2508 v7 的**核心语义**（区域圆圈 + 关联势边 + 失误率配色），
    不搬其全部装饰（桥节点/中心锚线等）——那些在 PWA 交互版里更有价值。
    """
    plt = _import_plt()
    import networkx as nx
    part = region_partition(records, n=n, vocab=vocab)
    E, V = part["E"], part["V"]
    edges = sorted(E.items(), key=lambda kv: -kv[1])[:max_edges]
    if not edges:
        raise VizUnavailable("没有足够的共现组合，无法出图（题数或组合太少）")
    G = nx.Graph()
    for (a, b), w in edges:
        G.add_edge(a, b, weight=float(w))
    pos = nx.spring_layout(G, seed=42, k=0.9, iterations=120, weight="weight")
    rates = rates or {}
    vmax = max([rates.get(x, 0.0) for x in G.nodes()] or [1.0]) or 1.0
    node_colors = [_loss_color(rates.get(x, 0.0), vmax) for x in G.nodes()]
    sizes = [300 + 1800 * (V.get(x, 0.0) / (max(V.values()) or 1.0)) for x in G.nodes()]
    wmax = max(w for _, w in edges) or 1.0
    widths = [0.6 + 3.4 * (G[u][v]["weight"] / wmax) for u, v in G.edges()]

    fig, ax = plt.subplots(figsize=(10, 8), dpi=140)
    # 社区圆圈（区域聚类）
    groups: dict[int, list[str]] = defaultdict(list)
    for node, gid in part["partition"].items():
        if node in pos:
            groups[gid].append(node)
    for gid, members in groups.items():
        if len(members) < 2:
            continue
        xs = [pos[m][0] for m in members]
        ys = [pos[m][1] for m in members]
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        r = max(max(abs(x - cx) for x in xs), max(abs(y - cy) for y in ys)) + 0.18
        ax.add_patch(plt.Circle((cx, cy), r, fill=False, ls="--", lw=1,
                                color="#94a3b8", alpha=0.75))
        ax.text(cx, cy + r + 0.04, f"区域{gid}", fontsize=9, color="#64748b",
                ha="center")
    nx.draw_networkx_edges(G, pos, ax=ax, width=widths, alpha=0.45, edge_color="#94a3b8")
    nx.draw_networkx_nodes(G, pos, ax=ax, node_color=node_colors, node_size=sizes,
                           edgecolors="#334155", linewidths=0.8)
    nx.draw_networkx_labels(G, pos, ax=ax, font_size=9)
    ax.set_title(title or f"知识点共现网络（{n} 元，边={max_edges}）\n"
                          f"节点颜色=加权失误率（红高绿低），大小=关联势")
    ax.axis("off")
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)
    return out


def available() -> dict:
    """探测可视化依赖是否就绪（供 doctor / PWA 提示）。"""
    out = {"ok": True, "missing": []}
    for mod in ("matplotlib", "networkx"):
        try:
            __import__(mod)
        except ImportError:
            out["ok"] = False
            out["missing"].append(mod)
    if not out["ok"]:
        out["hint"] = ("缺少可视化依赖：" + "、".join(out["missing"])
                       + "。请重跑 start.sh / start.bat，或 pip install -e engine[viz]")
    return out

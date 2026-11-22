"""D216：批阅前置的「程序对齐」——判断学生做的是哪份作业纸（纯 Python，0 token）。

设计见 docs/158-D215 / docs/159-D216。要点：

1. **一次计算、两处复用**：审计与批阅前置共用同一实现与结果；
2. **只读**：不改 tag / 快照，只产出证据与建议；
3. **mismatch 仅警告、仍出分**；unknown 沿用现有审计判定口径；
4. 副产品：`questionMap[].kb` 给出**每道题真实的题库**，供提示词与算分按题生效。

匹配器直接复用 `tag_audit`（字面 n-gram + 数值常量），不另造算法。
"""
from __future__ import annotations

import time
from typing import Any

from . import tag_audit as TA

VERDICT_MATCH = "match"
VERDICT_MISMATCH = "mismatch"
VERDICT_UNKNOWN = "unknown"


def _cfg(cfg: "dict | None" = None) -> dict:
    """对齐参数：继承 tagAudit 的配置，再补三个对齐专用阈值。

    兼容两种入参：`{tagAudit: {...}}`（整份 rules）或扁平 `{...}`（tagAudit 段）。
    """
    raw = cfg or {}
    if isinstance(raw.get("tagAudit"), dict):
        raw = raw["tagAudit"]
    c = TA._cfg(raw)
    # 对齐专用阈值不在 TA.DEFAULTS 里，需显式读取并做范围校验
    for k, dv, lo, hi, cast in (
            ("coverageMin", 0.6, 0.0, 1.0, float),
            ("worksheetMarginMin", 0.15, 0.0, 1.0, float),
            ("matchScore", c.get("mediumScore", 0.45), 0.0, 1.0, float),
            ("alignMinChars", 6, 1, 100, int)):
        c.setdefault(k, dv)
        if k in raw and raw.get(k) is not None:
            try:
                v = cast(raw[k])
                if lo <= v <= hi:
                    c[k] = v
            except (TypeError, ValueError):
                pass
    return c


def _paper_score(blocks: list[dict], questions: list[dict], c: dict) -> dict:
    """转写题块 ↔ 某张作业纸：最优分配 → 覆盖率/均分/逐题映射。"""
    stems = [str(q.get("stem") or "") for q in questions or []]
    block_stems = [str(b.get("stem") or "") for b in blocks]
    _avg, pairs = (TA.best_assignment(block_stems, stems, c)
                   if stems and block_stems else (0.0, []))
    match_score = float(c.get("matchScore") or 0.45)
    mapped = []
    hit = 0
    total = 0.0
    used_paper: set[int] = set()
    for bi, qi, score in pairs:
        blk = blocks[bi] if bi < len(blocks) else {}
        q = questions[qi] if qi < len(questions) else {}
        mapped.append({
            "transcriptNo": str(blk.get("no") or bi + 1),
            "padNo": str(q.get("no") or qi + 1),
            "qid": str(q.get("qid") or ""),
            "kb": str(q.get("kb") or ""),
            "score": round(float(score), 4),
            "matched": float(score) >= match_score,
        })
        if float(score) >= match_score:
            hit += 1
            total += float(score)
            used_paper.add(qi)
    n_blocks = len(blocks)
    n_paper = len(questions or [])
    coverage = (hit / n_blocks) if n_blocks else 0.0
    coverage_rev = (hit / n_paper) if n_paper else 0.0
    mean_score = (total / hit) if hit else 0.0
    # 综合分：覆盖率为主，反向覆盖率为辅（防“整张卷只对上一题”）
    combined = 0.7 * coverage + 0.3 * coverage_rev
    return {"coverage": round(coverage, 4), "coverageReverse": round(coverage_rev, 4),
            "meanScore": round(mean_score, 4), "combined": round(combined, 4),
            "matched": hit, "questionMap": mapped,
            "unmatched": [str(b.get("no") or i + 1)
                          for i, b in enumerate(blocks) if i not in {p[0] for p in pairs
                                                                    if float(p[2]) >= match_score}]}


def align_student(transcript: "dict | None", papers: "list[dict] | None", *,
                  roster_tag: str = "", cfg: "dict | None" = None,
                  ws=None) -> dict:
    """对单个学生做程序对齐。

    `papers`: `[{padId, tag, questions:[{no, qid, stem, kb}]}]`
    `roster_tag`: 该生当前（快照）tag，决定“批阅将使用哪张卷”。

    返回（全部为只读证据）：
      verdict     match | mismatch | unknown
      padId/tag   批阅实际使用（或建议）的作业纸
      coverage/margin/bestPadId/bestTag
      questionMap 转写题号 → 作业纸题号 / kb / 相似度
      reason      人类可读说明
    """
    if cfg is None and ws is not None:
        try:
            from .rules import global_rules
            cfg = global_rules(ws)
        except Exception:  # noqa: BLE001 —— 读规则失败用默认值
            cfg = None
    c = _cfg(cfg)
    blocks = TA._items_of(transcript or {})
    min_chars = int(c.get("alignMinChars") or 6)
    usable = [b for b in blocks
              if len(TA.normalize_text(b.get("stem") or "", student=True)) >= min_chars]
    if not usable:
        # 兜底：只要有非空题干就参与对齐（短题干也强于“完全不对齐”）
        usable = [b for b in blocks if str(b.get("stem") or "").strip()]
    base: dict[str, Any] = {
        "verdict": VERDICT_UNKNOWN, "padId": "", "tag": str(roster_tag or ""),
        "coverage": 0.0, "margin": 0.0, "bestPadId": "", "bestTag": "",
        "bestCoverage": 0.0, "questionMap": [], "unmatched": [],
        "blocks": len(blocks), "usableBlocks": len(usable),
        "reason": "", "source": "align-python",
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if not blocks:
        base["reason"] = "转写里没有可用的题目块（未转写或转写无 items）"
        return base
    if not usable:
        base["reason"] = "题干太短/无法识别，无法做题目对齐（沿用当前 tag 批阅）"
        return base
    if not papers:
        base["reason"] = "作业包内没有可用题目（无法对齐，沿用当前 tag 批阅）"
        return base

    scored: list[dict] = []
    for p in papers:
        qs = [q for q in (p.get("questions") or []) if isinstance(q, dict)]
        if not qs:
            continue
        r = _paper_score(usable, qs, c)
        scored.append({"padId": str(p.get("padId") or ""), "tag": str(p.get("tag") or ""),
                       **r})
    if not scored:
        base["reason"] = "作业包内没有可用题目（无法对齐，沿用当前 tag 批阅）"
        return base

    scored.sort(key=lambda x: (-x["combined"], -x["meanScore"]))
    best = scored[0]
    second = scored[1] if len(scored) > 1 else None
    margin = round(best["combined"] - (second["combined"] if second else 0.0), 4)

    base.update({"bestPadId": best["padId"], "bestTag": best["tag"],
                 "bestCoverage": best["coverage"], "margin": margin})

    # 批阅实际使用的卷：优先“与该生 tag 同 tag 的那张”，找不到就用最佳卷
    selected = next((x for x in scored
                     if str(x["tag"]) and str(x["tag"]) == str(roster_tag or "")), best)
    base.update({"padId": selected["padId"], "tag": selected["tag"],
                 "coverage": selected["coverage"],
                 "questionMap": selected["questionMap"],
                 "unmatched": selected["unmatched"]})

    coverage_min = float(c.get("coverageMin") or 0.6)
    margin_min = float(c.get("worksheetMarginMin") or 0.15)

    if best["coverage"] >= coverage_min and margin >= margin_min:
        same_tag = (str(best["tag"]) == str(roster_tag or "")) or not str(roster_tag or "")
        if same_tag:
            base["verdict"] = VERDICT_MATCH
            base["reason"] = (f"作答与当前作业纸匹配（覆盖率 {best['coverage']:.0%}，"
                              f"领先次佳 {margin:.2f}）")
        else:
            # 仅警告、仍出分：批阅继续用当前 tag 的卷
            base["verdict"] = VERDICT_MISMATCH
            base["reason"] = (f"作答更像 tag「{best['tag']}」的作业纸"
                              f"（覆盖率 {best['coverage']:.0%}，领先次佳 {margin:.2f}）；"
                              f"当前 tag 为「{roster_tag}」。已按当前 tag 继续评阅，"
                              f"建议核对 tag 后重批")
    else:
        base["verdict"] = VERDICT_UNKNOWN
        base["reason"] = (f"题目对齐置信不足（最佳覆盖率 {best['coverage']:.0%}，"
                          f"领先次佳 {margin:.2f}）；沿用当前 tag 评阅，建议人工复核")
    return base


def align_all(transcripts: "dict[str, dict]", papers: "list[dict] | None",
              *, roster_tags: "dict[str, str] | None" = None,
              cfg: "dict | None" = None) -> dict:
    """批量对齐：{学生名: align}。"""
    tags = roster_tags or {}
    out: dict[str, dict] = {}
    for name, t in (transcripts or {}).items():
        out[str(name)] = align_student(t, papers, roster_tag=str(tags.get(name) or ""),
                                       cfg=cfg)
    return out


def summarize(align_rows: "dict[str, dict] | None") -> dict:
    """对齐结果汇总（供 UI/报告）。"""
    rows = align_rows or {}
    counts = {VERDICT_MATCH: 0, VERDICT_MISMATCH: 0, VERDICT_UNKNOWN: 0}
    for r in rows.values():
        v = str((r or {}).get("verdict") or VERDICT_UNKNOWN)
        counts[v] = counts.get(v, 0) + 1
    return {"total": len(rows), **counts}

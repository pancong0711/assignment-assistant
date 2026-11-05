"""error_stats.py — D168 §1：知识点**加权失误率**统计。

## 为什么不是「得分率」

教师原话（docs/112-D168 §1.1）：
> 我们的评阅标准是扣分制且扣分有上限（并不固定每题总分，主要为鼓励及时提交），
> 所以从得分看困难，**失分次数**好统计。比如一张作业纸 4 道题，
> 其中 2 道提到同一知识点且学生都错了，则该知识点错了 **2 次**。

→ 2508 的 `S_k = 1 − Σa/ΣF`（满分加权得分率）**不适用**；
→ 改用**失误次数**计数，同一题同一知识点错 2 次记 **2 次**。

## 加权公式（docs/112-D168 §1.3）

单班分 tag：
    E_k(tag) = 该 tag 内该知识点的失误次数 / 该 tag 提交人数
    W(tag)   = 该 tag 提交人数 / 该班全部提交人数
    W_k(班)  = Σ_tag [ E_k(tag) × W(tag) ]

跨班（两层）：
    W_k = Σ_班 Σ_tag [ E_k(班,tag) × (该班该tag提交人数 / 全部提交人数) ]

跨包（按**总题数**归一，教师拍板）：
    W_k(跨包) = Σ_包 (该包该知识点失误次数) / Σ_包 (该包总题数)

## 为什么按「已提交人数」加权

教师原话（§1.3）：
> 按照当前提交人数里的同 tag 做失分次数平均、然后根据已提交人数里的不同 tag 占比做加权。

未提交者**不进分母**，但其影响体现在「提交率」上（§1.5 可信度判据）。

## 可信度保护（§1.5）

教师担忧：
> 某 tag 失误率很低、但其实由于提交次数很少且提交的时候正确率较高导致？

→ **任何失误率必须与提交率成对出现**；提交率 < 60% 或提交人数 < 5 → 标 `low`。
"""
from __future__ import annotations

from collections import defaultdict

# 可信度阈值（docs/112-D168 §1.5）
MIN_SUBMIT_RATE = 0.60
MIN_SAMPLE = 5
UNCLASSIFIED = "(词表外)"


# ---------------- 从批阅结果抽取失误记录 ----------------

def collect_errors(records: "list[dict]", *, vocab: dict | None = None,
                   only_known: bool = False) -> dict:
    """从 `evaluations/*.json` 记录抽取失误计数。

    `records` 每项：{student, tag?, analysis:{questions:[{id, errors:[{knowledge[],
    confidence}]}]}, per_question_rules?:[...]}

    返回：
      {
        "byTerm": {term: {count, students:set, questions:Counter}},
        "byStudent": {student: {term: count}},
        "unclassified": Counter,       # 词表外术语的失误次数（不进主统计）
        "students": set,                # 有作答记录的学生
        "byTag": {tag: {term: count}},
        "totals": {"errors": N, "students": N, "questions": N},
        "questionCount": {student: 题数},
      }

    D168：`vocab` 提供时做**别名归并**；`only_known=True` 时词表外术语
    只进 `unclassified`，不进 `byTerm`（docs/112-D168 §4.3）。
    """
    from .vocab import normalize_terms

    by_term: dict[str, dict] = {}
    by_student: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_tag: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    unclassified: dict[str, int] = defaultdict(int)
    students: set[str] = set()
    question_count: dict[str, int] = {}
    n_errors = 0
    n_questions = 0

    for r in records or []:
        if not isinstance(r, dict):
            continue
        stu = str(r.get("student") or "").strip()
        if not stu:
            continue
        tag = str(r.get("tag") or "").strip()
        students.add(stu)
        ana = r.get("analysis") or {}
        questions = [q for q in (ana.get("questions") or []) if isinstance(q, dict)]
        question_count[stu] = len(questions)
        n_questions += len(questions)
        for q in questions:
            qid = str(q.get("id") or "?")
            for e in (q.get("errors") or []):
                if not isinstance(e, dict):
                    continue
                # 低置信度不计（与现有 teacher_report 口径一致）
                if str(e.get("confidence") or "high").lower() == "low":
                    continue
                raw_terms = _terms_of(e.get("knowledge"))
                if not raw_terms:
                    continue
                if vocab is not None:
                    terms, unknown = normalize_terms(raw_terms, vocab,
                                                     keep_unknown=not only_known)
                    for u in unknown:
                        unclassified[u] += 1
                else:
                    terms, unknown = raw_terms, []
                for t in terms:
                    n_errors += 1
                    rec = by_term.setdefault(t, {"count": 0, "students": set(),
                                                 "questions": defaultdict(int)})
                    rec["count"] += 1
                    rec["students"].add(stu)
                    rec["questions"][qid] += 1
                    by_student[stu][t] += 1
                    if tag:
                        by_tag[tag][t] += 1

    return {"byTerm": by_term, "byStudent": {k: dict(v) for k, v in by_student.items()},
            "byTag": {k: dict(v) for k, v in by_tag.items()},
            "unclassified": dict(unclassified), "students": students,
            "questionCount": question_count,
            "totals": {"errors": n_errors, "students": len(students),
                       "questions": n_questions}}


def _terms_of(value) -> "list[str]":
    """`knowledge` 字段 → 术语列表（兼容 str / list / None）。

    与 teacher_report._terms_of 同语义：字符串按分隔符拆（避免被当成单字遍历）。
    """
    if value is None:
        return []
    if isinstance(value, str):
        import re
        parts = [x.strip() for x in re.split(r"[,，、;；/|]+", value)]
        return [x for x in parts if x]
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for v in value:
            out.extend(_terms_of(v))
        return out
    t = str(value).strip()
    return [t] if t else []


# ---------------- 加权失误率 ----------------

def weighted_error_rate(by_tag_counts: dict, submitted_by_tag: dict) -> dict:
    """按 tag 分值加权的失误率（docs/112-D168 §1.3）。

    `by_tag_counts`：{tag: {term: 失误次数}}（该 tag 内）
    `submitted_by_tag`：{tag: 该 tag **提交**人数}（分母）

    返回 {term: {"rate", "byTag": {tag: rate}, "errorCount", "students"}}
    以及 "weights": {tag: 权重}。
    """
    total_sub = sum(int(v) for v in (submitted_by_tag or {}).values())
    if total_sub <= 0:
        return {"terms": {}, "weights": {}, "totalSubmitted": 0}
    weights = {t: (int(n) / total_sub) for t, n in submitted_by_tag.items()}
    terms: set[str] = set()
    for t, counts in (by_tag_counts or {}).items():
        terms.update(counts.keys())
    out: dict[str, dict] = {}
    for term in terms:
        by_tag_rate: dict[str, float] = {}
        acc = 0.0
        err_total = 0
        for tag, w in weights.items():
            n_sub = int(submitted_by_tag.get(tag) or 0)
            if n_sub <= 0:
                continue
            cnt = int(((by_tag_counts or {}).get(tag) or {}).get(term, 0))
            err_total += cnt
            r = cnt / n_sub
            by_tag_rate[tag] = round(r, 4)
            acc += r * w
        out[term] = {"rate": round(acc, 4), "byTag": by_tag_rate,
                     "errorCount": err_total}
    return {"terms": out, "weights": {k: round(v, 4) for k, v in weights.items()},
            "totalSubmitted": total_sub}


def confidence(submit_rate: float, submitted: int) -> dict:
    """可信度判据（docs/112-D168 §1.5）。"""
    reasons = []
    if submit_rate < MIN_SUBMIT_RATE:
        reasons.append(f"提交率 {submit_rate:.0%} < {MIN_SUBMIT_RATE:.0%}")
    if submitted < MIN_SAMPLE:
        reasons.append(f"提交人数 {submitted} < {MIN_SAMPLE}")
    return {"level": "low" if reasons else "ok", "reasons": reasons}


def merged_error_rate(stats: dict, submitted_total: int) -> dict:
    """整个（多 tag 合并后的）失误率，供 `weighted_error_rate` 复用。

    直接用 `stats["byTerm"]` 的次数除以**总提交人数**——因为按 tag 加权后
    与「总次数 / 总人数」在数学上等价（加权平均的加权和）。
    """
    terms = {}
    for term, rec in (stats.get("byTerm") or {}).items():
        cnt = int(rec.get("count") or 0)
        terms[term] = {"rate": round(cnt / submitted_total, 4) if submitted_total else 0.0,
                       "errorCount": cnt, "students": len(rec.get("students") or [])}
    return terms


# ---------------- 跨包归一 ----------------

def cross_pack_rate(pack_stats: "list[dict]") -> dict:
    """跨包失误率：`Σ失误次数 / Σ总题数`（教师拍板的"按总题数归一"）。

    `pack_stats` 每项：{packId, byTerm: {term: count}, totalQuestions: int}
    返回 {term: {"rate", "errorCount", "totalQuestions", "packs": {packId: count}}}
    """
    total_q = sum(int(p.get("totalQuestions") or 0) for p in (pack_stats or []))
    terms: set[str] = set()
    for p in (pack_stats or []):
        terms.update((p.get("byTerm") or {}).keys())
    out: dict[str, dict] = {}
    for term in terms:
        cnt = 0
        packs: dict[str, int] = {}
        for p in (pack_stats or []):
            c = int(((p.get("byTerm") or {}).get(term) or 0))
            if c:
                cnt += c
                packs[str(p.get("packId") or "?")] = c
        out[term] = {"rate": round(cnt / total_q, 4) if total_q else 0.0,
                     "errorCount": cnt, "totalQuestions": total_q, "packs": packs}
    return {"terms": out, "totalQuestions": total_q}


# ---------------- 报告组装 ----------------

def build_report(records: "list[dict]", *, submitted_by_tag: dict,
                 vocab: dict | None = None, only_known: bool = True) -> dict:
    """一站式：批阅记录 → 失误统计 + 加权失误率 + 可信度。

    `submitted_by_tag` 来自 D168 快照（`snapshots.submit_stats()["byTag"]` 的
    `submitted` 字段），**不是**班级人数。
    """
    stats = collect_errors(records, vocab=vocab, only_known=only_known)
    rated = weighted_error_rate(stats["byTag"], submitted_by_tag)
    total_sub = int(rated.get("totalSubmitted") or 0)
    merged = merged_error_rate(stats, total_sub) if total_sub else {}
    # 合并每题的失误率与可信度
    items = []
    for term, rec in (merged or {}).items():
        by_tag = (rated["terms"].get(term) or {}).get("byTag") or {}
        items.append({
            "term": term,
            "rate": rec["rate"],
            "byTag": by_tag,
            "errorCount": rec["errorCount"],
            "errStudents": rec["students"],
            "questions": sorted((stats["byTerm"].get(term) or {}).get("questions") or {}),
        })
    items.sort(key=lambda x: (-x["rate"], x["term"]))
    return {
        "ok": True,
        "items": items,
        "weights": rated.get("weights") or {},
        "totalSubmitted": total_sub,
        "confidence": confidence(
            submit_rate=(total_sub / max(1, sum(
                int(v) for v in (submitted_by_tag or {}).values())) if total_sub else 0.0),
            submitted=total_sub),
        "unclassified": stats["unclassified"],
        "totals": stats["totals"],
    }

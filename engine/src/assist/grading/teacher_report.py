"""teacher_report.py — D126-B：**教师总结报告**（易错知识点汇总 + 共现 + 得分率）。

与"学生报告"严格区分（docs/12 D126-B）：
- 学生报告：一名学生一份，进 `reports/<学生>.html`，会发给学生；
- 教师报告：**全班/全作业**一份，只给教师看，落 `reports/_teacher_report.*`，
  **不上传、不发给学生**。

数据源（均在 D127/D130/D131 已备好，无需再调 LLM）：
- `evaluations/<学生>.json`：
  - `questions[].errors[].knowledge[]` → 该生**出错**的知识点（易错点来源）
  - `knowledge_missing[]`              → `summary` 题漏掉的本章知识点（D131）
  - `per_question_scores[]`            → 逐题得分（得分率）
  - `per_question_rules[]`             → 逐题来源/规则（可按题型分组统计）
  - `total_score`

产出：
1. **易错知识点 Top N**（出错人数 / 出错率 / 涉及题号）
2. **知识点共现**（同一份作业里同时出错的成对知识点 → 暗示概念关联）
3. **逐题得分率**（哪道题全班都错）
4. **题型维度**（按 `per_question_rules[].kind` 聚合，看哪类题整体薄弱）
5. **本章遗漏知识点**（`summary` 类；D131 清单为依据）
6. 分数段分布 + 学生明细

设计原则：**纯组装，不调 LLM**（与 D127 报告口径一致：可复现、可核对、免费）。
"""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from loguru import logger

MIN_COOCCURRENCE = 2      # 共现少于 2 人视为噪声，不展示


# ---------------- 读取 ----------------
def load_evaluations(eval_dir) -> list[dict]:
    """读全部评阅结果（跳过 `_` 开头的汇总文件与坏文件）。"""
    out: list[dict] = []
    for f in sorted(Path(eval_dir).glob("[!_]*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[教师报告] 跳过坏文件 {f.name}: {exc}")
            continue
        if isinstance(d, dict):
            d.setdefault("student", f.stem)
            out.append(d)
    return out


def collect_multi(ws, class_dirs: "list[str]", pack_ids: "list[str]",
                  tags: "list[str] | None" = None) -> "tuple[list[dict], list[str]]":
    """D153：从**多个班级 × 多个作业包**收集评阅结果（教师报告多选）。

    - `tags`：按名单 join 过滤（**评阅结果里没有 tag 字段**）；
    - 返回 `(records, sources)`，`sources` 形如 `["classes/化工25/pack1", ...]`
      供前端回显"这次报告汇总了哪几份作业"。
    """
    from pathlib import Path as _P
    ws_p = _P(ws).resolve()
    records: list[dict] = []
    sources: list[str] = []
    want_tags = {str(t).strip() for t in (tags or []) if str(t).strip()}
    for cd in (class_dirs or []):
        cd_s = str(cd or "").strip().strip("/")
        if not cd_s:
            continue
        # tag 过滤：从名单读 姓名 → tag
        name_tag: dict[str, str] = {}
        if want_tags:
            try:
                from ..files import roster_io
                ros = roster_io.read_roster_file(ws_p, cd_s) or {}
                for st in (ros.get("students") or []):
                    nm = str(st.get("name") or "").strip()
                    if nm:
                        name_tag[nm] = str(st.get("tag") or st.get("group") or "").strip()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[教师报告] 读取名单失败（不按 tag 过滤）：{exc}")
        for pid in (pack_ids or []):
            pid_s = str(pid or "").strip()
            if not pid_s:
                continue
            ev = ws_p / cd_s / "grading" / pid_s / "evaluations"
            if not ev.is_dir():
                continue
            got = load_evaluations(ev)
            if want_tags and name_tag:
                got = [r for r in got
                       if name_tag.get(str(r.get("student") or "")) in want_tags]
            for r in got:
                r.setdefault("_sourcePack", f"{cd_s}/{pid_s}")
            records.extend(got)
            sources.append(f"{cd_s}/{pid_s}")
    return records, sources


# ---------------- 分析 ----------------
def _norm(term: str) -> str:
    return str(term or "").strip()


def _terms_of(value) -> list[str]:
    """把 `knowledge` 字段规范成术语列表。

    兼容三种真实写法：`["动量守恒"]`（标准）、`"动量守恒"`（旧模型偶尔给字符串，
    若直接遍历会**拆成单个汉字**——曾因此把"动量守恒"统计成"动/量/守/恒"四份）、`None`。
    """
    if value is None:
        return []
    if isinstance(value, str):
        parts = [x.strip() for x in value.replace("，", ",").replace("、", ",").split(",")]
        return [x for x in parts if x]
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for v in value:
            out.extend(_terms_of(v))
        return out
    t = str(value).strip()
    return [t] if t else []


def analyze(records: "list[dict]", *, top_n: int = 15,
            topics: "dict[str, str] | None" = None) -> dict:
    """纯函数：评阅结果 → 统计结构（便于单测，不碰磁盘）。

    D138：`topics` = `{术语: 主题}`（来自本章知识点清单的两层分类）。
    提供时在 `knowledge_errors[]` 里附 `topic` 并按主题归组（`by_topic`）；
    不提供时行为与 D126-B **完全一致**。
    """
    n = len(records)
    if not n:
        return {"students": 0, "knowledge_errors": [], "cooccurrence": [],
                "question_rates": [], "kind_stats": [], "missing": [],
                "segments": {}, "avg": 0.0, "min": 0, "max": 0,
                "manual": 0, "substitution": 0}

    # 1) 易错知识点：出错人数（同一学生同一知识点只计一次）
    err_students: dict[str, set[str]] = defaultdict(set)
    err_questions: dict[str, Counter] = defaultdict(Counter)
    err_evidence: dict[str, list[str]] = defaultdict(list)
    for r in records:
        stu = str(r.get("student") or "")
        for q in (r.get("analysis") or {}).get("questions") or []:
            qid = str(q.get("id") or "?")
            for e in (q.get("errors") or []):
                if not isinstance(e, dict):
                    continue
                # 低置信度不计（与计分口径一致：只提示不扣分）
                if str(e.get("confidence") or "high").lower() == "low":
                    continue
                for t in _terms_of(e.get("knowledge")):
                    err_students[t].add(stu)
                    err_questions[t][qid] += 1
                    if len(err_evidence[t]) < 3 and e.get("description"):
                        err_evidence[t].append(f"第{qid}题：{e['description']}")
    knowledge_errors = [
        {"term": t, "students": len(s), "rate": round(len(s) / n, 3),
         "questions": [q for q, _c in err_questions[t].most_common(6)],
         "examples": err_evidence[t]}
        for t, s in err_students.items()
    ]
    knowledge_errors.sort(key=lambda x: (-x["students"], x["term"]))

    # 2) 共现：同一学生同一份作业里，多个知识点同时出错 → 概念关联线索
    pair_students: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in records:
        stu = str(r.get("student") or "")
        terms: set[str] = set()
        for q in (r.get("analysis") or {}).get("questions") or []:
            for e in (q.get("errors") or []):
                if not isinstance(e, dict):
                    continue
                if str(e.get("confidence") or "high").lower() == "low":
                    continue
                for t in _terms_of(e.get("knowledge")):
                    terms.add(t)
        for a, b in combinations(sorted(terms), 2):
            pair_students[(a, b)].add(stu)
    cooccurrence = [
        {"a": a, "b": b, "students": len(s), "rate": round(len(s) / n, 3)}
        for (a, b), s in pair_students.items() if len(s) >= MIN_COOCCURRENCE
    ]
    cooccurrence.sort(key=lambda x: (-x["students"], x["a"], x["b"]))

    # 3) 逐题得分率（按题号聚合 per_question_scores；缺失题号一律跳过）
    # 每题满分：计分是"100 分均分到各题"（score_from_analysis 同口径），
    # 因此某题满分 = 100 / 该生题数；不同学生题数可能不同 → 按人记录满分再取均值。
    q_scores: dict[str, list[float]] = defaultdict(list)
    q_full: dict[str, list[float]] = defaultdict(list)
    for r in records:
        qs = r.get("per_question_scores") or []
        rules = r.get("per_question_rules") or []
        n_q = len(qs)
        if not n_q:
            continue
        ids = [str(x.get("id")) for x in rules if isinstance(x, dict)]
        for i, s in enumerate(qs):
            try:
                qid = ids[i] if i < len(ids) else str(i + 1)
                q_scores[qid].append(float(s))
                # 与 scoring 的均分基线一致：base=100//n，余数分给前几题
                base = 100 // n_q
                rem = 100 % n_q
                q_full[qid].append(float(base + (1 if i < rem else 0)))
            except (TypeError, ValueError):
                continue
    question_rates = []
    for qid, vals in q_scores.items():
        if not vals:
            continue
        fulls = q_full.get(qid) or []
        full = (sum(fulls) / len(fulls)) if fulls else 100.0
        avg = sum(vals) / len(vals)
        question_rates.append({"id": qid, "students": len(vals),
                               "avg_score": round(avg, 1),
                               "max_possible": round(full, 1),
                               "rate": round(min(1.0, avg / full), 3) if full else 0})
    question_rates.sort(key=lambda x: (x["rate"], x["id"]))

    # 4) 题型维度（per_question_rules[].kind + 该题扣分）
    kind_deduct: dict[str, list[float]] = defaultdict(list)
    for r in records:
        for pr in (r.get("per_question_rules") or []):
            if not isinstance(pr, dict):
                continue
            k = str(pr.get("kind") or "problems")
            try:
                kind_deduct[k].append(float(pr.get("deduct") or 0))
            except (TypeError, ValueError):
                kind_deduct[k].append(0.0)
    kind_stats = [
        {"kind": k, "questions": len(v),
         "avg_deduct": round(sum(v) / len(v), 2) if v else 0,
         "total_deduct": round(sum(v), 1)}
        for k, v in kind_deduct.items()
    ]
    kind_stats.sort(key=lambda x: -x["avg_deduct"])

    # 5) 本章遗漏知识点（D131 summary 题）
    miss_cnt: Counter = Counter()
    for r in records:
        for t in _terms_of(r.get("knowledge_missing")):
            miss_cnt[t] += 1
    missing = [{"term": t, "students": c, "rate": round(c / n, 3)}
               for t, c in miss_cnt.most_common(top_n)]

    # 6) 分数段
    scores = []
    for r in records:
        try:
            scores.append(float(r.get("total_score") or 0))
        except (TypeError, ValueError):
            pass
    segments = {"90-100": 0, "80-89": 0, "70-79": 0, "60-69": 0, "<60": 0}
    for s in scores:
        k = ("90-100" if s >= 90 else "80-89" if s >= 80 else
             "70-79" if s >= 70 else "60-69" if s >= 60 else "<60")
        segments[k] += 1

    return {
        "students": n,
        "avg": round(sum(scores) / len(scores), 1) if scores else 0.0,
        "min": min(scores) if scores else 0,
        "max": max(scores) if scores else 0,
        "manual": sum(1 for r in records if r.get("_manual_review")),
        "substitution": sum(1 for r in records
                            if r.get("verdict") == "suspected-substitution"),
        "segments": segments,
        "knowledge_errors": _attach_topics(knowledge_errors[:top_n], topics),
        "byTopic": _group_by_topic(_attach_topics(knowledge_errors[:top_n], topics)),
        "cooccurrence": cooccurrence[:top_n],
        "question_rates": question_rates,
        "kind_stats": kind_stats,
        "missing": missing,
        "students_detail": [
            {"student": str(r.get("student") or "?"),
             "score": r.get("total_score", 0),
             "verdict": ("顶替嫌疑" if r.get("verdict") == "suspected-substitution"
                         else "需人工" if r.get("_manual_review") else "OK")}
            for r in sorted(records, key=lambda x: str(x.get("student") or ""))
        ],
    }


# ---------------- 渲染 ----------------
def _attach_topics(items: list[dict], topics: "dict[str, str] | None") -> list[dict]:
    """给每条易错知识点附上 `topic`（无映射则空串，不影响其它字段）。"""
    if not items:
        return items
    tp = topics or {}
    out: list[dict] = []
    for x in items:
        y = dict(x)
        y["topic"] = str(tp.get(str(x.get("term") or ""), "") or "")
        out.append(y)
    return out


def _group_by_topic(items: list[dict]) -> list[dict]:
    """按 `topic` 归组（同章内的"块"）。

    没有 topic 的条目归入「其他」并**排在最后**（不丢、不隐藏）；
    若所有条目都没有 topic，返回空列表（调用方据此退回旧的扁平表格）。
    """
    if not items or not any(x.get("topic") for x in items):
        return []
    buckets: dict[str, list[dict]] = {}
    for x in items:
        t = str(x.get("topic") or "").strip() or "其他"
        buckets.setdefault(t, []).append(x)
    named = [{"topic": t, "items": v} for t, v in buckets.items() if t != "其他"]
    other = [{"topic": t, "items": v} for t, v in buckets.items() if t == "其他"]
    # 组内仍按出错人数降序；组间按组内最高出错人数降序
    for g in named + other:
        g["items"].sort(key=lambda x: (-int(x.get("students") or 0), str(x.get("term"))))
    named.sort(key=lambda g: -int(g["items"][0].get("students") or 0))
    return named + other


def render_md(stat: dict, *, title: str = "", subtitle: str = "") -> str:
    n = stat.get("students") or 0
    lines = ["# 教师总结报告（易错知识点汇总）", ""]
    if title:
        lines.append(f"**作业：** {title}")
    if subtitle:
        lines.append(f"**班级：** {subtitle}")
    lines += [f"**生成时间：** {time.strftime('%Y-%m-%d %H:%M')}",
              f"**已评阅：** {n} 人", "",
              "> 本报告仅供教师使用（含错误分布与共现分析），**不发给学生**。", ""]
    if not n:
        lines += ["（暂无评阅结果：先跑批阅再生成教师总结报告。）"]
        return "\n".join(lines) + "\n"

    lines += ["---", "", "## 一、统计概览", "",
              "| 指标 | 数值 |", "|---|---|",
              f"| 已评阅 | {n} 人 |",
              f"| 平均分 | {stat['avg']} |",
              f"| 最高 / 最低 | {stat['max']} / {stat['min']} |",
              f"| 需人工评阅 | {stat['manual']} 人 |",
              f"| 顶替嫌疑 | {stat['substitution']} 人 |", "",
              "### 分数段分布", "", "| 分数段 | 人数 |", "|---|---|"]
    for seg in ("90-100", "80-89", "70-79", "60-69", "<60"):
        lines.append(f"| {seg} | {(stat.get('segments') or {}).get(seg, 0)} 人 |")

    # 二、易错知识点
    lines += ["", "---", "", "## 二、易错知识点（按出错人数排序）", ""]
    ke = stat.get("knowledge_errors") or []
    if not ke:
        lines.append("（无知识点级错误记录：可能本次批阅未产生 `errors[].knowledge`，"
                     "或全部答对。）")
    else:
        by_topic = stat.get("byTopic") or []
        if by_topic:
            # D138：按「主题」分块展示，教师一眼看出"这几个是同一条线上错的"
            for g in by_topic:
                lines += [f"### 📚 {g['topic']}", "",
                          "| 知识点 | 出错人数 | 出错率 | 涉及题号 |", "|---|---|---|---|"]
                for x in g["items"]:
                    qs = "、".join(x["questions"][:6]) or "—"
                    lines.append(f"| **{x['term']}** | {x['students']} | "
                                 f"{x['rate'] * 100:.0f}% | {qs} |")
                lines.append("")
        else:
            lines += ["| 知识点 | 出错人数 | 出错率 | 涉及题号 |", "|---|---|---|---|"]
            for x in ke:
                qs = "、".join(x["questions"][:6]) or "—"
                lines.append(f"| **{x['term']}** | {x['students']} | "
                             f"{x['rate'] * 100:.0f}% | {qs} |")
        top = ke[0]
        lines += ["", f"> **最需讲评：** {top['term']}（{top['students']} 人出错，"
                      f"占 {top['rate'] * 100:.0f}%）。"]
        for x in ke[:3]:
            if x.get("examples"):
                lines.append(f"> - {x['term']}：{x['examples'][0]}")

    # 三、共现
    lines += ["", "---", "", "## 三、易错点之间的关联（共现）", "",
              f"> 同一份作业里**同时出错**、且至少 {MIN_COOCCURRENCE} 人出现的知识点组合；"
              "可用于判断是否同一个概念没讲透。", ""]
    co = stat.get("cooccurrence") or []
    if not co:
        lines.append("（暂无达到阈值的共现组合。）")
    else:
        lines += ["| 知识点 A | 知识点 B | 同时出错人数 | 占比 |", "|---|---|---|---|"]
        for x in co:
            lines.append(f"| {x['a']} | {x['b']} | {x['students']} | {x['rate'] * 100:.0f}% |")

    # 四、逐题得分率
    lines += ["", "---", "", "## 四、逐题得分率（升序，越低越该讲）", ""]
    qr = stat.get("question_rates") or []
    if not qr:
        lines.append("（无逐题分数记录。）")
    else:
        lines += ["| 题号 | 平均分 | 该题满分 | 得分率 |", "|---|---|---|---|"]
        for x in qr:
            lines.append(f"| 第{x['id']}题 | {x['avg_score']} | {x['max_possible']} | "
                         f"{x['rate'] * 100:.0f}% |")

    # 五、题型维度
    ks = stat.get("kind_stats") or []
    if ks:
        lines += ["", "---", "", "## 五、按题目来源（题型）", "",
                  "| 题型 | 题次 | 平均扣分 | 累计扣分 |", "|---|---|---|---|"]
        for x in ks:
            lines.append(f"| {x['kind']} | {x['questions']} | {x['avg_deduct']} | "
                         f"{x['total_deduct']} |")

    # 六、本章遗漏知识点
    ms = stat.get("missing") or []
    if ms:
        lines += ["", "---", "", "## 六、本章遗漏知识点（依据课堂资料清单）", "",
                  "| 知识点 | 遗漏人数 | 占比 |", "|---|---|---|"]
        for x in ms:
            lines.append(f"| {x['term']} | {x['students']} | {x['rate'] * 100:.0f}% |")

    # 七、学生明细
    lines += ["", "---", "", "## 七、学生明细", "",
              "| 学生 | 分数 | 状态 |", "|---|---|---|"]
    for x in stat.get("students_detail") or []:
        lines.append(f"| {x['student']} | {x['score']} | {x['verdict']} |")

    lines += ["", "---", "*教师总结报告 · 由批阅结果自动汇总（不做额外 AI 推理）*", ""]
    return "\n".join(lines)


def export_png(md_text: str, out_path, *, title: str = "", subtitle: str = "") -> "str | None":
    """D135：教师报告 → PNG（A4 宽长图）。复用学生报告的 Playwright 链路。

    浏览器/playwright 不可用时返回 None（**不抛**）：导图是附加能力，
    不能让"看不到图"变成"报告生成失败"。
    """
    try:
        from .report import render_report_png
        p = render_report_png(md_text, out_path, kind="teacher",
                              title=title, subtitle=subtitle)
        return str(p) if p else None
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[教师报告] PNG 导出失败（已跳过）：{exc}")
        return None


def export_pdf(png_path) -> "str | None":
    """D135：PNG → 单页 PDF（reportlab，已有依赖）。

    用"图片贴满 PDF 页"而不是重新排版：教师报告是**长图**，
    重排版会让"和我看到的不一样"，与 D87 "预览=打印"的口径一致。
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas

        src = Path(png_path)
        if not src.is_file():
            return None
        w, h = ImageReader(str(src)).getSize()
        # 页面宽度固定 A4 宽，高度按图片比例（长图就长页），避免内容被压扁
        page_w = A4[0]
        page_h = page_w * (h / w) if w else A4[1]
        out = src.with_suffix(".pdf")
        c = canvas.Canvas(str(out), pagesize=(page_w, page_h))
        c.drawImage(str(src), 0, 0, width=page_w, height=page_h)
        c.showPage()
        c.save()
        return str(out)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[教师报告] PDF 导出失败（已跳过）：{exc}")
        return None


def load_topic_map(ws, chaps: "list[str] | None" = None) -> dict[str, str]:
    """D138：从各章生效清单读 `{术语: 主题}`（用于报告按主题分组）。

    读不到（无清单/无 topic）时返回空 dict —— 报告自动退回扁平表格。
    """
    out: dict[str, str] = {}
    try:
        from ..files import materials as M
        for c in (chaps or M.list_chaps(ws)):
            for topic, terms in (M.knowledge_topics(ws, c) or {}).items():
                if topic == "其他":
                    continue
                for t in terms:
                    out.setdefault(t, topic)
    except Exception as exc:  # noqa: BLE001 —— 分组是增强，读不到不影响报告
        logger.warning(f"[教师报告] 读取主题归类失败（已跳过分组）：{exc}")
    return out


def generate(eval_dir, out_dir, *, title: str = "", subtitle: str = "",
             top_n: int = 15, render_png: bool = False,
             render_pdf: bool = False, topics: "dict[str, str] | None" = None) -> dict:
    """读 evaluations → 写 `reports/_teacher_report.md`（+ stats JSON 供 PWA 画图）。

    D135：`render_png=True` 额外导出 `_teacher_report.png`；
    `render_pdf=True` 再导出 `_teacher_report.pdf`（依赖 PNG）。
    """
    records = load_evaluations(eval_dir)
    stat = analyze(records, top_n=top_n, topics=topics)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    md = render_md(stat, title=title, subtitle=subtitle)
    md_path = out / "_teacher_report.md"
    md_path.write_text(md, encoding="utf-8")
    stats_path = out / "_teacher_report.stats.json"
    stats_path.write_text(json.dumps(stat, ensure_ascii=False, indent=1), encoding="utf-8")
    logger.info(f"[教师报告] 已生成（{stat['students']} 人）→ {md_path}")

    png_path = pdf_path = None
    if render_png or render_pdf:
        png_path = export_png(md, out / "_teacher_report.png",
                              title=title or "教师总结报告", subtitle=subtitle)
        if render_pdf and png_path:
            pdf_path = export_pdf(png_path)
    return {"ok": True, "students": stat["students"], "md": str(md_path),
            "stats": str(stats_path), "png": png_path, "pdf": pdf_path, "stat": stat}

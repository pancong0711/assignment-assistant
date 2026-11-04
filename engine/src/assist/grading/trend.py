"""trend.py — D135：**跨多次作业的知识点趋势**（同一知识点是否反复出错）。

为什么需要单独模块（而不是塞进 teacher_report）：
- `teacher_report` 的口径是「**一次作业**内全班分析」；
- 趋势的口径是「**同一班级的多次作业**串成序列，看同一知识点是否反复出现」。
  两者输入、聚合维度、报告对象都不同，混在一起会把"单次报告"的语义搅浑。

作业序列口径（D135 定稿，**不引入新概念**）：
    同一 `class_dir` 下、按**评阅时间**（`evaluations/*.json` 的 `timestamp`，
    缺失时回落到文件 mtime）**升序**排列的作业包序列。
不做"按章节串"（那需要额外标注章节-作业映射，暂时没有可靠依据）。

数据来源（D127/D130/D131 已备好，**纯统计不调 LLM**）：
- `evaluations/<学生>.json` → `analysis.questions[].errors[].knowledge[]`
  （该生**出错**的知识点，低置信度已排除，与计分口径一致）
- 评阅结果里的 `timestamp` / 作业包 `name`

产出：
1. **反复出错的知识点**：出现在 ≥2 次作业里 → `recurring[]`（按出现次数排序）
2. **每个知识点的逐次轨迹**：`[{packId, name, at, students, rate}]`
3. **首次/末次出现**、是否改善（末次出错率 < 首次）
4. 仅在单次作业出现的知识点 → `oneOff[]`（可忽略）

设计原则：与 D126-B 一致——**纯组装、可复现、可核对、免费**。
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

from loguru import logger

MIN_RECUR = 2       # 至少在这么多次作业里出现才算"反复出错"


# ---------------- 读取 ----------------
def _pack_name(ws, pack_id: str) -> str:
    """作业包显示名（读不到就回退 id，不让报告因缺包而失败）。"""
    try:
        from ..packs import read_pack
        d = read_pack(ws, pack_id) or {}
        return str(d.get("name") or pack_id)
    except Exception:  # noqa: BLE001
        return pack_id


def _eval_time(eval_dir: Path) -> str:
    """该次作业的评阅时间：优先取结果里的 `timestamp`，缺失回落目录最新 mtime。

    同一作业包内多名学生的 `timestamp` 可能略有差异（批阅跨分钟），
    取**最大值**代表"这次作业评阅完成的时间"，序列排序用它。
    """
    latest = ""
    newest_mtime = 0.0
    for f in sorted(eval_dir.glob("[!_]*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        ts = str(d.get("timestamp") or "").strip()
        if ts > latest:
            latest = ts
        try:
            newest_mtime = max(newest_mtime, f.stat().st_mtime)
        except OSError:
            pass
    if latest:
        return latest
    if newest_mtime:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(newest_mtime))
    return ""


def discover_sequence(ws, class_dir: str) -> list[dict]:
    """扫描某班级目录下的全部评阅产物 → **按评阅时间升序**的作业序列。

    返回 `[{packId, name, at, dir, students}]`；没有评阅结果的包不进入序列
    （否则趋势里会出现"空节点"，学生看到的是断档）。
    """
    ws_p = Path(ws).resolve()
    base = ws_p / str(class_dir).strip().strip("/") / "grading"
    if not base.is_dir():
        return []
    seq: list[dict] = []
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        ev = d / "evaluations"
        if not ev.is_dir():
            continue
        files = [f for f in ev.glob("[!_]*.json")]
        if not files:
            continue
        seq.append({
            "packId": d.name,
            "name": _pack_name(ws_p, d.name),
            "at": _eval_time(ev),
            "dir": str(ev),
            "students": len(files),
        })
    # 按评阅时间升序；时间相同按包名稳定排序（避免顺序抖动导致报告每次不同）
    seq.sort(key=lambda x: (x["at"] or "9999", x["packId"]))
    return seq


def _load_knowledge_errors(eval_dir) -> dict[str, set[str]]:
    """读一次作业 → {知识点: 出错学生集合}（低置信度不计，与计分口径一致）。"""
    out: dict[str, set[str]] = defaultdict(set)
    for f in sorted(Path(eval_dir).glob("[!_]*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[趋势] 跳过坏文件 {f.name}: {exc}")
            continue
        if not isinstance(d, dict):
            continue
        stu = str(d.get("student") or f.stem)
        for q in (d.get("analysis") or {}).get("questions") or []:
            for e in (q.get("errors") or []):
                if not isinstance(e, dict):
                    continue
                if str(e.get("confidence") or "high").lower() == "low":
                    continue
                for t in (e.get("knowledge") or []):
                    t = str(t or "").strip()
                    if t:
                        out[t].add(stu)
    return out


# ---------------- 分析 ----------------
def analyze(ws, class_dir: str, *, min_recur: int = MIN_RECUR,
            sequence: "list[dict] | None" = None,
            topics: "dict[str, str] | None" = None) -> dict:
    """纯统计：多次作业 → 反复出错的知识点 + 逐次轨迹。

    输入 `sequence` 可直接传（测试用），否则从磁盘发现。
    """
    seq = sequence if sequence is not None else discover_sequence(ws, class_dir)
    if not seq:
        return {"ok": True, "classDir": class_dir, "sequence": [], "recurring": [],
                "oneOff": [], "summary": {"packs": 0, "terms": 0, "recurring": 0}}

    # 逐次作业：知识点 → 出错学生
    per_pack: list[tuple[dict, dict[str, set[str]]]] = []
    for p in seq:
        per_pack.append((p, _load_knowledge_errors(p["dir"])))

    # 知识点 → 逐次轨迹
    traj: dict[str, list[dict]] = defaultdict(list)
    for p, kn in per_pack:
        n = max(1, int(p.get("students") or 0))
        for term, students in kn.items():
            traj[term].append({
                "packId": p["packId"], "name": p["name"], "at": p.get("at") or "",
                "students": len(students), "rate": round(len(students) / n, 3),
            })

    recurring, one_off = [], []
    for term, points in traj.items():
        # 只保留**按序列顺序**的点（discover_sequence 已排序；测试传参需自行保证）
        pts = [pt for pt in points]
        if len(pts) < min_recur:
            one_off.append({"term": term, "packs": [pt["packId"] for pt in pts],
                            "students": max((pt["students"] for pt in pts), default=0)})
            continue
        first, last = pts[0], pts[-1]
        recurring.append({
            "term": term,
            "packs": len(pts),
            "trail": pts,
            "firstAt": first.get("at") or "",
            "lastAt": last.get("at") or "",
            "peakStudents": max(pt["students"] for pt in pts),
            # 改善 = 末次出错率低于首次（人数口径可能因班额变化失真，故用比率）
            "improving": last["rate"] < first["rate"],
            "persisting": last["rate"] >= first["rate"],
        })
    # D138：附上主题并按主题归组（同一条线上的知识点一起看才有意义）
    tp = topics or {}
    for r in recurring:
        r["topic"] = str(tp.get(r["term"], "") or "")
    by_topic: list[dict] = []
    if any(r["topic"] for r in recurring):
        buckets: dict[str, list[dict]] = {}
        for r in recurring:
            buckets.setdefault(r["topic"] or "其他", []).append(r)
        named = [{"topic": t, "items": v} for t, v in buckets.items() if t != "其他"]
        other = [{"topic": t, "items": v} for t, v in buckets.items() if t == "其他"]
        named.sort(key=lambda g: -int(g["items"][0]["packs"] or 0))
        by_topic = named + other
    recurring.sort(key=lambda x: (-x["packs"], -x["peakStudents"], x["term"]))
    one_off.sort(key=lambda x: (-x["students"], x["term"]))

    return {
        "ok": True,
        "classDir": class_dir,
        "sequence": [{k: p[k] for k in ("packId", "name", "at", "students")} for p in seq],
        "recurring": recurring,
        "byTopic": by_topic,
        "oneOff": one_off,
        "summary": {"packs": len(seq), "terms": len(traj),
                    "recurring": len(recurring),
                    "persisting": sum(1 for r in recurring if r["persisting"])},
    }


# ---------------- 渲染 ----------------
def _render_one(lines: list, r: dict) -> None:
    mark = "⚠️ 仍在持续" if r["persisting"] else "📉 有改善"
    lines.append(f"#### {r['term']} — 出现 {r['packs']} 次 · {mark}")
    for pt in r["trail"]:
        lines.append(f"- {pt['name']}（{pt.get('at') or '—'}）："
                     f"{pt['students']} 人出错（{pt['rate'] * 100:.0f}%）")
    lines.append("")


def render_md(stat: dict, *, title: str = "") -> str:
    """教师可读的 Markdown（只给教师，不进学生报告）。"""
    s = stat.get("summary") or {}
    lines = [f"# {title or '知识点趋势（跨作业）'}", ""]
    seq = stat.get("sequence") or []
    if not seq:
        lines.append("（该班级还没有任何评阅结果，无法生成趋势）")
        return "\n".join(lines)
    lines += [f"**班级目录**：`{stat.get('classDir')}`　"
              f"**作业序列**：{s.get('packs', 0)} 次　"
              f"**涉及知识点**：{s.get('terms', 0)} 个　"
              f"**反复出错**：{s.get('recurring', 0)} 个"
              f"（其中仍在持续：{s.get('persisting', 0)} 个）", ""]
    lines.append("## 作业序列（按评阅时间）")
    for i, p in enumerate(seq, start=1):
        lines.append(f"{i}. **{p['name']}**（`{p['packId']}`）"
                     f" {p.get('at') or '—'} · {p.get('students', 0)} 人")
    lines.append("")

    rec = stat.get("recurring") or []
    lines.append("## 反复出错的知识点")
    if not rec:
        lines.append("（没有知识点在 ≥2 次作业里反复出错）")
    by_topic = stat.get("byTopic") or []
    if by_topic and len(by_topic) > 1:
        # D138：同一条线上的知识点放一起，教师能看出"整块没掌握"
        for g in by_topic:
            lines.append(f"### 📚 {g['topic']}")
            for r in g["items"]:
                _render_one(lines, r)
        rec = []          # 已按主题渲染，避免下面重复
    for r in rec:
        mark = "⚠️ 仍在持续" if r["persisting"] else "📉 有改善"
        lines.append(f"### {r['term']} — 出现 {r['packs']} 次 · {mark}")
        for pt in r["trail"]:
            lines.append(f"- {pt['name']}（{pt.get('at') or '—'}）："
                         f"{pt['students']} 人出错（{pt['rate'] * 100:.0f}%）")
        lines.append("")
    oo = stat.get("oneOff") or []
    if oo:
        lines += ["## 仅出现一次（可能是当次内容难点）",
                  "、".join(x["term"] for x in oo[:30]), ""]
    lines.append("---")
    lines.append("*本报告只给教师：汇总同一班级多次作业的出错知识点，不上传、不发给学生。*")
    return "\n".join(lines)


def generate(ws, class_dir: str, out_dir=None, *, title: str = "",
             min_recur: int = MIN_RECUR) -> dict:
    """统计 + 落盘（`trend.md` / `trend.json`）。"""
    topics: dict[str, str] = {}
    try:
        from .teacher_report import load_topic_map
        topics = load_topic_map(ws)
    except Exception:  # noqa: BLE001 —— 分组是增强，失败不影响趋势本身
        topics = {}
    stat = analyze(ws, class_dir, min_recur=min_recur, topics=topics)
    md = render_md(stat, title=title)
    stat["feedback_md"] = md
    written: list[str] = []
    if out_dir is not None:
        d = Path(out_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / "trend.md").write_text(md, encoding="utf-8")
        (d / "trend.json").write_text(
            json.dumps({k: v for k, v in stat.items() if k != "feedback_md"},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        written = [str(d / "trend.md"), str(d / "trend.json")]
    return {"ok": True, "stat": {k: v for k, v in stat.items() if k != "feedback_md"},
            "markdown": md, "written": written}

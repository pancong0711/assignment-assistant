"""D86 §6：把批阅结果落成"本地批阅草稿"（供 PWA 人工批阅栏查看/修改/一键上传）。

产物来源：`classes/<dir>/grading/<task>/{evaluations,transcripts,reports}`
写入：`<xxt_home>/grade-drafts/<classId>/<workId>.json`（D85 存储，键=workAnswerId→姓名）
- AI 草稿：score=total_score、comment=feedback_md（纯文本）、images=[报告 PNG base64]
- 支持 `kind="ai"|"human"`：报告标注不同（人工报告用于"教师自己写的批阅"）
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from loguru import logger


def _cut_markdown(text: str) -> str:
    """把 Markdown 批语收敛成"适合直接贴进平台的纯文本"（去重格式符，保留公式）。"""
    out = []
    for line in str(text or "").splitlines():
        t = line.rstrip()
        t = t.replace("**", "").replace("__", "")
        if t.startswith(("- ", "* ")):
            t = "· " + t[2:]
        out.append(t)
    return "\n".join(out).strip()


def save_drafts_from_grading(ws, *, class_id: str, work_id: str, task_id: str,
                             class_dir: str = "", kind: str = "ai",
                             with_report_png: bool = True, katex_dir=None,
                             home=None) -> dict:
    """读批阅产物 → 写本地批阅草稿（键优先用 plan 里的 workAnswerId，回落姓名）。"""
    from ..xxt import grade_store
    from .flow import grading_dir
    from .report import build_report_md, render_report_png

    ws = Path(ws)
    resolved_class_dir = str(class_dir or "").strip().strip("/") or f"classes/{class_id}"
    task = {"id": str(task_id), "class_dir": resolved_class_dir}
    base = grading_dir(ws, task)
    ev_dir, tr_dir = base / "evaluations", base / "transcripts"
    if not ev_dir.is_dir():
        return {"ok": False, "error": f"无评阅产物：{ev_dir}"}

    # plan（可选）：拿 workAnswerId / tag
    wa_by_name: dict[str, str] = {}
    try:
        from . import inputs as _inputs
        plan = _inputs.load_plan(ws, task_id, class_dir) or {}
        for s in (plan.get("students") or []):
            if s.get("name"):
                wa_by_name[str(s["name"])] = str(s.get("workAnswerId") or "")
    except Exception:  # noqa: BLE001
        pass

    written = []
    for f in sorted(ev_dir.glob("[!_]*.json")):
        try:
            ev = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        student = str(ev.get("student") or f.stem)
        key = wa_by_name.get(student) or student
        score = ev.get("total_score")
        comment = _cut_markdown(ev.get("feedback_md") or "")
        images = []
        if with_report_png:
            tf = tr_dir / f"{f.stem}.json"
            if tf.is_file():
                try:
                    md = build_report_md(tf, f)
                    sub = f"{student}" + (f" · tag {ev.get('tag')}" if ev.get("tag") else "")
                    png = render_report_png(md, base / "reports" / f"{f.stem}.png",
                                            kind=kind, title=f"{student} 批阅报告",
                                            subtitle=sub, katex_dir=katex_dir)
                    if png and Path(png).is_file():
                        images.append({"name": f"{f.stem}-report.png",
                                       "data_b64": base64.b64encode(Path(png).read_bytes()).decode()})
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"报告 PNG 生成失败（{student}）：{str(exc)[:120]}")
        # D92-R2：写入**双套**结构；AI 产物落 ai 套（人工审核另写 human/修订，不覆盖此基线）
        ai_set = {"score": score, "comment": comment, "reportImages": images or []}
        if str(kind) == "human":
            # D119：按 (ws, class_dir, task_id) 写入新布局 —— 不同作业批次互不覆盖
            rep = grade_store.save_draft_sets(
                home, class_id, work_id, key, human={**ai_set, "used": True},
                human_mode="replace", student=student, tag=ev.get("tag") or "",
                ws=ws, class_dir=resolved_class_dir, task_id=str(task_id))
        else:
            rep = grade_store.save_draft_sets(
                home, class_id, work_id, key, ai=ai_set,
                student=student, tag=ev.get("tag") or "",
                ws=ws, class_dir=resolved_class_dir, task_id=str(task_id))
        written.append({"student": student, "key": key, "ok": rep.get("ok"),
                        "score": score, "images": len(images)})
    return {"ok": bool(written), "count": len(written), "drafts": written,
            "file": str(grade_store.draft_file(ws, class_id, work_id,
                                               class_dir=resolved_class_dir,
                                               task_id=str(task_id), home=home) or "")}

def render_reports_from_drafts(ws, *, class_id: str, work_id: str, task_id: str = "",
                               class_dir: str = "", home=None, katex_dir=None,
                               with_report_png: bool = True) -> dict:
    """D92-R2：按**已保存的双套草稿**逐生生成报告 PNG（人工在前 + 【附件】AI + 修订标红）。

    - 读 <xxt_home>/grade-drafts/<classId>/<workId>.json → normalize_draft；
    - 按 {构成 × 修订} 生成 md/html/png；写回草稿 human.reportImages（覆盖旧报告图）。
    """
    import base64
    from pathlib import Path
    from ..xxt import grade_store
    from .report import (_mode_report_md, report_html_from_md, html_to_png)

    ws = Path(ws)
    if home is None:
        from ..xxt.session import xxt_home
        home = xxt_home()
    # D119：新布局优先，旧布局回落
    data = grade_store.read_drafts(home, class_id, work_id, ws=ws,
                                   class_dir=str(class_dir or f"classes/{class_id}"),
                                   task_id=str(task_id))
    if not data:
        return {"ok": False, "error": "无本地批阅草稿（先跑一次 AI 批阅或保存人工批阅）"}
    out_root = ws / (class_dir or f"classes/{class_id}") / "grading" / (task_id or "task") / "reports"
    out_root.mkdir(parents=True, exist_ok=True)
    done = []
    for key, raw in data.items():
        d = grade_store.normalize_draft(raw if isinstance(raw, dict) else {})
        student = str(d.get("student") or key)
        md, kind = _mode_report_md(student=student, ai=d.get("ai") or {},
                                   human=d.get("human") or {},
                                   human_mode=d.get("humanMode") or "none",
                                   revision=d.get("revision") or {},
                                   revised=bool(d.get("revised")))
        title = f"{student} 批阅报告"
        base = out_root / f"{student}"
        md_file = base.with_suffix(".md"); md_file.write_text(md, encoding="utf-8")
        html_file = base.with_suffix(".html")
        html_file.write_text(report_html_from_md(md, kind=kind, title=title,
                                                 katex_dir=katex_dir), encoding="utf-8")
        imgs = []
        if with_report_png:
            png = html_to_png(report_html_from_md(md, kind=kind, title=title, katex_dir=katex_dir),
                              base.with_suffix(".png"))
            if png and Path(png).is_file():
                imgs.append({"name": f"{student}-report.png",
                             "data_b64": base64.b64encode(Path(png).read_bytes()).decode()})
        # 报告图回写人工套（供上传）；不动 ai 基线
        grade_store.save_draft_sets(home, class_id, work_id, key,
                                    human={"reportImages": imgs} if imgs else None)
        done.append({"key": key, "student": student, "kind": kind,
                     "revised": bool(d.get("revised")), "png": bool(imgs)})
    return {"ok": True, "count": len(done), "reports": done, "dir": str(out_root)}


def save_transcripts_to_drafts(ws, *, class_id: str, work_id: str, task_id: str,
                               class_dir: str = "", transcripts_dir=None,
                               plan: "dict | None" = None) -> int:
    """D126：把转录产物写入批阅草稿的 `ai.transcript`（仅转录也能在逐生审核里看到）。

    只填空缺的 transcript 字段，**不影响**已有的分数/批语；返回写入条数。

    D126-FIX：`plan` 可由调用方直接传入。草稿 key 必须是 **workAnswerId**
    （前端 `drafts[students[].key]` 按它取），而 plan 未落盘时 `load_plan()` 读不到，
    过去会静默退化成用姓名当 key → 写了草稿但逐生审核依旧空白。
    """
    from pathlib import Path
    from ..xxt import grade_store

    if not (class_id and work_id):
        return 0
    tdir = Path(transcripts_dir) if transcripts_dir else None
    if tdir is None or not tdir.is_dir():
        return 0
    # 学生名 → workAnswerId：优先用调用方传入的 plan（run_task 的 plan 不一定落盘）
    if plan is None:
        try:
            from . import inputs as _inputs
            plan = _inputs.load_plan(ws, task_id, class_dir) or {}
        except Exception:  # noqa: BLE001
            plan = {}
    wa_by_name: dict[str, str] = {}
    for st in ((plan or {}).get("students") or []):
        if st.get("name"):
            wa_by_name[str(st["name"])] = str(st.get("workAnswerId") or "")

    n = 0
    for tf in sorted(tdir.glob("[!_]*.json")):
        try:
            t = json.loads(tf.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        student = str(t.get("student") or tf.stem)
        key = wa_by_name.get(student) or student
        text = str(t.get("markdown") or "").strip()
        if not text:
            continue
        rep = grade_store.save_draft_sets(
            None, class_id, work_id, key,
            ai={"transcript": text, "transcriptModel": str(t.get("model") or "")},
            student=student, ws=Path(ws), class_dir=class_dir, task_id=task_id)
        if rep.get("ok"):
            n += 1
    return n

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
    task = {"id": str(task_id), "class_dir": class_dir or f"classes/{class_id}"}
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
        rep = grade_store.save_draft(
            home, class_id, work_id, key, score=score, comment=comment,
            images=images or None,
            extra={"source": f"ai:{task_id}" if kind == "ai" else f"human:{task_id}",
                   "student": student, "tag": ev.get("tag") or ""})
        written.append({"student": student, "key": key, "ok": rep.get("ok"),
                        "score": score, "images": len(images)})
    return {"ok": bool(written), "count": len(written), "drafts": written,
            "file": str((grade_store.draft_file(home, class_id, work_id) or ""))}

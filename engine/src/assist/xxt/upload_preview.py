"""D193 §2/§3：上传前对照表（只读）。

回答教师三个问题：
1. 这名学生平台是否已批阅？（status）
2. 本地要上传的分数/批语/报告版本是什么？（local）
3. 平台当前那份是什么？（platform —— 仅在已批阅时读取）

只读：打开批阅列表 + 逐个读取批阅页读回，不写任何内容；不落截图正文、不回显 cookie。
"""
from __future__ import annotations

import time
from pathlib import Path


def build_preview(*, storage, course_id: str, class_id: str, cpi: str, work_id: str,
                  payloads: "list[dict] | None" = None,
                  only: str = "", read_platform: bool = True) -> dict:
    """生成对照表行：{student, platformStatus, localScore, localCommentLength,
    reportVersion, platformScore, platformCommentLength, decision, reason}。

    `read_platform=False` 时只做本地部分（不启动浏览器）。
    """
    from . import grade_plan, grade_upload
    rows: list[dict] = []
    local = {}
    for p in payloads or []:
        stu = str(p.get("student") or p.get("key") or "")
        if only and only not in (stu, str(p.get("key") or "")):
            continue
        local[stu] = p
        rows.append({
            "student": stu,
            "localScore": p.get("score"),
            "localCommentLength": len(grade_plan.text_of(p.get("comment") or "")),
            "reportVersion": str((p.get("report") or {}).get("version") or ""),
            "reportTag": str((p.get("report") or {}).get("tag") or ""),
            "platformStatus": "",
            "platformScore": None,
            "platformCommentLength": None,
            "decision": "",
            "reason": "",
        })
    if not read_platform or not rows:
        for r in rows:
            p = local.get(r["student"]) or {}
            plan = grade_plan.decide(status="", local_score=p.get("score"),
                                     local_comment=str(p.get("comment") or ""))
            r["decision"], r["reason"] = plan["decision"], plan["reason"]
        return {"ok": True, "mode": "local-only", "rows": rows,
                "summary": grade_plan.summarize(
                    [{"student": r["student"], "decision": r["decision"],
                      "ok": r["decision"] in (grade_plan.NEW,)} for r in rows])}

    from .grade_upload import (resolve_work_id_on_page, _open_mark_list,
                               _students_from_mark_list, find_student_row,
                               _start_browser, _close)
    from .marking import open_mark_page, read_back
    pw, browser, page, err = _start_browser(storage)
    if err:
        return {**err, "ok": False, "rows": rows, "mode": "platform"}
    try:
        wid = resolve_work_id_on_page(page, str(course_id), str(class_id), str(cpi), str(work_id))
        _open_mark_list(page, str(course_id), str(class_id), wid)
        platform_rows = _students_from_mark_list(page)
        for r in rows:
            prow = find_student_row(platform_rows, r["student"])
            status = str((prow or {}).get("status") or "")
            r["platformStatus"] = status
            platform = None
            wa = str((prow or {}).get("workAnswerId") or "")
            if read_platform and "已批阅" in status and wa:
                try:
                    open_mark_page(page, str(course_id), str(class_id), wid, wa)
                    rb = read_back(page)
                    snap = grade_plan.platform_snapshot(rb)
                    platform = snap
                    r["platformScore"] = snap.get("score")
                    r["platformCommentLength"] = snap.get("commentLength")
                except Exception as exc:  # noqa: BLE001 —— 单生读取失败不影响其它行
                    r["reason"] = f"读取平台批阅内容失败：{str(exc)[:120]}"
            p = local.get(r["student"]) or {}
            plan = grade_plan.decide(status=status,
                                     local_score=p.get("score"),
                                     local_comment=str(p.get("comment") or ""),
                                     platform=platform,
                                     has_local_content=bool(p))
            r["decision"], r["reason"] = plan["decision"], plan["reason"]
            r["needsConfirm"] = bool(plan.get("needsConfirm"))
        summary = grade_plan.summarize(
            [{"student": r["student"], "decision": r["decision"],
              "ok": r["decision"] in (grade_plan.NEW, grade_plan.UNCHANGED)}
             for r in rows])
        # D196：上传范围 = **已提交**学生；未提交不上传，批语空要提醒去批阅。
        readiness = grade_plan.upload_readiness(
            platform_rows=platform_rows,
            payloads=[p for p in (payloads or [])])
        for r in rows:
            hit = next((x for x in readiness["rows"] if x["student"] == r["student"]), None)
            if hit:
                r["submitted"] = hit["submitted"]
                r["readyState"] = hit["state"]
                r["readyReason"] = hit["reason"]
        return {"ok": True, "mode": "platform", "rows": rows, "summary": summary,
                "readiness": readiness,
                "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    finally:
        _close(pw, browser)


def local_preview(*, ws, class_dir: str = "", task_id: str = "",
                  class_id: str = "", work_id: str = "", only: str = "") -> dict:
    """纯本地对照（不触网）：本地草稿分数/批语 + 报告版本 + 最近上传清单结果。"""
    from ..xxt import grade_store
    from ..grading import report_versions
    from .grade_upload import drafts_to_payloads, upload_manifest_path

    home = None
    try:
        from .session import xxt_home
        home = xxt_home()
    except Exception:  # noqa: BLE001
        home = None
    drafts = grade_store.read_drafts_normalized(home, class_id, work_id, ws=Path(ws),
                                                class_dir=class_dir, task_id=task_id)
    payloads = drafts_to_payloads(drafts, only=only)
    reports_dir = Path(ws) / (class_dir or f"classes/{class_id}") / "grading" / (
        task_id or "task") / "reports"
    rows = []
    for p in payloads:
        stu = str(p.get("student") or p.get("key") or "")
        entry = report_versions.latest_entry(reports_dir, stu) or {}
        rows.append({
            "student": stu,
            "key": str(p.get("key") or ""),
            "localScore": p.get("score"),
            "localCommentLength": len(str(p.get("comment") or "")),
            "reportVersion": str((p.get("report") or {}).get("version")
                                 or entry.get("version") or ""),
            "reportTag": str((p.get("report") or {}).get("tag") or entry.get("tag") or ""),
        })
    # D196：本地就能判断“批语为空/无报告”的学生 → 提醒去批阅（不需要读平台）
    need_comment = [r["student"] for r in rows if not r["localCommentLength"]]
    no_report = [r["student"] for r in rows if not r["reportVersion"]]
    return {"ok": True, "count": len(rows), "rows": rows,
            "needComment": need_comment, "noReport": no_report,
            "reportsDir": str(reports_dir),
            "manifest": str(upload_manifest_path(ws, class_dir, task_id, work_id) or "")}

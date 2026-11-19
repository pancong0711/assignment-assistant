"""D193 §2/§3：上传前对照表（只读）。

回答教师三个问题：
1. 这名学生平台是否已批阅？（status）
2. 本地要上传的分数/批语/报告版本是什么？（local）
3. 平台当前那份是什么？（platform —— 仅在已批阅时读取）

只读：打开批阅列表 + 逐个读取批阅页读回，不写任何内容；不落截图正文、不回显 cookie。
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

CACHE_VERSION = 1
DEFAULT_TTL_SEC = 1800      # 平台状态缓存默认 30 分钟


def _safe(x: str) -> str:
    import re
    return re.sub(r"[\\/:*?\"<>|]", "_", str(x or "")).strip(" .") or "x"


def cache_path(ws, class_dir: str = "", task_id: str = "",
               work_id: str = "") -> "Path | None":
    """D210：上传前对照的本地缓存文件。

    位置：`<ws>/<classDir>/grading/<taskId>/upload/preview-<workId>.json`
    （与上传清单同目录，便于一起清理/备份）。
    """
    cd = str(class_dir or "").strip().strip("/")
    tid = str(task_id or "").strip()
    wid = str(work_id or "").strip()
    if not (ws and cd and tid and wid):
        return None
    return Path(ws).resolve() / cd / "grading" / _safe(tid) / "upload" / f"preview-{_safe(wid)}.json"


def payload_fingerprint(payloads: "list[dict] | None") -> str:
    """本地内容指纹：学生/分数/批语/报告版本。用于判断缓存是否“本地已过期”。"""
    items = []
    for p in payloads or []:
        p = p or {}
        items.append([
            str(p.get("student") or p.get("key") or ""),
            str(p.get("score")),
            hashlib.sha256(str(p.get("comment") or "").encode("utf-8")).hexdigest()[:12],
            str((p.get("report") or {}).get("version") or ""),
            len(p.get("images") or []),
        ])
    items.sort()
    raw = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def read_cache(path: "Path | None") -> "dict | None":
    if path is None or not Path(path).is_file():
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 —— 坏缓存当没有
        return None
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return None
    if not isinstance(data.get("platformRows"), list):
        return None
    return data


def write_cache(path: "Path | None", *, course_id: str, class_id: str,
                work_id: str, task_id: str, class_dir: str,
                platform_rows: list, per_student: dict,
                fingerprint: str) -> None:
    if path is None:
        return
    data = {
        "version": CACHE_VERSION,
        "courseId": str(course_id), "classId": str(class_id),
        "workId": str(work_id), "taskId": str(task_id), "classDir": str(class_dir),
        "fetchedAt": time.time(),
        "fetchedAtText": time.strftime("%Y-%m-%d %H:%M:%S"),
        "fingerprint": fingerprint,
        "platformRows": platform_rows,
        "perStudent": per_student,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        from ..filelock import atomic_write_text
        atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=1))
    except Exception:  # noqa: BLE001 —— 缓存写失败不影响主流程
        pass


def invalidate_cache(ws, class_dir: str = "", task_id: str = "",
                     work_id: str = "") -> bool:
    """D210：上传后使缓存失效（平台状态已变），下次对照会重新读取。"""
    p = cache_path(ws, class_dir, task_id, work_id)
    try:
        if p is not None and p.is_file():
            p.unlink()
            return True
    except OSError:
        pass
    return False


def _platform_row_brief(row: dict) -> dict:
    return {"name": str(row.get("name") or ""),
            "status": str(row.get("status") or ""),
            "score": str(row.get("score") or ""),
            "workAnswerId": str(row.get("workAnswerId") or "")}


def compose_preview(*, payloads: "list[dict] | None", platform_rows: "list[dict] | None",
                    per_student: "dict | None" = None, only: str = "",
                    mode: str = "platform") -> dict:
    """D210：由「本地 payloads + 平台快照」组装对照表（live / cache 共用同一口径）。

    这样缓存命中时**不需要重新计算逻辑**：只要把缓存的平台快照喂进来即可，
    本地批语/分数变化会立刻反映在 decision 上。
    """
    from . import grade_plan
    per_student = per_student or {}
    local = {}
    rows: list[dict] = []
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
    if mode == "local-only":
        for r in rows:
            p = local.get(r["student"]) or {}
            plan = grade_plan.decide(status="", local_score=p.get("score"),
                                     local_comment=str(p.get("comment") or ""))
            r["decision"], r["reason"] = plan["decision"], plan["reason"]
        return {"ok": True, "mode": "local-only", "rows": rows,
                "summary": grade_plan.summarize(
                    [{"student": r["student"], "decision": r["decision"],
                      "ok": r["decision"] in (grade_plan.NEW,)} for r in rows])}

    for r in rows:
        prow = next((x for x in platform_rows or []
                     if str(x.get("name") or "").strip() == r["student"]), None)
        status = str((prow or {}).get("status") or "")
        r["platformStatus"] = status
        r["platformScore"] = (prow or {}).get("score") or None
        snap = per_student.get(r["student"]) or None
        if snap:
            r["platformScore"] = snap.get("score")
            r["platformCommentLength"] = snap.get("commentLength")
        p = local.get(r["student"]) or {}
        plan = grade_plan.decide(status=status,
                                 local_score=p.get("score"),
                                 local_comment=str(p.get("comment") or ""),
                                 platform=snap,
                                 has_local_content=bool(p))
        r["decision"], r["reason"] = plan["decision"], plan["reason"]
        r["needsConfirm"] = bool(plan.get("needsConfirm"))
    summary = grade_plan.summarize(
        [{"student": r["student"], "decision": r["decision"],
          "ok": r["decision"] in (grade_plan.NEW, grade_plan.UNCHANGED)}
         for r in rows])
    readiness = grade_plan.upload_readiness(platform_rows=platform_rows,
                                            payloads=[p for p in (payloads or [])])
    for r in rows:
        hit = next((x for x in readiness["rows"] if x["student"] == r["student"]), None)
        if hit:
            r["submitted"] = hit["submitted"]
            r["readyState"] = hit["state"]
            r["readyReason"] = hit["reason"]
    return {"ok": True, "mode": mode, "rows": rows, "summary": summary,
            "readiness": readiness, "at": time.strftime("%Y-%m-%d %H:%M:%S")}


def build_preview(*, storage, course_id: str, class_id: str, cpi: str, work_id: str,
                  payloads: "list[dict] | None" = None,
                  only: str = "", read_platform: bool = True,
                  ws=None, class_dir: str = "", task_id: str = "",
                  force_refresh: bool = False,
                  max_age_sec: int = DEFAULT_TTL_SEC) -> dict:
    """生成对照表行：{student, platformStatus, localScore, localCommentLength,
    reportVersion, platformScore, platformCommentLength, decision, reason}。

    `read_platform=False` 时只做本地部分（不启动浏览器）。
    """
    from . import grade_plan

    if not read_platform or not (payloads or []):
        return compose_preview(payloads=payloads, platform_rows=[], only=only,
                               mode="local-only")

    # D210：优先用本地缓存（平台状态读取很慢：需打开批阅列表并逐生读批阅页）
    cp = cache_path(ws, class_dir, task_id, work_id)
    fp = payload_fingerprint(payloads)
    cached = read_cache(cp)
    if cached and not force_refresh:
        age = max(0.0, time.time() - float(cached.get("fetchedAt") or 0))
        if age <= max_age_sec:
            rep = compose_preview(payloads=payloads,
                                  platform_rows=cached.get("platformRows") or [],
                                  per_student=cached.get("perStudent") or {},
                                  only=only, mode="cache")
            rep["cache"] = {
                "hit": True, "ageSec": int(age), "maxAgeSec": int(max_age_sec),
                "fetchedAt": cached.get("fetchedAtText") or "",
                "stale": str(cached.get("fingerprint") or "") != fp,
            }
            if rep["cache"]["stale"]:
                rep["cache"]["hint"] = ("本地批语/分数/报告版本已变化"
                                        "（已按最新本地内容重新判定）；"
                                        "如需最新平台状态请点「重新读取平台状态」")
            return rep

    from .grade_upload import (resolve_work_id_on_page, _open_mark_list,
                               _students_from_mark_list, find_student_row,
                               _start_browser, _close)
    from .marking import open_mark_page, read_back
    pw, browser, page, err = _start_browser(storage)
    if err:
        # 浏览器起不来时，把“仅本地”的对照结果一并返回，至少让教师看到本地内容
        local_rep = compose_preview(payloads=payloads, platform_rows=[], only=only,
                                    mode="local-only")
        return {**err, "ok": False, "mode": "platform",
                "rows": local_rep.get("rows") or [],
                "summary": local_rep.get("summary") or {}}
    try:
        wid = resolve_work_id_on_page(page, str(course_id), str(class_id), str(cpi), str(work_id))
        _open_mark_list(page, str(course_id), str(class_id), wid)
        platform_rows = _students_from_mark_list(page)
        per_student: dict = {}
        for p in payloads or []:
            stu = str(p.get("student") or p.get("key") or "")
            if not stu:
                continue
            prow = find_student_row(platform_rows, stu)
            status = str((prow or {}).get("status") or "")
            wa = str((prow or {}).get("workAnswerId") or "")
            # 只有“已批阅”类状态才值得打开批阅页读回内容（逐生打开很慢）
            if wa and grade_plan.is_reviewed_status(status):
                try:
                    open_mark_page(page, str(course_id), str(class_id), wid, wa)
                    snap = grade_plan.platform_snapshot(read_back(page))
                    per_student[stu] = snap
                except Exception:  # noqa: BLE001 —— 单生读取失败不影响其它行
                    pass
        rep = compose_preview(payloads=payloads, platform_rows=platform_rows,
                              per_student=per_student, only=only, mode="platform")
        write_cache(cp, course_id=str(course_id), class_id=str(class_id),
                    work_id=str(work_id), task_id=str(task_id),
                    class_dir=str(class_dir), platform_rows=[
                        _platform_row_brief(x) for x in platform_rows],
                    per_student=per_student, fingerprint=fp)
        rep["cache"] = {"hit": False, "ageSec": 0, "maxAgeSec": int(max_age_sec),
                        "fetchedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "stale": False}
        return rep
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

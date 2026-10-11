"""D75-1b/c：作答页只读探针 + 学生图片/两栏批语下载。

只读保证：只放行 GET/HEAD/OPTIONS（+ 调用方显式传入的只读 POST 白名单）；
被拦下的非 GET 全部记录到 probe/aborted，便于补白名单或排查。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse


def _install_route(ctx, aborted: list, allow_post: "list[str] | None" = None):
    allow = tuple(allow_post or ())

    def handler(route, request):
        m = (request.method or "").upper()
        if m in ("GET", "HEAD", "OPTIONS") or any(p in request.url for p in allow):
            return route.continue_()
        aborted.append({"method": m, "url": request.url[:300]})
        return route.abort()

    ctx.route("**/*", handler)


def _students_from_mark(page, course_id: str, class_id: str, work_id: str) -> list[dict]:
    from .extractor import JS_REVIEW, MARK_URL, parse_work_answer_id
    page.goto(MARK_URL.format(course=course_id, clazz=class_id, work=work_id),
              wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    rows = page.evaluate(JS_REVIEW) or []
    out = []
    for r in rows:
        wa = parse_work_answer_id(r.get("review_path") or "")
        if r.get("name") and wa:
            out.append({"name": r.get("name"), "status": r.get("status") or "",
                        "workAnswerId": wa, "review_path": r.get("review_path") or ""})
    return out


def _detail_summary(detail: dict) -> dict:
    detail = detail or {}
    return {
        "images": len(detail.get("images") or []),
        "comment_len": len(detail.get("comment") or ""),
        "per_question_comments": len(detail.get("per_question_comments") or []),
        "score": detail.get("score") or "",
        "error": detail.get("error") or "",
    }


def probe_review(storage, course_id: str, class_id: str, work_id: str, *,
                 sample: int = 1, use_fallback: bool = False,
                 allow_post: "list[str] | None" = None) -> dict:
    """只读探针：打开列表页 + 前 N 个学生详情页，记录被拦截的非 GET 请求与字段命中。"""
    from playwright.sync_api import sync_playwright
    from .session import check_session, _launch
    from .extractor import JS_REVIEW_DETAIL, review_work_url
    storage = Path(storage)
    chk = check_session(storage)
    rep: dict = {"ok": False, "aborted": [], "students": [], "details": []}
    if chk.get("verdict") != "alive":
        rep.update({"error": "session dead", "hint": chk.get("hint", "请先 assist xxt login")})
        return rep
    with sync_playwright() as pw:
        browser = _launch(pw, headless=True)
        ctx = browser.new_context(storage_state=str(storage),
                                  viewport={"width": 1440, "height": 1000}, locale="zh-CN")
        aborted: list = []
        _install_route(ctx, aborted, allow_post)
        page = ctx.new_page()
        students = _students_from_mark(page, course_id, class_id, work_id)
        rep["students"] = [{"name": s["name"], "status": s["status"],
                            "workAnswerId": s["workAnswerId"]} for s in students]
        for s in students[: max(1, int(sample))]:
            sp = ctx.new_page()
            try:
                sp.goto(review_work_url(course_id, class_id, work_id,
                                        s["workAnswerId"], fallback=use_fallback),
                        wait_until="load", timeout=60000)
                sp.wait_for_timeout(2000)
                detail = sp.evaluate(JS_REVIEW_DETAIL)
            except Exception as exc:  # noqa: BLE001
                detail = {"error": str(exc)[:200]}
            rep["details"].append({"name": s["name"], "workAnswerId": s["workAnswerId"],
                                   **_detail_summary(detail)})
            sp.close()
        browser.close()
    rep.update({"ok": True, "aborted": aborted})
    return rep


def download_review(storage, home, course_id: str, class_id: str, work_id: str, *,
                    course_name: str = "", class_name: str = "", work_name: str = "",
                    use_fallback: bool = False, limit: int = 0,
                    allow_post: "list[str] | None" = None,
                    months: int = 6) -> dict:
    """逐生下载作答图片 + 两栏批语，写 students.json；返回回执。"""
    from playwright.sync_api import sync_playwright
    from .session import check_session, _launch
    from .extractor import JS_REVIEW_DETAIL, review_work_url
    from . import review as review_store
    storage = Path(storage)
    chk = check_session(storage)
    if chk.get("verdict") != "alive":
        return {"ok": False, "error": "session dead",
                "hint": chk.get("hint", "请先 assist xxt login")}
    wdir = review_store.work_dir(home, class_id, work_id)
    wdir.mkdir(parents=True, exist_ok=True)
    aborted: list = []
    students_out: list = []
    steps: list = []
    total_images = 0
    with sync_playwright() as pw:
        browser = _launch(pw, headless=True)
        ctx = browser.new_context(storage_state=str(storage),
                                  viewport={"width": 1440, "height": 1000}, locale="zh-CN")
        _install_route(ctx, aborted, allow_post)
        page = ctx.new_page()
        students = _students_from_mark(page, course_id, class_id, work_id)
        if limit and int(limit) > 0:
            students = students[: int(limit)]
        for idx, s in enumerate(students, 1):
            sp = ctx.new_page()
            imgs: list[str] = []
            detail: dict = {}
            try:
                sp.goto(review_work_url(course_id, class_id, work_id,
                                        s["workAnswerId"], fallback=use_fallback),
                        wait_until="load", timeout=60000)
                sp.wait_for_timeout(2000)
                detail = sp.evaluate(JS_REVIEW_DETAIL) or {}
                for n, url in enumerate(detail.get("images") or [], 1):
                    try:
                        resp = ctx.request.get(url, timeout=30000)
                        if not resp.ok:
                            continue
                        ext = os.path.splitext(urlparse(url).path)[1] or ".jpg"
                        fn = review_store.image_filename(
                            s["name"], class_name or class_id, work_name or work_id, n, ext)
                        (wdir / fn).write_bytes(resp.body())
                        imgs.append(fn)
                        total_images += 1
                    except Exception:  # noqa: BLE001
                        continue
                steps.append({"action": "下载学生作答",
                              "detail": f'{s["name"]}: {len(imgs)} 张图',
                              "ts": time.strftime("%H:%M:%S")})
            except Exception as exc:  # noqa: BLE001
                detail = {"error": str(exc)[:200]}
                steps.append({"action": "下载失败", "detail": f'{s["name"]}: {exc}'[:120],
                              "ts": time.strftime("%H:%M:%S")})
            finally:
                sp.close()
            students_out.append({
                "studentId": "",
                "name": s["name"],
                "workAnswerId": s["workAnswerId"],
                "status": s.get("status") or "",
                "images": imgs,
                "comment": detail.get("comment") or "",
                "per_question_comments": detail.get("per_question_comments") or [],
                "ueditor0": detail.get("ueditor0") or "",
                "score": detail.get("score") or "",
                "error": detail.get("error") or "",
            })
        browser.close()
    manifest = {
        "classId": str(class_id), "workId": str(work_id), "courseId": str(course_id),
        "courseName": course_name, "className": class_name or str(class_id),
        "workName": work_name or str(work_id),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "students": students_out, "aborted": aborted[:80],
    }
    mp = review_store.write_manifest(home, class_id, work_id, manifest)
    try:
        pruned = review_store.prune_review(home, months=months)
    except Exception:  # noqa: BLE001
        pruned = None
    return {"ok": True, "classId": str(class_id), "workId": str(work_id),
            "students": len(students_out), "images": total_images,
            "aborted": len(aborted), "manifest": str(mp), "out_dir": str(wdir),
            "steps": steps, "pruned": pruned}

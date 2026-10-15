"""D84 §2/§3：批阅回传领域层（设为已交 + 评语/图片上传 + 打分）。

- `mark_submitted()`：把某「未交」学生设为已交（补交/测试用），并取回 workAnswerId；
- `upload_grade()`：在某学生批阅页写作业批语（文字+图片）/题目批语/分数，可选提交。

安全口径（与 notice/work-publish 一致）：
- 目标班必须命中 `xxt.write_allowlist`（validate_work_target）；
- **默认 dry-run**：只打开/填入/上传媒体，不点提交；
- 真提交需显式 `send=True`；幂等：已批阅状态默认拒绝重复提交（force=True 覆盖）；
- 截图 + receipt 落 `<xxt_home>/grade-uploads/`；异常带步骤名返回。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from loguru import logger

from .marking import (fill_scores, normalize_comment_html, open_mark_page,
                      read_back, set_comment_html, set_question_comments_html,
                      submit, upload_comment_image)


def receipt_dir(home=None) -> Path:
    """receipt/截图目录：<xxt_home>/grade-uploads（home 仅测试可注入）。"""
    if home is None:
        from .session import xxt_home
        home = xxt_home()
    d = Path(home) / "grade-uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _shot(page, tag: str) -> str:
    try:
        p = receipt_dir() / f"{tag}-{int(time.time())}.png"
        page.screenshot(path=str(p), full_page=True)
        return str(p)
    except Exception:  # noqa: BLE001
        return ""


def _write_receipt(kind: str, payload: dict) -> str:
    try:
        p = receipt_dir() / f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}.json"
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        return str(p)
    except Exception:  # noqa: BLE001
        return ""


# ---------------- 学生定位（纯函数便于测试） ----------------

def find_student_row(rows: list[dict], student: str) -> "dict | None":
    """在 mark 页学生行里按姓名/学号/workAnswerId 匹配（大小写不敏感）。"""
    key = str(student or "").strip().lower()
    if not key:
        return None
    fuzzy = None
    for r in rows or []:
        name = str(r.get("name") or "").strip().lower()
        wa = str(r.get("workAnswerId") or "").lower()
        if key == name or key == wa:
            return r
        if fuzzy is None and key and key in name:
            fuzzy = r
    return fuzzy


def _students_from_mark_list(page) -> list[dict]:
    from .extractor import JS_REVIEW, parse_work_answer_id
    rows = page.evaluate(JS_REVIEW) or []
    out = []
    for r in rows:
        wa = parse_work_answer_id(r.get("review_path") or "")
        out.append({"name": str(r.get("name") or "").strip(),
                    "status": str(r.get("status") or "").strip(),
                    "workAnswerId": wa, "review_path": r.get("review_path") or ""})
    return out


def _open_mark_list(page, course_id: str, class_id: str, work_id: str) -> str:
    from .extractor import MARK_URL
    url = MARK_URL.format(course=course_id, clazz=class_id, work=work_id)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    return url


def _start_browser(storage):
    """→ (pw, browser, page, err)。err 非 None 时调用方直接返回。"""
    from playwright.sync_api import sync_playwright
    from .session import check_session, _launch
    chk = check_session(Path(storage))
    if chk.get("verdict") != "alive":
        return None, None, None, {"ok": False, "error": "session dead",
                                  "hint": chk.get("hint", "请先 assist xxt login")}
    pw = sync_playwright().start()
    try:
        browser = _launch(pw, headless=True)
    except Exception as exc:  # noqa: BLE001
        pw.stop()
        return None, None, None, {"ok": False, "error": f"浏览器启动失败：{str(exc)[:200]}"}
    ctx = browser.new_context(storage_state=str(storage),
                              viewport={"width": 1440, "height": 1000}, locale="zh-CN")
    page = ctx.new_page()
    page.on("dialog", lambda d: d.accept())
    return pw, browser, page, None


def _close(pw, browser) -> None:
    for obj in (browser, pw):
        try:
            obj.close() if obj is browser else obj.stop()
        except Exception:  # noqa: BLE001
            pass


# ---------------- §3 设为已交 ----------------

_JS_CLICK_SET_SUBMITTED = """(name) => {
  const uls = document.querySelectorAll('ul.dataBody_td');
  for (const ul of uls) {
    const nameEl = ul.querySelector('li.taskBody_name div.py_name');
    if (!nameEl || nameEl.textContent.trim() !== name) continue;
    for (const a of ul.querySelectorAll('a')) {
      const txt = (a.textContent || '').trim();
      const onclick = a.getAttribute('onclick') || '';
      if (txt.includes('设为已交') || onclick.includes('setSubmit')) {
        a.scrollIntoView();
        a.click();
        return {ok: true, text: txt};
      }
    }
  }
  return {ok: false, reason: 'no-setSubmit-link'};
}"""

_JS_CONFIRM_SUBMITTED_POPUP = """(score) => {
  const inp = document.querySelector('#submitScore');
  if (inp) {
    inp.value = '';
    inp.value = String(score);
    inp.dispatchEvent(new Event('change', {bubbles: true}));
    inp.dispatchEvent(new Event('input', {bubbles: true}));
  }
  const all = document.querySelectorAll('a,button,input[type=button],input[type=submit]');
  for (const el of all) {
    const txt = (el.textContent || el.value || '').trim();
    if (txt !== '确定') continue;
    const st = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    if (st.display !== 'none' && st.visibility !== 'hidden' && r.width > 0 && r.height > 0) {
      el.click();
      return {ok: true, scoreInput: !!inp};
    }
  }
  return {ok: false, reason: 'no-visible-confirm', scoreInput: !!inp};
}"""


def mark_submitted(*, storage, course_id: str, class_id: str, cpi: str, work_id: str,
                   student: str, score: float = 0.0, send: bool = False,
                   workspace=None) -> dict:
    """把某学生设为已交（返回 workAnswerId）；默认 dry-run（不点确定）。"""
    from .work import validate_work_target
    err = validate_work_target(str(course_id), str(class_id), workspace)
    if err:
        return {"ok": False, "error": err}
    pw, browser, page, err = _start_browser(storage)
    if err:
        return err
    result: dict = {"ok": False, "mode": "send" if send else "dry-run",
                    "student": student, "courseId": str(course_id),
                    "classId": str(class_id), "workId": str(work_id)}
    step = "打开批阅列表"
    try:
        list_url = _open_mark_list(page, str(course_id), str(class_id), str(work_id))
        result["listUrl"] = list_url
        rows = _students_from_mark_list(page)
        result["rows"] = len(rows)
        row = find_student_row(rows, student)
        if row is None:
            result["error"] = f"批阅列表未找到学生：{student}（共 {len(rows)} 行）"
            result["screenshot"] = _shot(page, "mark-submitted-notfound")
            return result
        result["matched"] = {"name": row.get("name"), "status": row.get("status"),
                             "workAnswerId": row.get("workAnswerId")}
        if row.get("workAnswerId"):
            result.update({"ok": True, "status": "already-submitted",
                           "workAnswerId": row["workAnswerId"]})
            result["receipt"] = _write_receipt("mark-submitted", result)
            return result

        step = "点击「设为已交」"
        clicked = page.evaluate(_JS_CLICK_SET_SUBMITTED, str(row.get("name") or student))
        if not clicked.get("ok"):
            result["error"] = f"未找到「设为已交」入口：{clicked}"
            result["screenshot"] = _shot(page, "mark-submitted-nolink")
            return result
        page.wait_for_timeout(2000)
        step = "确认弹窗"
        popup = page.evaluate(_JS_CONFIRM_SUBMITTED_POPUP, float(score))
        result["popup"] = popup
        if not popup.get("ok"):
            result["error"] = f"确认弹窗处理失败：{popup}"
            result["screenshot"] = _shot(page, "mark-submitted-popup")
            return result
        result["screenshot"] = _shot(page, "mark-submitted-" + ("sent" if send else "dry"))
        if not send:
            result.update({"ok": True, "status": "dry-run-clicked",
                           "note": "dry-run 已完成弹窗填写；未点「确定」不会生效"})
            result["receipt"] = _write_receipt("mark-submitted", result)
            return result

        step = "等待设交生效"
        page.wait_for_timeout(4000)
        step = "回读 workAnswerId"
        _open_mark_list(page, str(course_id), str(class_id), str(work_id))
        rows2 = _students_from_mark_list(page)
        row2 = find_student_row(rows2, student)
        result["after"] = {"matched": row2, "rows": len(rows2)}
        wa = (row2 or {}).get("workAnswerId") or ""
        result.update({"ok": bool(wa), "status": "submitted" if wa else "wa-not-found",
                       "workAnswerId": wa, "screenshot": _shot(page, "mark-submitted-after")})
        if not wa:
            result["error"] = "设为已交后未回读到 workAnswerId（请查看截图/批阅列表）"
        result["receipt"] = _write_receipt("mark-submitted", result)
        return result
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"设为已交失败（步骤：{step}）：{str(exc)[:400]}"
        result["step"] = step
        result["screenshot"] = _shot(page, "mark-submitted-fail")
        return result
    finally:
        _close(pw, browser)


# ---------------- §4 grading 产物装配 ----------------

def build_upload_payloads(ws, task_path) -> list[dict]:
    """从某任务包的批阅产物装配上传 payload（每生一条）。

    产物位置：`classes/<class>/grading/<task>/evaluations/<student>.json`
    payload：{student, total_score, question_scores, comment(纯文本段落), report_html?}
    """
    import json as _json
    from ..grading.flow import grading_dir
    task_path = Path(task_path).expanduser().resolve()
    task = _json.loads(task_path.read_text(encoding="utf-8"))
    base = grading_dir(Path(ws).expanduser().resolve(), task)
    eval_dir = base / "evaluations"
    out: list[dict] = []
    if not eval_dir.is_dir():
        return out
    for f in sorted(eval_dir.glob("[!_]*.json")):
        try:
            d = _json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            logger.warning(f"evaluation 读取失败，跳过：{f.name}")
            continue
        student = str(d.get("student") or f.stem)
        scores = [float(x) for x in (d.get("per_question_scores") or []) if _is_num(x)]
        out.append({
            "student": student,
            "total_score": (float(d["total_score"]) if _is_num(d.get("total_score")) else None),
            "question_scores": scores,
            "comment": str(d.get("feedback_md") or ""),
            "verdict": str(d.get("verdict") or "normal"),
            "evalFile": str(f),
        })
    return out


def _is_num(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def find_payload(payloads: list[dict], student: str) -> "dict | None":
    """按学生名匹配 payload（精确优先，其次子串）。"""
    key = str(student or "").strip().lower()
    if not key:
        return None
    for p in payloads or []:
        if str(p.get("student") or "").strip().lower() == key:
            return p
    for p in payloads or []:
        if key in str(p.get("student") or "").strip().lower():
            return p
    return None


# ---------------- §2 批阅上传 ----------------

def _resolve_target(page, course_id: str, class_id: str, work_id: str,
                    student: str, work_answer_id: str) -> "dict | None":
    _open_mark_list(page, course_id, class_id, work_id)
    rows = _students_from_mark_list(page)
    if work_answer_id:
        for r in rows:
            if str(r.get("workAnswerId")) == str(work_answer_id):
                return r
        return {"name": student or work_answer_id, "status": "",
                "workAnswerId": str(work_answer_id)}
    return find_student_row(rows, student)


def upload_grade(*, storage, course_id: str, class_id: str, cpi: str, work_id: str,
                 student: str = "", work_answer_id: str = "",
                 comment: str = "", comment_images: "list[str] | None" = None,
                 question_comments: "list[str] | None" = None,
                 total_score: "float | None" = None,
                 question_scores: "list[float] | None" = None,
                 send: bool = False, force: bool = False,
                 workspace=None) -> dict:
    """批阅页写入批语/图片/分数；dry-run 默认只填不提交。"""
    from .work import validate_work_target
    err = validate_work_target(str(course_id), str(class_id), workspace)
    if err:
        return {"ok": False, "error": err}
    if not student and not work_answer_id:
        return {"ok": False, "error": "必须给 --student 或 --work-answer-id"}
    pw, browser, page, err = _start_browser(storage)
    if err:
        return err
    result: dict = {"ok": False, "mode": "send" if send else "dry-run",
                    "courseId": str(course_id), "classId": str(class_id),
                    "workId": str(work_id), "student": student}
    step = "定位学生"
    try:
        row = _resolve_target(page, str(course_id), str(class_id), str(work_id),
                              student, work_answer_id)
        if row is None:
            result["error"] = f"未找到学生：{student or work_answer_id}"
            result["screenshot"] = _shot(page, "grade-upload-notfound")
            return result
        wa = row.get("workAnswerId") or ""
        if not wa:
            result["error"] = (f"学生「{row.get('name')}」尚无 workAnswerId"
                               f"（status={row.get('status')}）→ 需先设为已交或学生提交")
            result["screenshot"] = _shot(page, "grade-upload-nowa")
            return result
        if "已批阅" in str(row.get("status") or "") and not force:
            result.update({"ok": False, "status": "already-reviewed",
                           "error": "该学生已是「已批阅」；如需覆盖请加 force"})
            return result
        result["matched"] = {"name": row.get("name"), "status": row.get("status"),
                             "workAnswerId": wa}
        step = "打开批阅页"
        result["url"] = open_mark_page(page, str(course_id), str(class_id),
                                       str(work_id), wa)
        result["before"] = read_back(page)
        result["preScreenshot"] = _shot(page, "grade-upload-pre")

        if comment:
            step = "写作业批语"
            result["commentResult"] = set_comment_html(page, normalize_comment_html(comment))
        for img in (comment_images or []):
            step = "上传评语图片"
            up = upload_comment_image(page, img)
            result.setdefault("commentImages", []).append(up)
            if not up.get("ok"):
                raise RuntimeError(f"评语图片上传失败：{up.get('error')}")
        if question_comments:
            step = "写题目批语"
            result["questionCommentResults"] = set_question_comments_html(page, question_comments)

        step = "填分数"
        result["scoreResult"] = fill_scores(page, total=total_score,
                                            per_question=question_scores)
        step = "读回校验"
        result["after"] = read_back(page)
        result["postScreenshot"] = _shot(page, "grade-upload-" + ("sent" if send else "dry"))

        if send:
            step = "提交批阅"
            result["submitResult"] = submit(page)
            result["postScreenshot"] = _shot(page, "grade-upload-submitted")
            result["ok"] = bool(result["submitResult"].get("ok"))
            result["status"] = "submitted" if result["ok"] else "submit-failed"
            if not result["ok"]:
                result["error"] = f"提交失败：{result['submitResult']}"
        else:
            result.update({"ok": True, "status": "dry-run-filled",
                           "note": "dry-run：已填入并读回，未点提交"})
        result["receipt"] = _write_receipt("grade-upload", result)
        return result
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"批阅上传失败（步骤：{step}）：{str(exc)[:400]}"
        result["step"] = step
        result["screenshot"] = _shot(page, "grade-upload-fail")
        result["receipt"] = _write_receipt("grade-upload", result)
        return result
    finally:
        _close(pw, browser)

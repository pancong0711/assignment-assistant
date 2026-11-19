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
import re
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


def pick_work_id(items: list[dict], given: str) -> str:
    """把 workLibraryId 归一为 mark/review 页需要的 workId（纯函数）。

    学习通两套 id：作业库条目=workLibraryId，班级已发布记录=workId；
    `work/list` 的 viewWork('lib','wid','cid') 同时给出两者。
    """
    g = str(given or "").strip()
    if not g:
        return ""
    for it in items or []:
        if str(it.get("workLibraryId") or "") == g and it.get("workId"):
            return str(it["workId"])
    for it in items or []:
        if str(it.get("workId") or "") == g:
            return g
    return g


def resolve_work_id_on_page(page, course_id: str, class_id: str, cpi: str, work: str) -> str:
    """在**当前 page** 上打开班级已发布列表并归一为 workId（避免嵌套 sync_playwright）。"""
    from .work import CLASS_WORKS_JS, class_works_url
    try:
        page.goto(class_works_url(str(course_id), str(class_id), str(cpi)),
                  wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        items = page.evaluate(CLASS_WORKS_JS) or []
        return pick_work_id(items, work)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"workId 解析失败（原样使用 {work}）：{str(exc)[:120]}")
        return str(work)


def _unsubmitted_rows(page) -> list[dict]:
    """未交列表行：姓名 + 是否有「设为已交」入口（该视图无 cz_py，不能用 JS_REVIEW）。"""
    return page.evaluate(r"""() => Array.from(document.querySelectorAll('ul.dataBody_td')).map(ul => {
      const nameEl = ul.querySelector('li.taskBody_name div.py_name');
      const links = Array.from(ul.querySelectorAll('a'));
      const setLink = links.find(a => (a.textContent || '').includes('设为已交'));
      return {name: nameEl ? (nameEl.textContent || '').trim() : '',
              status: (ul.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 60),
              canSetSubmitted: !!setLink};
    }).filter(r => r.name)""")


def _students_from_mark_list(page) -> list[dict]:
    from .extractor import JS_REVIEW, parse_work_answer_id
    rows = page.evaluate(JS_REVIEW) or []
    out = []
    for r in rows:
        wa = parse_work_answer_id(r.get("review_path") or "")
        out.append({"name": str(r.get("name") or "").strip(),
                    "status": str(r.get("status") or "").strip(),
                    "score": str(r.get("score") or "").strip(),
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
    # D203：记录平台自己的 confirm/alert 调用（提交被取消时能从结果里看到原因），
    # 并把 confirm 一律接受（学习通“确定提交？”需要确认才会真正保存）。
    try:
        page.add_init_script("""
          window.__assistDialogs = window.__assistDialogs || [];
          const _c = window.confirm;
          window.confirm = function(msg) {
            window.__assistDialogs.push({type: 'confirm', msg: String(msg || ''), accepted: true});
            return true;
          };
          const _a = window.alert;
          window.alert = function(msg) {
            window.__assistDialogs.push({type: 'alert', msg: String(msg || '')});
          };
        """)
    except Exception:  # noqa: BLE001 —— 诊断增强失败不影响主流程
        pass
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
    from .marking import open_mark_unsubmitted
    step = "解析 workId + 打开未交列表"
    try:
        wid = resolve_work_id_on_page(page, str(course_id), str(class_id), str(cpi), str(work_id))
        result["resolvedWorkId"] = wid
        list_url = open_mark_unsubmitted(page, str(course_id), str(class_id), wid)
        result["listUrl"] = list_url
        rows = _unsubmitted_rows(page)
        result["rows"] = len(rows)
        row = find_student_row(rows, student)
        if row is None and rows:
            result["error"] = f"未交列表未找到学生：{student}；实际：{[r.get('name') for r in rows]}"
            result["screenshot"] = _shot(page, "mark-submitted-notfound")
            return result
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

        # 注意（真机实证 2026-10-15）：点「设为已交」**本身立即生效**，
        # 弹窗只是填分数；因此 dry-run 绝不能点它 → 只定位 + 截图。
        if not row.get("canSetSubmitted"):
            result["error"] = ("该学生行没有「设为已交」入口（可能已交/已批阅）："
                               f"{row.get('status')}")
            result["screenshot"] = _shot(page, "mark-submitted-nolink")
            return result
        if not send:
            result.update({"ok": True, "status": "dry-run-ready",
                           "note": "dry-run：已定位「设为已交」入口，未点击（点击即生效）"})
            result["screenshot"] = _shot(page, "mark-submitted-dry")
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
        result["screenshot"] = _shot(page, "mark-submitted-sent")
        step = "等待设交生效"
        page.wait_for_timeout(4000)
        step = "回读 workAnswerId"
        _open_mark_list(page, str(course_id), str(class_id), wid)
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

def draft_report_version(d: dict) -> dict:
    """D193：从草稿里取报告版本（`human.report`）；旧草稿没有则返回空。"""
    rep = ((d or {}).get("human") or {}).get("report")
    if not isinstance(rep, dict):
        return {}
    return {k: rep.get(k) for k in ("version", "tag", "sha256", "generatedAt", "file", "kind")
            if rep.get(k) is not None}


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


def resolve_draft_effective(d: dict) -> dict:
    """D175：把双套草稿解析成**实际要上传**的 (score, comment)。

    规则与报告生成（`report._mode_report_md`）保持同一口径：

    | humanMode | 批语 | 分数 |
    |---|---|---|
    | none    | AI 批语（有修订版则用修订版） | AI 分；若老师只填了分数（human.score 非空）用人工分 |
    | replace | 人工批语（空则回落 AI） | 人工分（空则 AI） |
    | append  | AI 批语 + 教师补充批语 | 人工分优先（这是"我改了分数"的地方） |
    | revise  | 修订版（没有则 AI 批语） | 人工分优先 |

    此前只看草稿**顶层** `score/comment`（D92 双套结构里根本没有这两个键），
    于是 `--from-drafts` 上传的分数/批语**恒为空** —— 教师在审核里改的分"没变化"。
    """
    d = d if isinstance(d, dict) else {}
    ai = d.get("ai") or {}
    human = d.get("human") or {}
    rev = d.get("revision") or {}
    hm = str(d.get("humanMode") or "none")
    ai_comment = str(ai.get("comment") or "")
    rev_text = str(rev.get("text") or "").strip()
    h_comment = str(human.get("comment") or "")
    h_used = bool(human.get("used"))
    h_score = human.get("score")
    a_score = ai.get("score")

    if not h_used and hm in ("", "none") and not rev_text:
        comment = ai_comment
    elif hm in ("replace", "human"):
        comment = h_comment or ai_comment
    elif hm == "append":
        comment = ai_comment
        if h_comment.strip():
            comment = (comment + "\n\n【教师补充批语】\n" + h_comment) if comment else h_comment
    elif hm == "revise" or rev_text:
        comment = rev_text or ai_comment
    else:                                   # none，但老师写了人工批语 → 仍以人工为准
        comment = h_comment or ai_comment

    # 分数：与报告同一口径 —— 只要人工套被使用且填了分数，就以人工分为准
    # （包括 humanMode=none、"只改分数不替代 AI"的情况：这才是教师"改了分数"的落点）
    if h_used and h_score is not None:
        score = h_score
    elif hm in ("replace", "human", "append", "revise") and h_score is not None:
        score = h_score
    else:
        score = a_score if a_score is not None else h_score
    return {"score": score, "comment": comment,
            "source": "human" if (h_used or hm in ("replace", "human", "append", "revise")) else "ai",
            "humanMode": hm}


def drafts_to_payloads(drafts: dict, only: str = "") -> list[dict]:
    """本地草稿表 → 每生 payload（D85 §3）。only 给定时只取匹配 key/姓名的一项。

    D175：草稿可能是**双套** `{ai, human, humanMode, revision}`（D92 起）。
    此前只读顶层 `score/comment`（D92 之前的单套结构）→ 双套草稿上传时
    分数/批语为空，教师"改了分数但没变化"。现在按 `resolve_draft_effective` 取值；
    旧单套草稿仍按原样兼容（顶层没有 ai/human 时直接用顶层字段）。
    """
    from . import grade_store
    only = str(only or "").strip()
    out: list[dict] = []
    for key, raw in (drafts or {}).items():
        if not isinstance(raw, dict):
            continue
        if only and only not in (str(key), str(raw.get("name") or raw.get("student") or "")):
            continue
        legacy = "ai" not in raw and "human" not in raw
        d = grade_store.normalize_draft(raw)
        eff = resolve_draft_effective(d)
        if legacy and eff["score"] is None and not eff["comment"]:
            eff = {"score": raw.get("score"), "comment": str(raw.get("comment") or ""),
                   "source": str(raw.get("source") or "ai"),
                   "humanMode": str(raw.get("humanMode") or "none")}
        imgs = [i for i in ((d.get("human") or {}).get("reportImages")
                            or d.get("images") or []) if isinstance(i, dict)]
        out.append({"key": str(key), "score": eff["score"], "comment": eff["comment"],
                    "images": imgs, "student": str(d.get("student") or ""),
                    "source": eff["source"], "humanMode": eff["humanMode"],
                    # D193：报告版本随 payload 走，上传清单/对照表与报告页脚可对齐
                    "report": draft_report_version(d)})
    return sorted(out, key=lambda x: x["key"])


def enrich_payloads_from_evaluations(payloads: list[dict], ws,
                                     *, class_dir: str = "", task_id: str = "") -> list[dict]:
    """D200：草稿缺批语/分数时，用 `evaluations/*.json` 的 AI 评阅结果补齐。

    现场：教师确认“全部学生都有 AI 批语”，但上传对照表却显示大量“批语为空”。
    原因是草稿的 `ai.comment` 可能为空（例如只写入了转写/报告图，或旧版本落盘缺字段），
    而 AI 批语实际在 `evaluations/<学生>.json` 的 `feedback_md` 里。

    只补空字段，不覆盖已有内容；找不到 evaluations 时原样返回。
    """
    import json as _json
    from pathlib import Path as _P
    if not payloads:
        return payloads or []
    cd = str(class_dir or "").strip().strip("/")
    tid = str(task_id or "").strip()
    if not cd or not tid:
        return payloads
    import re as _re
    safe = lambda x: _re.sub(r"[\\/:*?\"<>|]", "_", str(x)).strip(" .") or "x"  # noqa: E731
    ev_dir = _P(ws).resolve() / cd / "grading" / safe(tid) / "evaluations"
    if not ev_dir.is_dir():
        return payloads
    by_name: dict[str, dict] = {}
    for f in sorted(ev_dir.glob("[!_]*.json")):
        try:
            d = _json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(d, dict):
            continue
        nm = str(d.get("student") or f.stem).strip()
        if nm:
            by_name[nm] = d
    if not by_name:
        return payloads
    out: list[dict] = []
    for p in payloads:
        q = dict(p or {})
        nm = str(q.get("student") or "").strip()
        ev = by_name.get(nm)
        if ev:
            filled = []
            if not str(q.get("comment") or "").strip():
                fb = str(ev.get("feedback_md") or "").strip()
                if fb:
                    q["comment"] = fb
                    filled.append("comment")
            if q.get("score") is None and _is_num(ev.get("total_score")):
                q["score"] = float(ev["total_score"])
                filled.append("score")
            if filled:
                q["filledFromEvaluations"] = filled
        out.append(q)
    return out


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


def verify_submission(page, course_id: str, class_id: str, work_id: str, *,
                      student: str = "", work_answer_id: str = "",
                      expect_score=None) -> dict:
    """D202：**提交后核验**——重新打开批阅列表，确认平台真的保存了。

    现场：界面显示“已上传”，但学习通仍显示未批阅、也没有分数。
    旧实现只检查“是否点到了 markAction(1) 按钮”，把“点了按钮”当成“写成功了”。

    判定：
      - 能在列表里找到该学生；
      - 状态包含“已批阅”；
      - 若给了 `expect_score`，列表回读的分数与之相符（容差 0.005）。
    """
    from .grade_plan import same_score
    try:
        _open_mark_list(page, course_id, class_id, work_id)
        rows = _students_from_mark_list(page)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"提交后重新读取批阅列表失败：{str(exc)[:200]}"}
    row = None
    if work_answer_id:
        row = next((r for r in rows
                    if str(r.get("workAnswerId") or "") == str(work_answer_id)), None)
    if row is None:
        row = find_student_row(rows, student)
    if row is None:
        return {"ok": False, "error": f"提交后未在批阅列表找到学生：{student or work_answer_id}",
                "rows": len(rows)}
    status = str(row.get("status") or "")
    got = row.get("score")
    out = {"ok": False, "name": row.get("name"), "status": status,
           "score": got, "expectScore": expect_score, "rows": len(rows)}
    # D206：平台界面可能是英文（Reviewed/Unreview）；也有的版本列表行不写状态文本。
    reviewed = ("已批阅" in status) or bool(re.search(r"\breviewed\b", status, re.I)) \
        and not re.search(r"unreview", status, re.I)
    score_ok = expect_score is None or same_score(got, expect_score)
    # 状态文本**明确**表示未批阅（如“待批阅”“Unreview”）时，优先报状态问题（最直观）
    if status.strip() and not reviewed:
        out["error"] = f"提交后平台状态仍为「{status}」（未变成已批阅）"
        return out
    if not score_ok:
        out["error"] = f"提交后平台分数为「{got or '空'}」，与期望 {expect_score} 不一致"
        return out
    if not reviewed:
        # 状态文本缺失但分数已与期望一致 → 视为已保存
        # （真实平台列表行有时不渲染状态文本，见 docs/149-D206）
        if expect_score is None:
            out["error"] = "提交后平台未显示批阅状态，且未指定期望分数，无法确认已保存"
            return out
        out["note"] = "列表未渲染状态文本，但分数已与期望一致"
    out["ok"] = True
    return out


def upload_grade(*, storage, course_id: str, class_id: str, cpi: str, work_id: str,
                 student: str = "", work_answer_id: str = "",
                 comment: str = "", comment_images: "list[str] | None" = None,
                 question_comments: "list[str] | None" = None,
                 total_score: "float | None" = None,
                 question_scores: "list[float] | None" = None,
                 send: bool = False, force: bool = False,
                 workspace=None) -> dict:
    """批阅页写入批语/图片/分数；dry-run 默认只填不提交。

    D193 §2：上传前先判断平台状态（未批阅 / 已批阅但一致 / 已批阅但冲突），
    冲突需 `force=True`（= 教师在上传对照表里显式确认覆盖）。
    """
    from . import grade_plan
    from .grade_plan import decide, platform_snapshot, same_score
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
        wid = resolve_work_id_on_page(page, str(course_id), str(class_id), str(cpi), str(work_id))
        result["resolvedWorkId"] = wid
        row = _resolve_target(page, str(course_id), str(class_id), wid,
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
        result["matched"] = {"name": row.get("name"), "status": row.get("status"),
                             "workAnswerId": wa}
        def _open_and_check() -> "dict | None":
            """打开该生批阅页并校验页面状态（D204：会话过期/非批阅页在写之前拦住）。"""
            nonlocal step
            step = "打开批阅页"
            result["url"] = open_mark_page(page, str(course_id), str(class_id), wid, wa)
            from .marking import page_state as _page_state
            _st = _page_state(page)
            result["pageState"] = {k: _st.get(k) for k in
                                   ("url", "title", "loginRedirect", "hasPassword",
                                    "hasCommentBox", "hasScoreInput") if k in _st}
            if _st.get("loginRedirect") or (_st.get("hasPassword")
                                           and not _st.get("hasCommentBox")):
                return {"ok": False, "status": "session-expired",
                        "error": "学习通会话已失效（批阅页跳到了登录页）",
                        "hint": "请点「🔁 重新扫码登录」后再上传"}
            if not _st.get("hasCommentBox") and not _st.get("hasScoreInput"):
                return {"ok": False, "status": "not-mark-page",
                        "error": ("打开的页面既没有批语框也没有分数框，"
                                  "可能不是批阅页（作业/班级参数不对或平台改版）"),
                        "hint": "请在逐生预览里确认该生批阅页能正常打开"}
            return None

        def _fill_page(*, first: bool) -> "dict | None":
            """在当前已打开的批阅页上：三态判断 → 传图/批语 → 打分 → 读回校验。"""
            nonlocal step
            result["before"] = read_back(page)
            if first:
                result["preScreenshot"] = _shot(page, "grade-upload-pre")
                # D196：状态明确未交 → 不上传
                if "未交" in str(row.get("status") or "") \
                        or "未提交" in str(row.get("status") or ""):
                    return {"ok": False, "status": grade_plan.NOT_SUBMITTED,
                            "decision": grade_plan.NOT_SUBMITTED,
                            "decisionReason": "该学生平台状态为未交/未提交，不上传批阅报告",
                            "skipped": True,
                            "error": "学生未提交，跳过上传批阅报告"}
                if not (str(comment or "").strip() or total_score is not None
                        or question_comments or comment_images):
                    return {"ok": False, "status": grade_plan.NO_COMMENT,
                            "decision": grade_plan.NO_COMMENT,
                            "decisionReason": "本地没有批语/分数：请先 AI 批阅或填写人工批语",
                            "needsReview": True, "skipped": True,
                            "error": "该学生批语为空，请先批阅（AI 批阅或人工批语）后再上传"}
                plan = decide(status=str(row.get("status") or ""),
                              local_score=total_score, local_comment=comment,
                              platform=platform_snapshot(result["before"]),
                              has_local_content=True, force=bool(force))
                result.update({"decision": plan["decision"],
                               "decisionReason": plan["reason"],
                               "needsConfirm": plan["needsConfirm"],
                               "platformBefore": plan["platformBefore"]})
                if not plan["upload"]:
                    return {"ok": plan["decision"] in (grade_plan.UNCHANGED,),
                            "status": plan["decision"], "error": plan["reason"],
                            "skipped": True}
            # 先传图片（UEditor 会插到文首），再把批语文字放到图片**之前**，保证阅读顺序
            for img in (comment_images or []):
                step = "上传评语图片"
                up = upload_comment_image(page, img)
                result.setdefault("commentImages", []).append(up)
                if not up.get("ok"):
                    raise RuntimeError(f"评语图片上传失败：{up.get('error')}")
            if comment:
                step = "写作业批语"
                html = normalize_comment_html(comment)
                if comment_images:
                    imgs = re.findall(r"<img\b[^>]*>", str(read_back(page).get("comment") or ""))
                    if imgs:
                        html = html + "".join(imgs)  # 文字在前、图片在后
                result["commentResult"] = set_comment_html(page, html)
            if question_comments:
                step = "写题目批语"
                result["questionCommentResults"] = set_question_comments_html(
                    page, question_comments)
            step = "填分数"
            result["scoreResult"] = fill_scores(page, total=total_score,
                                                per_question=question_scores)
            step = "读回校验"
            result["after"] = read_back(page)
            result["postScreenshot"] = _shot(
                page, "grade-upload-" + ("sent" if send else "dry"))
            # D202：提交前确认“要写的分数确实进了页面”。
            if total_score is not None:
                got_before = str((result.get("after") or {}).get("score") or "").strip()
                if not same_score(got_before, total_score):
                    return {"ok": False, "status": "score-not-filled",
                            "error": (f"分数未成功写入页面（页面读到「{got_before or '空'}」，"
                                      f"期望 {total_score}），已中止提交")}
            return None

        err = _open_and_check()
        if err:
            result.update(err)
            result["receipt"] = _write_receipt("grade-upload", result)
            return result
        err = _fill_page(first=True)
        if err:
            result.update(err)
            result["receipt"] = _write_receipt("grade-upload", result)
            return result

        if send:
            attempts: list[dict] = []
            ver: dict = {}
            clicked = False
            matched_name = str(result.get("matched", {}).get("name") or student)
            for attempt in (1, 2):
                if attempt > 1:
                    # D205：重试必须**重新打开批阅页并重填**。
                    # 旧实现直接在原地再点提交——而上一轮核验已把页面导航到批阅列表，
                    # 那里根本没有提交按钮 → 误报“未找到提交按钮”。
                    result["commentImages"] = []
                    err = _open_and_check()
                    if err:
                        result.update(err)
                        break
                    err = _fill_page(first=False)
                    if err:
                        result.update(err)
                        break
                step = "提交批阅"
                result["submitResult"] = submit(page)
                clicked = bool(result["submitResult"].get("ok"))
                attempts.append({
                    "attempt": attempt, "clicked": clicked,
                    "confirmPopup": result["submitResult"].get("confirmPopup"),
                    "dialogs": result["submitResult"].get("dialogs"),
                    "urlAfter": result["submitResult"].get("urlAfter"),
                })
                result["postScreenshot"] = _shot(
                    page, "grade-upload-submitted" + ("" if attempt == 1 else "-retry"))
                # D202：**必须核验平台真的保存了**。
                step = "提交后核验"
                ver = verify_submission(page, str(course_id), str(class_id), wid,
                                        student=matched_name, work_answer_id=wa,
                                        expect_score=total_score)
                result["afterSubmit"] = ver
                if clicked and ver.get("ok"):
                    break
                sub = result.get("submitResult") or {}
                if str(sub.get("status") or "") == "session-expired":
                    result.update({"ok": False, "status": "session-expired",
                                   "error": sub.get("error"),
                                   "hint": "请先点「🔁 重新扫码登录」，登录成功后再上传"})
                    result["receipt"] = _write_receipt("grade-upload", result)
                    return result
                if not clicked:
                    break          # 连按钮都找不到，重试没意义
                page.wait_for_timeout(2000)
            result["submitAttempts"] = attempts
            result["ok"] = bool(clicked and ver.get("ok"))
            if result["ok"]:
                result["status"] = "submitted"
            else:
                result["status"] = "unverified" if clicked else "submit-failed"
                attrs = ""
                try:
                    cp = (result.get("submitResult") or {}).get("confirmPopup") or {}
                    attrs = (f"；确认弹窗 {len(cp.get('popups') or [])} 个，"
                             f"点击 {cp.get('clicks')}")
                except Exception:  # noqa: BLE001
                    attrs = ""
                dialogs = (result.get("submitResult") or {}).get("dialogs") or []
                if dialogs:
                    attrs += "；页面提示：" + " | ".join(
                        str(x.get("msg") or "")[:80] for x in dialogs[:3])
                cands = (result.get("submitResult") or {}).get("submitCandidates") or []
                if cands:
                    attrs += "；候选按钮：" + "、".join(
                        f"{c.get('text')}({c.get('onclick')})" for c in cands[:4])
                result["error"] = ((f"提交后核验失败：{ver.get('error')}" if clicked
                                    else f"提交失败：{result['submitResult']}")
                                   + attrs)
                if clicked:
                    result["hint"] = ("已点到提交按钮但平台未保存：常见原因是确认弹窗未点中"
                                      "（新版用 confirmPiyueWork()）或分数校验未通过。"
                                      "详情见 submitAttempts / receipts 截图。")
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


# ---------------- D121-G6：上传清单落盘（可复现 / 可审计） ----------------

def upload_manifest_path(ws, class_dir: str, task_id: str, work_id: str) -> "Path | None":
    """`<ws>/<class_dir>/grading/<taskId>/upload/<workId>.json`。"""
    import re as _re
    cd = str(class_dir or "").strip().strip("/")
    tid = str(task_id or "").strip()
    wid = str(work_id or "").strip()
    if not cd or not tid or not wid:
        return None
    safe = lambda s: _re.sub(r"[\\/:*?\"<>|]", "_", s).strip(" .") or "x"  # noqa: E731
    from pathlib import Path as _P
    return _P(ws).resolve() / cd / "grading" / safe(tid) / "upload" / f"{safe(wid)}.json"


def write_upload_manifest(ws, class_dir: str, task_id: str, work_id: str,
                          payloads: list[dict], *, source: str = "",
                          result: "dict | None" = None) -> dict:
    """上传**前**写入「即将发送什么」；上传后可用 `result` 追加结果。

    目的：出问题时能回答"上次到底给学习通发了什么"（此前 payload 现场拼装、不落盘）。
    """
    p = upload_manifest_path(ws, class_dir, task_id, work_id)
    if p is None:
        return {"ok": False, "error": "classDir/taskId/workId 不完整"}
    prev = {}
    if p.is_file():
        try:
            prev = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            prev = {}
    # D121-FIX：payloads 里的图片带 base64（报告 PNG），原样落盘会让清单膨胀到 MB 级。
    # 清单只记录**元信息**（文件名/大小），不存图片数据本身。
    def _slim(p: dict) -> dict:
        d = dict(p or {})
        imgs = d.pop("images", None)
        if isinstance(imgs, list):
            metas = []
            for im in imgs:
                if not isinstance(im, dict):
                    continue
                data = str(im.get("data_b64") or "")
                metas.append({
                    "name": str(im.get("name") or ""),
                    "bytes": (len(data) * 3 // 4) if data else 0,
                    "hasData": bool(data),
                })
            if metas:
                d["images"] = metas
        return d

    data = {
        "workId": str(work_id), "taskId": str(task_id), "classDir": str(class_dir),
        "source": source or prev.get("source") or "",
        # D193：清单带“这是哪一版报告”的元信息，便于和报告 .versions 索引对照
        "reportVersions": sorted({
            str((x or {}).get("report", {}).get("version") or "")
            for x in (payloads or []) if isinstance(x, dict)
        } - {""}),
        "generatedAt": prev.get("generatedAt") or time.strftime("%Y-%m-%d %H:%M:%S"),
        "items": [_slim(x) for x in (payloads or [])],
    }
    if result is not None:
        data["result"] = {**result, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    elif prev.get("result"):
        data["result"] = prev["result"]
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        from ..filelock import atomic_write_text
        atomic_write_text(p, json.dumps(data, ensure_ascii=False, indent=1))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"上传清单落盘失败：{exc}")
        return {"ok": False, "error": str(exc)[:200]}
    return {"ok": True, "path": str(p), "items": len(data["items"])}

"""D79-C：学习通平台作业（work）只读列表与发布设置套壳。

基于 2026-10-13 真机侦察：
- 作业库：/mooc2-ans/work/library?courseid=&clazzid=&cpi=
- 发布设置：/mooc2-ans/work/library/setting?courseid=&cpi=&workLibraryId=&fromCreate=1
- 发布：POST /mooc2-ans/work/library/publish
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

# 与通知发布相同的临时写操作白名单。
WORK_TEST_ALLOWLIST = {
    ("217801417", "40009084"),
}


def validate_work_target(course_id: str, class_id: str, workspace=None) -> str | None:
    from .allowlist import is_allowed
    if not is_allowed(str(course_id), str(class_id), workspace):
        return (f"写操作白名单拒绝：courseId={course_id}, classId={class_id}；"
                "请在「发布-学习通」中勾选该班级加入白名单")
    return None


def _receipt_dir() -> Path:
    from .session import xxt_home
    d = Path(xxt_home()) / "work-publishes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_works(storage, course_id: str, class_id: str, cpi: str = "0", directory_id: str = "0") -> dict:
    """只读列出作业库条目（含未发布草稿）。"""
    from playwright.sync_api import sync_playwright
    from .session import check_session, _launch
    storage = Path(storage)
    chk = check_session(storage)
    if chk.get("verdict") != "alive":
        return {"ok": False, "error": "session dead",
                "hint": chk.get("hint", "请先 assist xxt login")}
    url = (f"https://mooc2-ans.chaoxing.com/mooc2-ans/work/library"
           f"?courseid={course_id}&clazzid={class_id}&cpi={cpi}&selectClassid={class_id}")
    with sync_playwright() as pw:
        browser = _launch(pw, headless=True)
        ctx = browser.new_context(storage_state=str(storage),
                                  viewport={"width": 1440, "height": 1000}, locale="zh-CN")
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)
        items = page.evaluate("""() => Array.from(document.querySelectorAll('ul.dataBody_td[data]')).filter(e => (e.getAttribute('type') || '') === '1').map(e => ({
          workLibraryId: e.getAttribute('data') || '',
          type: e.getAttribute('type') || '',
          text: (e.innerText || '').trim().slice(0, 120),
          canEdit: e.getAttribute('data-can-edit') === 'true',
        }))""")
        browser.close()
    for it in items:
        it["publishedClasses"] = published_classes(str(course_id), str(it.get("workLibraryId") or ""))
    return {"ok": True, "courseId": str(course_id), "classId": str(class_id),
            "cpi": str(cpi), "directoryId": str(directory_id), "items": items}


def publish_work(storage, course_id: str, class_id: str, work_library_id: str, *,
                 cpi: str, start_time: str, end_time: str,
                 allow_late: bool = False, late_deadline: str = "",
                 redo_times: int = 0, send: bool = False) -> dict:
    """打开发布设置页，选目标班、填时间/重做，dry-run 或真正发布。"""
    err = validate_work_target(course_id, class_id)
    if err:
        return {"ok": False, "error": err}
    _dup_key = f"{course_id}|{work_library_id}|{class_id}"
    if send and _dup_key in _load_index():
        return {"ok": False, "error": "该作业已在本班发布过；同一作业同一班级不允许重复发布，"
                                       "如需修改请先在学习通创建副本（副本+时间戳）后再发布。"}
    try:
        det = work_detail(storage, course_id, class_id, str(cpi), str(work_library_id))
        if det.get("workUsed") and send:
            return {"ok": False, "error": "该作业已发布过（至少一个班）；同一作业不允许重复发布，"
                                           "如需修改请先创建副本（副本+时间戳）后再发布。"}
    except Exception:  # noqa: BLE001
        pass
    from playwright.sync_api import sync_playwright
    from .session import check_session, _launch
    storage = Path(storage)
    chk = check_session(storage)
    if chk.get("verdict") != "alive":
        return {"ok": False, "error": "session dead",
                "hint": chk.get("hint", "请先 assist xxt login")}
    url = (f"https://mooc2-ans.chaoxing.com/mooc2-ans/work/library/setting"
           f"?courseid={course_id}&cpi={cpi}&workLibraryId={work_library_id}"
           f"&fromCreate=1&from=")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_id = f"xxt-work-publish-{stamp}"
    reqs: list = []
    resps: list = []
    with sync_playwright() as pw:
        browser = _launch(pw, headless=True)
        ctx = browser.new_context(storage_state=str(storage),
                                  viewport={"width": 1440, "height": 1100}, locale="zh-CN")
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())
        page.on("request", lambda r: reqs.append({"method": r.method, "url": r.url,
                                                   "post": r.post_data}) if r.method != "GET" else None)
        page.on("response", lambda r: resps.append({"status": r.status, "url": r.url,
                                                     "body": (r.text() if "publish" in r.url else "")[:1500]})
                if r.request.method != "GET" else None)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)
        # 选目标班（弹窗）
        page.locator("#choosepublish").click(timeout=10000)
        page.wait_for_timeout(2000)
        names = page.evaluate("""() => Array.from(document.querySelectorAll('#objectList .classData')).map(e => ({id:e.getAttribute('data'), name:(e.innerText||'').trim()}))""")
        hit = next((x for x in names if str(x.get("id")) == str(class_id)), None)
        if hit is None:
            browser.close()
            return {"ok": False, "error": f"目标班不在发放对象中：{class_id}",
                    "classes": names}
        page.locator(f'a.classData[data="{class_id}"]').first.click(timeout=10000)
        page.wait_for_timeout(500)
        # 点击对应的 class_check（classData 本身可能只展开）
        try:
            page.locator("li.classLi .class_check").first.click(timeout=5000)
        except Exception:
            pass
        page.locator("#confirmchoose").click(timeout=10000)
        page.wait_for_timeout(1000)
        # 时间
        page.evaluate("""([st, en, late, lateDeadline]) => {
          const s=document.querySelector('#startTime'); if (s && st) s.value=st;
          const e=document.querySelector('#endTime'); if (e && en) e.value=en;
          if (window.endTimeChanged) endTimeChanged();
          const a=document.querySelector('#answerAfterEnd'); if (a) a.value=late ? '1' : '0';
          const ab=document.querySelector('#answerAfterEndBtn'); if (ab && late && !ab.className.includes('opacity30')) ab.click();
          const ad=document.querySelector('#answerDeadlinePicker'); if (ad && lateDeadline) ad.value=lateDeadline;
        }""", [start_time, end_time, bool(allow_late), late_deadline])
        if redo_times:
            page.locator(".showSetting").click(timeout=10000)
            page.wait_for_timeout(500)
            try:
                page.locator("#redoTimesBtn").click(timeout=5000)
            except Exception:
                pass
            page.evaluate("""(n) => { const el=document.querySelector('#redoTimes'); if(el){el.value=String(n); if(window.inputRedoTimes) inputRedoTimes(el);} }""",
                          int(redo_times))
        pre = _receipt_dir() / f"{run_id}-pre.png"
        page.screenshot(path=str(pre), full_page=True)
        if not send:
            browser.close()
            return {"ok": True, "mode": "dry-run", "runId": run_id, "screenshot": str(pre),
                    "classes": names, "courseId": str(course_id), "classId": str(class_id),
                    "workLibraryId": work_library_id}
        page.locator("a.jb_btn", has_text="发放").first.click(timeout=10000)
        page.wait_for_timeout(10000)
        post = _receipt_dir() / f"{run_id}-post.png"
        page.screenshot(path=str(post), full_page=True)
        browser.close()
    body = ""
    for r in resps:
        if "publish" in r.get("url", ""):
            body = r.get("body") or ""
    parsed = {}
    try:
        parsed = json.loads(body)
    except Exception:
        pass
    if parsed.get("status"):
        try:
            idx = _load_index()
            idx[_dup_key] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "runId": run_id,
                             "workId": ((parsed.get("workRelationArray") or [{}])[0]).get("workId")}
            _save_index(idx)
        except Exception:  # noqa: BLE001
            pass
    return {"ok": bool(parsed.get("status")), "mode": "send", "runId": run_id,
            "courseId": str(course_id), "classId": str(class_id),
            "workLibraryId": work_library_id, "response": parsed,
            "responseText": body[:1000], "screenshot": str(post),
            "requests": reqs[-5:], "responses": resps[-5:]}

def list_folders(storage, course_id: str, class_id: str, cpi: str = "0") -> dict:
    """只读列出作业库文件夹（用于「发布-学习通」的文件夹设置）。"""
    from playwright.sync_api import sync_playwright
    from .session import check_session, _launch
    storage = Path(storage)
    chk = check_session(storage)
    if chk.get("verdict") != "alive":
        return {"ok": False, "error": "session dead"}
    url = (f"https://mooc2-ans.chaoxing.com/mooc2-ans/work/library"
           f"?courseid={course_id}&clazzid={class_id}&cpi={cpi}&selectClassid={class_id}")
    with sync_playwright() as pw:
        browser = _launch(pw, headless=True)
        ctx = browser.new_context(storage_state=str(storage),
                                  viewport={"width": 1440, "height": 1000}, locale="zh-CN")
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        rows = page.evaluate("""() => Array.from(document.querySelectorAll('li[onclick^="intoFolder"]')).map(e => ({
          directoryId: (e.id || '').replace('folder', ''),
          name: (e.innerText || '').trim().split(String.fromCharCode(10))[0],
          onclick: e.getAttribute('onclick') || '',
        }))""")
        browser.close()
    return {"ok": True, "courseId": str(course_id), "classId": str(class_id), "cpi": str(cpi), "items": rows}


def work_detail(storage, course_id: str, class_id: str, cpi: str, work_library_id: str) -> dict:
    """只读读取作业标题和题目题干（简答题）。"""
    from playwright.sync_api import sync_playwright
    from .session import check_session, _launch
    storage = Path(storage)
    chk = check_session(storage)
    if chk.get("verdict") != "alive":
        return {"ok": False, "error": "session dead"}
    url = (f"https://mooc2-ans.chaoxing.com/mooc2-ans/work/goToWorkEditor"
           f"?courseid={course_id}&clazzid={class_id}&cpi={cpi}&workid={work_library_id}&built=1&from=")
    with sync_playwright() as pw:
        browser = _launch(pw, headless=True)
        ctx = browser.new_context(storage_state=str(storage),
                                  viewport={"width": 1440, "height": 1000}, locale="zh-CN")
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)
        title = page.input_value("#title") if page.query_selector("#title") else ""
        stem = page.evaluate("""() => { try { return UE.getEditor('content') ? UE.getEditor('content').getContent() : ''; } catch(e) { return ''; } }""")
        if not stem:
            stem = page.evaluate("""() => {
              const t=document.body.innerText || '';
              const i=t.indexOf('(简答题');
              if (i >= 0) {
                let rest=t.slice(i);
                const j=rest.indexOf('答案');
                const k=rest.indexOf('答案解析');
                let cut=j;
                if (cut < 0 || (k >= 0 && k < cut)) cut=k;
                if (cut > 0) return rest.slice(0, cut).split(String.fromCharCode(10)).slice(1).join(String.fromCharCode(10)).trim();
              }
              const el=document.querySelector('#danxuan .edit_content') || document.querySelector('#danxuan');
              return el ? (el.innerText || '').trim() : '';
            }""")
        work_used = page.eval_on_selector("#workUsed", "e => e ? e.value : '' ") if page.query_selector("#workUsed") else ""
        browser.close()
    return {"ok": True, "title": title, "stemHtml": stem, "workUsed": str(work_used).lower() == "true"}


def create_work(storage, course_id: str, class_id: str, cpi: str, title: str,
                stem_html: str, directory_id: str = "0") -> dict:
    """新建 1 道简答题草稿，保存到指定作业库文件夹；返回 workLibraryId。"""
    err = validate_work_target(course_id, class_id)
    if err:
        return {"ok": False, "error": err}
    from playwright.sync_api import sync_playwright
    from .session import check_session, _launch
    storage = Path(storage)
    chk = check_session(storage)
    if chk.get("verdict") != "alive":
        return {"ok": False, "error": "session dead"}
    url = (f"https://mooc2-ans.chaoxing.com/mooc2-ans/work/goToWorkEditor"
           f"?courseid={course_id}&clazzid={class_id}&mooc=1&workid=&built=1&cpi={cpi}&from=")
    reqs: list = []
    with sync_playwright() as pw:
        browser = _launch(pw, headless=True)
        ctx = browser.new_context(storage_state=str(storage),
                                  viewport={"width": 1440, "height": 1000}, locale="zh-CN")
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())
        page.on("request", lambda r: reqs.append({"method": r.method, "url": r.url}) if r.method != "GET" else None)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)
        page.get_by_text("简答题", exact=True).first.click(timeout=10000)
        page.wait_for_timeout(2500)
        page.evaluate("""(stem) => { const ed=UE.getEditor('content'); if (ed) ed.setContent(stem); }""", stem_html or "<p></p>")
        page.wait_for_timeout(500)
        page.locator("a.jb_btn", has_text="完成").first.click(timeout=10000)
        page.wait_for_timeout(4000)
        work_id = page.eval_on_selector("#workid", "e=>e.value") if page.query_selector("#workid") else ""
        if title:
            page.fill("#title", title[:100])
        page.evaluate("""(d) => { const el=document.querySelector('#directoryid'); if (el) el.value=String(d); }""", directory_id)
        page.locator("a", has_text="保存").first.click(timeout=10000)
        page.wait_for_timeout(5000)
        browser.close()
    return {"ok": bool(work_id), "workLibraryId": work_id, "title": title, "requests": reqs[-8:]}

def _index_path() -> Path:
    return _receipt_dir() / "index.json"


def _load_index() -> dict:
    p = _index_path()
    if not p.is_file():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_index(d: dict) -> None:
    _index_path().write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def published_classes(course_id: str, work_library_id: str) -> list[str]:
    idx = _load_index()
    return [k.split("|")[-1] for k in idx if k.startswith(f"{course_id}|{work_library_id}|")]



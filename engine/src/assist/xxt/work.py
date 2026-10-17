"""D79-C：学习通平台作业（work）只读列表与发布设置套壳。

基于 2026-10-13 真机侦察：
- 作业库：/mooc2-ans/work/library?courseid=&clazzid=&cpi=
- 发布设置：/mooc2-ans/work/library/setting?courseid=&cpi=&workLibraryId=&fromCreate=1
- 发布：POST /mooc2-ans/work/library/publish
"""
from __future__ import annotations

import json

from loguru import logger
import re
import time
from pathlib import Path

# 与通知发布相同的临时写操作白名单。
WORK_TEST_ALLOWLIST = {
    ("217801417", "40009084"),
}


def validate_work_target(course_id: str, class_id: str, workspace=None) -> str | None:
    from .allowlist import is_allowed, read_allowlist, _settings_path
    if not is_allowed(str(course_id), str(class_id), workspace):
        # D83-5.0：回显实际读取的白名单文件与条目，便于一眼看出「勾选了却被拒」是否 workspace 不一致
        try:
            entries = read_allowlist(workspace)
            path = _settings_path(workspace)
        except Exception:  # noqa: BLE001
            entries, path = [], "?"
        names = ", ".join(f"{e.get('courseId')}:{e.get('classId')}"
                          + (f"({e.get('name')})" if e.get("name") else "") for e in entries) or "（空）"
        return (f"写操作白名单拒绝：请求 courseId={course_id}, classId={class_id}；"
                f"实际读取白名单文件 {path}，当前条目：{names}。"
                "请确认该班级已在「发布-学习通」勾选（注意 workspace 是否一致）")
    return None


def _receipt_dir() -> Path:
    from .session import xxt_home
    d = Path(xxt_home()) / "work-publishes"
    d.mkdir(parents=True, exist_ok=True)
    return d


# D97：班级已发布集合的**进程内短期缓存**（避免多班逐个开浏览器；10 分钟 TTL）。
_PUB_CACHE: dict = {}
_PUB_TTL = 600


def _published_cached(storage, course_id: str, class_id: str, cpi: str) -> set:
    key = (str(course_id), str(class_id), str(cpi))
    hit = _PUB_CACHE.get(key)
    if hit and (time.time() - hit[0]) < _PUB_TTL:
        return hit[1]
    try:
        pub = published_library_ids(storage, course_id, class_id, cpi)
    except Exception:  # noqa: BLE001
        pub = set()
    _PUB_CACHE[key] = (time.time(), pub)
    return pub


def list_works(storage, course_id: str, class_id: str, cpi: str = "0", directory_id: str = "0",
               class_ids: "list[str] | None" = None) -> dict:
    """只读列出作业库条目（含未发布草稿）。

    D97：`class_ids`（多目标班）时，`publishedClasses` 填**这些班里已发布该作业的班**（逐班判定）。
    """
    from playwright.sync_api import sync_playwright
    from .session import check_session, _launch
    storage = Path(storage)
    chk = check_session(storage)
    if chk.get("verdict") != "alive":
        return {"ok": False, "error": "session dead",
                "hint": chk.get("hint", "请先 assist xxt login")}
    url = (f"https://mooc2-ans.chaoxing.com/mooc2-ans/work/library"
           f"?courseid={course_id}&directoryid={directory_id}&cpi={cpi}&from=&topicid=0&backurl=")
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
    # D97：逐目标班判定「已发布」；无 class_ids 时退回单班
    targets = [str(x) for x in (class_ids or []) if str(x).strip()] or [str(class_id)]
    pub_by_class: dict[str, set] = {}
    for cid in targets:
        pub_by_class[cid] = _published_cached(storage, course_id, cid, cpi)
    for it in items:
        wid = str(it.get("workLibraryId") or "")
        it["publishedClasses"] = [cid for cid in targets if wid in pub_by_class.get(cid, set())]
    return {"ok": True, "courseId": str(course_id), "classId": str(class_id),
            "cpi": str(cpi), "directoryId": str(directory_id), "items": items}


def publish_work(storage, course_id: str, class_id: str, work_library_id: str, *,
                 cpi: str, start_time: str, end_time: str,
                 allow_late: bool = False, late_deadline: str = "",
                 redo_times: int = 0, send: bool = False,
                 class_ids: "list[str] | None" = None) -> dict:
    """打开发布设置页，选目标班（D95：支持多班一次发布）、填时间/重做，dry-run 或真正发布。

    D95：`class_ids`（多班，平台"发放对象"支持一次勾选多班）优先于单个 `class_id`；
    逐班做白名单校验与"同班同作业"重复发布校验；任一班已发布即拒绝（避免半成功）。
    """
    # D97：缺省时间 = 现在 + 5 分钟（开始）/ + 5 天（截止），避免"开始<当前"被平台拒。
    if not str(start_time or "").strip() or not str(end_time or "").strip():
        import datetime as _dt
        _now = _dt.datetime.now()
        if not str(start_time or "").strip():
            start_time = (_now + _dt.timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        if not str(end_time or "").strip():
            end_time = (_now + _dt.timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
    targets = [str(x) for x in (class_ids or []) if str(x).strip()] or [str(class_id)]
    # 去重保序
    seen = set(); targets = [t for t in targets if not (t in seen or seen.add(t))]
    errs = []
    for cid in targets:
        e = validate_work_target(course_id, cid)
        if e:
            errs.append(e)
    if errs:
        return {"ok": False, "error": "；".join(errs)}
    # 重复发布校验（逐班）
    if send:
        idx = _load_index()
        dup = [cid for cid in targets if f"{course_id}|{work_library_id}|{cid}" in idx]
        if dup:
            return {"ok": False, "error": f"该作业已在班级 {dup} 发布过；同一作业同一班级不允许重复发布，"
                                           "如需修改请先在学习通创建副本（副本+时间戳）后再发布。"}
        try:
            pub = published_library_ids(storage, course_id, targets[0], str(cpi)) or []
        except Exception:  # noqa: BLE001
            pub = []
        if str(work_library_id) in [str(x) for x in pub]:
            return {"ok": False, "error": "该作业已在班级发布过（平台侧）；禁止重复发布。"}
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
        # 选目标班（弹窗）——D95：支持多班，逐个点其 class_check
        page.locator("#choosepublish").click(timeout=10000)
        page.wait_for_timeout(2000)
        names = page.evaluate("""() => Array.from(document.querySelectorAll('#objectList .classData')).map(e => ({id:e.getAttribute('data'), name:(e.innerText||'').trim()}))""")
        avail = {str(x.get("id")): x.get("name") for x in names}
        missing = [c for c in targets if str(c) not in avail]
        if missing:
            browser.close()
            return {"ok": False, "error": f"目标班不在发放对象中：{missing}",
                    "classes": names}
        picked = []
        for cid in targets:
            # 点该班所在 li.classLi 内的 .class_check（复选框 span）
            ok_pick = page.evaluate("""(cid) => {
              const a = document.querySelector(`#objectList .classData[data="${cid}"]`);
              if (!a) return false;
              const li = a.closest('li.classLi') || a.parentElement;
              const cb = li ? li.querySelector('.class_check') : null;
              if (!cb) return false;
              if (!/class_checked/.test(cb.className)) cb.click();
              return /class_checked/.test(cb.className);
            }""", str(cid))
            page.wait_for_timeout(500)
            if ok_pick:
                picked.append(str(cid))
        if sorted(picked) != sorted([str(c) for c in targets]):
            # 兜底：逐个用 playwright click 再试
            for cid in targets:
                if str(cid) in picked:
                    continue
                try:
                    page.locator(f'a.classData[data="{cid}"]').first.click(timeout=5000)
                    page.wait_for_timeout(300)
                    page.locator('li.classLi .class_check').first.click(timeout=3000)
                    picked.append(str(cid))
                except Exception:  # noqa: BLE001
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
                    "classes": names, "courseId": str(course_id), "classId": str(targets[0]),
                    "classIds": targets, "workLibraryId": work_library_id}
        # D95：平台前端 checkQuestion() 依赖隐藏域 #classid 做前置校验；多选时页面不自动赋值 →
        # 点「发放」前显式补设（否则 AJAX clazzid 为空、校验不过、不触发提交）。
        page.evaluate("""(cid) => {
            const el = document.querySelector('#classid');
            if (el && !el.value) el.value = String(cid);
            // 兜底：若 .selectClass 为空，说明确认未生效
        }""", str(targets[0]))
        page.wait_for_timeout(300)
        # D83 修复：与 create_work 同款健壮点击（可见过滤 + 多定位器 + JS 兜底）
        _click_first_visible(
            page,
            [page.locator("a.jb_btn", has_text="发放"),
             page.locator("a", has_text="发放"),
             page.get_by_role("link", name="发放")],
            "点击「发放」", timeout=10000, js_text="发放")
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


# D83 修复：作业编辑器里附件/图片插入正文的标记集合（实测 2026-10-15 真机 DOM）。
# - PDF/doc 等：<div class="editor-iframe"><iframe class="attach-iframe" ...>
# - 图片：<img class="ans-ued-img" ...>（作业编辑器专有；通知页是 drag-image-wrap）
_ATTACH_MARKERS = ('class="editor-iframe"', 'class="attach-iframe"',
                   'class="drag-image-wrap"', 'ans-ued-img')


def _work_attachment_count(page) -> int:
    """统计作业简答题编辑器（id=content）里的附件/图片块（见 _ATTACH_MARKERS）。"""
    try:
        content = page.evaluate("UE.getEditor('content').getContent()") or ""
        return sum(content.count(m) for m in _ATTACH_MARKERS)
    except Exception:
        return -1


def _attachment_dialog_frame(page, timeout_s: float = 10.0):
    """作业编辑器「附件」弹窗 iframe（.../dialogs/attachment_new/attachment.html）或 None。

    D83 修复：作业编辑器的附件按钮点开后是**弹窗 iframe**，webuploader 的
    file input 在 iframe 内；此前代码在主页面找 input[type=file] → 必然超时。
    """
    deadline = time.time() + max(0.0, timeout_s)
    while True:
        for fr in page.frames:
            if "attachment_new/attachment.html" in (fr.url or ""):
                return fr
        if time.time() >= deadline:
            return None
        try:
            page.wait_for_timeout(400)
        except Exception:  # noqa: BLE001
            return None


def _open_work_attachment_dialog(page) -> bool:
    """点开内容编辑器的附件按钮：作业编辑器 .edui-for-attachment_new（通知页 .edui-for-attachment）。"""
    for spec in (".edui-for-attachment_new", ".edui-for-attachment"):
        try:
            loc = page.locator(spec).first
            if loc.count() == 0:
                continue
            loc.scroll_into_view_if_needed(timeout=3000)
            loc.click(timeout=5000)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"附件按钮点击失败（{spec}）：{str(exc)[:140]}")
    return False


def _upload_work_attachments(page, att_paths: list[Path]) -> list[str]:
    """D83-7：把本地附件上传插入到那道唯一简答题的正文。

    D83 修复（2026-10-15 真机实测）：
    - 附件按钮 = .edui-for-attachment_new（作业编辑器；通知页才是 .edui-for-attachment）；
    - 点开后是弹窗 iframe，webuploader 的 file input 在 iframe 内 → 用 frame 定位；
    - 图片插入标记 ans-ued-img / 附件 editor-iframe，都要计入 _work_attachment_count。
    """
    uploaded: list[str] = []
    _open_work_attachment_dialog(page)
    count = _work_attachment_count(page)
    for apath in att_paths:
        before = count
        done = False
        last_err: "Exception | None" = None
        for attempt in range(2):  # 弹窗可能被上一轮上传关掉 → 重开一次
            frame = _attachment_dialog_frame(page, 6.0)
            if frame is None:
                _open_work_attachment_dialog(page)
                frame = _attachment_dialog_frame(page, 6.0)
            if frame is not None:
                try:
                    inp = frame.locator("input[type=file]").first
                    inp.wait_for(state="attached", timeout=8000)
                    inp.set_input_files(str(apath))
                    done = True
                    break
                except Exception as exc:  # noqa: BLE001
                    last_err = exc
                    logger.warning(f"附件弹窗内 set_input_files 失败（第 {attempt + 1} 次）：{str(exc)[:140]}")
            else:
                last_err = RuntimeError("附件弹窗 iframe 未出现")
        if not done:
            # 回退：通知页那种「主页面 hidden input」口径（兼容老页面）
            try:
                loc = page.locator('.edui-for-attachment input[type=file]').first
                if loc.count() == 0:
                    loc = page.locator('input[type=file]').first
                loc.wait_for(state="attached", timeout=8000)
                loc.set_input_files(str(apath))
                done = True
            except Exception as exc:  # noqa: BLE001
                last_err = exc
        if not done:
            raise RuntimeError(f"附件上传入口不可用：{apath.name}（{str(last_err)[:160]}）")
        deadline = time.time() + 90
        ok = False
        while time.time() < deadline:
            count = _work_attachment_count(page)
            if count > before:
                ok = True
                break
            page.wait_for_timeout(1000)
        if not ok:
            raise RuntimeError(f"附件未插入简答题正文：{apath.name}")
        uploaded.append(apath.name)
    if uploaded:
        page.wait_for_timeout(2500)  # WebUploader 收尾请求
    return uploaded


def _fail_shot(page, tag: str) -> str:
    """失败现场截图（full page）到 xxt_home/work-publishes/；失败返回空串不阻断。"""
    try:
        from .session import xxt_home
        d = Path(xxt_home()) / "work-drafts"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"create-fail-{tag}-{int(time.time())}.png"
        page.screenshot(path=str(p), full_page=True)
        return str(p)
    except Exception:  # noqa: BLE001
        return ""


def _click_first_visible(page, locs, step: str, timeout: int = 10000,
                         js_text: "str | None" = None) -> None:
    """D83 修复：多定位器 + 可见过滤 + JS 兜底的健壮点击。

    背景：真机报「element is not visible」重试超时 —— 页面上存在同名隐藏元素
    （模板/下拉容器），`.first` 按文档序取到的是隐藏的那个。这里逐个定位器
    先按 visible 过滤再点；全部失败时用 JS 找「可见且文本精确匹配」的元素兜底。
    """
    errors: list[str] = []
    for loc in locs:
        try:
            vis = loc.filter(visible=True).first
            vis.wait_for(state="visible", timeout=max(2000, timeout // 2))
            vis.click(timeout=timeout)
            return
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {str(exc).splitlines()[0][:140]}")
    if js_text:
        try:
            clicked = page.evaluate(
                """(t) => {
                    const els = Array.from(document.querySelectorAll('a,button,li,span,div,p'))
                        .filter(e => e.offsetParent !== null
                                    && e.childElementCount === 0
                                    && e.textContent.trim() === t);
                    if (els.length) { els[0].click(); return true; }
                    return false;
                }""", js_text)
            if clicked:
                return
        except Exception as exc:  # noqa: BLE001
            errors.append(f"JS兜底: {str(exc).splitlines()[0][:140]}")
    raise RuntimeError(f"{step}：{len(locs)} 种定位器与 JS 兜底均无法点击可见元素；"
                       + " || ".join(errors[:3]))


# ---- D85：题型面板（按课程题型集合不同；简答题可能在「更多」弹层里）----

_JS_TYPE_EVIDENCE = r"""([title]) => {
  const stem = document.querySelector('.eidt_stem');
  const wid = (document.querySelector('#workid') || {}).value || '';
  const stemText = stem ? (stem.innerText || '') : '';
  return {stem: stemText.trim().slice(0, 40), workid: wid,
          stemHas: stemText.includes(title), hasWid: !!wid};
}"""


def _click_first_actionable(page, locators: list, timeout_ms: int = 4000) -> dict:
    """依次尝试多个定位器（正常 click → DOM click 兜底）；返回命中信息。

    真机经验：外层 span/li[title] 常 0×0 或被父级 overflow 裁剪，Playwright 的
    可见性判定会认为不可点；但内层 <a> 实际有 82×34 的盒子。故：
    先 Playwright click（自带等待/滚动），失败再 `element.click()` DOM 兜底。
    """
    last = ""
    for name, loc in locators:
        try:
            n = loc.count()
        except Exception as exc:  # noqa: BLE001
            last = f"{name}: {str(exc).splitlines()[0][:100]}"
            continue
        if not n:
            last = f"{name}: not-found"
            continue
        for i in range(min(n, 3)):
            item = loc.nth(i)
            try:
                item.click(timeout=timeout_ms)
                return {"ok": True, "via": f"click:{name}", "index": i}
            except Exception as exc:  # noqa: BLE001
                last = f"{name}#{i}: {str(exc).splitlines()[0][:100]}"
            try:
                item.evaluate("e => e.click()")   # DOM 兜底
                return {"ok": True, "via": f"dom-click:{name}", "index": i}
            except Exception as exc:  # noqa: BLE001
                last = f"{name}#{i}(dom): {str(exc).splitlines()[0][:100]}"
    return {"ok": False, "reason": "click-failed", "lastError": last}


def _type_locators(page, title: str, where: str) -> list:
    """题型可点元素候选：内层 <a> 优先，其次元素自身。where ∈ addTitle/morePop。"""
    if where == "morePop":
        scope = '.morePop'
    else:
        scope = '.addTitle'
    return [
        (f"{scope}-a", page.locator(f'{scope} [title="{title}"] a')),
        (f"{scope}-self", page.locator(f'{scope} [title="{title}"]')),
    ]


def _wait_type_evidence(page, title: str, timeout_s: float = 8.0) -> dict:
    """等"题目/草稿已创建"的判据（`.eidt_stem` 出现题型名 或 `#workid` 非空）。"""
    deadline = time.time() + max(1.0, timeout_s)
    last: dict = {}
    while time.time() < deadline:
        last = page.evaluate(_JS_TYPE_EVIDENCE, [title])
        if last.get("stemHas") or last.get("hasWid"):
            return last
        page.wait_for_timeout(500)
    return {}


def _ensure_question_type(page, title: str = "简答题", timeout_s: float = 15.0,
                          force_more: bool = False) -> dict:
    """D85：添加题型（直接列表 → 「更多」弹层），以**成功判据**决定是否收工。

    真机依据：
    - 不同课程「添加题目」直接题型集合不同（C2Z 班没有简答题直钮，只在 `.morePop` 里）；
    - 外层 `span/li[title]` 常被 0×0/overflow 裁剪 → Playwright click 判不可点，
      内层 `<a>` 才是目标（click 失败再 DOM click 兜底）；
    - 点题型按钮本身即创建草稿（`#workid` 立即有值）→ 所以"点完必须验到题目/草稿"，
      验不到就换「更多」路径，避免 DOM 兜底点了隐藏按钮却什么都没发生。
    `force_more=True` 仅测试钩子（直接跳过直点路径）。
    """
    info: dict = {"title": title, "attempts": [], "usedPath": None}
    paths = ["more"] if force_more else ["direct", "more"]
    for path in paths:
        if path == "direct":
            click = _click_first_actionable(page, _type_locators(page, title, "addTitle"))
        else:
            more = _click_first_actionable(page, [
                ("addQTypeBtn", page.locator("#addQTypeBtn")),
                ("moreCon-a", page.locator(".moreCon a.more")),
                ("moreCon", page.locator(".moreCon")),
            ], timeout_ms=4000)
            info["attempts"].append({"path": "open-more", **more})
            page.wait_for_timeout(800)
            click = _click_first_actionable(page, _type_locators(page, title, "morePop"),
                                            timeout_ms=5000)
        info["attempts"].append({"path": path, **click})
        if not click.get("ok"):
            continue
        ev = _wait_type_evidence(page, title, timeout_s=min(8.0, timeout_s))
        if ev:
            info.update({"ok": True, "usedPath": path, "evidence": ev})
            return info
        info["attempts"].append({"path": path, "note": "clicked-but-no-evidence"})
    info.update({"ok": False,
                 "error": f"题型「{title}」直接列表与「更多」弹层均未成功创建题目"})
    return info


def create_work(storage, course_id: str, class_id: str, cpi: str, title: str,
                stem_html: str, directory_id: str = "0",
                attachments: "list[str] | None" = None, workspace=None) -> dict:
    """新建 1 道简答题草稿（可带附件），保存到指定作业库文件夹；返回 workLibraryId。

    D83-7：attachments 为本地文件路径列表（图片/pdf/doc 等，按通知同款扩展名白名单校验），
    全部内嵌插入到那道唯一简答题的正文里。
    """
    err = validate_work_target(course_id, class_id, workspace)
    if err:
        return {"ok": False, "error": err}
    # 附件路径安全校验（复用 notice.safe_attachment_path：限 workspace 内 + 扩展名白名单）
    att_paths: list[Path] = []
    if attachments:
        from .notice import safe_attachment_path
        ws = Path(workspace).resolve() if workspace else None
        for a in attachments:
            pth = safe_attachment_path(a, ws)
            if pth is None:
                return {"ok": False, "error": f"附件被拒绝（越界或格式不在白名单）：{a}"}
            att_paths.append(pth)
    from playwright.sync_api import sync_playwright
    from .session import check_session, _launch
    storage = Path(storage)
    chk = check_session(storage)
    if chk.get("verdict") != "alive":
        return {"ok": False, "error": "session dead"}
    # D85：编辑器 URL 必须带 directoryid（草稿在"加题"时由服务端落目录，事后改隐藏域无效）
    url = (f"https://mooc2-ans.chaoxing.com/mooc2-ans/work/goToWorkEditor"
           f"?courseid={course_id}&clazzid={class_id}&mooc=1&workid=&built=1&cpi={cpi}"
           f"&directoryid={directory_id or '0'}&from=")
    reqs: list = []
    with sync_playwright() as pw:
        browser = _launch(pw, headless=True)
        ctx = browser.new_context(storage_state=str(storage),
                                  viewport={"width": 1440, "height": 1000}, locale="zh-CN")
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())
        page.on("request", lambda r: reqs.append({"method": r.method, "url": r.url}) if r.method != "GET" else None)
        step = "打开作业编辑器"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(6000)

            # D85：题型按课程不同（简答题可能在「更多」弹层）→ 直接列表 → 更多 → 成功判据
            step = "选择题型（简答题）"
            type_res = _ensure_question_type(page, "简答题")
            if not type_res.get("ok"):
                raise RuntimeError(f"{type_res.get('error')}；尝试记录={type_res.get('attempts')}")
            page.wait_for_timeout(2500)

            step = "填入题干"
            page.evaluate("""(stem) => { const ed=UE.getEditor('content'); if (ed) ed.setContent(stem); }""", stem_html or "<p></p>")
            page.wait_for_timeout(500)

            # D83-7：附件内嵌进这道简答题正文
            step = "上传附件"
            if att_paths:
                try:
                    _upload_work_attachments(page, att_paths)
                except Exception as exc:  # noqa: BLE001
                    shot = _fail_shot(page, "attach")
                    browser.close()
                    return {"ok": False,
                            "error": f"附件上传失败：{exc}" + (f"；现场截图：{shot}" if shot else ""),
                            "step": step, "screenshot": shot,
                            "attachmentsTried": [p.name for p in att_paths]}

            step = "点击「完成」"
            _click_first_visible(
                page,
                [page.locator("a.jb_btn", has_text="完成"),
                 page.locator("a", has_text="完成"),
                 page.get_by_role("link", name="完成")],
                step, timeout=10000, js_text="完成")
            page.wait_for_timeout(4000)

            step = "读取作业ID"
            work_id = page.eval_on_selector("#workid", "e=>e.value") if page.query_selector("#workid") else ""

            step = "填写标题与文件夹"
            if title:
                page.fill("#title", title[:100])
            page.evaluate("""(d) => { const el=document.querySelector('#directoryid'); if (el) el.value=String(d); }""", directory_id)

            step = "点击「保存」"
            _click_first_visible(
                page,
                [page.locator("a.jb_btn", has_text="保存"),
                 page.locator("a", has_text="保存"),
                 page.get_by_role("link", name="保存")],
                step, timeout=10000, js_text="保存")
            page.wait_for_timeout(5000)
        except Exception as exc:  # noqa: BLE001
            shot = _fail_shot(page, step)
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass
            return {"ok": False,
                    "error": f"新建作业失败（步骤：{step}）：{str(exc)[:400]}"
                             + (f"；现场截图：{shot}" if shot else ""),
                    "step": step, "screenshot": shot, "requests": reqs[-8:]}
        browser.close()
    # D85：保存后用作业库列表回读，确认草稿真落在指定文件夹（主浏览器已关，避免嵌套 sync）
    directory_check: dict = {"directoryId": str(directory_id or "0")}
    if work_id:
        try:
            rep = list_works(storage, course_id, class_id, cpi, str(directory_id or "0"))
            ids = [str(x.get("workLibraryId") or "") for x in (rep.get("items") or [])]
            directory_check["ok"] = str(work_id) in ids
            if not directory_check["ok"]:
                directory_check["hint"] = ("草稿未出现在该文件夹（可能落到了根目录）；"
                                           "请检查目录 ID 或平台目录接口变化")
        except Exception as exc:  # noqa: BLE001
            directory_check["ok"] = None
            directory_check["error"] = str(exc)[:200]
    return {"ok": bool(work_id), "workLibraryId": work_id, "title": title,
            "attachments": [p.name for p in att_paths],
            "typePanel": type_res if isinstance(type_res, dict) else None,
            "directoryCheck": directory_check, "requests": reqs[-8:]}

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

def create_folder(storage, course_id: str, class_id: str, cpi: str, directory_id: str, title: str) -> dict:
    """在作业库指定父文件夹下创建文件夹。"""
    err = validate_work_target(course_id, class_id)
    if err:
        return {"ok": False, "error": err}
    from playwright.sync_api import sync_playwright
    from .session import check_session, _launch
    storage = Path(storage)
    chk = check_session(storage)
    if chk.get("verdict") != "alive":
        return {"ok": False, "error": "session dead"}
    parent = str(directory_id or "0")
    url = (f"https://mooc2-ans.chaoxing.com/mooc2-ans/work/library"
           f"?courseid={course_id}&directoryid={parent}&cpi={cpi}&from=&topicid=0&backurl=")
    with sync_playwright() as pw:
        browser = _launch(pw, headless=True)
        ctx = browser.new_context(storage_state=str(storage),
                                  viewport={"width": 1440, "height": 1000}, locale="zh-CN")
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        res = page.evaluate("""async ([cid, did, cpi, title]) => {
          const u = '/mooc2-ans/work/library/addfolder?courseid=' + encodeURIComponent(cid)
            + '&directoryid=' + encodeURIComponent(did) + '&title=' + encodeURIComponent(title)
            + '&cpi=' + encodeURIComponent(cpi);
          const r = await fetch(u, {headers:{'Accept':'application/json'}});
          return {status:r.status, body:(await r.text()).slice(0,1000)};
        }""", [str(course_id), parent, str(cpi), title[:50]])
        browser.close()
    return {"ok": True, "response": res, "courseId": str(course_id), "classId": str(class_id),
            "parentDirectoryId": parent, "title": title[:50]}


def copy_work(storage, course_id: str, class_id: str, cpi: str, directory_id: str,
              work_library_id: str, new_title: str = "") -> dict:
    """复制已有作业库作业到指定文件夹，并按 new_title 重命名（副本+时间戳）。"""
    err = validate_work_target(course_id, class_id)
    if err:
        return {"ok": False, "error": err}
    from playwright.sync_api import sync_playwright
    from .session import check_session, _launch
    storage = Path(storage)
    chk = check_session(storage)
    if chk.get("verdict") != "alive":
        return {"ok": False, "error": "session dead"}
    directory = str(directory_id or "0")
    url = (f"https://mooc2-ans.chaoxing.com/mooc2-ans/work/library"
           f"?courseid={course_id}&directoryid={directory}&cpi={cpi}&from=&topicid=0&backurl=")
    old_ids: set[str] = set()
    with sync_playwright() as pw:
        browser = _launch(pw, headless=True)
        ctx = browser.new_context(storage_state=str(storage),
                                  viewport={"width": 1440, "height": 1000}, locale="zh-CN")
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        old_ids = set(page.evaluate("""() => Array.from(document.querySelectorAll('ul.dataBody_td[data]')).filter(e=>(e.getAttribute('type')||'')==='1').map(e=>e.getAttribute('data')||'')"""))
        res = page.evaluate("""async ([cid, did, wid, cpi]) => {
          const u = '/mooc2-ans/work/library/copy?courseid=' + encodeURIComponent(cid)
            + '&directoryid=' + encodeURIComponent(did) + '&workid=' + encodeURIComponent(wid)
            + '&cpi=' + encodeURIComponent(cpi);
          const r = await fetch(u, {headers:{'Accept':'application/json'}});
          return {status:r.status, body:(await r.text()).slice(0,1000)};
        }""", [str(course_id), directory, str(work_library_id), str(cpi)])
        page.wait_for_timeout(2500)
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        new_ids = set(page.evaluate("""() => Array.from(document.querySelectorAll('ul.dataBody_td[data]')).filter(e=>(e.getAttribute('type')||'')==='1').map(e=>e.getAttribute('data')||'')"""))
        browser.close()
    new_id = next(iter(new_ids - old_ids), "")
    renamed = {"ok": False, "error": "未找到副本 id"}
    if new_id and new_title:
        renamed = rename_work(storage, course_id, class_id, cpi, directory, new_id, new_title)
    return {"ok": bool(new_id), "sourceWorkLibraryId": str(work_library_id),
            "newWorkLibraryId": new_id, "title": new_title, "copyResponse": res,
            "renameResponse": renamed}


def rename_work(storage, course_id: str, class_id: str, cpi: str, directory_id: str,
                work_library_id: str, new_title: str) -> dict:
    """重命名作业库作业：打开编辑器改标题后保存（学习通库内重命名接口只对文件夹生效）。"""
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
           f"?courseid={course_id}&clazzid={class_id}&cpi={cpi}&workid={work_library_id}&built=1&from=")
    with sync_playwright() as pw:
        browser = _launch(pw, headless=True)
        ctx = browser.new_context(storage_state=str(storage),
                                  viewport={"width": 1440, "height": 1000}, locale="zh-CN")
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)
        if page.query_selector("#title"):
            page.fill("#title", new_title[:100])
        try:
            # D83 修复：与 create_work 同款健壮点击（可见过滤 + 多定位器 + JS 兜底）
            _click_first_visible(
                page,
                [page.locator("a.jb_btn", has_text="保存"),
                 page.locator("a", has_text="保存"),
                 page.get_by_role("link", name="保存")],
                "rename_work 保存", timeout=10000, js_text="保存")
            page.wait_for_timeout(5000)
        except Exception as exc:  # noqa: BLE001
            shot = _fail_shot(page, "rename")
            return {"ok": False,
                    "error": f"保存标题失败：{exc}" + (f"；现场截图：{shot}" if shot else ""),
                    "screenshot": shot}
        browser.close()
    return {"ok": True, "workLibraryId": str(work_library_id), "title": new_title}

def class_works_url(course_id: str, class_id: str, cpi: str = "0") -> str:
    """班级已发布作业列表 URL（D84：workId 的唯一来源）。"""
    return (f"https://mooc2-ans.chaoxing.com/mooc2-ans/work/list"
            f"?courseid={course_id}&clazzid={class_id}&cpi={cpi}"
            f"&selectClassid={class_id}&status=-1&v=0&topicid=0")


CLASS_WORKS_JS = """() => {
  const out=[]; const seen=new Set();
  document.querySelectorAll('h2[onclick]').forEach(h => {
    const parts=((h.getAttribute('onclick')||'').split("'"));
    if(parts.length < 7) return;
    const lib=parts[1], wid=parts[3], cid=parts[5];
    if(!lib || seen.has(lib)) return; seen.add(lib);
    out.push({workLibraryId:lib, workId:wid, classId:cid, title:(h.innerText||'').trim().slice(0,100)});
  });
  return out;
}"""


def list_class_works(storage, course_id: str, class_id: str, cpi: str = "0") -> dict:
    """只读拉取某班级已发布作业列表（viewWork(libraryId, workId, classId)）。"""
    from playwright.sync_api import sync_playwright
    from .session import check_session, _launch
    storage = Path(storage)
    chk = check_session(storage)
    if chk.get("verdict") != "alive":
        return {"ok": False, "error": "session dead"}
    url = class_works_url(course_id, class_id, cpi)
    with sync_playwright() as pw:
        browser = _launch(pw, headless=True)
        ctx = browser.new_context(storage_state=str(storage),
                                  viewport={"width": 1440, "height": 1000}, locale="zh-CN")
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)
        items = page.evaluate(CLASS_WORKS_JS)
        browser.close()
    return {"ok": True, "courseId": str(course_id), "classId": str(class_id), "cpi": str(cpi), "items": items}


def published_library_ids(storage, course_id: str, class_id: str, cpi: str = "0") -> set[str]:
    rep = list_class_works(storage, course_id, class_id, cpi)
    return {str(x.get("workLibraryId") or "") for x in (rep.get("items") or []) if x.get("workLibraryId")}


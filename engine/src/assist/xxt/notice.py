"""D77：学习通课程通知发布（写操作；默认 dry-run，白名单保护）。

实现方式与 2026-10-12 真机联调一致：复用教师本机 Playwright storage_state，
打开 `richtextNotice?courseId=` 表单页，注入收件人 sendMap、填写标题/正文、
通过 UEditor/WebUploader 隐藏 input 上传附件，最后点击 `.sendNotice.submitBtn`。

安全边界：
- 默认只 dry-run；必须显式 `send=True` / CLI `--send` 才真正发送；
- 只允许命中 workspace `settings.local.json → xxt.write_allowlist` 的 courseId:classId
  （由 `xxt.allowlist.is_allowed` 判定；早期硬编码常量 `NOTICE_TEST_ALLOWLIST` 已删除）；
- 附件路径必须位于 workspace 下，且后缀在 `xxt.notice_attachment_exts`（缺省
  pdf/doc/docx/jpg/jpeg/png/webp/gif，见 `allowlist.DEFAULT_NOTICE_ATTACHMENT_EXTS`）；
- 每次预检/发送都保存截图和 JSON receipt 到 `<xxt_home>/notice-sends/`。
"""
from __future__ import annotations

import html as _html
import json
import re
import secrets
import time
from pathlib import Path

# 写操作白名单已统一到 workspace `settings.local.json → xxt.write_allowlist`
# （见 `xxt.allowlist`）；此处不再保留硬编码课程/班级常量（P0 清理）。
#
# ATTACH_SUFFIXES 仅作兼容常量保留；真正的扩展名白名单走
# `allowlist.read_notice_attachment_exts(ws)`，避免两套规则不一致。
ATTACH_SUFFIXES = (".pdf", ".doc", ".docx", ".xls", ".xlsx",
                   ".jpg", ".jpeg", ".png", ".webp", ".gif")

# D99：通知编辑器里附件/图片块的 DOM 标记（与 work.py 的 _ATTACH_MARKERS 同口径）。
# 文档类（pdf/doc/docx/xls/xlsx）→ editor-iframe；图片 → drag-image-wrap。
_EDITOR_ATTACH_MARKERS = ('class="editor-iframe"', 'class="attach-iframe"',
                          'class="drag-image-wrap"', 'ans-ued-img')
# 上传中/失败占位文案：出现即「还没就绪」，不能当成功。
_UPLOAD_PENDING_MARKERS = ("正在上传", "上传中", "uploadinfotext", "attachprogress")
_UPLOAD_FAILED_MARKERS = ("imguploaderror", "上传失败", "附件上传失败")


def normalize_targets(raw) -> list[dict]:
    """把 PWA/CLI 的多种目标形态归一为 courses[].classes[]。"""
    out: list[dict] = []
    if not raw:
        return out
    for course in raw or []:
        cid = str(course.get("courseId") or "").strip()
        cname = str(course.get("courseName") or course.get("name") or cid).strip()
        classes_raw = course.get("classes") or course.get("classIds") or []
        classes: list[dict] = []
        if isinstance(classes_raw, dict):
            classes_raw = [classes_raw]
        for cl in classes_raw:
            if isinstance(cl, str) or isinstance(cl, int):
                kid = str(cl).strip()
                classes.append({"classId": kid, "name": kid})
                continue
            kid = str(cl.get("classId") or cl.get("id") or "").strip()
            kname = str(cl.get("name") or cl.get("className") or kid).strip()
            if kid:
                classes.append({"classId": kid, "name": kname})
        if cid and classes:
            out.append({"courseId": cid, "courseName": cname, "classes": classes})
    return out


def validate_targets(targets: list[dict], workspace=None) -> str | None:
    """返回错误字符串；None 表示通过。"""
    if not targets:
        return "未选择任何课程/班级"
    for c in targets:
        cid = str(c.get("courseId") or "")
        if not re.fullmatch(r"[0-9A-Za-z\\-_]{1,40}", cid):
            return f"非法 courseId：{cid}"
        for k in c.get("classes") or []:
            kid = str(k.get("classId") or "")
            if not re.fullmatch(r"[0-9A-Za-z\\-_]{1,40}", kid):
                return f"非法 classId：{kid}"
            from .allowlist import is_allowed
            if not is_allowed(cid, kid, workspace):
                return (f"写操作白名单拒绝：courseId={cid}, classId={kid}；"
                        "请在「发布-学习通」中勾选该班级加入白名单")
    return None


def safe_attachment_path(path: str | Path, workspace: Path | str | None = None, allowed_exts=None) -> Path | None:
    """只允许 workspace 下的 pdf/doc/docx 附件。"""
    if workspace is None:
        try:
            from ..workspace import find_workspace
            ws = Path(find_workspace(None)).resolve()
        except Exception:
            ws = Path.cwd().resolve()
    else:
        ws = Path(workspace).resolve()
    p = Path(str(path)).expanduser()
    if not p.is_absolute():
        # CLI/PWA 可能传 workspace 相对路径，也可能传当前工作目录相对路径。
        candidates = [ws / p, Path.cwd() / p]
        rp = next((c.resolve() for c in candidates if c.exists()), None)
        if rp is None:
            return None
        p = rp
    try:
        rp = p.resolve()
    except Exception:
        return None
    if not rp.is_file():
        return None
    try:
        rp.relative_to(ws)
    except ValueError:
        return None
    from .allowlist import normalize_exts, read_notice_attachment_exts
    allowed = normalize_exts(allowed_exts) if allowed_exts is not None else read_notice_attachment_exts(ws)
    if rp.suffix.lower().lstrip(".") not in allowed:
        return None
    return rp


def list_notice_attachments(workspace: Path | str | None = None, limit: int = 200) -> list[dict]:
    """列出可发布的作业纸 PDF（workspace/classes/**/sheets/**/*.pdf）。"""
    if workspace is None:
        try:
            from ..workspace import find_workspace
            ws = Path(find_workspace(None)).resolve()
        except Exception:
            ws = Path.cwd().resolve()
    else:
        ws = Path(workspace).resolve()
    out: list[dict] = []
    root = ws / "classes"
    if not root.is_dir():
        return out
    for p in root.rglob("*.pdf"):
        rel = p.relative_to(ws)
        if "sheets" not in rel.parts:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        out.append({
            "name": p.name,
            "path": str(p),
            "rel": rel.as_posix(),
            "size": st.st_size,
            "mtime": st.st_mtime,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
        })
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out[:limit]


def body_to_html(body: str, *, is_html: bool = False) -> str:
    text = (body or "").strip()
    if not text:
        return "<p><br/></p>"
    if is_html or ("<p" in text.lower() or "<div" in text.lower()):
        return text
    esc = _html.escape(text)
    lines = [x.strip() for x in esc.splitlines() if x.strip()]
    if not lines:
        return "<p><br/></p>"
    return "".join(f"<p>{line}</p>" for line in lines)


def _receipt_dir(home=None) -> Path:
    from .session import xxt_home
    d = Path(home or xxt_home()) / "notice-sends"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _editor_content(page) -> str | None:
    """取编辑器 HTML；UEditor 不可用/上下文销毁时返回 None。"""
    try:
        return page.evaluate("UE.getEditor('container').getContent()") or ""
    except Exception:
        return None


def _editor_attachment_count(page) -> int:
    """统计编辑器里的附件/图片块（_EDITOR_ATTACH_MARKERS）；不可用时返回 -1。"""
    content = _editor_content(page)
    if content is None:
        return -1
    return sum(content.count(m) for m in _EDITOR_ATTACH_MARKERS)


def _editor_snapshot(page) -> dict | None:
    """**一次** evaluate 取回编辑器状态（块数 / pending / error 节点 / 内容长度）。

    D99 关键修复：图片编辑器的进度层是瞬态的（先出现 `imguploaderror`，几百 ms
    后被清掉换成 `<img>`）。如果分两次 evaluate 分别取「块数」和「error 数」，
    两次之间状态就可能翻转，导致把「已经成功」误判成「本次新增失败」。
    因此所有判定字段必须在**同一个** JS 快照里取。
    """
    try:
        return page.evaluate(r"""() => {
          const content = (window.UE && UE.getEditor('container'))
            ? (UE.getEditor('container').getContent() || '') : null;
          if (content === null) return null;
          const count = (s) => content.split(s).length - 1;
          return {
            len: content.length,
            count: ['class="editor-iframe"', 'class="attach-iframe"',
                    'class="drag-image-wrap"', 'ans-ued-img']
                     .reduce((n, m) => n + count(m), 0),
            pending: ['正在上传', '上传中', 'uploadinfotext', 'attachprogress']
                       .some((m) => content.includes(m)),
            errors: ['imguploaderror', '上传失败', '附件上传失败']
                      .reduce((n, m) => n + count(m), 0),
            // 成功证据：图片已换成真实/内联地址，或文档进度的 progress 层已消失。
            settled: (() => {
              const imgs = content.match(/<img[^>]*\ssrc="(data:image\/|https?:\/\/)/g) || [];
              const blocks = count('class="editor-iframe"') + count('class="attach-iframe"')
                           + count('class="drag-image-wrap"');
              const progress = count('attachprogress') + count('imgprogress')
                             + count('uploadinfotext') + count('imguploaderror');
              return blocks > 0 && progress === 0 && (imgs.length > 0 || count('drag-image-wrap') === 0);
            })(),
          };
        }""")
    except Exception:
        return None


def _upload_progress(page, before: int) -> dict:
    """单次快照 → 是否就绪、块数、是否仍在「正在上传」、失败占位数量。

    D99 修复：上传刚触发时 DOM 里**已经**有 `editor-iframe`（里面写着
    「正在上传...」），旧实现只要块数 > before 就判成功 → 假阳性。这里要求
    块数增加 **且** 无 pending 标记才算就绪。失败与否由调用方用 errors 差分判断。
    """
    snap = _editor_snapshot(page)
    if snap is None:
        return {"ok": False, "count": -1, "pending": True, "errors": 0,
                "settled": False, "error": "UEditor 不可用"}
    return {"ok": snap["count"] > before and not snap["pending"],
            "count": snap["count"], "pending": snap["pending"],
            "errors": snap["errors"], "settled": snap.get("settled", True), "error": ""}


def _upload_error_count(page) -> int:
    """编辑器里失败占位的数量（用于「本次上传前后」差分）。"""
    snap = _editor_snapshot(page)
    return int(snap["errors"]) if snap else 0


def _wait_upload(page, before: int, timeout_s: int = 90, poll_s: float = 0.5,
                 stable_hits: int = 2, before_failed: int | None = None,
                 error_grace_s: float = 5.0) -> tuple[bool, int]:
    """等附件真正就绪：块数增加 + 无「正在上传」+ 连续若干次快照一致。

    返回 (ok, count)。D99 用**采样轮询**替代旧的固定 `wait_for_timeout(2500)`：
    小文件 ~1s 就绪，大文件/云盘慢时不会被 2.5s 误判为完成。

    失败占位（imguploaderror）在真机上是**瞬态**的：png 上传时 0.07s 就出现
    `imguploaderror`、0.33s 已有真实 `<img>`、1.1s 才清掉错误节点。所以：
    - 出现新增失败占位**不立即判失败**，而是等 `error_grace_s` 宽限；
    - 宽限内看到「成功证据」（真实 img src / progress 层清空）→ 按成功处理；
    - 宽限耗尽仍失败 → 判失败。

    `before_failed` 是上传前失败占位计数；不传按 0（严格模式，仅测试用）。
    """
    base_failed = 0 if before_failed is None else int(before_failed)
    start = time.time()
    deadline = start + timeout_s
    last_count = before
    stable = 0
    err_since: float | None = None
    while time.time() < deadline:
        st = _upload_progress(page, before)
        if st["count"] < 0:
            return False, last_count
        now = time.time()
        has_new_err = int(st["errors"]) > base_failed
        if has_new_err:
            err_since = err_since if err_since is not None else now
        else:
            err_since = None
        if st["ok"] and st.get("settled", True):
            if st["count"] == last_count:
                stable += 1
            else:
                last_count, stable = st["count"], 1
            if stable >= stable_hits:
                return True, st["count"]
        elif has_new_err and (now - (err_since or now)) > error_grace_s:
            return False, st["count"]
        else:
            stable = 0
            last_count = st["count"]
        page.wait_for_timeout(int(poll_s * 1000))
    return False, last_count


def _inject_send_map(page, items: list[dict]) -> list[dict]:
    return page.evaluate("""(items) => {
      const C = window.CourseSend_NoticeRtf;
      if (!C || !C.sendMap) throw new Error('CourseSend_NoticeRtf.sendMap missing');
      C.sendMap.clear();
      if (C.selectMap) C.selectMap.clear();
      if (C.toccMap) C.toccMap.clear();
      for (const it of items) {
        C.sendMap.put('course_' + String(it.id), {id: String(it.id), type: 'course', name: it.name || String(it.id)});
      }
      const dump=[];
      for (let i=0;i<C.sendMap.size();i++) dump.push(C.sendMap.element(i));
      return dump;
    }""", [{"id": k.get("classId"), "name": k.get("name")} for k in items])


def _upload_fail_reason(state: dict, new_failed: bool = False) -> str:
    """把采样状态翻成人话，写进 receipt/异常信息。"""
    if state.get("count", 0) < 0:
        return "UEditor 不可用（无法读取编辑器内容）"
    if new_failed:
        return "本次上传后新增了失败占位（imguploaderror / 上传失败）"
    return "编辑器块已出现但仍在「正在上传」，或 90s 内未稳定"


def send_notice_from_spec(spec: dict, *, send: bool = False, storage: Path | str | None = None,
                          workspace: Path | str | None = None) -> dict:
    """执行一个通知 spec。spec: targets/title/bodyHtml/attachments/dryRun。"""
    from playwright.sync_api import sync_playwright
    from .session import check_session, _launch, xxt_home
    from .layout import pages_dir

    targets = normalize_targets(spec.get("targets"))
    err = validate_targets(targets, workspace)
    title = str(spec.get("title") or "").strip()
    body_html = body_to_html(str(spec.get("bodyHtml") or spec.get("body") or ""),
                             is_html=bool(spec.get("bodyHtml")))
    attachments_raw = spec.get("attachments") or []
    if not title:
        err = err or "标题不能为空"
    if err:
        return {"ok": False, "error": err, "sent": 0, "dryRun": not send}

    att_paths: list[Path] = []
    for a in attachments_raw:
        p = safe_attachment_path(a, workspace)
        if p is None:
            from .allowlist import read_notice_attachment_exts
            allowed = "/".join(read_notice_attachment_exts(workspace))
            return {"ok": False,
                    "error": (f"附件不可用或不在 workspace 内：{a}；"
                              f"允许的后缀：{allowed}"
                              "（可用 `assist xxt attachment-exts set --add --ext xxx` 扩展）"),
                    "sent": 0, "dryRun": not send}
        att_paths.append(p)

    storage = Path(storage) if storage else xxt_home() / "xxt-storage.json"
    home = xxt_home()
    chk = check_session(storage)
    if chk.get("verdict") != "alive":
        return {"ok": False, "error": "session dead", "hint": chk.get("hint", "请先 assist xxt login"),
                "sent": 0, "dryRun": not send}

    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_id = f"xxt-notice-{stamp}-{secrets.token_hex(3)}"
    receipts: list[dict] = []
    results: list[dict] = []
    failures: list[dict] = []
    sent = 0

    with sync_playwright() as pw:
        browser = _launch(pw, headless=True)
        ctx = browser.new_context(storage_state=str(storage),
                                  viewport={"width": 1440, "height": 1000}, locale="zh-CN")
        page = ctx.new_page()
        # 发送按钮可能弹原生 confirm/协议确认；默认 Playwright 会 dismiss，导致请求不发出。
        page.on("dialog", lambda d: d.accept())
        reqs: list[dict] = []
        resps: list[dict] = []
        page.on("request", lambda r: reqs.append({"method": r.method, "url": r.url})
                if r.method != "GET" else None)
        page.on("response", lambda r: resps.append({"status": r.status, "url": r.url})
                if r.request.method != "GET" else None)

        for course in targets:
            cid = str(course["courseId"])
            cname = str(course.get("courseName") or cid)
            classes = course.get("classes") or []
            item_reqs: list[dict] = []
            item_resps: list[dict] = []
            url = f"https://notice.chaoxing.com/pc/course/notice/richtextNotice?courseId={cid}"
            list_url = (f"https://notice.chaoxing.com/pc/course/notice/myNoticeList"
                        f"?courseid={cid}&clazzid={classes[0]['classId']}")
            result = {"courseId": cid, "courseName": cname,
                      "classes": classes, "ok": False, "dryRun": not send}
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)

                injected = _inject_send_map(page, classes)
                got_ids = sorted([str((x.get("value") or {}).get("id")) for x in injected])
                want_ids = sorted([str(k.get("classId")) for k in classes])
                if got_ids != want_ids:
                    raise RuntimeError(f"收件人注入失败：want={want_ids}, got={got_ids}")

                page.fill("input.title", title)
                page.evaluate("(body) => { UE.getEditor('container').setContent(body); }", body_html)

                count = _editor_attachment_count(page)
                if count < 0:
                    raise RuntimeError("UEditor 不可用，无法确认正文/附件状态")
                uploaded = []
                upload_waits = []
                # 失败占位可能是常驻节点：用「本次上传前后计数差」判定，而不是看有没有该节点。
                failed_before = _upload_error_count(page)
                if att_paths:
                    # 让 WebUploader 的文件输入处于可交互状态；不同页面可能有多个 hidden input。
                    try:
                        btn = page.locator(".edui-for-attachment").first
                        btn.scroll_into_view_if_needed(timeout=3000)
                        btn.click(timeout=5000)
                    except Exception as exc:
                        result.setdefault("notes", []).append(f"attachment-button-click-failed: {str(exc)[:160]}")
                for apath in att_paths:
                    before = count
                    # 附件按钮用的是 WebUploader 的通用 hidden input（无 accept）；
                    # 页面另有图片/文档转在线等 input。优先取附件按钮容器内的 input。
                    loc = page.locator('.edui-for-attachment input[type=file]').first
                    if loc.count() == 0:
                        loc = page.locator('input[type=file]').first
                    loc.wait_for(state="attached", timeout=10000)
                    t_up = time.time()
                    loc.set_input_files(str(apath))
                    # D99：轮询「块数增加 + 无正在上传 + 连续两次稳定」，不再固定等 2.5s。
                    ok, count = _wait_upload(page, before, before_failed=failed_before)
                    item_wait = {"name": apath.name, "ok": ok,
                                 "wait_s": round(time.time() - t_up, 1)}
                    upload_waits.append(item_wait)
                    if not ok:
                        st = _upload_progress(page, before)
                        new_failed = int(st.get("errors") or 0) > failed_before
                        item_wait.update(pending=st.get("pending"), failed=new_failed,
                                         count=st.get("count"), errors=st.get("errors"))
                        fail_shot = _receipt_dir(home) / f"{run_id}-{cid}-attach-fail.png"
                        try:
                            page.screenshot(path=str(fail_shot), full_page=True)
                        except Exception:
                            fail_shot = None
                        raise RuntimeError(
                            f"附件上传未就绪：{apath.name}；{_upload_fail_reason(st, new_failed)}"
                            + (f"；截图={fail_shot}" if fail_shot else "")
                            + f"；reqs={len(reqs)}")
                    # 该文件已就绪：后续文件沿用新的基线，避免把前一个的遗留节点算到下一个头上。
                    failed_before = _upload_error_count(page)
                    uploaded.append(apath.name)
                if att_paths:
                    result["uploadWaits"] = upload_waits

                pre_shot = _receipt_dir(home) / f"{run_id}-{cid}-pre.png"
                page.screenshot(path=str(pre_shot), full_page=True)
                result.update({"attachments": uploaded, "preScreenshot": str(pre_shot),
                               "recipients": injected})

                if not send:
                    result.update({"ok": True, "status": "dry-run"})
                    receipts.append(result)
                    continue

                item_reqs.clear(); item_resps.clear()
                page.on("request", lambda r: item_reqs.append({"method": r.method, "url": r.url, "post": r.post_data})
                        if r.method != "GET" else None)
                page.on("response", lambda r: item_resps.append({"status": r.status, "url": r.url,
                                                                 "body": (r.text() if 'addNotice' in r.url else '')[:2000]})
                        if r.request.method != "GET" else None)
                with page.expect_response(lambda r: "addNotice" in r.url, timeout=60000) as ri:
                    page.click(".sendNotice.submitBtn")
                resp = ri.value
                text = resp.text()
                parsed = {}
                try:
                    parsed = json.loads(text)
                except Exception:
                    pass
                msg = parsed.get("msg") if isinstance(parsed.get("msg"), dict) else {}
                result.update({
                    "httpStatus": resp.status,
                    "statusJson": parsed.get("status"),
                    "noticeId": msg.get("id"),
                    "noticeIdCode": msg.get("idCode"),
                    "responseText": text[:2000],
                    "posts": item_reqs[:20],
                    "responses": item_resps[:20],
                })
                post_shot = _receipt_dir(home) / f"{run_id}-{cid}-post.png"
                page.screenshot(path=str(post_shot), full_page=True)
                result["postScreenshot"] = str(post_shot)

                page.goto(list_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)
                body_text = page.evaluate("document.body.innerText")
                found = title in (body_text or "")
                list_shot = _receipt_dir(home) / f"{run_id}-{cid}-list.png"
                page.screenshot(path=str(list_shot), full_page=True)
                result["foundInList"] = found
                result["listScreenshot"] = str(list_shot)
                ok = bool(parsed.get("status")) and found
                result.update({"ok": ok, "status": "sent" if ok else "failed"})
                if ok:
                    sent += 1
                else:
                    failures.append({"scope": "course", "ref": cid,
                                     "detail": result.get("responseText") or "send failed"})
            except Exception as e:
                result.update({"ok": False, "status": "exception", "error": str(e)[:500]})
                failures.append({"scope": "course", "ref": cid, "kind": "exception",
                                 "detail": str(e)[:300]})
            finally:
                receipts.append(result)
                results.append(result)

        browser.close()

    receipt = {
        "run_id": run_id,
        "ts_start": stamp,
        "ts_end": time.strftime("%Y%m%d-%H%M%S"),
        "mode": "send" if send else "dry-run",
        "title": title,
        "bodyHtml": body_html,
        "attachments": [str(p) for p in att_paths],
        "targets": targets,
        "results": results,
        "failures": failures,
        "nonGetRequests": reqs[:50],
        "nonGetResponses": resps[:50],
    }
    fn = _receipt_dir(home) / f"{run_id}.json"
    fn.write_text(json.dumps(receipt, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = (not failures) if send else all(r.get("ok") for r in results)
    return {
        "ok": ok,
        "run_id": run_id,
        "mode": receipt["mode"],
        "sent": sent,
        "courses": len(targets),
        "classes": sum(len(c.get("classes") or []) for c in targets),
        "attachments": [p.name for p in att_paths],
        "receipt": str(fn),
        "failures": failures,
        "results": results,
    }

def save_notice_uploads(workspace, items: list[dict], allowed_exts=None) -> list[dict]:
    """D79-B：把 PWA base64 上传的附件保存到 workspace 临时目录。

    items: [{name, data_b64}]；返回 [{name, path, size}]。
    """
    import base64
    import re as _re
    if workspace is None:
        try:
            from ..workspace import find_workspace
            ws = Path(find_workspace(None)).resolve()
        except Exception:
            ws = Path.cwd().resolve()
    else:
        ws = Path(workspace).resolve()
    from .allowlist import normalize_exts, read_notice_attachment_exts
    allowed = normalize_exts(allowed_exts) if allowed_exts is not None else read_notice_attachment_exts(ws)
    dest = ws / ".runtime" / "xxt" / "notice-uploads" / time.strftime("%Y%m%d-%H%M%S")
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for it in items[:20]:
        name = _re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._()（）+\- ]", "_", str(it.get("name") or "file"))[:120]
        if not name:
            name = "file"
        ext = Path(name).suffix.lower().lstrip(".")
        if allowed and ext not in allowed:
            continue
        raw = str(it.get("data_b64") or "")
        if not raw:
            continue
        try:
            body = base64.b64decode(raw)
        except Exception:
            continue
        if len(body) > 20 * 1024 * 1024:
            continue
        p = dest / name
        p.write_bytes(body)
        out.append({"name": name, "path": str(p), "size": len(body)})
    return out


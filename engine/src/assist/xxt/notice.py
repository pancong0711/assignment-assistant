"""D77：学习通课程通知发布（写操作；默认 dry-run，白名单保护）。

实现方式与 2026-10-12 真机联调一致：复用教师本机 Playwright storage_state，
打开 `richtextNotice?courseId=` 表单页，注入收件人 sendMap、填写标题/正文、
通过 UEditor/WebUploader 隐藏 input 上传附件，最后点击 `.sendNotice.submitBtn`。

安全边界：
- 默认只 dry-run；必须显式 `send=True` / CLI `--send` 才真正发送；
- 当前测试阶段仅允许 `NOTICE_TEST_ALLOWLIST` 中的 courseId:classId；
- 附件路径必须位于 workspace 下，且后缀为 pdf/doc/docx；
- 每次预检/发送都保存截图和 JSON receipt 到 `<xxt_home>/notice-sends/`。
"""
from __future__ import annotations

import html as _html
import json
import re
import secrets
import time
from pathlib import Path

# 临时写操作白名单：用户明确要求先只开通已真机验证过的课程/班级。
# 后续扩大范围时改这里或迁移到配置项。
NOTICE_TEST_ALLOWLIST = {
    ("217801417", "40009084"),
}
ATTACH_SUFFIXES = (".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png", ".webp", ".gif")


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


def validate_targets(targets: list[dict]) -> str | None:
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
            if (cid, kid) not in NOTICE_TEST_ALLOWLIST:
                return (f"写操作白名单拒绝：courseId={cid}, classId={kid}；"
                        "当前仅开放已真机验证的大学物理知识点拾遗（by pc）/默认班级")
    return None


def safe_attachment_path(path: str | Path, workspace: Path | str | None = None) -> Path | None:
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
    if rp.suffix.lower() not in ATTACH_SUFFIXES:
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


def _editor_attachment_count(page) -> int:
    try:
        content = page.evaluate("UE.getEditor('container').getContent()")
        return len(re.findall(r'class=\"editor-iframe\"', content or ""))
    except Exception:
        return -1


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


def _wait_upload(page, before: int, timeout_s: int = 90) -> tuple[bool, int]:
    deadline = time.time() + timeout_s
    last = before
    while time.time() < deadline:
        last = _editor_attachment_count(page)
        if last > before:
            return True, last
        page.wait_for_timeout(1000)
    return False, last


def send_notice_from_spec(spec: dict, *, send: bool = False, storage: Path | str | None = None,
                          workspace: Path | str | None = None) -> dict:
    """执行一个通知 spec。spec: targets/title/bodyHtml/attachments/dryRun。"""
    from playwright.sync_api import sync_playwright
    from .session import check_session, _launch, xxt_home
    from .layout import pages_dir

    targets = normalize_targets(spec.get("targets"))
    err = validate_targets(targets)
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
            return {"ok": False, "error": f"附件不可用或不在 workspace 内：{a}", "sent": 0, "dryRun": not send}
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
                # 让 WebUploader 的文件输入处于可交互状态；不同页面可能有多个 hidden input。
                try:
                    btn = page.locator(".edui-for-attachment").first
                    btn.scroll_into_view_if_needed(timeout=3000)
                    btn.click(timeout=5000)
                except Exception as exc:
                    result.setdefault("notes", []).append(f"attachment-button-click-failed: {str(exc)[:160]}")
                uploaded = []
                for apath in att_paths:
                    before = count
                    # 附件按钮用的是 WebUploader 的通用 hidden input（无 accept）；
                    # 页面另有图片/文档转在线等 input。优先取附件按钮容器内的 input。
                    loc = page.locator('.edui-for-attachment input[type=file]').first
                    if loc.count() == 0:
                        loc = page.locator('input[type=file]').first
                    loc.wait_for(state="attached", timeout=10000)
                    loc.set_input_files(str(apath))
                    ok, count = _wait_upload(page, before)
                    if not ok:
                        fail_shot = _receipt_dir(home) / f"{run_id}-{cid}-attach-fail.png"
                        try:
                            page.screenshot(path=str(fail_shot), full_page=True)
                        except Exception:
                            fail_shot = None
                        raise RuntimeError(
                            f"附件上传未插入编辑器：{apath.name}"
                            + (f"；截图={fail_shot}" if fail_shot else "")
                            + f"；reqs={len(reqs)}")
                    uploaded.append(apath.name)
                if att_paths:
                    # WebUploader 插入 iframe 后仍有草稿/上传收尾请求；立即点发送可能被页面校验拦住。
                    page.wait_for_timeout(2500)

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

def save_notice_uploads(workspace, items: list[dict]) -> list[dict]:
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
    dest = ws / ".runtime" / "xxt" / "notice-uploads" / time.strftime("%Y%m%d-%H%M%S")
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for it in items[:20]:
        name = _re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._()（）+\- ]", "_", str(it.get("name") or "file"))[:120]
        if not name:
            name = "file"
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


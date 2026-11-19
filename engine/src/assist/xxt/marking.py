"""D84 §1：学习通批阅页（mark/review-work）写入原语。

只做「页面级动作」，不含白名单/CLI 决策（见 grade_upload.py + cli.py）：
- open_mark_page      打开某学生的批阅页（workId + workAnswerId）
- set_comment_html    作业批语（UEditor key = textarea[name=comment] 的 id）
- set_question_comments_html  题目批语（textarea[id^=answer] → UE key）
- upload_comment_image 作业批语内插入图片（UEditor insertimage 弹窗 → WebUploader）
- fill_scores         每题分（.inputBranch.questionScore）+ 总分（#tmpscore）
- submit / handle_confirmation_dialog  提交（markAction(1)）+ 确认弹窗
- read_back           读回批语/分数/图片数，用于 dry-run 校验

真机依据（2026-10-15 存档 `.scratch/xxt-pages/recon-review-student.html`）：
- 批语 UE 容器默认 `display:none`（`.kark_comment_edit`）→ 需先亮出工具栏；
- 作业批语：`textarea[name="comment"]`，页面 JS 调 `UE.getEditor('comment<id>')`；
- 题目批语：`textarea[id^="answer"]`，页面 JS 调 `UE.getEditor('answer<qid>')`；
- 提交：`a[onclick*="markAction(1)"]`；确认弹窗：`#popok/#popokTwice/#confirmPiyueWin`。
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from loguru import logger

# 提交确认弹窗（沿用遗留 uploader.py 口径）
CONFIRM_POPUPS = ("#tabindexWorkpop", "#tabindexWorkpopTwice", "#confirmPiyueWin")
# 图片上传弹窗 iframe（UEditor insertimage）
IMAGE_DIALOG_HINTS = ("imageNew", "dialogs/image", "image.html")


def normalize_comment_html(text: str) -> str:
    """纯文本 → HTML 段落（已是 HTML 则原样返回）。CLI/PWA 都可能传纯文本。"""
    s = str(text or "")
    if re.search(r"</?[a-zA-Z][^>]*>", s):
        return s
    parts = [p.strip() for p in re.split(r"\n+", s) if p.strip()]
    return "".join(f"<p>{p}</p>" for p in parts)


def parse_question_scores(spec) -> list[float]:
    """解析每题分：支持 "10,20,30" / [10,20] / (10, 20)；非法项忽略。"""
    if spec is None:
        return []
    if isinstance(spec, (list, tuple)):
        items = list(spec)
    else:
        items = re.split(r"[,\s]+", str(spec))
    out: list[float] = []
    for it in items:
        try:
            out.append(float(str(it).strip()))
        except (TypeError, ValueError):
            continue
    return out


# D84 关键口径：mark 页的 id= 是 **workId**（不是 workLibraryId）；
# 未交列表必须带 submit=false&evaluation=0（否则渲染成已交视图 → 0 行）。
MARK_UNSUBMITTED_URL = ("https://mooc2-ans.chaoxing.com/mooc2-ans/work/mark"
                        "?courseid={course}&clazzid={clazz}&id={work}"
                        "&submit=false&evaluation=0")


def open_mark_unsubmitted(page, course_id: str, class_id: str, work_id: str,
                          *, wait_ms: int = 3000) -> str:
    """打开「未交」批阅列表（设为已交入口在此）。work_id 必须是 workId。"""
    url = MARK_UNSUBMITTED_URL.format(course=course_id, clazz=class_id, work=work_id)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(wait_ms)
    return url


def open_mark_page(page, course_id: str, class_id: str, work_id: str,
                   work_answer_id: str, *, wait_ms: int = 3000) -> str:
    """打开某学生批阅页；返回最终 URL。"""
    from .extractor import review_work_url
    url = review_work_url(str(course_id), str(class_id), str(work_id), str(work_answer_id))
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(wait_ms)
    return url


# ---------------- 批语（UEditor） ----------------

_JS_SET_UE = """([sel, html]) => {
  const ta = document.querySelector(sel);
  if (!ta) return {ok: false, reason: 'no-textarea', sel};
  let mode = 'textarea';
  if (window.UE && UE.getEditor) {
    const ed = UE.getEditor(ta.id);
    if (ed) {
      ed.setContent(html);
      try { ed.sync(); } catch (e) {}
      mode = 'ueditor';
    }
  }
  if (mode === 'textarea') ta.value = html;
  return {ok: true, key: ta.id, mode};
}"""

_JS_GET_COMMENT = """() => {
  const ta = document.querySelector('textarea[name="comment"]');
  if (!ta) return {html: '', key: ''};
  let html = ta.value || '';
  try {
    if (window.UE && UE.getEditor) {
      const ed = UE.getEditor(ta.id);
      if (ed && ed.getContent) html = ed.getContent() || html;
    }
  } catch (e) {}
  return {html, key: ta.id};
}"""


def set_comment_html(page, html: str) -> dict:
    """写作业批语（UE key 取 textarea[name=comment].id）。"""
    return page.evaluate(_JS_SET_UE, ['textarea[name="comment"]', str(html or "")])


def set_question_comments_html(page, comments_by_index) -> list[dict]:
    """按顺序写题目批语（第 n 个 textarea[id^=answer]）；空串/None 跳过。"""
    out: list[dict] = []
    for idx, html in enumerate(comments_by_index or []):
        if not html:
            continue
        out.append(page.evaluate(
            """([idx, html]) => {
              const tas = Array.from(document.querySelectorAll('textarea[id^="answer"]'));
              const ta = tas[idx];
              if (!ta) return {ok: false, reason: 'no-textarea', idx};
              if (window.UE && UE.getEditor) {
                const ed = UE.getEditor(ta.id);
                if (ed) { ed.setContent(html); try { ed.sync(); } catch (e) {}
                          return {ok: true, key: ta.id, mode: 'ueditor', idx}; }
              }
              ta.value = html;
              return {ok: true, key: ta.id, mode: 'textarea', idx};
            }""", [idx, str(html)]))
    return out


def read_back(page) -> dict:
    """读回批语/题目批语/分数/图片数（dry-run 校验用）。"""
    return page.evaluate(
        """() => {
          const imgCount = (html) => (String(html).match(/<img/gi) || []).length;
          const ta = document.querySelector('textarea[name="comment"]');
          let comment = ta ? (ta.value || '') : '';
          if (ta && window.UE && UE.getEditor) {
            const ed = UE.getEditor(ta.id);
            if (ed && ed.getContent) comment = ed.getContent() || comment;
          }
          const answers = Array.from(document.querySelectorAll('textarea[id^="answer"]')).map(x => {
            let v = x.value || '';
            try {
              const ed = window.UE && UE.getEditor(x.id);
              if (ed && ed.getContent) v = ed.getContent() || v;
            } catch (e) {}
            return v;
          });
          const scoreEl = document.querySelector('#tmpscore');
          const qScores = Array.from(document.querySelectorAll('.inputBranch.questionScore'))
            .map(x => x.value);
          return {comment, commentImages: imgCount(comment), answers,
                  answerImages: answers.map(imgCount),
                  score: scoreEl ? (scoreEl.value || '') : '', questionScores: qScores};
        }""")


# ---------------- 评语图片上传 ----------------

_JS_REVEAL_TOOLBAR = """() => {
  const ta = document.querySelector('textarea[name="comment"]');
  if (!ta) return false;
  // UEditor 根容器：优先 UE.container，其次沿 DOM 上溯找 .kark_comment_edit / .edui-editor
  let node = null;
  try {
    if (window.UE && UE.getEditor) {
      const ed = UE.getEditor(ta.id);
      if (ed && ed.container) node = ed.container;
    }
  } catch (e) {}
  if (!node) node = ta.closest('.kark_comment_edit') || ta.parentElement;
  // 逐级解除 display:none（遗留 show_ueditor_toolbar 同口径）
  let el = node;
  while (el && el !== document.body) {
    const style = getComputedStyle(el);
    if (style.display === 'none') { el.style.display = 'block'; }
    el = el.parentElement;
  }
  return !!node;
}"""

_JS_CLICK_INSERTIMAGE = """() => {
  const ta = document.querySelector('textarea[name="comment"]');
  let rootId = '';
  try {
    if (window.UE && UE.getEditor) {
      const ed = UE.getEditor(ta.id);
      if (ed && ed.container) rootId = ed.container.id || '';
    }
  } catch (e) {}
  if (!rootId) {
    const box = ta.closest('.kark_comment_edit') || document;
    const root = box.querySelector('.edui-editor');
    rootId = root ? root.id : '';
  }
  const scope = rootId ? document.getElementById(rootId) : document;
  if (!scope) return {ok: false, reason: 'no-editor-root'};
  const btn = scope.querySelector('.edui-for-insertimage .edui-button-body')
           || scope.querySelector('.edui-for-insertimage');
  if (!btn) return {ok: false, reason: 'no-insertimage', rootId};
  btn.click();
  return {ok: true, rootId};
}"""


def _image_dialog_frame(page, timeout_s: float = 15.0):
    """找 insertimage 上传弹窗 iframe（按 URL 特征）。"""
    deadline = time.time() + max(0.0, timeout_s)
    while True:
        for fr in page.frames:
            url = fr.url or ""
            if any(h in url for h in IMAGE_DIALOG_HINTS):
                return fr
        if time.time() >= deadline:
            return None
        try:
            page.wait_for_timeout(400)
        except Exception:  # noqa: BLE001
            return None


def upload_comment_image(page, image_path, *, timeout_s: float = 60.0) -> dict:
    """在作业批语里插入一张图片（走 UEditor insertimage 弹窗的 WebUploader）。

    返回 {ok, uploaded?, error?}；dry-run 也可以用（只上传媒体、不提交批阅）。
    """
    p = Path(image_path)
    if not p.is_file():
        return {"ok": False, "error": f"图片不存在：{p}"}
    before = read_back(page).get("commentImages", 0)
    page.evaluate(_JS_REVEAL_TOOLBAR)
    clicked = page.evaluate(_JS_CLICK_INSERTIMAGE)
    if not clicked.get("ok"):
        return {"ok": False, "error": f"找不到插入图片按钮：{clicked}"}
    frame = _image_dialog_frame(page, timeout_s=15.0)
    if frame is None:
        return {"ok": False, "error": "图片上传弹窗 iframe 未出现"}
    try:
        inp = frame.locator("input[type=file]").first
        inp.wait_for(state="attached", timeout=8000)
        inp.set_input_files(str(p))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"弹窗内设置文件失败：{str(exc)[:200]}"}
    deadline = time.time() + max(10.0, timeout_s)
    while time.time() < deadline:
        rb = read_back(page)
        if rb.get("commentImages", 0) > before:
            return {"ok": True, "image": p.name, "images": rb.get("commentImages")}
        page.wait_for_timeout(1000)
    return {"ok": False, "error": f"图片未插入批语：{p.name}"}


# ---------------- 打分与提交 ----------------

def fill_scores(page, *, total: float | None = None,
                per_question: "list[float] | None" = None) -> dict:
    """填总分（#tmpscore）与每题分（.inputBranch.questionScore），并派发 change/input。"""
    out: dict = {}
    if per_question:
        out["questionScores"] = page.evaluate(
            """(scores) => {
              const inputs = Array.from(document.querySelectorAll('.inputBranch.questionScore'));
              inputs.forEach((inp, i) => {
                const v = i < scores.length ? scores[i] : scores[scores.length - 1];
                inp.value = '';
                inp.focus();
                inp.value = String(v);
                // D202：学习通需要 change/input + 失焦（blur）与回车才会真正提交该值，
                // 只派发 change/input 时偶尔会被框架回滚 → 提交的是空分数。
                inp.dispatchEvent(new Event('input', {bubbles: true}));
                inp.dispatchEvent(new Event('change', {bubbles: true}));
                inp.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true, key: 'Enter'}));
                inp.blur();
              });
              return inputs.length;
            }""", [float(x) for x in per_question])
    if total is not None:
        out["total"] = page.evaluate(
            """(score) => {
              const inp = document.querySelector('#tmpscore');
              if (!inp) return false;
              inp.focus();
              inp.value = '';
              inp.value = String(score);
              inp.dispatchEvent(new Event('input', {bubbles: true}));
              inp.dispatchEvent(new Event('change', {bubbles: true}));
              inp.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true, key: 'Enter'}));
              inp.blur();
              return true;
            }""", float(total))
    return out


_JS_PAGE_STATE = r"""() => {
  // D204：提交前先判断“当前到底是什么页面”——会话过期会跳到 passport 登录页，
  // 此时页面上当然找不到提交按钮；旧实现只会报“未找到提交按钮”，误导排查方向。
  const url = location.href;
  const host = location.hostname || '';
  const path = (location.pathname || '').toLowerCase();
  const loginRedirect = /passport|login|sso/i.test(host) || /login/i.test(path);
  const hasPassword = !!document.querySelector('input[type=password]');
  const hasCommentBox = !!document.querySelector('textarea[name="comment"]');
  const hasScoreInput = !!document.querySelector('#tmpscore');
  const vis = (el) => {
    if (!el) return false;
    const st = getComputedStyle(el);
    return st.display !== 'none' && st.visibility !== 'hidden' && el.offsetParent !== null;
  };
  const candidates = [];
  document.querySelectorAll('a,button,input[type=button],input[type=submit]').forEach(el => {
    if (!vis(el)) return;
    const onclick = el.getAttribute('onclick') || '';
    const text = (el.textContent || el.value || '').replace(/\s+/g, ' ').trim().slice(0, 40);
    if (/markAction|confirmPiyueWork|submit|save|publish/i.test(onclick)
        || /提交|保存|批阅|发布/.test(text)) {
      candidates.push({text, onclick: onclick.slice(0, 160),
                       id: el.id || '', cls: (el.className || '').toString().slice(0, 60)});
    }
  });
  return {url, host, title: (document.title || '').slice(0, 120), loginRedirect,
          hasPassword, hasCommentBox, hasScoreInput, candidates,
          bodyText: (document.body ? document.body.innerText : '').replace(/\s+/g, ' ').slice(0, 300)};
}"""


def page_state(page) -> dict:
    """D204：只读页面状态（URL/标题/是否登录页/关键控件是否存在/提交候选按钮）。"""
    try:
        return page.evaluate(_JS_PAGE_STATE) or {}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:200]}


_JS_CLICK_SUBMIT = r"""() => {
  // D206：真实学习通的提交按钮可能是 <div>/<span>（实测：
  // <div class="btnBlue fr fs14" onclick="markAction(1)">Submit</div>），
  // 旧实现只找 a,button → 永远 no-markAction(1)。
  const vis = (el) => {
    if (!el) return false;
    const st = getComputedStyle(el);
    return st.display !== 'none' && st.visibility !== 'hidden' && el.offsetParent !== null;
  };
  const all = Array.from(document.querySelectorAll('[onclick]'));
  for (const el of all) {
    const onclick = el.getAttribute('onclick') || '';
    if (/markAction\(1\)/.test(onclick)) {
      try { el.scrollIntoView(); } catch (e) {}
      el.click();
      return {ok: true, text: (el.textContent || '').trim().slice(0, 40),
              tag: el.tagName, cls: (el.className || '').toString().slice(0, 60)};
    }
  }
  // 退化：英文界面 Submit / 中文 提交（无 onclick 的按钮）
  for (const el of Array.from(document.querySelectorAll('a,button,input[type=button],div,span'))) {
    const t = (el.textContent || el.value || '').trim();
    if (!vis(el) || !/^(submit|提交|提交批阅)$/i.test(t)) continue;
    try { el.scrollIntoView(); } catch (e) {}
    el.click();
    return {ok: true, text: t, tag: el.tagName, how: 'text'};
  }
  return {ok: false, reason: 'no-markAction(1)'};
}"""


_JS_FIND_POPUP = r"""() => {
  // D203：弹窗选择器放宽——不同版本学习通的确认层 id 不一致。
  const sels = ['#tabindexWorkpop', '#tabindexWorkpopTwice', '#confirmPiyueWin',
                '#popok', '#popokTwice', '.layui-layer', '.popup', '.dialog'];
  const visible = (el) => {
    if (!el) return false;
    const st = getComputedStyle(el);
    return st.display !== 'none' && st.visibility !== 'hidden' && el.offsetParent !== null;
  };
  for (const sel of sels) {
    for (const el of document.querySelectorAll(sel)) {
      if (!visible(el)) continue;
      const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
      // 只把“带确定按钮/带提示文案”的层当作确认弹窗，避免误点页面其它浮层
      const hasConfirm = !!(el.querySelector('#popok, #popokTwice') ||
        Array.from(el.querySelectorAll('a,button,span')).some(x =>
          /confirmPiyueWork|确定|确认|继续/.test((x.getAttribute('onclick') || '') +
                                                (x.textContent || ''))));
      if (!hasConfirm && !/确定|确认|是否|未批阅|评分/.test(text)) continue;
      return {id: sel, text: text.slice(0, 200)};
    }
  }
  return null;
}"""

_JS_CLICK_POPUP_CONFIRM = r"""() => {
  const visible = (el) => {
    if (!el) return false;
    const st = getComputedStyle(el);
    return st.display !== 'none' && st.visibility !== 'hidden' && el.offsetParent !== null;
  };
  const cands = [];
  // 1) 经典 id
  for (const sel of ['#popok', '#popokTwice']) {
    document.querySelectorAll(sel).forEach(el => cands.push([el, sel]));
  }
  // 2) 调用 confirmPiyueWork() 的按钮（学习通新版的确认入口）
  document.querySelectorAll('a,button,span,input').forEach(el => {
    const onclick = el.getAttribute('onclick') || '';
    if (/confirmPiyueWork/.test(onclick)) cands.push([el, 'onclick:confirmPiyueWork']);
  });
  // 3) 弹窗内文案为“确定/确认/继续”的按钮
  document.querySelectorAll('a,button,span').forEach(el => {
    const t = (el.textContent || '').replace(/\s+/g, '');
    if (/^(确定|确认|继续|确定提交|ok|confirm|yes|submit)$/i.test(t)) {
      cands.push([el, 'text:' + t]);
    }
  });
  for (const [el, how] of cands) {
    if (!visible(el)) continue;
    try { el.scrollIntoView(); el.click(); } catch (e) { continue; }
    return {ok: true, how, text: (el.textContent || '').trim().slice(0, 40)};
  }
  return {ok: false, reason: 'no-visible-confirm'};
}"""


def handle_confirmation_dialog(page, timeout_s: float = 10.0) -> dict:
    """D203：处理提交后的确认弹窗（可能有多层），返回处理详情。

    现场：点 `markAction(1)` 后平台弹确认层，但确认按钮**不是** `#popok`
    （新版调用 `confirmPiyueWork()`）→ 旧实现只认 `#popok`，点不到确认，
    提交实际被取消，平台状态一直停在「待批阅」。
    """
    deadline = time.time() + max(0.0, timeout_s)
    popups: list[dict] = []
    clicks: list[dict] = []
    idle = 0
    clicked_keys: set = set()
    repeat = 0
    while time.time() < deadline:
        try:
            popup = page.evaluate(_JS_FIND_POPUP)
        except Exception:  # noqa: BLE001
            return {"ok": False, "popups": popups, "clicks": clicks,
                    "error": "读取确认弹窗失败"}
        if not popup:
            idle += 1
            # 连续 3 次（约 1.5s）没有弹窗 → 认为已处理完
            if idle >= 3:
                break
            page.wait_for_timeout(500)
            continue
        idle = 0
        key = (str(popup.get("id") or ""), str(popup.get("text") or "")[:80])
        if key in clicked_keys:
            # D205：同一个弹窗**不重复点击**。旧实现会在弹窗关闭/导航前反复点“确定”，
            # 造成重复提交或把请求打断；这里等它自己关闭，最多再观察 2 次。
            repeat += 1
            if repeat >= 2:
                return {"ok": False, "popups": popups, "clicks": clicks,
                        "stillOpen": True,
                        "error": ("确认弹窗点击后仍未关闭（可能被平台校验拦住）："
                                  + str(popup.get("text") or "")[:120])}
            page.wait_for_timeout(500)
            continue
        repeat = 0
        popups.append(popup)
        clicked = page.evaluate(_JS_CLICK_POPUP_CONFIRM)
        clicked_keys.add(key)
        clicks.append({"popup": popup.get("id"), "clicked": clicked})
        logger.info(f"批阅提交确认弹窗：{popup.get('id')} → 点击={clicked}")
        page.wait_for_timeout(800)
    return {"ok": bool(clicks) or not popups, "popups": popups, "clicks": clicks}


_JS_CLICK_SUBMIT_FALLBACK = r"""() => {
  // D204：markAction(1) 找不到时的兜底——按 onclick 关键字/按钮文案点提交。
  const vis = (el) => {
    if (!el) return false;
    const st = getComputedStyle(el);
    return st.display !== 'none' && st.visibility !== 'hidden' && el.offsetParent !== null;
  };
  const tried = [];
  const els = Array.from(document.querySelectorAll(
    '[onclick],a,button,input[type=button],input[type=submit],div,span'));
  const rank = (el) => {
    const onclick = el.getAttribute('onclick') || '';
    const text = (el.textContent || el.value || '').trim();
    if (/markAction\(1\)/.test(onclick)) return 100;
    if (/confirmPiyueWork/.test(onclick)) return 90;
    if (/submit|save|publish/i.test(onclick)) return 80;
    if (/^(提交(批阅)?|submit)$/i.test(text)) return 70;
    if (/^(保存(并批阅)?|save)$/i.test(text)) return 60;
    if (/提交|保存|submit|save/i.test(text)) return 50;
    return 0;
  };
  const cands = els.filter(vis).map(el => [el, rank(el)])
    .filter(([, r]) => r > 0).sort((a, b) => b[1] - a[1]);
  for (const [el, r] of cands) {
    const onclick = el.getAttribute('onclick') || '';
    const text = (el.textContent || el.value || '').trim().slice(0, 40);
    // D208：绝不点“提交并进入下一份”——那会把批阅带到下一个学生
    if (/next|下一|下一位|下份/i.test(text + ' ' + onclick)) {
      tried.push({text, onclick: onclick.slice(0, 120), rank: r, skipped: 'next-student'});
      continue;
    }
    tried.push({text, onclick: onclick.slice(0, 120), rank: r});
    try { el.scrollIntoView(); el.click(); } catch (e) { continue; }
    return {ok: true, how: 'fallback', text, tried};
  }
  return {ok: false, reason: 'no-submit-candidate', tried};
}"""


def submit(page, *, handle_confirm: bool = True) -> dict:
    """点提交（markAction(1)）并处理确认弹窗。真正写操作，调用方必须已过白名单。

    D204：先判断页面状态——会话过期会跳 passport 登录页，此时不可能有提交按钮；
    再依次尝试 `markAction(1)` → `confirmPiyueWork` → onclick 关键字 → 按钮文案。
    """
    st = page_state(page)
    diag = {"page": {k: st.get(k) for k in
                     ("url", "title", "loginRedirect", "hasPassword",
                      "hasCommentBox", "hasScoreInput") if k in st},
            "candidates": (st.get("candidates") or [])[:8]}
    if st.get("error"):
        return {"ok": False, "status": "page-unreadable",
                "error": f"读取批阅页失败：{st['error']}", **diag}
    if st.get("loginRedirect") or (st.get("hasPassword") and not st.get("hasCommentBox")):
        return {"ok": False, "status": "session-expired",
                "error": ("学习通会话已失效（当前页跳到了登录页/出现登录框）："
                          "请点「🔁 重新扫码登录」后重试"),
                **diag}
    res = page.evaluate(_JS_CLICK_SUBMIT)
    if not res.get("ok"):
        fb = page.evaluate(_JS_CLICK_SUBMIT_FALLBACK)
        diag["fallback"] = fb
        if not fb.get("ok"):
            return {"ok": False, "status": "no-submit-button",
                    "error": ("未找到提交按钮（页面结构可能与预期不同）"
                              + ("" if st.get("hasCommentBox") else
                                 "；且未检测到批语输入框，页面可能不是批阅页")),
                    **diag}
        res = fb
    page.wait_for_timeout(1500)
    if handle_confirm:
        res["confirmPopup"] = handle_confirmation_dialog(page)
    page.wait_for_timeout(2500)
    res["urlAfter"] = page.url
    # D203：诊断信息——平台 confirm/alert 文案 + 页面上所有 markAction 候选按钮。
    try:
        res["dialogs"] = page.evaluate("() => window.__assistDialogs || []")
    except Exception:  # noqa: BLE001
        res["dialogs"] = []
    res["page"] = diag["page"]
    res["pageCandidates"] = diag["candidates"]
    try:
        res["submitCandidates"] = page.evaluate(r"""() => Array.from(
            document.querySelectorAll('a,button')).map(el => ({
              text: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 40),
              onclick: (el.getAttribute('onclick') || '').slice(0, 120),
            })).filter(x => /markAction|confirmPiyueWork|submit/i.test(x.onclick)
              || /提交|保存|批阅/.test(x.text))""")
    except Exception:  # noqa: BLE001
        res["submitCandidates"] = []
    return res

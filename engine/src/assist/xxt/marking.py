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


def open_mark_page(page, course_id: str, class_id: str, work_id: str,
                   work_answer_id: str, *, wait_ms: int = 3000) -> str:
    """打开某学生批阅页；返回最终 URL。"""
    from .extractor import review_work_url
    url = review_work_url(str(course_id), str(class_id), str(work_id), str(work_answer_id))
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(wait_ms)
    return url


# ---------------- 批语（UEditor） ----------------

_JS_SET_UE = """(sel, html) => {
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
                inp.value = String(v);
                inp.dispatchEvent(new Event('change', {bubbles: true}));
                inp.dispatchEvent(new Event('input', {bubbles: true}));
              });
              return inputs.length;
            }""", [float(x) for x in per_question])
    if total is not None:
        out["total"] = page.evaluate(
            """(score) => {
              const inp = document.querySelector('#tmpscore');
              if (!inp) return false;
              inp.value = '';
              inp.value = String(score);
              inp.dispatchEvent(new Event('change', {bubbles: true}));
              inp.dispatchEvent(new Event('input', {bubbles: true}));
              return true;
            }""", float(total))
    return out


_JS_CLICK_SUBMIT = """() => {
  const links = Array.from(document.querySelectorAll('a,button'));
  for (const el of links) {
    const onclick = el.getAttribute('onclick') || '';
    if (onclick.includes('markAction(1)')) {
      el.scrollIntoView();
      el.click();
      return {ok: true, text: (el.textContent || '').trim()};
    }
  }
  return {ok: false, reason: 'no-markAction(1)'};
}"""


def handle_confirmation_dialog(page, timeout_s: float = 10.0) -> bool:
    """处理提交后的确认弹窗（未评分/未全部批阅等情况）；无弹窗返回 False。"""
    deadline = time.time() + max(0.0, timeout_s)
    while time.time() < deadline:
        popup = page.evaluate(
            """() => {
              const sels = ['#tabindexWorkpop', '#tabindexWorkpopTwice', '#confirmPiyueWin'];
              for (const sel of sels) {
                const el = document.querySelector(sel);
                if (!el) continue;
                const st = getComputedStyle(el);
                if (st.display !== 'none' && st.visibility !== 'hidden' && el.offsetParent !== null) {
                  return {id: sel, text: (el.innerText || '').slice(0, 120)};
                }
              }
              return null;
            }""")
        if popup:
            clicked = page.evaluate(
                """() => {
                  const el = document.querySelector('#popok, #popokTwice');
                  if (el && el.offsetParent !== null) { el.click(); return true; }
                  return false;
                }""")
            logger.info(f"批阅提交确认弹窗：{popup} → 确定={clicked}")
            return True
        try:
            page.wait_for_timeout(500)
        except Exception:  # noqa: BLE001
            return False
    return False


def submit(page, *, handle_confirm: bool = True) -> dict:
    """点提交（markAction(1)）并处理确认弹窗。真正写操作，调用方必须已过白名单。"""
    res = page.evaluate(_JS_CLICK_SUBMIT)
    if not res.get("ok"):
        return {"ok": False, "error": f"未找到提交按钮：{res}"}
    page.wait_for_timeout(1500)
    if handle_confirm:
        res["confirmPopup"] = handle_confirmation_dialog(page)
    page.wait_for_timeout(2500)
    res["urlAfter"] = page.url
    return res

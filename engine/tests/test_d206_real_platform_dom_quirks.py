"""D206：真实学习通页面的三个差异（已在真实平台实测确认）。

1. 提交按钮可能是 **`<div onclick="markAction(1)">Submit</div>`**，
   不是 `<a>/<button>` → 旧选择器 `a,button` 找不到，报 `no-markAction(1)`。
2. 界面可能为**英文**（Submit / Save / Unreview）→ 中文文案匹配失效。
3. 批阅列表行有时**不渲染状态文本**（空串），但分数已保存 →
   旧核验只认“已批阅”，会把成功判成失败。
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest

from assist.xxt import grade_upload as GU


# ---------------- 1) 核验容忍“状态为空但分数已保存” ----------------

def _patch_rows(monkeypatch, rows):
    monkeypatch.setattr(GU, "_open_mark_list", lambda *a, **k: "url")
    monkeypatch.setattr(GU, "_students_from_mark_list", lambda page: rows)


def test_verify_ok_when_status_empty_but_score_matches(monkeypatch):
    _patch_rows(monkeypatch, [{"name": "学生甲", "status": "", "score": "100",
                               "workAnswerId": "wa1"}])
    rep = GU.verify_submission(object(), "c", "k", "w", student="学生甲",
                               work_answer_id="wa1", expect_score=100)
    assert rep["ok"] is True
    assert "note" in rep  # 说明“列表未渲染状态，但分数一致”


def test_verify_fails_when_status_empty_and_score_wrong(monkeypatch):
    _patch_rows(monkeypatch, [{"name": "学生甲", "status": "", "score": "60",
                               "workAnswerId": "wa1"}])
    rep = GU.verify_submission(object(), "c", "k", "w", student="学生甲",
                               work_answer_id="wa1", expect_score=100)
    assert rep["ok"] is False
    assert "不一致" in rep["error"]


def test_verify_accepts_english_reviewed(monkeypatch):
    _patch_rows(monkeypatch, [{"name": "学生甲", "status": "Reviewed", "score": "100",
                               "workAnswerId": "wa1"}])
    rep = GU.verify_submission(object(), "c", "k", "w", student="学生甲",
                               work_answer_id="wa1", expect_score=100)
    assert rep["ok"] is True


def test_verify_rejects_english_unreview(monkeypatch):
    _patch_rows(monkeypatch, [{"name": "学生甲", "status": "Unreview", "score": "100",
                               "workAnswerId": "wa1"}])
    rep = GU.verify_submission(object(), "c", "k", "w", student="学生甲",
                               work_answer_id="wa1", expect_score=100)
    assert rep["ok"] is False


# ---------------- 2) 源码契约：选择器/英文/状态 ----------------

def test_submit_selector_covers_div_buttons():
    src = (Path(__file__).resolve().parents[1] / "src/assist/xxt/marking.py").read_text(
        encoding="utf-8")
    body = src.split("_JS_CLICK_SUBMIT = ")[1].split("_JS_CLICK_SUBMIT_FALLBACK")[0]
    assert "querySelectorAll('[onclick]')" in body, '未按 onclick 属性全量查找提交按钮'
    assert "markAction\\\\(1\\\\)" in body or "markAction(1)" in body
    assert "submit" in body.lower(), '未覆盖英文 Submit'


def test_fallback_and_popup_cover_english():
    src = (Path(__file__).resolve().parents[1] / "src/assist/xxt/marking.py").read_text(
        encoding="utf-8")
    assert "submit|save" in src
    assert "ok|confirm|yes|submit" in src


def test_review_list_parses_english_status():
    src = (Path(__file__).resolve().parents[1] / "src/assist/xxt/extractor.py").read_text(
        encoding="utf-8")
    assert "Reviewed" in src and "Unreview" in src


# ---------------- 3) 端到端：DIV 提交按钮 + 英文界面 ----------------

MARK_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Mark</title></head><body>
<textarea name="comment" id="comment"></textarea>
<input id="tmpscore" value="">
<a class="menu">Mark by student</a>
<div class="btnBlue fr fs14" onclick="markAction(1)">Submit</div>
<div id="tabindexWorkpop" style="display:none">
  <div>Submit this review?</div>
  <a href="javascript:;" onclick="confirmPiyueWork()">OK</a>
</div>
<script>
window.__confirmEnabled = true;
function markAction(n){ document.getElementById('tabindexWorkpop').style.display='block'; }
function confirmPiyueWork(){
  if (!window.__confirmEnabled) return false;
  fetch('/save', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({score: document.getElementById('tmpscore').value})})
    .then(() => { location.href = '/list'; });
  return true;
}
</script></body></html>"""

LIST_PAGE = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<ul class="dataBody_td">
  <li class="taskBody_name"><div class="py_name">学生甲</div></li>
  <li><a class="cz_py" data="https://x/review-work?workAnswerId=101">Open</a></li>
  <li><input class="scoreInput" value="__SCORE__"></li>
  <li>__STATUS__</li>
</ul></body></html>"""


class _Srv:
    def __init__(self):
        self.state = {"saved": False, "score": ""}
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, body, ctype="text/html; charset=utf-8"):
                b = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                u = urlparse(self.path)
                if u.path == "/mark":
                    outer.state["saved"] = False
                    self._send(MARK_PAGE)
                elif u.path == "/list":
                    # 故意不渲染状态文本（真实平台实测如此）
                    score = outer.state["score"] if outer.state["saved"] else ""
                    self._send(LIST_PAGE.replace("__SCORE__", score)
                               .replace("__STATUS__", ""))
                else:
                    self._send("ok")

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(n) or b"{}")
                outer.state.update({"saved": True, "score": str(data.get("score") or "")})
                self._send(json.dumps({"ok": True}), "application/json")

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


def test_e2e_div_submit_button_and_empty_status(monkeypatch):
    """核心回归：DIV 提交按钮 + 英文界面 + 列表无状态文本，仍必须判成功。"""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    from assist.xxt.session import _launch
    import assist.xxt.work as W

    mock = _Srv()
    pw = sync_playwright().start()
    try:
        try:
            browser = _launch(pw, headless=True)
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"浏览器不可用：{str(exc)[:100]}")
        page = browser.new_page()
        monkeypatch.setattr(W, "validate_work_target", lambda *a, **k: "")
        monkeypatch.setattr(GU, "resolve_work_id_on_page", lambda *a, **k: "w1")
        monkeypatch.setattr(GU, "open_mark_page", lambda pg, c, k, w, wa, **kw: (
            pg.goto(f"{mock.base}/mark", wait_until="domcontentloaded"), pg.url)[-1])
        monkeypatch.setattr(GU, "_open_mark_list", lambda pg, c, k, w: (
            pg.goto(f"{mock.base}/list", wait_until="domcontentloaded"), pg.url)[-1])
        monkeypatch.setattr(GU, "_shot", lambda pg, tag: "")
        monkeypatch.setattr(GU, "_write_receipt", lambda kind, payload: "")
        monkeypatch.setattr(GU, "_start_browser", lambda storage: (None, None, page, None))
        monkeypatch.setattr(GU, "_close", lambda pw_, browser_: None)

        rep = GU.upload_grade(
            storage="x", course_id="c1", class_id="k1", cpi="0", work_id="w1",
            student="学生甲", comment="批语", comment_images=[], total_score=100,
            send=True, force=True, workspace=None)
        assert rep["ok"] is True, rep.get("error")
        assert rep["submitResult"]["ok"] is True
        # 提交按钮是 DIV
        assert (rep["submitResult"].get("tag") or "").upper() == "DIV"
        assert mock.state["saved"] is True and mock.state["score"] == "100"
        assert rep["afterSubmit"]["ok"] is True
        browser.close()
    finally:
        pw.stop()
        mock.close()

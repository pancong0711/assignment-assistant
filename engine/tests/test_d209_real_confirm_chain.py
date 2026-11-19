"""D209：真实学习通的提交确认链（真机实测确认）。

真实流程（从页面 JS 源码确认）：

    markAction(1) ──(500ms)──> pigai(1)
        ├─ 校验分数/批语（失败 toast 并 return）
        └─ showConfirmV1(markTip, "Continue", "Cancel", "checkPass()")
              └─ 点「保存并继续」(onclick=checkPass()) → checkPass()
                    ├─ 分数达标 → comfirmMark()
                    └─ comfirmMark() → formSubmit() → 真正保存

旧实现对确认按钮只匹配 `#popok` 与「确定/确认/继续」，
点不到 `保存并继续(checkPass())` → 提交被静默取消（平台状态一直不变）。

另：`pigai()` 首行有 `if (window.itemScoreCheck) {...; return;}` 守卫，
残留为真会让提交静默失败。
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest

pytest.importorskip("playwright.sync_api")

MARK_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Mark</title></head><body>
<textarea name="comment" id="comment"></textarea>
<input id="tmpscore" value="">
<input id="score" value="">
<div class="btnBlue fr fs14" onclick="markAction(1)">提交</div>

<div id="confirmPop2" style="display:none">
  <a class="jb_btn jb_btn_92 fr fs14 confirmHref" onclick="checkPass()">保存并继续</a>
  <a class="btnBlue btn_92_cancel fr fs14" onclick="hidePop()">Cancel</a>
</div>
<div id="confirmPop3" style="display:none">
  <a class="jb_btn jb_btn_92 fr fs14 confirm" onclick="comfirmMark()">提交</a>
</div>

<script>
window.itemScoreCheck = false;
function markAction(n){ setTimeout(() => pigai(n), 200); }
function pigai(n){
  if (window.itemScoreCheck) { window.itemScoreCheck = false; return; }
  const s = (document.getElementById('tmpscore').value || '').trim();
  document.getElementById('score').value = s;
  if (!s) { toast('Please enter score'); return; }
  document.getElementById('confirmPop2').style.display = 'block';
}
function checkPass(){
  document.getElementById('confirmPop2').style.display = 'none';
  document.getElementById('confirmPop3').style.display = 'block';
}
function comfirmMark(){
  document.getElementById('confirmPop3').style.display = 'none';
  fetch('/save', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({score: document.getElementById('score').value})})
    .then(() => { location.href = '/list'; });
}
function hidePop(){ document.getElementById('confirmPop2').style.display = 'none'; }
function toast(m){
  const d = document.createElement('div');
  d.className = 'toast'; d.textContent = m;
  document.body.appendChild(d);
  setTimeout(() => d.remove(), 4000);
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
                    score = outer.state["score"] if outer.state["saved"] else ""
                    status = "Completed" if outer.state["saved"] else "To be reviewed"
                    self._send(LIST_PAGE.replace("__SCORE__", score)
                               .replace("__STATUS__", status))
                else:
                    self._send("ok")

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(n) or b"{}")
                outer.state.update({"saved": True,
                                    "score": str(data.get("score") or "")})
                self._send(json.dumps({"ok": True}), "application/json")

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


@pytest.fixture()
def harness(monkeypatch):
    from playwright.sync_api import sync_playwright
    from assist.xxt.session import _launch
    from assist.xxt import grade_upload as GU
    import assist.xxt.work as W

    mock = _Srv()
    pw = sync_playwright().start()
    try:
        browser = _launch(pw, headless=True)
    except Exception as exc:  # pragma: no cover
        pw.stop()
        mock.close()
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
    yield mock, page
    try:
        browser.close()
    finally:
        pw.stop()
        mock.close()


def _upload(**kw):
    from assist.xxt import grade_upload as GU
    return GU.upload_grade(
        storage="x", course_id="c1", class_id="k1", cpi="0", work_id="w1",
        student="学生甲", comment="批语", comment_images=[], total_score=88,
        send=True, force=True, workspace=None, **kw)


def test_confirm_chain_clicks_checkpass_then_confirm(harness):
    """核心：必须点中「保存并继续(checkPass())」，再点「提交」，最终保存成功。"""
    mock, _page = harness
    rep = _upload()
    assert rep["ok"] is True, rep.get("error")
    steps = (rep["submitResult"].get("confirmPopup") or {}).get("steps") or []
    hows = [s.get("how") for s in steps]
    assert any(h and h.startswith("onclick:checkPass") for h in hows), hows
    assert mock.state["saved"] is True
    assert mock.state["score"] == "88"


def test_cancel_button_never_clicked(harness):
    mock, _page = harness
    rep = _upload()
    steps = (rep["submitResult"].get("confirmPopup") or {}).get("steps") or []
    assert all("Cancel" not in str(s.get("text") or "") for s in steps)
    assert mock.state["saved"] is True


def test_verify_accepts_completed_status(harness):
    mock, _page = harness
    rep = _upload()
    assert rep["afterSubmit"]["ok"] is True
    assert rep["afterSubmit"]["status"] == "Completed"
    assert rep["afterSubmit"]["score"] == "88"


def test_source_contract_for_d209():
    root = Path(__file__).resolve().parents[1]
    src = (root / "src/assist/xxt/marking.py").read_text(encoding="utf-8")
    assert "def click_confirm_chain(" in src
    assert "checkPass|comfirmMark|formSubmit|confirmPiyueWork" in src
    assert "itemScoreCheck" in src
    assert "toasts" in src
    assert "confirmPop2" in src

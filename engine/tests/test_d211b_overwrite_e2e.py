"""D211：覆盖模式的端到端验证——清除旧报告图，只保留新图。

现场：不覆盖时 UEditor 会把新报告图**追加**到旧图后面，
导致学生批语里堆两张报告图。覆盖模式应先清空批语框再插图。
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest

pytest.importorskip("playwright.sync_api")

OLD_IMG = '<img src="old-report.png">'

MARK_PAGE = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<div class="kark_comment_edit">
  <div class="edui-editor" id="edui1">
    <div class="edui-for-insertimage"><div class="edui-button-body" id="btnimg">图片</div></div>
  </div>
  <textarea name="comment" id="comment">__OLD__</textarea>
</div>
<input id="tmpscore" value="">
<a class="btnBlue" onclick="markAction(1)">提交</a>
<div id="confirmPop2" style="display:none">
  <a onclick="checkPass()">保存并继续</a>
</div>
<div id="confirmPop3" style="display:none">
  <a onclick="comfirmMark()">提交</a>
</div>
<script>
function markAction(n){ setTimeout(() => pigai(n), 150); }
function pigai(n){
  if (!(document.getElementById('tmpscore').value || '').trim()) return;
  document.getElementById('confirmPop2').style.display='block';
}
function checkPass(){ document.getElementById('confirmPop2').style.display='none';
                      document.getElementById('confirmPop3').style.display='block'; }
function comfirmMark(){
  document.getElementById('confirmPop3').style.display='none';
  fetch('/save', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({score: document.getElementById('tmpscore').value,
      comment: document.querySelector('textarea[name=comment]').value})})
    .then(() => { location.href='/list'; });
}
document.getElementById('btnimg').addEventListener('click', () => {
  const f = document.createElement('iframe');
  f.src = '/ueditor/dialogs/image/image.html';
  document.body.appendChild(f);
});
</script></body></html>"""

IMG_DIALOG = """<!doctype html><html><body><input type="file" id="f">
<script>
document.getElementById('f').addEventListener('change', (e) => {
  const file = e.target.files[0]; if (!file) return;
  const ta = window.parent.document.querySelector('textarea[name=comment]');
  ta.value = (ta.value || '') + '<img src="uploaded/' + file.name + '">';
});
</script></body></html>"""

LIST_PAGE = """<!doctype html><html><body>
<ul class="dataBody_td">
  <li class="taskBody_name"><div class="py_name">学生甲</div></li>
  <li><a class="cz_py" data="https://x/review-work?workAnswerId=101">Open</a></li>
  <li><input class="scoreInput" value="__SCORE__"></li>
  <li>__STATUS__</li>
</ul></body></html>"""


class _Srv:
    def __init__(self):
        self.state = {"saved": False, "score": "", "comment": OLD_IMG}
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
                    self._send(MARK_PAGE.replace("__OLD__", OLD_IMG))
                elif u.path == "/list":
                    score = outer.state["score"] if outer.state["saved"] else ""
                    status = "Completed" if outer.state["saved"] else "To be reviewed"
                    self._send(LIST_PAGE.replace("__SCORE__", score)
                               .replace("__STATUS__", status))
                elif "dialogs/image" in u.path:
                    self._send(IMG_DIALOG)
                else:
                    self._send("ok")

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(n) or b"{}")
                outer.state.update({"saved": True,
                                    "score": str(data.get("score") or ""),
                                    "comment": str(data.get("comment") or "")})
                self._send(json.dumps({"ok": True}), "application/json")

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from playwright.sync_api import sync_playwright
    from assist.xxt.session import _launch
    from assist.xxt import grade_upload as GU
    import assist.xxt.work as W

    mock = _Srv()
    pw = sync_playwright().start()
    try:
        browser = _launch(pw, headless=True)
    except Exception as exc:  # pragma: no cover
        pw.stop(); mock.close()
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
    png = tmp_path / "new-report.png"
    png.write_bytes(PNG)
    yield mock, png
    try:
        browser.close()
    finally:
        pw.stop()
        mock.close()


def _run(GU, mock, png, **kw):
    return GU.upload_grade(
        storage="x", course_id="c1", class_id="k1", cpi="0", work_id="w1",
        student="学生甲", comment="", comment_images=[str(png)], total_score=88,
        send=True, force=True, workspace=None, **kw)


def test_overwrite_removes_old_report_image(env, monkeypatch):
    """核心：覆盖模式后批语里只应有新报告图，旧图被清除。"""
    from assist.xxt import grade_upload as GU
    mock, png = env
    rep = _run(GU, mock, png, overwrite=True)
    assert rep["ok"] is True, rep.get("error")
    imgs = mock.state["comment"].count("<img")
    assert imgs == 1, mock.state["comment"]      # 旧图已清除，只剩新图
    assert "new-report.png" in mock.state["comment"]
    assert "old-report.png" not in mock.state["comment"]
    assert mock.state["score"] == "88"
    assert rep.get("overwrite") is True


def test_without_overwrite_keeps_old_image(env, monkeypatch):
    """对照：不覆盖时旧图会保留（这正是现场“两张报告图”的原因）。"""
    from assist.xxt import grade_upload as GU
    mock, png = env
    rep = _run(GU, mock, png)
    assert rep["ok"] is True, rep.get("error")
    assert mock.state["comment"].count("<img") == 2
    assert "old-report.png" in mock.state["comment"]

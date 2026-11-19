"""D205：用**本地仿真学习通批阅页**跑真实上传代码路径（不需要真实会话）。

覆盖真实的页面交互代码（`upload_grade` / `marking`），仿真点与真实页面一致：
- `textarea[name="comment"]` + `.kark_comment_edit` + `.edui-editor`
- `.edui-for-insertimage` 点击 → iframe（URL 含 dialogs/image）+ `input[type=file]`
- `#tmpscore` 总分、`.inputBranch.questionScore` 每题分
- `a[onclick="markAction(1)"]` 提交 → 确认层 → 确认按钮（`#popok` 或 `confirmPiyueWork()`）
- 提交后 `/list` 页面用 `ul.dataBody_td` + `div.py_name` + `a.cz_py`（供核验解析）

边界：不连真实学习通、不用真实学生数据；真实平台的 UEditor 细节仍以线上为准。
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest

pytest.importorskip("playwright.sync_api")

MARK_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>批阅</title></head><body>
<div class="kark_comment_edit">
  <div class="edui-editor" id="edui1">
    <div class="edui-for-insertimage"><div class="edui-button-body" id="btnimg">图片</div></div>
  </div>
  <textarea name="comment" id="comment"></textarea>
</div>
<div>总分：<input id="tmpscore" value=""></div>
<div class="inputBranch"><input class="questionScore" value=""></div>
<a href="javascript:;" onclick="markAction(1)">提交</a>
<div id="tabindexWorkpop" style="display:none">
  <div>确认提交本次批阅？</div>
  __CONFIRM__
</div>
<script>
window.__confirmEnabled = true;
function markAction(n){ document.getElementById('tabindexWorkpop').style.display='block'; }
function confirmPiyueWork(){
  if (!window.__confirmEnabled) { return false; }
  fetch('/save', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({score: document.getElementById('tmpscore').value,
                          comment: document.querySelector('textarea[name=comment]').value})})
    .then(() => { location.href = '/list'; });
  return true;
}
document.getElementById('btnimg').addEventListener('click', () => {
  const f = document.createElement('iframe');
  f.src = '/ueditor/dialogs/image/image.html';
  f.style.cssText = 'width:300px;height:120px';
  document.body.appendChild(f);
});
if (!window.confirm) {
  window.confirm = function(){ return true; };
}
</script></body></html>"""

CONFIRM_POPOK = '<a id="popok" href="javascript:;" onclick="confirmPiyueWork()">确定</a>'
CONFIRM_ONLY_FUNC = '<a href="javascript:;" onclick="confirmPiyueWork()">确定</a>'

IMG_DIALOG = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<input type="file" id="f">
<script>
document.getElementById('f').addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const ta = window.parent.document.querySelector('textarea[name=comment]');
  ta.value = (ta.value || '') + '<img src="uploaded/' + file.name + '">';
});
</script></body></html>"""

LIST_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>批阅列表</title></head><body>
<ul class="dataBody_td">
  <li class="taskBody_name"><div class="py_name">学生甲</div></li>
  <li><a class="cz_py" data="https://x/review-work?workAnswerId=101">批阅</a></li>
  <li><input class="scoreInput" value="__SCORE__"></li>
  <li>__STATUS__</li>
</ul></body></html>"""

PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082")


class _Mock:
    def __init__(self, confirm_html: str):
        self.state = {"saved": False, "score": "", "comment": ""}
        self.confirm_html = confirm_html
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, body: str, ctype="text/html; charset=utf-8"):
                b = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                u = urlparse(self.path)
                if u.path == "/mark":
                    # 每次打开批阅页代表一次新的提交尝试
                    outer.state["saved"] = False
                    self._send(MARK_PAGE.replace("__CONFIRM__", outer.confirm_html))
                elif u.path == "/list":
                    score = outer.state["score"] if outer.state["saved"] else ""
                    status = "已批阅" if outer.state["saved"] else "待批阅"
                    self._send(LIST_PAGE.replace("__SCORE__", score)
                               .replace("__STATUS__", status))
                elif "dialogs/image" in u.path:
                    self._send(IMG_DIALOG)
                else:
                    self._send("ok")

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(n) or b"{}")
                if urlparse(self.path).path == "/save":
                    outer.state.update({"saved": True,
                                        "score": str(data.get("score") or ""),
                                        "comment": str(data.get("comment") or "")})
                    self._send(json.dumps({"ok": True}), "application/json")
                else:
                    self._send("{}")

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


@pytest.fixture()
def browser_page():
    from playwright.sync_api import sync_playwright
    from assist.xxt.session import _launch
    pw = sync_playwright().start()
    try:
        b = _launch(pw, headless=True)
    except Exception as exc:  # pragma: no cover - 环境无浏览器时跳过
        pw.stop()
        pytest.skip(f"浏览器不可用：{str(exc)[:120]}")
    yield pw, b
    try:
        b.close()
    finally:
        pw.stop()


def _run_upload(monkeypatch, page, mock, tmp_path: Path, open_mark=None, **kwargs):
    """把网络入口替换成本地仿真页，其余走真实 upload_grade 代码。"""
    from assist.xxt import grade_upload as GU
    import assist.xxt.work as W

    monkeypatch.setattr(W, "validate_work_target", lambda *a, **k: "")
    monkeypatch.setattr(GU, "resolve_work_id_on_page", lambda *a, **k: "w1")
    default_open = lambda pg, c, k, w, wa, **kw: (  # noqa: E731
        pg.goto(f"{mock.base}/mark", wait_until="domcontentloaded"), pg.url)[-1]
    monkeypatch.setattr(GU, "open_mark_page", open_mark or default_open)
    monkeypatch.setattr(GU, "_open_mark_list", lambda pg, c, k, w: (
        pg.goto(f"{mock.base}/list", wait_until="domcontentloaded"), pg.url)[-1])
    monkeypatch.setattr(GU, "_shot", lambda pg, tag: "")
    monkeypatch.setattr(GU, "_write_receipt", lambda kind, payload: "")
    monkeypatch.setattr(GU, "_start_browser", lambda storage: (None, None, page, None))
    monkeypatch.setattr(GU, "_close", lambda pw, browser: None)

    png = tmp_path / "report.png"
    png.write_bytes(PNG_BYTES)
    kwargs.setdefault("comment_images", [str(png)])
    kwargs.setdefault("total_score", 90)
    kwargs.setdefault("comment", "人工批语：思路清晰")
    kwargs.setdefault("send", True)
    kwargs.setdefault("force", True)
    return GU.upload_grade(
        storage="ignored", course_id="c1", class_id="k1", cpi="0", work_id="w1",
        student="学生甲", workspace=None, **kwargs)


def test_e2e_upload_image_and_score_then_verified(browser_page, monkeypatch, tmp_path):
    """核心：插图 + 打分 + 提交 + 提交后核验通过。"""
    pw, browser = browser_page
    mock = _Mock(CONFIRM_POPOK)
    page = browser.new_page()
    try:
        rep = _run_upload(monkeypatch, page, mock, tmp_path)
        assert rep["ok"] is True, rep.get("error")
        assert rep["status"] == "submitted"
        # 图片确实插入到批语
        assert rep["commentImages"] and rep["commentImages"][0]["ok"] is True
        assert "<img" in mock.state["comment"]
        # 分数写入并提交
        assert mock.state["score"] == "90"
        # 提交后核验通过（这是 D202 的关键）
        assert rep["afterSubmit"]["ok"] is True
        assert rep["afterSubmit"]["status"] == "已批阅"
        assert rep["afterSubmit"]["score"] == "90"
    finally:
        page.close()
        mock.close()


def test_e2e_confirm_button_without_popok_id(browser_page, monkeypatch, tmp_path):
    """D203 回归：确认按钮只有 confirmPiyueWork()、没有 #popok 时也必须成功。"""
    pw, browser = browser_page
    mock = _Mock(CONFIRM_ONLY_FUNC)
    page = browser.new_page()
    try:
        rep = _run_upload(monkeypatch, page, mock, tmp_path)
        assert rep["ok"] is True, rep.get("error")
        assert mock.state["saved"] is True
        # D209：确认处理改为“确认链”，结果结构从 clicks 变为 steps
        steps = (rep["submitResult"].get("confirmPopup") or {}).get("steps") or []
        assert steps and steps[0].get("how", "").startswith("onclick:confirmPiyueWork"), steps
    finally:
        page.close()
        mock.close()


def test_e2e_unverified_when_confirm_disabled_then_retry_succeeds(
        browser_page, monkeypatch, tmp_path):
    """D205 回归：第一次提交未保存 → 重试必须重新打开批阅页并重填，最终成功。"""
    pw, browser = browser_page
    mock = _Mock(CONFIRM_POPOK)
    page = browser.new_page()
    try:
        state = {"n": 0}

        def open_mark(pg, c, k, w, wa, **kw):
            state["n"] += 1
            pg.goto(f"{mock.base}/mark", wait_until="domcontentloaded")
            if state["n"] == 1:
                # 第一次尝试：让确认按钮失效（模拟“确认没点中”→ 平台未保存）
                pg.evaluate("() => { window.__confirmEnabled = false; }")
            return pg.url

        rep = _run_upload(monkeypatch, page, mock, tmp_path, open_mark=open_mark)
        assert state["n"] >= 2, "未在失败后重新打开批阅页重试"
        assert rep["ok"] is True, rep.get("error")
        assert len(rep["submitAttempts"]) == 2
        assert mock.state["saved"] is True
    finally:
        page.close()
        mock.close()


def test_e2e_session_expired_detected(browser_page):
    """D204 回归：批阅页变成登录页时必须识别为会话过期。"""
    pw, browser = browser_page
    page = browser.new_page()
    try:
        from assist.xxt import marking as MK
        page.set_content('<html><body><input type="password"><div>用户登录</div></body></html>')
        sub = MK.submit(page)
        assert sub["ok"] is False and sub["status"] == "session-expired"
        assert "重新扫码登录" in sub["error"]
    finally:
        page.close()

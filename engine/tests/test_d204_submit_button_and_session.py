"""D204：提交时报「未找到提交按钮」——先分辨“是不是会话过期/页面不对”。

现场：`提交失败：{'ok': False, 'error': "未找到提交按钮：{'ok': False,
'reason': 'no-markAction(1)'}"}；确认弹窗 0 个`。
教师提示“学习通应该已经过期”。会话过期会跳 passport 登录页，
页面上当然没有 `markAction(1)`；旧实现只会说“没找到按钮”，把人引向错误的排查方向。

同时：平台改版/不同入口时提交按钮可能不再是 `markAction(1)`，需要兜底识别。
"""
from __future__ import annotations

from pathlib import Path

from assist.xxt import marking as MK


class _Page:
    def __init__(self, state=None, click_results=None):
        self._state = state or {}
        self._clicks = list(click_results or [])
        self.calls = []
        self.url = "https://mooc1.chaoxing.com/mark"

    def evaluate(self, js, *args):
        if "hasCommentBox" in js and "loginRedirect" in js:
            self.calls.append("state")
            return self._state
        if "no-submit-candidate" in js:      # fallback
            self.calls.append("fallback")
            return self._clicks.pop(0) if self._clicks else {
                "ok": False, "reason": "no-submit-candidate", "tried": []}
        if "markAction(1)" in js and "no-markAction(1)" in js:
            self.calls.append("primary")
            return self._clicks.pop(0) if self._clicks else {
                "ok": False, "reason": "no-markAction(1)"}
        if "window.__assistDialogs" in js:
            return []
        if "hasConfirm" in js:
            return None
        if "no-visible-confirm" in js:
            return {"ok": False, "reason": "no-visible-confirm"}
        if "submitCandidates" in js or "Array.from" in js:
            return []
        return None

    def wait_for_timeout(self, ms):
        return None


def _mark_page(**kw):
    base = {"url": "https://mooc1.chaoxing.com/mark", "title": "批阅",
            "loginRedirect": False, "hasPassword": False,
            "hasCommentBox": True, "hasScoreInput": True, "candidates": []}
    base.update(kw)
    return base


def test_login_redirect_reports_session_expired():
    """核心回归：跳到登录页时必须报“会话已失效”，而不是“未找到提交按钮”。"""
    page = _Page(state=_mark_page(url="https://passport2.chaoxing.com/login",
                                  loginRedirect=True, hasPassword=True,
                                  hasCommentBox=False, hasScoreInput=False))
    rep = MK.submit(page)
    assert rep["ok"] is False
    assert rep["status"] == "session-expired"
    assert "重新扫码登录" in rep["error"]


def test_password_form_without_comment_box_is_session_expired():
    page = _Page(state=_mark_page(hasPassword=True, hasCommentBox=False))
    rep = MK.submit(page)
    assert rep["status"] == "session-expired"


def test_no_submit_button_reports_page_diagnostics():
    """页面正常但没有 markAction(1)：兜底也失败时，必须带回页面诊断。"""
    page = _Page(state=_mark_page(candidates=[{"text": "保存", "onclick": "saveX()"}]),
                 click_results=[{"ok": False, "reason": "no-markAction(1)"},
                                {"ok": False, "reason": "no-submit-candidate",
                                 "tried": [{"text": "保存", "rank": 60}]}])
    rep = MK.submit(page)
    assert rep["ok"] is False
    assert rep["status"] == "no-submit-button"
    assert rep["page"]["url"].endswith("/mark")
    assert rep["candidates"]


def test_fallback_clicks_submit_by_text_when_markaction_missing():
    """平台改版没有 markAction(1) 时，按文案/onclick 兜底点击。"""
    page = _Page(state=_mark_page(),
                 click_results=[{"ok": False, "reason": "no-markAction(1)"},
                                {"ok": True, "how": "fallback", "text": "提交",
                                 "tried": [{"text": "提交", "rank": 70}]}])
    rep = MK.submit(page)
    assert rep["ok"] is True
    assert rep["how"] == "fallback"


def test_page_state_helpers_present():
    src = (Path(__file__).resolve().parents[1] / "src/assist/xxt/marking.py").read_text(
        encoding="utf-8")
    assert "def page_state(" in src
    assert "hasCommentBox" in src and "hasScoreInput" in src
    assert "confirmPiyueWork" in src          # D203 的确认入口仍保留
    assert "no-submit-candidate" in src       # D204 兜底策略
    assert "session-expired" in src


def test_upload_grade_handles_session_expired_before_and_during_submit():
    src = (Path(__file__).resolve().parents[1] / "src/assist/xxt/grade_upload.py").read_text(
        encoding="utf-8")
    # 打开批阅页后先判页面
    assert 'result["pageState"]' in src
    assert "not-mark-page" in src
    # 提交阶段遇到会话过期直接收尾并提示重新扫码
    assert 'session-expired' in src
    assert "请先点「🔁 重新扫码登录」" in src
    assert "请先点「🔁 重新扫码登录」" in src

"""D203：提交后平台仍停在「待批阅」——确认弹窗没点中。

现场：上传返回「提交后核验失败：提交后平台状态仍为「待批阅」」，学习通确实未批阅。

根因：点 `markAction(1)` 后平台会弹确认层，但确认按钮**不是** `#popok/#popokTwice`：
新版学习通调用 `confirmPiyueWork()`（或只是文案“确定”的按钮）。
旧 `handle_confirmation_dialog()` 只认 `#popok, #popokTwice` → 点不到确认 →
提交被取消 → 状态一直「待批阅」。
"""
from __future__ import annotations

from pathlib import Path

from assist.xxt import marking as MK


class _Page:
    """替身页：按脚本依次返回弹窗/点击结果，并记录 evaluate 调用。"""

    def __init__(self, popups, clicks=None):
        self._popups = list(popups)
        self._clicks = list(clicks or [])
        self.calls: list[str] = []
        self.url = "https://mooc1.chaoxing.com/mark"

    def evaluate(self, js, *args):
        if "window.__assistDialogs" in js:
            return []
        if "hasConfirm" in js:            # _JS_FIND_POPUP（先判，避免与下面混淆）
            self.calls.append("popup")
            return self._popups.pop(0) if self._popups else None
        if "no-visible-confirm" in js:    # _JS_CLICK_POPUP_CONFIRM
            self.calls.append("click")
            return self._clicks.pop(0) if self._clicks else {"ok": False,
                                                             "reason": "no-visible-confirm"}
        return None

    def wait_for_timeout(self, ms):
        return None


def test_confirmation_clicks_confirm_piyue_work_button():
    """核心回归：弹窗确认按钮走 confirmPiyueWork 时也必须点到。"""
    page = _Page(popups=[{"id": "#tabindexWorkpop", "text": "确认提交？"}],
                 clicks=[{"ok": True, "how": "onclick:confirmPiyueWork", "text": "确定"}])
    rep = MK.handle_confirmation_dialog(page, timeout_s=2)
    assert rep["ok"] is True
    assert rep["clicks"][0]["clicked"]["how"] == "onclick:confirmPiyueWork"
    assert len(rep["popups"]) == 1


def test_confirmation_handles_multiple_layers():
    """可能有多层确认（先“确定提交”，再“是否继续”）。"""
    page = _Page(popups=[{"id": "#tabindexWorkpop"}, {"id": "#tabindexWorkpopTwice"}],
                 clicks=[{"ok": True, "how": "text:确定"},
                         {"ok": True, "how": "#popok, #popokTwice"}])
    rep = MK.handle_confirmation_dialog(page, timeout_s=2)
    assert rep["ok"] is True
    assert len(rep["clicks"]) == 2


def test_confirmation_no_popup_is_ok():
    page = _Page(popups=[])
    rep = MK.handle_confirmation_dialog(page, timeout_s=0.5)
    assert rep["ok"] is True and rep["clicks"] == []


def test_confirmation_reports_unclickable_popup():
    """弹窗存在但点不到确认 → 必须把“点不到”暴露出来，而不是静默返回成功。"""
    page = _Page(popups=[{"id": ".layui-layer"}],
                 clicks=[{"ok": False, "reason": "no-visible-confirm"}])
    rep = MK.handle_confirmation_dialog(page, timeout_s=1)
    assert rep["clicks"][0]["clicked"]["ok"] is False


def test_submit_includes_diagnostics():
    """submit() 必须带 confirmPopup/dialogs/submitCandidates 便于定位。"""
    src = (Path(__file__).resolve().parents[1] / "src/assist/xxt/marking.py").read_text(
        encoding="utf-8")
    body = src.split("def submit(page")[1]
    assert "confirmPopup" in body
    assert "__assistDialogs" in body
    assert "submitCandidates" in body


def test_find_popup_and_click_js_cover_new_platform():
    src = (Path(__file__).resolve().parents[1] / "src/assist/xxt/marking.py").read_text(
        encoding="utf-8")
    assert "confirmPiyueWork" in src, '未覆盖新版确认入口 confirmPiyueWork()'
    assert "no-visible-confirm" in src
    assert "text:确定" in src or "'确定'" in src or "确定提交" in src


def test_upload_grade_retries_once_when_unverified():
    src = (Path(__file__).resolve().parents[1] / "src/assist/xxt/grade_upload.py").read_text(
        encoding="utf-8")
    body = src.split("        if send:")[1].split('        result["receipt"]')[0]
    assert "for attempt in (1, 2)" in body, '未在“点了但没生效”时重试一次'
    assert "submitAttempts" in body, '未记录提交尝试明细'
    assert "confirmPiyueWork" in body, '错误信息未提示新版确认入口'

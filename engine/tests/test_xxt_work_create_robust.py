"""D83 修复：create_work 健壮点击（_click_first_visible）单测（无浏览器）。

背景：真机报「element is not visible」重试超时 —— `.first` 按文档序取到
同名隐藏元素。回归保障：可见过滤命中、多定位器回退、JS 兜底、全败报错带步骤名。
"""

import pytest

from assist.xxt.work import _click_first_visible


class _StubLocator:
    def __init__(self, name: str, visible_count: int = 0, click_raises: bool = False):
        self.name, self.visible_count, self.click_raises = name, visible_count, click_raises
        self.clicked = False

    def filter(self, visible=None):  # noqa: ARG002
        return self

    @property
    def first(self):
        return self

    def wait_for(self, state=None, timeout=None):  # noqa: ARG002
        if self.visible_count == 0:
            raise TimeoutError(f"{self.name}: waiting for element to be visible")
        return True

    def click(self, timeout=None):  # noqa: ARG002
        if self.click_raises:
            raise RuntimeError(f"{self.name}: click intercepted")
        self.clicked = True


class _StubPage:
    def __init__(self, js_result: bool = False):
        self.js_result = js_result
        self.js_called = False

    def evaluate(self, _expr, _arg=None):
        self.js_called = True
        return self.js_result


def test_visible_filter_hits_first_visible():
    hidden = _StubLocator("hidden-template", visible_count=0)
    visible = _StubLocator("real-btn", visible_count=1)
    page = _StubPage()
    _click_first_visible(page, [hidden, visible], "测试步骤")
    assert visible.clicked and not hidden.clicked


def test_js_fallback_when_all_locators_fail():
    page = _StubPage(js_result=True)
    _click_first_visible(page, [_StubLocator("a"), _StubLocator("b")], "测试步骤",
                         js_text="简答题")
    assert page.js_called


def test_all_fail_raises_with_step_name():
    page = _StubPage(js_result=False)
    with pytest.raises(RuntimeError) as ei:
        _click_first_visible(page, [_StubLocator("a"), _StubLocator("b")], "选择题型（简答题）",
                             js_text="简答题")
    assert "选择题型（简答题）" in str(ei.value)
    assert "TimeoutError" in str(ei.value)  # 携带各定位器失败原因


def test_later_locator_rescues_click_intercept():
    bad = _StubLocator("overlay-covered", visible_count=1, click_raises=True)
    good = _StubLocator("real-btn", visible_count=1)
    _click_first_visible(_StubPage(), [bad, good], "点击「保存」")
    assert good.clicked

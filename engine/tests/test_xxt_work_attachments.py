"""D83 修复：作业编辑器附件上传路径（真机 DOM 校准的回归）。

真机事实（2026-10-15 侦察，.scratch/xxt-pages/）：
- 附件按钮 class = .edui-for-attachment_new（通知页才是 .edui-for-attachment）；
- 点开后是弹窗 iframe .../dialogs/attachment_new/attachment.html，webuploader 的
  file input 在 iframe 内（主页面无任何 input[type=file]）；
- PDF/doc → <div class="editor-iframe">，图片 → <img class="ans-ued-img">。
"""

from pathlib import Path

import pytest

from assist.xxt.work import (_ATTACH_MARKERS, _attachment_dialog_frame,
                             _open_work_attachment_dialog, _upload_work_attachments,
                             _work_attachment_count)


class _StubEvalPage:
    def __init__(self, html: str):
        self.html = html

    def evaluate(self, *_a, **_k):
        return self.html


def test_work_attachment_count_recognizes_image_and_iframe():
    """图片(ans-ued-img)与附件(editor-iframe/attach-iframe)都要计数（旧实现漏了图片）。"""
    page = _StubEvalPage(
        '<p>题干</p><img class="ans-ued-img" src="x">'
        '<div class="editor-iframe"><iframe class="attach-iframe" src="y"></iframe></div>')
    assert _work_attachment_count(page) == 3  # ans-ued-img + editor-iframe + attach-iframe


def test_work_attachment_count_zero_for_plain_stem():
    assert _work_attachment_count(_StubEvalPage('<p>只有文字</p>')) == 0


def test_work_attachment_count_returns_minus_one_on_error():
    class Boom:
        def evaluate(self, *_a, **_k):
            raise RuntimeError("UE not defined")
    assert _work_attachment_count(Boom()) == -1


class _StubFrame:
    def __init__(self, url):
        self.url = url


class _StubClickLocator:
    def __init__(self, count=1, click_raises=False):
        self._count, self._raises, self.clicked = count, click_raises, False

    @property
    def first(self):
        return self

    def count(self):
        return self._count

    def scroll_into_view_if_needed(self, timeout=None):  # noqa: ARG002
        pass

    def click(self, timeout=None):  # noqa: ARG002
        if self._raises:
            raise RuntimeError("not visible")
        self.clicked = True


class _StubPage:
    def __init__(self, frames, locators):
        self.frames = frames
        self._locators = locators  # spec -> locator

    def locator(self, spec):
        return self._locators.get(spec, _StubClickLocator(count=0))

    def wait_for_timeout(self, _ms):
        pass


def test_attachment_dialog_frame_found_by_url():
    fr = _StubFrame("https://mooc2-ans.chaoxing.com/x/dialogs/attachment_new/attachment.html?v=1")
    page = _StubPage([_StubFrame("https://x/other.html"), fr], {})
    assert _attachment_dialog_frame(page, timeout_s=0) is fr


def test_attachment_dialog_frame_missing_returns_none():
    page = _StubPage([_StubFrame("https://x/other.html")], {})
    assert _attachment_dialog_frame(page, timeout_s=0) is None


def test_open_dialog_prefers_attachment_new_then_falls_back():
    new_btn = _StubClickLocator()
    old_btn = _StubClickLocator()
    page = _StubPage([], {".edui-for-attachment_new": new_btn, ".edui-for-attachment": old_btn})
    assert _open_work_attachment_dialog(page) is True
    assert new_btn.clicked and not old_btn.clicked

    new_missing = _StubClickLocator(count=0)
    old2 = _StubClickLocator()
    page2 = _StubPage([], {".edui-for-attachment_new": new_missing, ".edui-for-attachment": old2})
    assert _open_work_attachment_dialog(page2) is True
    assert old2.clicked

    page3 = _StubPage([], {})  # 两种都没有
    assert _open_work_attachment_dialog(page3) is False


class _StubFileInput:
    def __init__(self, sink):
        self.sink = sink

    @property
    def first(self):
        return self

    def wait_for(self, state=None, timeout=None):  # noqa: ARG002
        return True

    def set_input_files(self, path):
        self.sink.append(Path(path).name)


class _StubUploadFrame(_StubFrame):
    def __init__(self, url, sink, fail=False):
        super().__init__(url)
        self.sink, self.fail = sink, fail

    def locator(self, _spec):
        if self.fail:
            raise RuntimeError("input detached")
        return _StubFileInput(self.sink)


def test_upload_work_attachments_inserts_each_file(tmp_path):
    """弹窗 iframe 内 set_input_files；正文标记增长即成功（图片/PDF 两种标记都认）。"""
    sink: list[str] = []
    state = {"html": "<p>题干</p>"}
    frame = _StubUploadFrame(
        "https://mooc2-ans.chaoxing.com/x/dialogs/attachment_new/attachment.html", sink)

    class Page(_StubPage):
        def evaluate(self, *_a, **_k):
            # 每次上报后模拟正文被插入一个附件标记
            # 每个已上传文件插入一个标记（模拟真实正文增长）
            return state["html"] + '<div class="editor-iframe"></div>' * len(sink)

    page = Page([frame], {".edui-for-attachment_new": _StubClickLocator()})
    files = [tmp_path / "a.pdf", tmp_path / "b.png"]
    for f in files:
        f.write_bytes(b"x")
    out = _upload_work_attachments(page, files)
    assert out == ["a.pdf", "b.png"]
    assert sink == ["a.pdf", "b.png"]


def test_upload_work_attachments_raises_when_input_unavailable(tmp_path, monkeypatch):
    # 弹窗永远不出现 → 走回退路径并快速失败（不真等 6s 弹窗超时）
    monkeypatch.setattr("assist.xxt.work._attachment_dialog_frame", lambda *a, **k: None)

    class Page(_StubPage):
        def evaluate(self, *_a, **_k):
            return "<p>题干</p>"  # 标记永不增长

    page = Page([], {".edui-for-attachment_new": _StubClickLocator()})
    f = tmp_path / "a.pdf"; f.write_bytes(b"x")
    with pytest.raises(RuntimeError) as ei:
        _upload_work_attachments(page, [f])
    assert "附件上传入口不可用" in str(ei.value) or "附件未插入" in str(ei.value)

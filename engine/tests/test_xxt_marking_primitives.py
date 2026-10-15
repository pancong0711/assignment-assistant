"""D84 §1：批阅回传原语的纯逻辑/stub 回归（无浏览器）。"""

from pathlib import Path

import pytest

from assist.xxt.marking import (IMAGE_DIALOG_HINTS, _image_dialog_frame,
                                normalize_comment_html, parse_question_scores,
                                read_back, set_comment_html)


def test_normalize_comment_html_plain_text_to_paragraphs():
    assert normalize_comment_html("第一行\n第二行\n\n第三行") == \
        "<p>第一行</p><p>第二行</p><p>第三行</p>"


def test_normalize_comment_html_keeps_existing_html():
    html = '<p>已有<b>标签</b></p>'
    assert normalize_comment_html(html) == html


def test_normalize_comment_html_empty():
    assert normalize_comment_html("") == ""
    assert normalize_comment_html(None) == ""


def test_parse_question_scores_variants():
    assert parse_question_scores("10,20,30") == [10.0, 20.0, 30.0]
    assert parse_question_scores("10 20.5") == [10.0, 20.5]
    assert parse_question_scores([1, "2.5", "x"]) == [1.0, 2.5]
    assert parse_question_scores(None) == []
    assert parse_question_scores("") == []


class _StubFrame:
    def __init__(self, url):
        self.url = url


class _StubPage:
    def __init__(self, frames=(), evaluate_result=None):
        self.frames = list(frames)
        self._eval = evaluate_result
        self.calls = []

    def evaluate(self, js, arg=None):
        self.calls.append((js, arg))
        return self._eval

    def wait_for_timeout(self, _ms):
        pass


def test_image_dialog_frame_matches_known_urls():
    for hint in IMAGE_DIALOG_HINTS:
        fr = _StubFrame(f"https://x/mooc2-ans/js/editor20150812/dialogs/{hint}")
        assert _image_dialog_frame(_StubPage([fr]), timeout_s=0) is fr
    assert _image_dialog_frame(_StubPage([_StubFrame("https://x/other.html")]), timeout_s=0) is None


def test_set_comment_html_passes_selector_and_html():
    page = _StubPage(evaluate_result={"ok": True, "key": "comment123", "mode": "ueditor"})
    out = set_comment_html(page, "<p>很好</p>")
    assert out["ok"] and out["mode"] == "ueditor"
    js, arg = page.calls[0]
    assert arg[0] == 'textarea[name="comment"]' and arg[1] == "<p>很好</p>"


def test_read_back_passthrough_stub():
    page = _StubPage(evaluate_result={"comment": "<p>x</p>", "commentImages": 1,
                                      "answers": [], "answerImages": [],
                                      "score": "85", "questionScores": ["20"]})
    rb = read_back(page)
    assert rb["commentImages"] == 1 and rb["score"] == "85"

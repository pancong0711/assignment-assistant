"""D83 修复：CLI job 输出 → 错误摘要（PWA 只显示「}」的根因）。

背景：引擎 CLI 失败时先 echo indent JSON（含 "error"），末行是 '}'；
旧实现取末行 → PWA msg/journal error 显示「}」。
"""

from assist.serve import _job_error_summary


def test_error_field_preferred_over_trailing_brace():
    out = ['{', ' "ok": false,', ' "error": "新建作业失败（步骤：选择题型（简答题））：TimeoutError",',
           ' "step": "选择题型（简答题）"', '}']
    assert _job_error_summary(out) == "新建作业失败（步骤：选择题型（简答题））：TimeoutError"


def test_falls_back_to_last_nonempty_line_for_traceback():
    out = ["Traceback (most recent call last):", '  File "work.py", line 1, in <module>',
           "playwright._impl._errors.TimeoutError: Locator.click: Timeout 10000ms exceeded", ""]
    assert _job_error_summary(out) == "playwright._impl._errors.TimeoutError: Locator.click: Timeout 10000ms exceeded"


def test_escaped_json_error_decoded():
    out = ['{', ' "ok": false,', ' "error": "附件被拒绝（越界或格式不在白名单）：a\\\\b.zip\\n见截图" ', '}']
    got = _job_error_summary(out)
    assert "a\\b.zip" in got and "\n" in got


def test_larger_tail_window_covers_long_json():
    # JSON 可能很长（含 requests 数组），只扫最后 40 行也要能取到 error 字段
    out = ['{', ' "ok": false,', ' "error": "步骤：点击「保存」：not visible",']
    out += ['  "requests": ['] + [f'   {{"url": "https://x/{i}"}},' for i in range(60)] + ['  ]', '}', '}']
    assert _job_error_summary(out) == "步骤：点击「保存」：not visible"


def test_empty_output():
    assert _job_error_summary([]) == ""
    assert _job_error_summary(["", "  "]) == ""

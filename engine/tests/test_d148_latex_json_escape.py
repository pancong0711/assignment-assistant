"""D148：模型把 LaTeX 写进 JSON 时，反斜杠被 JSON 转义吃掉的问题。

现象（教师报）：生成评阅要点后，参考答案里的 LaTeX 显示成特殊字符。

根因：`\\f` `\\t` `\\b` `\\n` `\\r` 都是**合法 JSON 转义**，所以
`json.loads` 会"成功"，但 `\\frac` 被改成「换页符 + rac」、
`\\beta` 被改成「退格符 + eta」、「\\theta」→「制表符 + heta」。
"""
from __future__ import annotations

import pytest

from assist.grading.transcribe import parse_llm_json


def _raw(s: str) -> str:
    """构造"模型真实输出"的 JSON 文本（s 里是单个反斜杠）。"""
    return '{"reference_solution": "' + s + '", "rubric_points": []}'


@pytest.mark.parametrize("full", [
    "\\frac{1}{2}mv^2",
    "\\beta = 30",
    "\\theta",
    "\\rho",
    "\\times b",
    "\\nabla f",
])
def test_latex_commands_preserved(full):
    """模型输出里的单反斜杠 LaTeX 命令，解析后必须**原样保留**。"""
    out = parse_llm_json('{"reference_solution": "' + full + '", "rubric_points": []}')[
        "reference_solution"]
    assert out == full.replace("\\", "\\"), f"未还原：{out!r}"
    # 不得残留控制字符
    for c in ("\x0c", "\x08", "\t", "\r"):
        assert c not in out, f"残留控制字符 {c!r}：{out!r}"


def test_real_newline_still_works():
    """**不能误伤**：真正的换行必须保留。"""
    out = parse_llm_json('{"s": "第一行\\n第二行"}')["s"]
    assert out == "第一行\n第二行"


def test_plain_text_untouched():
    out = parse_llm_json('{"s": "没有公式的一段话"}')["s"]
    assert out == "没有公式的一段话"


def test_inline_math_dollars_ok():
    out = parse_llm_json('{"s": "求 $E=mc^2$ 的值"}')["s"]
    assert out == "求 $E=mc^2$ 的值"


def test_invalid_json_with_bare_backslash_recovers():
    """完全非法的 JSON（裸反斜杠）也能救回来。"""
    raw = '{"s": "公式 \\frac{1}{2}", "n": 1}'
    out = parse_llm_json(raw)
    assert "\\frac" in out["s"]


def test_rubric_prompt_mentions_escaping():
    """提示词必须明确要求双反斜杠（预防优于事后修）。"""
    from assist.grading.rubric import RUBRIC_PROMPT
    assert "JSON 转义" in RUBRIC_PROMPT
    assert "两个反斜杠" in RUBRIC_PROMPT

"""D166：LaTeX 转义根因修复（QA 参考答案出现 \\f / \\v / \\t 乱码）。

三类根因（docs/109 §1）：
  1. **单反斜杠 + 空白对齐**：`\\t` 被当制表符，后面还有空格再 `imes`
     → 旧正则 `\\\\[fbtrn](rac|...)` 要求紧贴，图案对不上，修复完全不触发；
  2. **🔴 主动弄坏合格输出**：模型按规范写 `\\\\frac` 时，旧 `_looks_like_eaten_latex`
     把合法 `\\\\` 当成"被吃掉的 \\" 再补一个 → `\\\\\\f`（静默坏数据）；
  3. **控制符后接空格**：`\\x0c   rac` 需要允许空白。
"""
from __future__ import annotations

import json

import pytest

from assist.grading.transcribe import parse_llm_json

BS = "\\"

# 需要覆盖的 LaTeX 命令（首字母都是 JSON 合法转义：f/b/t/n/r/v）
COMMANDS = [
    r"\frac{1}{2}", r"\times10^{-19}", r"\beta", r"\theta", r"\rho",
    r"\nabla V", r"\varepsilon", r"\forall", r"\bullet", r"\rightarrow",
]


def _one(text: str) -> str:
    return parse_llm_json('{"s": "' + text + '"}')["s"]


def _one_wrapped(text: str) -> str:
    """模型守规矩：json.dumps 会写成双反斜杠。"""
    return parse_llm_json(json.dumps({"s": text}, ensure_ascii=False))["s"]


# ---------------- 根因 2：不能弄坏合格输出（此前的严重 bug） ----------------

@pytest.mark.parametrize("cmd", COMMANDS)
def test_correct_output_is_not_broken(cmd):
    """模型**遵守**提示词（JSON 里双反斜杠）时，解析结果必须原样保留。

    这是 D166 发现的最严重问题：旧实现把合法 `\\\\frac` 改成 `\\\\\\f`（控制字符）。
    """
    assert _one_wrapped(cmd) == cmd


@pytest.mark.parametrize("cmd", COMMANDS)
def test_single_backslash_recovered(cmd):
    """模型偷懒写单反斜杠，也要能还原。"""
    assert _one(cmd) == cmd


@pytest.mark.parametrize("cmd", COMMANDS)
def test_control_char_then_spaces_recovered(cmd):
    r"""控制符 + 多个空格 + 尾巴（`\t        imes`，教师样例的真实形态）。"""
    head, tail = cmd[1], cmd[2:]
    assert _one(BS + head + "    " + tail) == cmd


# ---------------- 教师的真实样例（端到端） ----------------

def test_teacher_sample_times_with_spaces():
    """教师原话：`$e=1.602\\        imes10^{-19}$`。"""
    out = _one("$e=1.602" + BS + "t        imes10^{-19}" + BS + ",C$")
    assert r"\times10^{-19}" in out
    assert "imes" not in out.replace(r"\times", "")


def test_teacher_sample_frac_and_nabla():
    raw = ('{"reference_solution": "1. $e=1.602' + BS + 't        imes10^{-19}$；'
           '2. $' + BS + 'frac{1}{4' + BS + 'pi' + BS + 'varepsilon_0}$；'
           '7. $-' + BS + 'n abla V$"}')
    out = parse_llm_json(raw)["reference_solution"]
    for want in (r"\times10^{-19}", r"\frac{1}{4\pi\varepsilon_0}", r"\nabla V"):
        assert want in out, f"缺少 {want!r}：{out!r}"


def test_no_control_chars_left():
    """解析后不得残留换页/退格/垂直制表等控制字符。"""
    raw = ('{"s": "a' + BS + 'frac{1}{2} b' + BS + 'beta c' + BS + 'varepsilon d"}')
    out = parse_llm_json(raw)["s"]
    for c in ("\x0c", "\x08", "\x0b"):
        assert c not in out, f"残留控制字符 {c!r}：{out!r}"


# ---------------- 不能误伤 ----------------

@pytest.mark.parametrize("text,want", [
    ("第一行\\n第二行", "第一行\n第二行"),
    ("列一\\t列二", "列一\t列二"),
    ("a\\n    b", "a\n    b"),
])
def test_real_newline_and_tab_preserved(text, want):
    """**真换行/真制表符**必须保留（模型有意写的）。"""
    assert _one(text) == want


@pytest.mark.parametrize("text", [
    "The rate is 5 times higher",
    "结果 rac 与 eta 都正常",
    "alpha beta gamma",
    "没有公式的一段话",
])
def test_plain_text_untouched(text):
    """普通英文/中文（含命令尾巴单词）不能被改。"""
    assert _one_wrapped(text) == text


def test_bare_backslash_json_still_recovers():
    """完全非法的 JSON（裸反斜杠）仍能救回（D162 行为不回退）。"""
    out = parse_llm_json('{"s": "公式 \\frac{1}{2}", "n": 1}')
    assert r"\frac" in out["s"]


# ---------------- T5：write_xlsx 表头不能污染 ----------------

def test_write_xlsx_header_is_standard(tmp_path):
    """D166：write_xlsx 曾把 solution 表头写成带注释的长字符串 → 读回时该列消失。"""
    from assist.files import kb_io

    kb_io.write_xlsx(tmp_path / "qa.xlsx",
                     {"chap01": [{"id": "c1", "content": "题", "solution": "旧答案"}]})
    row = kb_io.read_xlsx(tmp_path / "qa.xlsx", tmp_path)["chap01"][0]
    assert "solution" in row, f"solution 列丢失，实际键：{list(row)}"
    assert row["solution"] == "旧答案"


def test_rubric_prompt_gives_concrete_bad_examples():
    """提示词要写清「坏法→后果」，而不只是说'用双反斜杠'。"""
    from assist.grading.rubric import RUBRIC_PROMPT
    for kw in ("制表符", "换页符", "两个反斜杠"):
        assert kw in RUBRIC_PROMPT, f"提示词缺少 {kw}"

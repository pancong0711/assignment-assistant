"""D185：评阅 JSON 偶发格式错误导致单生批阅失败的修复。

覆盖增强 JSON 解析、analyze() 重试边界、诊断字段与下游算分/批语。
使用合成数据，禁止真实模型调用。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from assist.grading import evaluate as EV
from assist.grading.transcribe import parse_llm_json


# ---------------- 1. 增强 JSON 解析纯函数 ----------------

def _minimal_analysis(**overrides) -> dict:
    """构造一个合法的评阅 analysis 骨架。"""
    return {
        "question_match": {"status": True, "match": True, "note": "匹配正常",
                           "evidence": "", "reason": ""},
        "questions": [{
            "id": 1,
            "reasoning": {"status": "ok", "note": "思路清晰"},
            "correct_points": ["列式正确"],
            "errors": [{
                "step": "第1步",
                "description": "符号错误",
                "evidence": "x = -3",
                "why": "方向应取反",
                "guidance": "再看一眼方向",
                "confidence": "high",
                "knowledge": ["符号约定"],
            }],
            "has_diagram": True,
        }],
        "has_signature": True,
        "summary": "整体较好",
        "guidance": "复查符号约定",
        "strengths": ["列式规范"],
        "weaknesses": ["符号"],
        **overrides,
    }


def test_normal_json_unchanged():
    """合法 JSON 必须原样解析，不附加诊断字段。"""
    data = _minimal_analysis()
    raw = json.dumps(data, ensure_ascii=False)
    repairs: list[str] = []
    out = parse_llm_json(raw, repairs_out=repairs)
    assert out == data
    assert repairs == []


def test_fence_and_preamble_stripped():
    """代码围栏 + 前后说明文字被剥离。"""
    data = _minimal_analysis()
    raw = json.dumps(data, ensure_ascii=False)
    wrapped = (
        "当然，这是评阅结果：\n\n"
        "```json\n" + raw + "\n```\n\n"
        "希望对你有帮助。"
    )
    repairs: list[str] = []
    out = parse_llm_json(wrapped, repairs_out=repairs)
    assert out == data
    assert "fence-strip" in repairs
    assert "preamble-strip" in repairs


def test_expecting_comma_delimiter_minimal_repro():
    """最小复现 `Expecting ',' delimiter`：字符串内未转义双引号。"""
    bad = (
        '{"questions": [{"id": 1, "errors": ['
        '{"evidence": "学生写 "v=4" 导致结果错", "confidence": "high"}]}]}'
    )
    out = parse_llm_json(bad)
    assert out["questions"][0]["errors"][0]["evidence"] == '学生写 "v=4" 导致结果错'


def test_trailing_commas_removed():
    """对象与数组尾逗号被修复。"""
    bad = json.dumps(_minimal_analysis(), ensure_ascii=False)
    # 在最后一个字段后加尾逗号
    bad = bad.replace('"weaknesses": ["符号"]', '"weaknesses": ["符号",]')
    bad = bad.replace('"has_signature": true,', '"has_signature": true,\n"trailing": 1,')
    out = parse_llm_json(bad)
    assert out["weaknesses"] == ["符号"]
    assert out.get("trailing") == 1


def test_bare_newline_and_backslash_recover():
    """字符串内裸换行 + 未转义反斜杠能恢复，且 LaTeX 语义保留。"""
    bad = (
        '{"s": "第一行\n第二行 公式 '
        '\\frac{1}{2}"}'
    )
    out = parse_llm_json(bad)
    assert out["s"] == "第一行\n第二行 公式 \\frac{1}{2}"


def test_multiple_unescaped_quotes():
    """同一字符串内多个未转义双引号。"""
    bad = '{"evidence": "学生写 "a" 和 "b" 两个值"}'
    out = parse_llm_json(bad)
    assert out["evidence"] == '学生写 "a" 和 "b" 两个值'


def test_truncation_balanced():
    """简单截断缺失右括号可补齐。"""
    bad = '{"questions": [{"id": 1, "errors": []}'  # 缺两个 }]
    out = parse_llm_json(bad)
    assert out["questions"][0]["id"] == 1


def test_truncation_unrecoverable_raises():
    """无法修复的截断仍应抛出 JSONDecodeError。"""
    bad = '{"questions": [{"id": 1, "errors": [}'  # 结构破坏严重
    with pytest.raises(json.JSONDecodeError):
        parse_llm_json(bad)


def test_parse_repairs_not_leaking_raw():
    """修复诊断只含类型标签，不含原文。"""
    bad = '{"a": "尾逗号",}'
    repairs: list[str] = []
    parse_llm_json(bad, repairs_out=repairs)
    assert "trailing-comma" in repairs
    for r in repairs:
        assert "尾逗号" not in r


# ---------------- 2. analyze() 重试与边界 ----------------

class _FakeLLMClient:
    """按顺序返回预设 raw 响应，记录调用次数。

    `repeat_last=True` 时，耗尽预设响应后继续重复最后一个（用于模拟持续截断）。
    """

    def __init__(self, responses: list[str], *, repeat_last: bool = False):
        self.responses = responses
        self.repeat_last = repeat_last
        self.calls: list[tuple[str, str, int]] = []  # (system_prompt, user_text, max_tokens)

    def chat(self, *, system_prompt: str, user_text: str, model=None,
             temperature=None, response_format=None, max_tokens: int = 8192,
             step: str = "evaluation") -> str:
        idx = len(self.calls)
        self.calls.append((system_prompt, user_text, max_tokens))
        if idx >= len(self.responses):
            if self.repeat_last and self.responses:
                return self.responses[-1]
            return "{}"
        return self.responses[idx]


def test_analyze_local_repair_succeeds_no_model_retry():
    """本地修复成功时不再请求模型重试。"""
    good = json.dumps(_minimal_analysis(), ensure_ascii=False)
    bad = good.replace('"weaknesses": ["符号"]', '"weaknesses": ["符号",],')
    client = _FakeLLMClient([bad])
    out = EV.analyze(client, "user prompt")
    assert out["summary"] == "整体较好"
    assert out.get("_parse_repairs")
    assert len(client.calls) == 1


def test_analyze_retries_limited_then_readable_error(monkeypatch):
    """本地修复失败时只重试有限次，最终报错可读且不泄原文。"""
    client = _FakeLLMClient(["not json", "still not json", "also bad"])
    # 把 sleep 置空加速测试
    monkeypatch.setattr(EV.time, "sleep", lambda _x: None)
    with pytest.raises(RuntimeError, match="评阅JSON解析失败") as exc:
        EV.analyze(client, "学生作答原文")
    err = str(exc.value)
    assert "学生作答原文" not in err
    assert "本地修复与模型重试均已耗尽" in err
    # 1 次原始 + 2 次重试 = 3 次模型调用
    assert len(client.calls) == 3
    # 后两次请求带上了"只返回合法 JSON"后缀
    assert EV._JSON_ONLY_SUFFIX in client.calls[1][1]
    assert EV._JSON_ONLY_SUFFIX in client.calls[2][1]


def test_analyze_truncation_doubles_max_tokens(monkeypatch):
    """截断类错误仍按现有逻辑翻倍 max_tokens。"""
    # 持续返回未闭合字符串（截断）
    client = _FakeLLMClient(['{"summary": "未完成'], repeat_last=True)
    monkeypatch.setattr(EV.time, "sleep", lambda _x: None)
    with pytest.raises(RuntimeError, match="翻倍重试耗尽"):
        EV.analyze(client, "prompt", max_tokens=12288)
    # 每次调用 max_tokens 应翻倍
    assert client.calls[0][2] == 12288
    assert client.calls[1][2] == 24576
    assert client.calls[2][2] == 49152


def test_analyze_model_retry_succeeds():
    """本地修复失败、模型重试返回合法 JSON 时成功。"""
    bad = "not json"
    good = json.dumps(_minimal_analysis(), ensure_ascii=False)
    client = _FakeLLMClient([bad, good])
    out = EV.analyze(client, "prompt")
    assert out["questions"][0]["id"] == 1
    assert len(client.calls) == 2


def test_analyze_does_not_duplicate_json_only_suffix():
    """"只返回合法 JSON"后缀不会重复追加。"""
    client = _FakeLLMClient(["bad", "bad", "bad"])
    # 预先带上后缀的请求不应再追加
    prompt = "prompt" + EV._JSON_ONLY_SUFFIX
    with pytest.raises(RuntimeError):
        EV.analyze(client, prompt)
    assert client.calls[1][1].count(EV._JSON_ONLY_SUFFIX) == 1


# ---------------- 3. 修复结果进入 score / feedback ----------------

def test_repaired_analysis_flows_to_score_and_feedback(tmp_path):
    """增强解析后的 analysis 能正常算分、生成批语，并带诊断字段。"""
    bad = (
        '{"question_match": {"status": true, "match": true, "note": "ok", '
        '"evidence": "", "reason": ""}, '
        '"questions": [{"id": 1, "reasoning": {"status": "ok", "note": "ok"}, '
        '"correct_points": ["对"], "errors": [{"step": "", "description": "错", '
        '"evidence": "学生写 "x"", "why": "原因", "guidance": "再看", '
        '"confidence": "high", "knowledge": ["k"]}], "has_diagram": true}], '
        '"has_signature": true, "summary": "总评", "guidance": "建议", '
        '"strengths": ["好"], "weaknesses": ["差"],}'
    )
    client = _FakeLLMClient([bad])
    analysis = EV.analyze(client, "prompt")
    result = EV.score_from_analysis(analysis, ws=tmp_path)
    assert result["total_score"] < 100
    md = EV.build_feedback_md(result, "学生甲", "测试作业", analysis=analysis)
    assert "学生写 \"x\"" in md
    assert analysis["_parse_repairs"]


# ---------------- 4. 回归：相关 D158/D166/D179/D171/D178 ----------------

def test_regression_d158_rigor_fields_preserved():
    """D158：evidence/why/correct_points 等严谨字段在修复后保留。"""
    data = _minimal_analysis()
    raw = json.dumps(data, ensure_ascii=False)
    bad = raw.replace('"evidence": "x = -3"', '"evidence": "x = "-3""')
    out = parse_llm_json(bad)
    err = out["questions"][0]["errors"][0]
    assert err["evidence"] == 'x = "-3"'
    assert err["why"] == "方向应取反"
    assert err["confidence"] == "high"
    assert out["questions"][0]["correct_points"] == ["列式正确"]


def test_regression_d166_latex_escape_not_broken():
    """D166：合法双反斜杠 LaTeX 不被过度修复。"""
    text = r"\frac{1}{2} \times \beta"
    raw = json.dumps({"s": text}, ensure_ascii=False)
    out = parse_llm_json(raw)
    assert out["s"] == text


def test_regression_d166_single_backslash_still_recovered():
    """D166：模型偷懒写单反斜杠仍要还原。"""
    raw = '{"s": "公式 \\frac{1}{2}"}'
    out = parse_llm_json(raw)
    assert out["s"] == r"公式 \frac{1}{2}"


def test_regression_d179_analysis_shape_after_repair(tmp_path):
    """D179：修复后的 analysis 进入归一化流程不崩溃。"""
    bad = (
        '{"question_match": {"status": true}, '
        '"questions": [{"id": 1, "reasoning": {"status": "ok", "note": "ok"}, '
        '"correct_points": ["对"], "errors": [{"step": "", "description": "错", '
        '"evidence": "原文", "why": "原因", "guidance": "再看", '
        '"confidence": "high", "knowledge": ["k"]}], "has_diagram": true}], '
        '"summary": "总评", "guidance": ["建议1", "建议2"], '
        '"strengths": "好", "weaknesses": ["差"],}'
    )
    analysis = parse_llm_json(bad)
    norm, fixes = EV._normalize_analysis_shape(analysis)
    md = EV.build_feedback_md(
        {"total_score": 90, "deductions": []}, "学生", "作业", analysis=norm)
    assert "建议1" in md and "建议2" in md
    assert norm["guidance"] == "建议1；建议2"


def test_regression_d171_copy_ignores_errors_after_repair(tmp_path):
    """D171：抄写题不读 errors 的逻辑在修复后仍生效。"""
    bad = (
        '{"questions": [{"id": 1, "kind": "copy", "topic_match": "match", '
        '"answer_chars": 200, "errors": [{"description": "推导错误", '
        '"evidence": "学生写 "x"导致", "why": "", "guidance": "", '
        '"confidence": "high", "knowledge": ["库仑定律"]}], '
        '"has_diagram": true}], "has_signature": true}'
    )
    analysis = parse_llm_json(bad)
    result = EV.score_from_analysis(analysis, ws=tmp_path)
    assert result["total_score"] == 100


def test_regression_d178_tag_alias_not_affected():
    """D178：tag_instruction 语义不受 JSON 修复影响。"""
    assert "抄写" in EV.tag_instruction("copy")
    assert EV.tag_instruction("unknown") == ""

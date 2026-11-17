"""D179：模型返回 analysis 字段类型漂移（数组/字典混进标量/列表字段）的归一化。

直接崩溃点：build_feedback_md 末尾 `"\n".join(lines)` 时，若顶层 guidance
是数组，lines 中混入 list，抛出
    TypeError: sequence item 20: expected str instance, list found

本文件用合成数据 + stub client，禁止真实网络请求。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from assist.grading import flow
from assist.grading import inputs as I
from assist.grading.evaluate import (
    _normalize_analysis_shape,
    build_feedback_md,
    build_result_from_analysis,
)


# ---------------- 1. 最小复现：未归一化时 build_feedback_md 会崩溃 ----------------

def _drifting_analysis():
    """构造会触发 sequence item 20 的漂移 analysis：

    2 道题 × 每题 1 个 error + 顶层 guidance 为数组，join 时数组被当元素。
    """
    return {
        "question_match": {"status": True, "note": "匹配正常"},
        "questions": [
            {
                "id": 1,
                "reasoning": {"status": "ok", "note": "思路清晰"},
                "correct_points": ["列式正确"],
                "errors": [
                    {
                        "step": "第2步",
                        "description": "符号错误",
                        "evidence": "x = -3",
                        "why": "方向应取反",
                        "guidance": ["再看一眼方向", "符号约定是否一致？"],
                        "confidence": "high",
                    }
                ],
                "has_diagram": True,
            },
            {
                "id": 2,
                "reasoning": {"status": "ok", "note": "过程完整"},
                "correct_points": ["单位统一"],
                "errors": [
                    {
                        "step": "第1步",
                        "description": ["漏写单位", "也漏了数量级"],
                        "evidence": "F = 10",
                        "why": "物理量必须带单位",
                        "guidance": "结果需要单位吗？",
                        "confidence": "high",
                    }
                ],
                "has_diagram": True,
            },
        ],
        "has_signature": True,
        "summary": ["整体较好", "但细节需加强"],
        "guidance": ["复查符号约定", "检查单位完整性"],
        "strengths": "列式规范",
        "weaknesses": ["单位", "符号"],
    }


def test_reproduce_sequence_item_20_then_fixed():
    """先用最小用例复现崩溃根因，再验证归一化后不再崩溃且内容保留。"""
    raw = _drifting_analysis()

    # 根因演示：旧逻辑把顶层 guidance（数组）直接放进 lines，"\n".join 崩溃。
    # 这正是生产上报错 "sequence item 20: expected str instance, list found" 的来源。
    with pytest.raises(TypeError, match="expected str instance, list found"):
        "\n".join(["# 批阅报告", raw["guidance"]])

    # 归一化后应正常出批语
    fixed, fixes = _normalize_analysis_shape(raw)
    md = build_feedback_md(
        {"total_score": 90, "deductions": ["测试扣分"]},
        "学生甲",
        "测试作业",
        analysis=fixed,
    )
    assert "复查符号约定" in md
    assert "检查单位完整性" in md
    assert "漏写单位" in md and "也漏了数量级" in md
    assert "再看一眼方向" in md and "符号约定是否一致？" in md
    # summary 被归一化为字符串保留在结果中（当前 md 模板不直接展示 summary）
    assert fixed["summary"] == "整体较好；但细节需加强"
    # 诊断字段只记录路径和修正类型
    assert "guidance: list→str" in fixes
    assert "summary: list→str" in fixes
    assert any("description" in f and "list→str" in f for f in fixes)


# ---------------- 2. 单元：各字段类型归一化 ----------------

def test_top_level_guidance_and_summary_array():
    a, fixes = _normalize_analysis_shape({
        "guidance": ["问题1", "问题2"],
        "summary": ["总评1", "总评2"],
        "questions": [],
    })
    assert a["guidance"] == "问题1；问题2"
    assert a["summary"] == "总评1；总评2"
    assert "guidance: list→str" in fixes
    assert "summary: list→str" in fixes


def test_strengths_weaknesses_various_shapes():
    a, fixes = _normalize_analysis_shape({
        "strengths": "单一字符串",
        "weaknesses": ["数组", 123, None, {"嵌套": "对象"}],
        "questions": [],
    })
    assert a["strengths"] == ["单一字符串"]
    assert a["weaknesses"] == ["数组", "123", '{"嵌套":"对象"}']
    assert "strengths: str→list[str]" in fixes
    assert "weaknesses: list[mixed]→list[str]" in fixes


def test_question_match_and_reasoning_note_scalars():
    a, fixes = _normalize_analysis_shape({
        "question_match": {
            "status": True,
            "note": ["注意", "顶替"],
            "evidence": ["原文1", "原文2"],
            "reason": "字符串保持",
        },
        "questions": [
            {"id": 1, "reasoning": {"status": "ok", "note": ["推理1", "推理2"]},
             "errors": []},
        ],
    })
    assert a["question_match"]["note"] == "注意；顶替"
    assert a["question_match"]["evidence"] == "原文1；原文2"
    assert a["question_match"]["reason"] == "字符串保持"
    assert a["questions"][0]["reasoning"]["note"] == "推理1；推理2"
    assert "question_match.note: list→str" in fixes
    assert "questions[0].reasoning.note: list→str" in fixes


def test_errors_fields_array():
    a, fixes = _normalize_analysis_shape({
        "questions": [
            {
                "id": 1,
                "errors": [
                    {
                        "step": ["第1步", "第2步"],
                        "description": "描述字符串",
                        "evidence": ["ev1", "ev2"],
                        "why": ["原因A", "原因B"],
                        "guidance": ["提示1", "提示2"],
                        "knowledge": ["动量守恒", "能量守恒"],
                    },
                ],
            },
        ],
    })
    e = a["questions"][0]["errors"][0]
    assert e["step"] == "第1步；第2步"
    assert e["description"] == "描述字符串"
    assert e["evidence"] == "ev1；ev2"
    assert e["why"] == "原因A；原因B"
    assert e["guidance"] == "提示1；提示2"
    assert e["knowledge"] == ["动量守恒", "能量守恒"]


def test_questions_and_errors_filter_non_dict():
    a, fixes = _normalize_analysis_shape({
        "questions": [
            "脏字符串",
            {
                "id": 1,
                "errors": [
                    None,
                    "脏错误",
                    {
                        "description": "正确错误",
                        "knowledge": "字符串应转列表",
                    },
                ],
            },
        ],
    })
    assert len(a["questions"]) == 1
    assert a["questions"][0]["id"] == 1
    assert len(a["questions"][0]["errors"]) == 1
    assert a["questions"][0]["errors"][0]["description"] == "正确错误"
    assert a["questions"][0]["errors"][0]["knowledge"] == ["字符串应转列表"]
    assert "questions[0]: non-dict filtered" in fixes
    # fixes 使用原始下标，便于定位模型输出位置
    assert "questions[1].errors[0]: non-dict filtered" in fixes
    assert "questions[1].errors[1]: non-dict filtered" in fixes


def test_dict_complex_value_fallback_to_json():
    a, _ = _normalize_analysis_shape({
        "guidance": {"提示": "复杂对象"},
        "questions": [],
    })
    assert a["guidance"] == '{"提示":"复杂对象"}'


def test_non_dict_root_returns_empty():
    a, fixes = _normalize_analysis_shape(["not", "a", "dict"])
    assert a == {"analysis_shape_fixes": ["root: non-dict→empty dict"]}
    assert fixes == ["root: non-dict→empty dict"]


# ---------------- 3. 端到端：evaluate_student 写出 JSON/MD ----------------

def _fake_analyze_with_drift(*a, **k):
    return _drifting_analysis()


def test_evaluate_student_end_to_end_writes_json_and_md(tmp_path, monkeypatch):
    import assist.grading.evaluate as EV

    monkeypatch.setattr(EV, "analyze", _fake_analyze_with_drift)

    ws = tmp_path
    out_dir = ws / "evaluations"
    transcript = ws / "张三.json"
    transcript.write_text(json.dumps({
        "student": "张三",
        "items": [
            {"no": "1", "printed_question": "题1", "answer": "答1"},
            {"no": "2", "printed_question": "题2", "answer": "答2"},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    items = [
        {"序号": "1", "content": "题1", "tag": "problems"},
        {"序号": "2", "content": "题2", "tag": "problems"},
    ]
    client = EV.LLMClient(settings={
        "base_url": "http://stub.invalid",
        "api_key": "stub",
        "model": "stub",
    })

    EV.evaluate_student(
        client, transcript, items, out_dir,
        homework_name="D179测试", model="stub")

    ev_path = out_dir / "张三.json"
    md_path = out_dir / "张三.md"
    assert ev_path.exists() and md_path.exists()
    ev = json.loads(ev_path.read_text(encoding="utf-8"))
    assert "feedback_md" in ev
    assert "analysis_shape_fixes" in ev["analysis"]
    assert "guidance: list→str" in ev["analysis"]["analysis_shape_fixes"]
    md = md_path.read_text(encoding="utf-8")
    assert "复查符号约定" in md
    assert "检查单位完整性" in md


# ---------------- 4. 批量回灌：build_result_from_analysis ----------------

def test_build_result_from_analysis_batch_path():
    raw = _drifting_analysis()
    result = build_result_from_analysis(
        raw, student="李四", homework_name="批量测试", model="stub")
    assert "feedback_md" in result
    assert result["analysis"]["guidance"] == "复查符号约定；检查单位完整性"
    assert "analysis_shape_fixes" in result["analysis"]
    md = result["feedback_md"]
    assert "复查符号约定" in md
    assert "漏写单位" in md and "也漏了数量级" in md


# ---------------- 5. 正常字符串行为不回归 ----------------

def test_normal_string_output_unchanged():
    """模型守规矩输出字符串时，归一化应是无副作用的透传。"""
    analysis = {
        "question_match": {"status": True, "note": "匹配"},
        "questions": [
            {"id": 1, "reasoning": {"status": "ok", "note": "思路完整"},
             "correct_points": ["正确"], "errors": [], "has_diagram": True},
        ],
        "has_signature": True,
        "summary": "整体尚可",
        "guidance": "继续加油",
        "strengths": ["步骤清晰"],
        "weaknesses": ["细节"],
    }
    fixed, fixes = _normalize_analysis_shape(analysis)
    assert fixes == []
    assert fixed["guidance"] == "继续加油"
    assert fixed["summary"] == "整体尚可"
    assert fixed["strengths"] == ["步骤清晰"]
    r = build_result_from_analysis(fixed, student="王五")
    assert "继续加油" in r["feedback_md"]
    assert "analysis_shape_fixes" not in fixed  # 无修正时不加该字段


# ---------------- 6. copyOnly 端到端不回归（复用 D178 风格） ----------------

LONG_ANSWER = ("直角三角形两条直角边的平方和等于斜边的平方。" * 8)


def _ws_with_pack(tmp_path: Path, *, pad_tag: str, stu_tag: str) -> tuple[Path, dict]:
    ws = tmp_path
    (ws / "classes" / "A" / "roster").mkdir(parents=True)
    (ws / "tasks").mkdir(parents=True)
    pad = {"id": "pad-co", "target_tag": pad_tag,
           "items": [{"kb": "copy", "chap": "c1", "ids": ["1"],
                      "tag": pad_tag, "content": "抄写勾股定理"}]}
    (ws / "tasks" / "pad-co.taskpad.json").write_text(
        json.dumps(pad, ensure_ascii=False), encoding="utf-8")
    pack = {"id": "p1", "name": "p1", "schema": 1,
            "pads": [{"padId": "pad-co", "tag": pad_tag}]}
    from openpyxl import Workbook
    wb = Workbook(); sh = wb.active
    sh.append(["姓名", "学号", "tag"]); sh.append(["张三", "1", stu_tag])
    wb.save(ws / "classes" / "A" / "roster" / "roster.xlsx")
    return ws, pack


def _plan(ws: Path, pack: dict):
    return I.build_plan(ws, task_id="p1", class_dir="classes/A", class_id="c1",
                        work_id="w1", pack=pack,
                        review_students=[{"name": "张三", "workAnswerId": "wa1",
                                          "images": ["a.jpg"]}])


def test_evaluate_student_tolerates_non_dict_analysis(tmp_path, monkeypatch):
    """模型返回顶层数组时，归一化应先于 _enrich_questions 生效，流程不崩溃。"""
    import assist.grading.evaluate as EV

    monkeypatch.setattr(EV, "analyze", lambda *a, **k: ["bad"])

    ws = tmp_path
    out_dir = ws / "evaluations"
    transcript = ws / "张三.json"
    transcript.write_text(json.dumps({
        "student": "张三",
        "items": [{"no": "1", "printed_question": "题1", "answer": "答1"}],
    }, ensure_ascii=False), encoding="utf-8")

    items = [{"序号": "1", "content": "题1", "tag": "problems"}]
    client = EV.LLMClient(settings={
        "base_url": "http://stub.invalid",
        "api_key": "stub",
        "model": "stub",
    })

    EV.evaluate_student(
        client, transcript, items, out_dir,
        homework_name="D179边界", model="stub")

    ev_path = out_dir / "张三.json"
    md_path = out_dir / "张三.md"
    assert ev_path.exists() and md_path.exists(), "必须写出 JSON/MD"
    ev = json.loads(ev_path.read_text(encoding="utf-8"))
    assert ev["analysis"] == {"analysis_shape_fixes": ["root: non-dict→empty dict"]}
    assert isinstance(ev["total_score"], int)
    assert "root: non-dict→empty dict" in ev["analysis"]["analysis_shape_fixes"]


def test_copyonly_student_with_guidance_array_still_gets_score(tmp_path, monkeypatch):
    """copyOnly 学生即使模型把 guidance 等字段输出成数组，也能拿到分数和批语。"""
    import assist.grading.evaluate as EV
    from assist.xxt import grade_store as GS

    ws, pack = _ws_with_pack(tmp_path, pad_tag="copy", stu_tag="copyonly")
    (ws / "settings.local.json").write_text(json.dumps(
        {"llm": {"base_url": "http://x", "api_key": "k", "model": "m"}}),
        encoding="utf-8")
    plan = _plan(ws, pack)
    I.save_plan(ws, "classes/A", plan)
    task = {"id": "p1", "pack_id": "p1", "class_dir": "classes/A",
            "grade": {"steps": ["evaluate"]}, "items": []}
    tp = ws / "t.json"; tp.write_text(json.dumps(task), encoding="utf-8")
    base = flow.grading_dir(ws, task)
    (base / "transcripts").mkdir(parents=True, exist_ok=True)
    (base / "transcripts" / "张三.json").write_text(json.dumps(
        {"student": "张三", "items": [{"no": "1", "printed_question": "抄写勾股定理",
                                       "answer": LONG_ANSWER}], "model": "m"},
        ensure_ascii=False), encoding="utf-8")

    def fake_analyze(*a, **k):
        # 关键：顶层 guidance 是数组，errors[].guidance 也是数组
        return {
            "question_match": {"status": True, "match": True},
            "questions": [
                {"id": "1", "reasoning": {"status": "ok", "note": "抄写完整"},
                 "correct_points": ["与主题一致"], "errors": [],
                 "confidence": "high", "has_diagram": True,
                 "topic_match": "match", "answer_chars": 120},
            ],
            "has_signature": True,
            "summary": ["抄写认真"],
            "guidance": ["保持", "继续练习"],
            "strengths": ["完整"],
            "weaknesses": [],
        }

    monkeypatch.setattr(EV, "analyze", fake_analyze)
    flow.run_task(tp, ws, plan=plan, class_dir="classes/A", students=["张三"], force=True)

    ev = json.loads((base / "evaluations" / "张三.json").read_text(encoding="utf-8"))
    assert ev["total_score"] == 100
    assert ev["feedback_md"].strip(), "必须有批语"
    assert "保持" in ev["feedback_md"] and "继续练习" in ev["feedback_md"]
    assert ev["per_question_rules"][0]["rules"] == ["topicMatch"]

    drafts = GS.read_drafts_normalized(None, "c1", "w1", ws=tmp_path,
                                       class_dir="classes/A", task_id="p1")
    d = next(iter(drafts.values()))
    assert d["ai"]["score"] == 100 and d["ai"]["comment"].strip()

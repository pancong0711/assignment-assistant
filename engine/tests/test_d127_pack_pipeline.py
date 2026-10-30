"""D127：作业包为唯一批次载体 + 转写结构化 + 评阅只给对应 tag 作业纸 + 报告组装。"""
import json
from pathlib import Path

import pytest

from assist.paper import pack as P


def _mk_pad(ws: Path, pid: str, tag: str, items=None):
    d = ws / "tasks"
    d.mkdir(parents=True, exist_ok=True)
    pad = {"id": pid, "target_tag": tag,
           "items": items or [{"kb": "problems", "chap": "c1", "ids": ["1"], "tag": tag}]}
    (d / f"{pid}.taskpad.json").write_text(json.dumps(pad, ensure_ascii=False), encoding="utf-8")
    return pad


def _mk_pack(ws: Path, pk: str, pads):
    d = ws / "packs"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{pk}.pack.json").write_text(json.dumps(
        {"id": pk, "name": pk, "pads": pads, "schema": 1}, ensure_ascii=False), encoding="utf-8")
    return {"id": pk, "name": pk, "pads": pads}


# ---------------- 包上下文：唯一取题入口 ----------------

def test_pack_context_and_pick_by_tag(tmp_path):
    ws = tmp_path
    _mk_pad(ws, "pad-qa", "qa")
    _mk_pad(ws, "pad-copy", "copy")
    pk = _mk_pack(ws, "pack1", [{"padId": "pad-qa", "tag": "qa"},
                                {"padId": "pad-copy", "tag": "copy"}])
    ctx = P.pack_context(ws, pk)
    assert ctx["packId"] == "pack1" and not ctx["dangling"]
    assert P.pick_pad_for_tag(ctx, "qa")["padId"] == "pad-qa"
    assert P.pick_pad_for_tag(ctx, "COPY")["padId"] == "pad-copy"   # tag 归一（大小写）


def test_pick_never_falls_back_outside_pack(tmp_path):
    """D127 核心：包里没有的 tag 不得回退到全库其他作业纸（防跨批次串题）。"""
    ws = tmp_path
    _mk_pad(ws, "pad-other", "qa")          # 存在，但**不属于** pack1
    _mk_pad(ws, "pad-copy", "copy")
    pk = _mk_pack(ws, "pack1", [{"padId": "pad-copy", "tag": "copy"}])
    ctx = P.pack_context(ws, pk)
    assert P.pick_pad_for_tag(ctx, "qa") is None
    assert P.tags_without_pad(ctx, ["qa", "copy"]) == ["qa"]


def test_pack_dangling_pad_reported(tmp_path):
    ws = tmp_path
    pk = _mk_pack(ws, "pack1", [{"padId": "missing", "tag": "qa"}])
    ctx = P.pack_context(ws, pk)
    assert ctx["dangling"] == ["missing"]


# ---------------- build_plan：题目按包内 tag 取 ----------------

def test_build_plan_uses_pack_only(tmp_path, monkeypatch):
    from assist.grading import inputs as I
    ws = tmp_path
    _mk_pad(ws, "pad-qa", "qa", items=[{"kb": "problems", "chap": "c1", "ids": ["1"], "tag": "qa"}])
    pk = _mk_pack(ws, "pack1", [{"padId": "pad-qa", "tag": "qa"}])
    monkeypatch.setattr(I, "students_with_tags",
                        lambda ws, cd: [{"name": "张三", "number": "1", "tag": "qa"},
                                        {"name": "李四", "number": "2", "tag": "未知tag"}])
    monkeypatch.setattr(I, "_questions_of", lambda task, ws=None: [{"no": "1", "content": "题1",
                                                                    "solution": "", "tag": "qa"}])
    plan = I.build_plan(ws, task_id="t1", class_dir="classes/A", pack=pk,
                        review_students=[])
    by = {s["name"]: s for s in plan["students"]}
    assert by["张三"]["padId"] == "pad-qa" and len(by["张三"]["questions"]) == 1
    # 包内没有该 tag → 题目为空（不得回退到别的作业纸）
    assert by["李四"]["questions"] == [] and by["李四"]["padId"] == ""
    assert plan["packId"] == "pack1"


# ---------------- 转写结构化 ----------------

def test_transcription_prompt_is_structured_and_no_svg():
    from assist.grading.prompts import TRANSCRIPTION_PROMPT as TP
    assert '"items"' in TP and "printed_question" in TP and "answer" in TP
    assert "diagrams" in TP
    assert "禁止 SVG" in TP or "不要画图" in TP or "禁止 ASCII" in TP


def test_transcript_to_markdown_splits_question_and_answer():
    from assist.grading.transcribe import transcript_to_markdown
    md = transcript_to_markdown({"items": [
        {"no": "1", "printed_question": "求加速度", "answer": "a=F/m",
         "diagrams": [{"kind": "受力图", "description": "重力竖直向下"}]}]})
    assert "**题目：** 求加速度" in md
    assert "**作答：**" in md and "a=F/m" in md
    assert "受力图" in md and "重力竖直向下" in md


def test_transcript_to_markdown_falls_back_to_legacy_markdown():
    from assist.grading.transcribe import transcript_to_markdown, is_structured
    assert is_structured({"markdown": "旧"}) is False
    assert transcript_to_markdown({"markdown": "旧内容"}) == "旧内容"


# ---------------- 评阅：题目一致由 LLM 判；缺题目不猜 ----------------

def test_evaluate_prompt_asks_match_before_review():
    from assist.grading.prompts import build_evaluate_prompt
    p = build_evaluate_prompt(questions=[{"no": "1", "content": "求加速度"}],
                              markdown_text="### 第1题\n作答：a=F/m", tag="qa")
    assert "先判断题目是否对应" in p or "判断题目是否对应" in p
    assert p.index("判断题目") < p.index("学生转写")


def test_evaluate_prompt_forbids_guessing_when_no_questions():
    from assist.grading.prompts import build_evaluate_prompt
    p = build_evaluate_prompt(questions=[], markdown_text="x", tag="")
    assert "请你先自行判断题目" not in p, "旧兜底文案必须删除"


def test_evaluation_schema_has_knowledge_and_match():
    from assist.grading.prompts import EVALUATION_SCHEMA
    schema = EVALUATION_SCHEMA["json_schema"]["schema"]
    qm = schema["properties"]["question_match"]["properties"]
    assert "match" in qm and "evidence" in qm and "reason" in qm
    err = schema["properties"]["questions"]["items"]["properties"]["errors"]["items"]
    assert "knowledge" in err["properties"], "errors[] 应带知识点数组"


def test_run_evaluate_skips_student_without_questions(tmp_path, monkeypatch):
    """D127：plan 模式下该生没有题目 → 跳过并写诊断，不得用整包题目兜底。"""
    from assist.grading import flow

    tdir = tmp_path / "tr"; tdir.mkdir()
    (tdir / "李四.json").write_text(json.dumps({"student": "李四", "markdown": "x"},
                                              ensure_ascii=False), encoding="utf-8")
    ctx = {"task": {}, "items": [{"序号": 1, "content": "别的题"}],
           "transcripts_dir": tdir, "evaluations_dir": tmp_path / "ev",
           "plan": {"students": [{"name": "李四", "questions": []}]},
           "journal": tmp_path / "j.jsonl", "run_id": "r1", "diag": tmp_path / "d.jsonl"}
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("不该调用评阅")
    monkeypatch.setattr(flow, "evaluate_student", _boom)
    outs = flow._run_evaluate(ctx, object(), tmp_path / "ev")
    assert outs == [] and called["n"] == 0


# ---------------- 报告：先列正确题目；无顶替标签；三态不同 ----------------

def test_report_lists_correct_questions_and_no_substitution_label(tmp_path):
    from assist.grading.report import build_report_md
    t = tmp_path / "张三.json"; e = tmp_path / "张三_eval.json"
    t.write_text(json.dumps({"student": "张三", "items": [
        {"no": "1", "printed_question": "求加速度", "answer": "a=F/m"}],
        "model": "m"}, ensure_ascii=False), encoding="utf-8")
    e.write_text(json.dumps({"student": "张三", "total_score": 80, "feedback_md": "批语",
                             "questions": [{"no": "1", "content": "一物体受力求加速度"}],
                             "question_match": {"match": False, "reason": "题号对不上"},
                             "verdict": "suspected-substitution"}, ensure_ascii=False),
                 encoding="utf-8")
    md = build_report_md(t, e)
    assert "顶替嫌疑" not in md, "学生报告不得贴顶替标签"
    assert "本次作业的题目" in md and "一物体受力求加速度" in md
    # 正确题目应出现在「二、AI 批阅」之后、批语之前
    assert md.index("## 二、AI 批阅") < md.index("本次作业的题目")
    assert "存在差异" in md


def test_report_modes_differ():
    from assist.grading.report import _mode_report_md
    ai = {"comment": "AI 批语", "score": 80}
    hu = {"comment": "人工批语", "score": 90, "used": True}
    md_rep, k_rep = _mode_report_md(student="s", ai=ai, human=hu, human_mode="replace",
                                    revision={}, revised=False)
    md_app, k_app = _mode_report_md(student="s", ai=ai, human=hu, human_mode="append",
                                    revision={}, revised=False)
    assert k_rep == "human" and "AI 批语" not in md_rep
    assert "AI 批语" in md_app and "教师补充批语" in md_app
    assert md_rep != md_app


def test_default_grade_steps_excludes_report(tmp_path, monkeypatch):
    """D127：完整批阅不再含 report；历史任务包里的 report 被忽略。"""
    from assist.grading import flow
    seen = {}

    def fake_run_task(*a, **k):
        raise RuntimeError("stop")

    ws = tmp_path / "ws"
    ws.mkdir()
    tp = ws / "t.taskpad.json"
    tp.write_text(json.dumps({"id": "t1", "class_dir": "classes/A",
                              "grade": {"steps": ["transcribe", "evaluate", "report"]}}),
                  encoding="utf-8")
    monkeypatch.setattr(flow, "_run_transcribe", fake_run_task)
    with pytest.raises(Exception):
        flow.run_task(tp, ws)
    jf = ws / "classes/A/grading/t1/journal.jsonl"
    first = json.loads(jf.read_text(encoding="utf-8").splitlines()[0])
    assert first["step"] == "transcribe", "report 步骤应被忽略"

"""D178：tag=copyonly 的学生批阅后"没有分数也没有批语"。

教师反馈：
  学生 tag 为 copyonly 的不能使用 AI 批阅，逐生批阅里点「批阅」和「转写+批阅」
  都执行了操作，但没有看到分数和批语。

根因（端到端复现）：
  1. **tag 匹配是逐字精确的**（只归一大小写/全半角）。而 `copyonly / copysp / copys /
     punish` 在**评阅规则**里都被归一到「抄写(copy)」，于是出现：
       学生 tag = copyonly，作业纸 target_tag = copy  → 匹配失败 → 该生 0 道题
       → `_run_evaluate` 跳过 → 无 evaluations/*.json → 无草稿 → 界面无分数无批语。
  2. 跳过只写日志/诊断，任务仍以 done 结束 → PWA 显示「✅ 完成」，
     教师完全不知道被跳过（"都执行了操作，但没有结果"）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from assist.grading import flow
from assist.grading import inputs as I
from assist.paper import pack as P


# 抄写题有字数下限（默认 80 字），测试用足量作答避免"字数不足"扣分干扰断言
LONG_ANSWER = ("直角三角形两条直角边的平方和等于斜边的平方。" * 8)


# ---------------- 夹具：真实 roster + taskpad + pack ----------------

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
    wb = Workbook(); sh = wb.active
    sh.append(["姓名", "学号", "tag"]); sh.append(["张三", "1", stu_tag])
    wb.save(ws / "classes" / "A" / "roster" / "roster.xlsx")
    return ws, pack


def _plan(ws: Path, pack: dict):
    return I.build_plan(ws, task_id="p1", class_dir="classes/A", class_id="c1",
                        work_id="w1", pack=pack,
                        review_students=[{"name": "张三", "workAnswerId": "wa1",
                                          "images": ["a.jpg"]}])


# ---------------- 1) tag 等价别名：三种组合都能匹配到题 ----------------

@pytest.mark.parametrize("pad_tag,stu_tag", [
    ("copyonly", "copyonly"),   # 完全一致（本来就该通）
    ("copy", "copyonly"),       # 教师最常踩的坑
    ("copyonly", "copy"),       # 反向
    ("copysp", "copyonly"),     # 其它抄写别名
])
def test_copy_tag_aliases_match(tmp_path, pad_tag, stu_tag):
    ws, pack = _ws_with_pack(tmp_path, pad_tag=pad_tag, stu_tag=stu_tag)
    stu = _plan(ws, pack)["students"][0]
    assert stu["padId"] == "pad-co", f"{pad_tag=} {stu_tag=} 应匹配到作业纸"
    assert len(stu["questions"]) == 1


def test_pick_pad_for_tag_uses_alias(tmp_path):
    ws, pack = _ws_with_pack(tmp_path, pad_tag="copy", stu_tag="copyonly")
    ctx = P.pack_context(ws, pack)
    assert P.pick_pad_for_tag(ctx, "copyonly") is not None
    assert P.pick_pad_for_tag(ctx, "COPYONLY") is not None      # 大小写归一
    assert P.pick_pad_for_tag(ctx, "qa") is None                # 不相关 tag 不得乱匹配


def test_alias_never_leaves_the_pack(tmp_path):
    """等价兜底只在本包内找；包里没有抄写纸就必须返回 None（D127 红线）。"""
    ws, pack = _ws_with_pack(tmp_path, pad_tag="qa", stu_tag="copyonly")
    ctx = P.pack_context(ws, pack)
    assert P.pick_pad_for_tag(ctx, "copyonly") is None


# ---------------- 2) 端到端：copyonly 学生能产出 分数 + 批语 ----------------

def _run(tmp_path, pad_tag, stu_tag, monkeypatch):
    import assist.grading.evaluate as EV
    ws, pack = _ws_with_pack(tmp_path, pad_tag=pad_tag, stu_tag=stu_tag)
    (ws / "settings.local.json").write_text(json.dumps(
        {"llm": {"base_url": "http://x", "api_key": "k", "model": "m"}}), encoding="utf-8")
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
        return {"question_match": {"status": True, "match": True},
                "questions": [{"id": "1", "reasoning": {"status": "ok", "note": "抄写完整"},
                               "correct_points": ["与主题一致"], "errors": [],
                               "confidence": "high", "has_diagram": True,
                               "topic_match": "match", "answer_chars": 120}],
                "has_signature": True, "summary": "良好", "guidance": "继续",
                "strengths": [], "weaknesses": []}
    # 注意：`flow.evaluate_student` 就是 evaluate 模块里的同一个函数，
    # 其 __globals__ 即 evaluate 模块字典 —— 只 patch 一次即可（重复 patch 会恢复错乱）
    monkeypatch.setattr(EV, "analyze", fake_analyze)
    flow.run_task(tp, ws, plan=plan, class_dir="classes/A", students=["张三"], force=True)
    return base


@pytest.mark.parametrize("pad_tag,stu_tag", [("copy", "copyonly"), ("copyonly", "copyonly")])
def test_copyonly_student_gets_score_and_comment(tmp_path, pad_tag, stu_tag, monkeypatch):
    base = _run(tmp_path, pad_tag, stu_tag, monkeypatch)
    ev = json.loads((base / "evaluations" / "张三.json").read_text(encoding="utf-8"))
    assert ev["total_score"] == 100
    assert ev["feedback_md"].strip(), "必须有批语"
    assert ev["per_question_rules"][0]["rules"] == ["topicMatch"]
    # 草稿里必须有 ai.score + ai.comment（界面据此显示"已评阅"）
    from assist.xxt import grade_store as GS
    drafts = GS.read_drafts_normalized(None, "c1", "w1", ws=tmp_path,
                                       class_dir="classes/A", task_id="p1")
    d = next(iter(drafts.values()))
    assert d["ai"]["score"] == 100 and d["ai"]["comment"].strip()


# ---------------- 3) 跳过必须可见：逐生补批全军覆没 → 可读错误 ----------------

def test_single_student_skip_raises_readable_error(tmp_path, monkeypatch):
    """tag 完全对不上时（如作业纸是 qa、学生是 copyonly），不能再"假成功"。"""
    import assist.grading.evaluate as EV
    ws, pack = _ws_with_pack(tmp_path, pad_tag="qa", stu_tag="copyonly")
    (ws / "settings.local.json").write_text(json.dumps(
        {"llm": {"base_url": "http://x", "api_key": "k", "model": "m"}}), encoding="utf-8")
    plan = _plan(ws, pack)
    I.save_plan(ws, "classes/A", plan)
    task = {"id": "p1", "pack_id": "p1", "class_dir": "classes/A",
            "grade": {"steps": ["evaluate"]}, "items": []}
    tp = ws / "t.json"; tp.write_text(json.dumps(task), encoding="utf-8")
    base = flow.grading_dir(ws, task)
    (base / "transcripts").mkdir(parents=True, exist_ok=True)
    (base / "transcripts" / "张三.json").write_text(json.dumps(
        {"student": "张三", "items": [], "model": "m"}), encoding="utf-8")
    monkeypatch.setattr(EV, "analyze", lambda *a, **k: {})
    with pytest.raises(flow.GradingInputError) as ei:
        flow.run_task(tp, ws, plan=plan, class_dir="classes/A", students=["张三"], force=True)
    msg = str(ei.value)
    assert "没有可用的作业纸题目" in msg
    assert "张三" in msg

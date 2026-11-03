"""D126-B：教师总结报告（易错知识点汇总 + 共现 + 得分率；只给教师）。

数据源完全复用 D127/D130/D131 已备好的产物，**不调 LLM**（纯组装）。
覆盖：易错点排序 / 共现阈值 / 逐题得分率（含多题满分分摊）/ 题型维度 /
本章遗漏知识点 / 分数段 / 渲染 / CLI / 与流程集成 / 防御性输入。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from assist.grading import teacher_report as T


def _rec(stu: str, score, *, errs=(), missing=(), kinds=None,
         per_q=None) -> dict:
    """构造一条 evaluations 记录（errs: 每题一个知识点列表）。"""
    questions = []
    for i, ks in enumerate(errs, start=1):
        questions.append({"id": i, "errors": [
            {"knowledge": list(ks), "description": f"第{i}题出错",
             "confidence": "high"}]})
    kinds = kinds or ["problems"] * len(errs)
    return {
        "student": stu, "total_score": score,
        "analysis": {"questions": questions},
        "per_question_scores": per_q if per_q is not None else [score] * len(errs),
        "per_question_rules": [{"id": i, "kind": kinds[i - 1], "deduct": 5}
                               for i in range(1, len(errs) + 1)],
        "knowledge_missing": list(missing),
    }


# ---------------- 易错知识点 ----------------
def test_knowledge_errors_ranked_by_students():
    recs = [
        _rec("张三", 80, errs=[["动量守恒"], ["动量守恒", "完全弹性碰撞"]]),
        _rec("李四", 75, errs=[["动量守恒"], ["完全弹性碰撞"]]),
        _rec("王五", 95, errs=[[]]),
    ]
    st = T.analyze(recs)
    top = {x["term"]: x for x in st["knowledge_errors"]}
    assert top["动量守恒"]["students"] == 2      # 张三、李四（同生同点只计一次）
    assert top["完全弹性碰撞"]["students"] == 2
    assert st["knowledge_errors"][0]["students"] >= st["knowledge_errors"][-1]["students"]
    assert "1" in top["动量守恒"]["questions"]


def test_same_student_same_term_counted_once():
    recs = [_rec("张三", 70, errs=[["动量守恒"], ["动量守恒"]])]
    st = T.analyze(recs)
    assert st["knowledge_errors"][0]["students"] == 1


def test_low_confidence_excluded_from_stats():
    """低置信度错误不计分（D98-B5），教师统计也必须排除，否则清单被幻觉污染。"""
    rec = {"student": "张三", "total_score": 90, "analysis": {"questions": [
        {"id": 1, "errors": [
            {"knowledge": ["真实错误"], "description": "x", "confidence": "high"},
            {"knowledge": ["幻觉错误"], "description": "y", "confidence": "low"}]}]},
        "per_question_scores": [90], "per_question_rules": [{"id": 1, "kind": "problems"}]}
    st = T.analyze([rec])
    terms = [x["term"] for x in st["knowledge_errors"]]
    assert "真实错误" in terms and "幻觉错误" not in terms


# ---------------- 共现 ----------------
def test_cooccurrence_requires_threshold():
    recs = [
        _rec("张三", 70, errs=[["动量守恒", "完全弹性碰撞"]]),
        _rec("李四", 70, errs=[["动量守恒", "完全弹性碰撞"]]),
        _rec("王五", 90, errs=[["孤立知识点", "另一个"]]),   # 只 1 人 → 不展示
    ]
    st = T.analyze(recs)
    pairs = {(x["a"], x["b"]): x for x in st["cooccurrence"]}
    assert ("动量守恒", "完全弹性碰撞") in pairs
    assert pairs[("动量守恒", "完全弹性碰撞")]["students"] == 2
    assert ("另一个", "孤立知识点") not in pairs


# ---------------- 逐题得分率 ----------------
def test_question_rate_uses_per_question_full_marks():
    """满分按题数分摊（与 scoring 的均分基线同口径），不是"全班 100 分"。"""
    recs = [
        {"student": "张三", "total_score": 50, "per_question_scores": [0, 50],
         "per_question_rules": [{"id": 1, "kind": "problems"}, {"id": 2, "kind": "problems"}],
         "analysis": {"questions": []}},
        {"student": "李四", "total_score": 50, "per_question_scores": [50, 0],
         "per_question_rules": [{"id": 1, "kind": "problems"}, {"id": 2, "kind": "problems"}],
         "analysis": {"questions": []}},
    ]
    st = T.analyze(recs)
    rates = {x["id"]: x for x in st["question_rates"]}
    assert rates["1"]["max_possible"] == 50.0
    assert rates["1"]["avg_score"] == 25.0 and rates["1"]["rate"] == 0.5
    assert all(x["rate"] <= 1.0 for x in st["question_rates"])


def test_question_rate_sorted_ascending():
    recs = [{"student": "张三", "total_score": 40,
             "per_question_scores": [10, 30],
             "per_question_rules": [{"id": 1}, {"id": 2}],
             "analysis": {"questions": []}}]
    rates = T.analyze(recs)["question_rates"]
    assert rates[0]["rate"] <= rates[-1]["rate"]


# ---------------- 题型 / 遗漏 / 分数段 ----------------
def test_kind_stats_grouped():
    recs = [_rec("张三", 70, errs=[["a"], ["b"]], kinds=["qa", "summary"])]
    ks = {x["kind"]: x for x in T.analyze(recs)["kind_stats"]}
    assert ks["qa"]["questions"] == 1 and ks["summary"]["questions"] == 1


def test_knowledge_missing_counted():
    recs = [_rec("张三", 70, errs=[["a"]], missing=["完全弹性碰撞"]),
            _rec("李四", 70, errs=[["a"]], missing=["完全弹性碰撞"])]
    ms = T.analyze(recs)["missing"]
    assert ms[0]["term"] == "完全弹性碰撞" and ms[0]["students"] == 2
    assert ms[0]["rate"] == 1.0


def test_segments_and_averages():
    recs = [_rec("a", 95, errs=[["x"]]), _rec("b", 85, errs=[["x"]]),
            _rec("c", 55, errs=[["x"]])]
    st = T.analyze(recs)
    assert st["students"] == 3
    assert st["segments"]["90-100"] == 1 and st["segments"]["<60"] == 1
    assert st["avg"] == round((95 + 85 + 55) / 3, 1)


def test_substitution_and_manual_flagged():
    r1 = _rec("张三", 80, errs=[["x"]]); r1["verdict"] = "suspected-substitution"
    r2 = _rec("李四", 80, errs=[["x"]]); r2["_manual_review"] = True
    st = T.analyze([r1, r2])
    assert st["substitution"] == 1 and st["manual"] == 1


# ---------------- 防御性：knowledge 可能是字符串 ----------------
def test_knowledge_as_string_not_split_into_chars():
    """旧模型偶尔把 knowledge 给成 "动量守恒" 字符串；
    若直接遍历会被拆成单个汉字（曾把 1 个知识点统计成 4 个）。"""
    rec = {"student": "张三", "total_score": 80, "analysis": {"questions": [
        {"id": 1, "errors": [{"knowledge": "动量守恒", "description": "x",
                              "confidence": "high"}]}]},
        "per_question_scores": [80], "per_question_rules": [{"id": 1}]}
    terms = [x["term"] for x in T.analyze([rec])["knowledge_errors"]]
    assert terms == ["动量守恒"]


def test_knowledge_none_and_empty_safe():
    rec = {"student": "张三", "total_score": 100, "analysis": {"questions": [
        {"id": 1, "errors": [{"knowledge": None, "confidence": "high"},
                             {"knowledge": [], "confidence": "high"}]}]},
        "per_question_scores": [100], "per_question_rules": [{"id": 1}]}
    assert T.analyze([rec])["knowledge_errors"] == []


def test_empty_records_do_not_crash():
    st = T.analyze([])
    assert st["students"] == 0
    assert T.render_md(st).count("暂无评阅结果") == 1


# ---------------- 渲染 ----------------
def test_render_contains_all_sections():
    recs = [
        _rec("张三", 80, errs=[["动量守恒"], ["动量守恒", "完全弹性碰撞"]],
             missing=["完全弹性碰撞"]),
        _rec("李四", 60, errs=[["动量守恒"], ["完全弹性碰撞"]]),
    ]
    st = T.analyze(recs)
    md = T.render_md(st, title="第1次作业", subtitle="classes/化工25")
    for sec in ("教师总结报告", "统计概览", "易错知识点", "共现", "逐题得分率",
                "按题目来源", "本章遗漏知识点", "学生明细"):
        assert sec in md, f"缺少章节：{sec}"
    assert "动量守恒" in md and "完全弹性碰撞" in md
    assert "不发给学生" in md          # 明确"只给教师"
    assert "第1次作业" in md and "classes/化工25" in md


# ---------------- 落盘 + CLI ----------------
def test_generate_writes_md_and_stats(tmp_path: Path):
    ev = tmp_path / "evaluations"
    ev.mkdir()
    (ev / "张三.json").write_text(json.dumps(_rec("张三", 80, errs=[["动量守恒"]]),
                                             ensure_ascii=False), encoding="utf-8")
    (ev / "李四.json").write_text(json.dumps(_rec("李四", 90, errs=[["动量守恒"]]),
                                             ensure_ascii=False), encoding="utf-8")
    # 下划线开头的汇总文件必须被忽略
    (ev / "_summary.json").write_text(json.dumps({"oops": 1}), encoding="utf-8")
    out = tmp_path / "reports"
    rep = T.generate(ev, out, title="作业1")
    assert rep["ok"] and rep["students"] == 2
    md = (out / "_teacher_report.md").read_text(encoding="utf-8")
    assert "动量守恒" in md
    stats = json.loads((out / "_teacher_report.stats.json").read_text(encoding="utf-8"))
    assert stats["students"] == 2 and stats["knowledge_errors"][0]["term"] == "动量守恒"


def test_generate_skips_corrupt_file(tmp_path: Path):
    ev = tmp_path / "evaluations"
    ev.mkdir()
    (ev / "good.json").write_text(json.dumps(_rec("张三", 80, errs=[["x"]]),
                                             ensure_ascii=False), encoding="utf-8")
    (ev / "bad.json").write_text("{not json", encoding="utf-8")
    rep = T.generate(ev, tmp_path / "r")
    assert rep["ok"] and rep["students"] == 1


def test_cli_teacher_report(tmp_path: Path):
    from click.testing import CliRunner
    from assist.cli import cli
    from assist.grading.flow import grading_dir

    ws = tmp_path
    task = {"id": "task1", "class_dir": "classes/化工25", "items": []}
    base = grading_dir(ws, task)
    (base / "evaluations").mkdir(parents=True, exist_ok=True)
    (base / "evaluations" / "张三.json").write_text(
        json.dumps(_rec("张三", 80, errs=[["动量守恒"]]), ensure_ascii=False),
        encoding="utf-8")
    task_file = ws / "t.taskpad.json"
    task_file.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
    out = CliRunner().invoke(cli, ["teacher-report", "--task", str(task_file),
                                   "-w", str(ws)])
    assert out.exit_code == 0, out.output
    assert (base / "reports" / "_teacher_report.md").is_file()


def test_cli_teacher_report_requires_evaluations(tmp_path: Path):
    from click.testing import CliRunner
    from assist.cli import cli
    task = {"id": "task2", "class_dir": "classes/化工25", "items": []}
    task_file = tmp_path / "t.taskpad.json"
    task_file.write_text(json.dumps(task), encoding="utf-8")
    out = CliRunner().invoke(cli, ["teacher-report", "--task", str(task_file),
                                   "-w", str(tmp_path)])
    assert out.exit_code != 0
    assert "没有评阅结果" in out.output

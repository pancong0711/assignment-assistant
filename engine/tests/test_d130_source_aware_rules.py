"""D130-P1a：按题目来源分型的评阅规则（T0/T1/T2/T3/T4/T11）。

覆盖验收标准（docs/78 §5）：
1. 同一份作业中 `qa` 与 `problems` 按**各自规则**扣分，报告标明来源与规则；
3. `qa` 缺要点按 missingPoints 扣分；`distinguish` 按长度档扣分、逻辑错误不扣但产生提问；
4. 「整体简略」仅 ≥80% 题目触发时对**总分**一次性 −5；
2. 规则参数修改后新批阅生效（已生成报告不变由"报告纯组装"保证，见 D127）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from assist.grading import rules as R
from assist.grading.evaluate import build_user_prompt, score_from_analysis
from assist.grading.prompts import KIND_OUTPUT_SCHEMA_HINT, kind_output_hint


# ---------------- 工具 ----------------
def _q(qid, *, kind=None, has_diagram=True, errors=(), reasoning="ok",
       key_points=None, copied=None, covered=None, answer_chars=None, relevance=None,
       question_text="", answer_text="", topic_match=None):
    q = {"id": qid, "reasoning": {"status": reasoning, "note": "",
                                  "question_text": question_text},
         "correct_points": [], "errors": list(errors), "confidence": "high",
         "has_diagram": has_diagram, "question_text": question_text,
         "answer_text": answer_text}
    if kind:
        q["kind"] = kind
    if key_points is not None:
        q["key_points"] = key_points
    if copied is not None:
        q["copied"] = copied
    if topic_match is not None:
        q["topic_match"] = topic_match
    if covered is not None:
        q["covered"] = covered
    if answer_chars is not None:
        q["answer_chars"] = answer_chars
    if relevance is not None:
        q["relevance"] = relevance
    return q


def _analysis(questions, *, has_signature=True):
    return {"question_match": {"status": True, "match": True, "note": "", "evidence": "",
                               "reason": ""},
            "questions": questions, "has_signature": has_signature, "summary": "",
            "guidance": "", "strengths": [], "weaknesses": []}


def _err(conf="high"):
    return {"step": "s", "description": "d", "guidance": "g", "deduct": 5,
            "evidence": "e", "confidence": conf, "why": "w", "knowledge": []}


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    (tmp_path / "kb").mkdir()
    return tmp_path


# ---------------- T0：来源透传 ----------------
def test_expand_items_passes_kb_and_normalized_kind(ws: Path):
    """T0：`expand_items` 必须把题库表名透传为 kb/kind（此前算了却不写）。"""
    from assist.files.kb_io import write_xlsx
    write_xlsx(ws / "kb" / "qa.xlsx",
               {"chap01": [{"id": "c1", "content": "什么是惯性？",
                            "solution": "惯性是…", "related": "惯性，牛顿第一定律"}]})
    from assist.grading.flow import expand_items
    out = expand_items(ws, {"items": [{"kb": "qa", "chap": "chap01"}]})
    assert out and out[0]["kb"] == "qa" and out[0]["kind"] == "qa"
    assert out[0]["related"] == "惯性，牛顿第一定律"


def test_questions_of_passes_kind(ws: Path):
    from assist.grading.inputs import _questions_of
    out = _questions_of({"items": [{"no": "1", "kb": "copyonly", "content": "抄写 xxx"}]}, ws)
    assert out[0]["kb"] == "copyonly" and out[0]["kind"] == "copy"


@pytest.mark.parametrize("raw,kind", [
    ("copys", "copy"), ("copyonly", "copy"), ("copysp", "copy"), ("punish", "copy"),
    ("COPY", "copy"), ("qa", "qa"), ("summary", "summary"), ("", "problems"),
    ("unknown-thing", "problems"),
])
def test_kind_alias_normalization(raw, kind):
    assert R.normalize_kind(raw) == kind


# ---------------- T1：规则文件 ----------------
def test_rules_file_written_with_defaults_on_first_read(ws: Path):
    data = R.read_rules(ws)
    p = ws / R.RULES_FILE
    assert p.is_file()
    assert json.loads(p.read_text(encoding="utf-8"))["types"]["qa"]["mode"] == "missingPoints"
    assert data["global"]["briefProcessDeduct"] == 5


def test_rules_corrupt_file_falls_back_and_is_not_overwritten(ws: Path):
    p = ws / R.RULES_FILE
    p.write_text("{not json", encoding="utf-8")
    data = R.read_rules(ws)
    assert data["types"]["copy"]["mode"] == "topicMatch"   # D170-T9
    assert p.read_text(encoding="utf-8") == "{not json"  # 用户文件保留，便于人工救回


def test_rules_user_file_missing_section_backfilled(ws: Path):
    (ws / R.RULES_FILE).write_text(json.dumps({"global": {"briefProcessDeduct": 7}}),
                                   encoding="utf-8")
    data = R.read_rules(ws)
    assert data["global"]["briefProcessDeduct"] == 7
    assert data["global"]["allBriefRatio"] == 0.8      # 缺字段补默认
    assert data["types"]["problems"]["mode"] == "errorCount"


def test_write_rules_validates_range_and_journals(ws: Path):
    bad = R.read_rules(ws)
    bad["global"]["allBriefRatio"] = 3.5
    res = R.write_rules(ws, bad)
    assert res["ok"] is False and any("allBriefRatio" in e for e in res["errors"])

    good = R.read_rules(ws)
    good["global"]["briefProcessDeduct"] = 8
    res = R.write_rules(ws, good)
    assert res["ok"] is True
    assert any(c["path"] == "global.briefProcessDeduct" for c in res["changes"])
    jl = (ws / "grading-rules.journal.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(jl[-1])["changes"][0]["new"] == 8
    # 落盘生效
    assert R.global_rules(ws)["briefProcessDeduct"] == 8


def test_reset_rules_restores_defaults(ws: Path):
    r = R.read_rules(ws)
    r["types"]["qa"]["perMissingPointDeduct"] = 9
    R.write_rules(ws, r)
    R.reset_rules(ws)
    assert R.type_rules(ws, "qa")["perMissingPointDeduct"] == 5


def test_validate_rejects_bad_mode_and_checklist(ws: Path):
    r = R.read_rules(ws)
    r["types"]["qa"]["mode"] = "whatever"
    r["types"]["copy"]["checklist"] = []
    errs = R.validate_rules(r)
    assert any("mode" in e for e in errs) and any("checklist" in e for e in errs)


# ---------------- T2/T11：prompt 按来源分型 ----------------
def test_prompt_injects_per_kind_rules_and_source(ws: Path):
    items = [{"序号": 1, "content": "求加速度", "solution": "a=F/m", "tag": "q1",
              "kb": "problems", "kind": "problems", "related": "牛顿第二定律"},
             {"序号": 2, "content": "什么是惯性", "solution": "惯性是…", "tag": "q1",
              "kb": "qa", "kind": "qa", "related": "惯性"}]
    p = build_user_prompt(items, "学生作答", "张三", ws=ws)
    # 两种范式各自的规则摘要都在
    assert "评阅范式：problems" in p and "评阅范式：qa" in p
    assert "每个未答到的评阅要点扣 5 分" in p
    assert "每处明确错误扣 5 分" in p
    assert "来源: problems" in p and "来源: qa" in p
    # T11：知识点术语优先沿用
    assert "优先原样使用这些术语" in p
    assert "牛顿第二定律" in p


def test_prompt_follows_modified_rules(ws: Path):
    """规则卡改数值 → prompt 里的规则摘要同步变化（新批阅生效）。"""
    r = R.read_rules(ws)
    r["types"]["qa"]["perMissingPointDeduct"] = 8
    R.write_rules(ws, r)
    p = build_user_prompt([{"序号": 1, "content": "q", "kb": "qa", "kind": "qa"}], "x", ws=ws)
    assert "每个未答到的评阅要点扣 8 分" in p


def test_every_supported_kind_has_output_hint():
    for k in R.SUPPORTED_KINDS:
        assert kind_output_hint(k), f"{k} 缺输出要求"
    assert set(KIND_OUTPUT_SCHEMA_HINT) == set(R.SUPPORTED_KINDS)


# ---------------- T3：计分按 mode 分派 ----------------
def test_error_count_matches_legacy(ws: Path):
    """problems/errorCount：与旧规则等价（每错 −5、单题上限 20）。"""
    a = _analysis([_q(1, kind="problems", errors=[_err()] * 5)])
    r = score_from_analysis(a, ws=ws)
    assert r["total_score"] == 80        # 5×5=25 → 上限 20

def test_error_count_uses_rule_value(ws: Path):
    rules = R.read_rules(ws)
    rules["types"]["problems"]["perErrorDeduct"] = 3
    R.write_rules(ws, rules)
    a = _analysis([_q(1, kind="problems", errors=[_err(), _err()])])
    assert score_from_analysis(a, ws=ws)["total_score"] == 94


def test_qa_missing_points_deduct(ws: Path):
    a = _analysis([_q(1, kind="qa", key_points=[
        {"point": "要点A", "answered": True, "evidence": "x"},
        {"point": "要点B", "answered": False, "evidence": ""},
    ])])
    r = score_from_analysis(a, ws=ws)
    assert r["total_score"] == 95
    assert any("未答到 1 个评阅要点" in d for d in r["deductions"])
    assert r["per_question_rules"][0]["kind"] == "qa"


def test_qa_missing_diagram_deduct(ws: Path):
    a = _analysis([_q(1, kind="qa", has_diagram=False, key_points=[
        {"point": "A", "answered": True, "evidence": "x"}])])
    r = score_from_analysis(a, ws=ws)
    assert r["total_score"] == 95
    assert any("缺示意图" in d for d in r["deductions"])


def test_checklist_mode_deduct(ws: Path):
    """checklist 模式：每缺一项扣一次。

    D170-T9：`copy` 的默认模式已改为 `topicMatch`（抄写题不再判"抄全三项"），
    所以这里**显式**把文档类题型设为 checklist 来测该模式本身。
    """
    # 用已支持的 kind（copy 默认已改 topicMatch）临时改成 checklist 来测该模式本身
    data = R.read_rules(ws)
    data["types"]["distinguish"] = {"mode": "checklist", "perMissingItemDeduct": 5,
                                    "checklist": ["题目", "解题过程", "示意图"],
                                    "requireDiagram": "if_question_has"}
    assert R.write_rules(ws, data)["ok"]
    a = _analysis([_q(1, kind="distinguish", copied={"题目": True, "解题过程": False,
                                                     "示意图": False})])
    r = score_from_analysis(a, ws=ws)
    assert r["total_score"] == 90
    assert any("未完成 2 项" in d for d in r["deductions"])


def test_copy_topic_match_no_checklist_deduct(ws: Path):
    """**D170-T9 核心**：抄写题不再因"没抄全三项"扣分。

    D171-T3：抄写题改判「主题 + 字数」，所以这里要给出正常的主题与字数，
    才能验证"不因抄全与否扣分"这件事。
    """
    a = _analysis([_q(1, kind="copy", copied={"题目": True, "解题过程": False,
                                             "示意图": False},
                      topic_match="match", answer_chars=200)])
    r = score_from_analysis(a, ws=ws)
    assert r["total_score"] == 100, f"抄写题不应按 checklist 扣分：{r['deductions']}"


def test_summary_covered_checklist(ws: Path):
    a = _analysis([_q(1, kind="summary", covered={"知识点与概念": True,
                                                  "重要公式及推导": False,
                                                  "示意图": True})])
    assert score_from_analysis(a, ws=ws)["total_score"] == 95


@pytest.mark.parametrize("kind", ["distinguish", "innovation", "translation"])
def test_length_based_tiers(ws: Path, kind):
    """<80% → −5；<50% → −10；完全无关 → −20；下限保护 60 字生效。"""
    # 题长 10 字 → 3×10=30 < 60 → 基准 60
    qtext = "简述动量守恒的条件及适用范围"  # 14 字 → 42 → 基准 60
    # 55 字：91% → 不扣
    a = _analysis([_q(1, kind=kind, question_text=qtext, answer_chars=55)])
    assert score_from_analysis(a, ws=ws)["total_score"] == 100
    # 40 字：67% → −5
    a = _analysis([_q(1, kind=kind, question_text=qtext, answer_chars=40)])
    assert score_from_analysis(a, ws=ws)["total_score"] == 95
    # 20 字：33% → −10
    a = _analysis([_q(1, kind=kind, question_text=qtext, answer_chars=20)])
    assert score_from_analysis(a, ws=ws)["total_score"] == 90
    # 无关 → −20
    a = _analysis([_q(1, kind=kind, question_text=qtext, answer_chars=80,
                      relevance="irrelevant")])
    assert score_from_analysis(a, ws=ws)["total_score"] == 80


def test_length_based_logic_errors_exempt(ws: Path):
    """逻辑错误豁免扣分，但提示"已转为启发式提问"。"""
    a = _analysis([_q(1, kind="distinguish", question_text="辨析动量与冲量" * 3,
                      answer_chars=200, errors=[_err(), _err()])])
    r = score_from_analysis(a, ws=ws)
    assert r["total_score"] == 100
    assert any("转为启发式提问" in d for d in r["deductions"]) or \
        any("启发式" in x for x in r["per_question_rules"][0]["detail"])


def test_mixed_kinds_scored_by_own_rules(ws: Path):
    """验收 1：同一份作业 qa 与 problems 各按自身规则扣分。"""
    a = _analysis([
        _q(1, kind="problems", errors=[_err()]),
        _q(2, kind="qa", key_points=[{"point": "A", "answered": False, "evidence": ""},
                                     {"point": "B", "answered": True, "evidence": "y"}]),
    ])
    r = score_from_analysis(a, ws=ws)
    assert r["total_score"] == 90            # 5 + 5
    kinds = {x["id"]: x["kind"] for x in r["per_question_rules"]}
    assert kinds == {1: "problems", 2: "qa"}
    assert any("errorCount" in x["rules"] for x in r["per_question_rules"])
    assert any("missingPoints" in x["rules"] for x in r["per_question_rules"])


# ---------------- T4：全局规则 ----------------
def test_brief_process_deduct_each_question(ws: Path):
    a = _analysis([_q(1, kind="problems", reasoning="brief"),
                   _q(2, kind="problems")])
    r = score_from_analysis(a, ws=ws)
    assert r["total_score"] == 95
    assert r["all_brief"] is False


def test_all_brief_only_fires_at_80_percent(ws: Path):
    """验收 4：≥80% 题目简略才额外 −5（一次性，非逐题）。"""
    # 4/5 = 80% → 触发：4×5 + 5 = 25
    a = _analysis([_q(i, kind="problems", reasoning="brief" if i <= 4 else "ok")
                   for i in range(1, 6)])
    r = score_from_analysis(a, ws=ws)
    assert r["all_brief"] is True
    assert r["total_score"] == 75
    assert any("一次性" in d for d in r["deductions"])
    # 3/5 = 60% → 不触发：3×5 = 15
    a = _analysis([_q(i, kind="problems", reasoning="brief" if i <= 3 else "ok")
                   for i in range(1, 6)])
    r = score_from_analysis(a, ws=ws)
    assert r["all_brief"] is False
    assert r["total_score"] == 85


def test_all_brief_not_double_counted_per_question(ws: Path):
    """一次性规则不会变成"每题都扣一次"。"""
    a = _analysis([_q(i, kind="problems", reasoning="brief") for i in range(1, 3)])
    r = score_from_analysis(a, ws=ws)
    # 2×5（逐题）+ 5（一次性）= 15，而不是 2×10
    assert r["total_score"] == 85
    assert sum("一次性" in d for d in r["deductions"]) == 1


def test_global_rules_configurable(ws: Path):
    rules = R.read_rules(ws)
    rules["global"].update({"briefProcessDeduct": 0, "allBriefDeduct": 0})
    R.write_rules(ws, rules)
    a = _analysis([_q(1, kind="problems", reasoning="brief")])
    assert score_from_analysis(a, ws=ws)["total_score"] == 100


def test_signature_deducted_and_cap_applied(ws: Path):
    """单题上限 20 + 无签名 −5（每题扣分受 perQuestionCap 约束）。"""
    a = _analysis([_q(1, kind="problems", errors=[_err()] * 20)], has_signature=False)
    r = score_from_analysis(a, ws=ws)
    assert r["total_score"] == 75                # 100 − 20(上限) − 5(签名)
    assert any("无签名" in d for d in r["deductions"])


def test_floor_applies_when_multiple_questions(ws: Path):
    """总分底线 40：多题累计扣分足够多时兜底。"""
    qs = [_q(i, kind="problems", errors=[_err()] * 4, reasoning="brief") for i in range(1, 6)]
    a = _analysis(qs, has_signature=False)
    r = score_from_analysis(a, ws=ws)
    assert r["total_score"] == 40
    assert r["all_brief"] is True


# ---------------- 向后兼容 ----------------
def test_without_items_behaves_like_problems(ws: Path):
    a = _analysis([_q(1, errors=[_err()])])
    r = score_from_analysis(a, ws=ws)
    assert r["total_score"] == 95
    assert r["per_question_rules"][0]["kind"] == "problems"


def test_rule_summary_mentions_mode_specifics(ws: Path):
    assert "3 倍" in R.rule_summary(ws, "distinguish")
    # D170-T9：copy 改为 topicMatch，摘要讲"主题一致 + 字数"
    copy_sum = R.rule_summary(ws, "copy")
    assert "主题" in copy_sum and "字数" in copy_sum
    assert "评阅要点" in R.rule_summary(ws, "qa")
    assert R.rubric_enabled(ws, "qa") is True
    assert R.rubric_enabled(ws, "copy") is False
    assert R.rubric_enabled(ws, "summary") is False


# ---------------- CLI：rules show / set / reset / summary ----------------
def test_cli_rules_show_set_reset(tmp_path: Path):
    from click.testing import CliRunner
    from assist.cli import cli
    r = CliRunner()
    args = ["rules"]
    w = ["-w", str(tmp_path)]
    out = r.invoke(cli, args + ["show"] + w)
    assert out.exit_code == 0, out.output
    assert '"briefProcessDeduct": 5' in out.output
    assert (tmp_path / R.RULES_FILE).is_file()

    out = r.invoke(cli, args + ["set", "--path",
                                "types.qa.perMissingPointDeduct", "--value", "8"] + w)
    assert out.exit_code == 0, out.output
    assert json.loads(out.output)["ok"] is True
    assert R.type_rules(tmp_path, "qa")["perMissingPointDeduct"] == 8

    out = r.invoke(cli, args + ["summary", "--kind", "qa"] + w)
    assert "每个未答到的评阅要点扣 8 分" in out.output

    out = r.invoke(cli, args + ["reset"] + w)
    assert out.exit_code == 0
    assert R.type_rules(tmp_path, "qa")["perMissingPointDeduct"] == 5


def test_cli_rules_set_rejects_out_of_range(tmp_path: Path):
    from click.testing import CliRunner
    from assist.cli import cli
    r = CliRunner()
    out = r.invoke(cli, ["rules", "set", "--path",
                         "global.allBriefRatio", "--value", "5", "-w", str(tmp_path)])
    assert out.exit_code != 0
    assert R.global_rules(tmp_path)["allBriefRatio"] == 0.8


# ---------------- 端到端：prompt → analysis → 分派计分 → 报告 ----------------
class _FakeClient:
    """假 LLM：记录收到的 prompt，返回固定 analysis（verify 传导与分派）。"""
    evaluation_model = "fake-eval"

    def __init__(self, analysis: dict):
        self.analysis = analysis
        self.last_prompt = ""

    def chat(self, *, system_prompt, user_text, model=None, temperature=0.2, **kw):
        self.last_prompt = user_text
        return json.dumps(self.analysis, ensure_ascii=False)


def _transcript(tmp_path: Path, items):
    p = tmp_path / "张三.json"
    p.write_text(json.dumps({"student": "张三", "model": "fake-tr",
                             "items": items}, ensure_ascii=False), encoding="utf-8")
    return p


def test_end_to_end_mixed_kinds(tmp_path: Path):
    """验收 1 端到端：qa 与 problems 各按自身规则扣分，报告标明来源与规则。"""
    from assist.grading.evaluate import evaluate_student
    from assist.grading.report import build_report_md

    items = [
        {"序号": 1, "content": "求加速度 a", "solution": "a=F/m", "kind": "problems",
         "kb": "problems", "tag": "q1"},
        {"序号": 2, "content": "什么是惯性", "solution": "惯性是…", "kind": "qa",
         "kb": "qa", "tag": "q1"},
    ]
    analysis = _analysis([
        _q(1, kind="problems", errors=[_err()]),
        _q(2, kind="qa", key_points=[
            {"point": "物体保持运动状态的性质", "answered": False, "evidence": ""}]),
    ])
    client = _FakeClient(analysis)
    tf = _transcript(tmp_path, [
        {"no": "1", "printed_question": "求加速度 a", "answer": "a=F/m = 2", "diagrams": []},
        {"no": "2", "printed_question": "什么是惯性",
         "answer": "惯性就是物体有惯性。", "diagrams": []},
    ])
    out = evaluate_student(client, tf, items, tmp_path / "eval", ws=tmp_path)
    res = json.loads(out.read_text(encoding="utf-8"))
    assert res["total_score"] == 90
    kinds = {r["id"]: r["kind"] for r in res["per_question_rules"]}
    assert kinds == {1: "problems", 2: "qa"}
    # prompt 里两种范式都在（说明来源真的传到了评阅端）
    assert "评阅范式：problems" in client.last_prompt
    assert "评阅范式：qa" in client.last_prompt
    # 报告标明来源与规则
    md = build_report_md(tf, out)
    assert "评分依据（按题目来源）" in md
    assert "第1题 · 来源：problems" in md and "第2题 · 来源：qa" in md
    assert "missingPoints" in md


def test_end_to_end_enriches_question_and_answer_text(tmp_path: Path):
    """长度档依赖的题面/作答原文由 Python 从转写补齐（不信模型自报字数）。"""
    from assist.grading.evaluate import evaluate_student
    qtext = "辨析动量与冲量的区别及其在碰撞问题中的适用条件"   # 24 字 → 基准 72
    items = [{"序号": 1, "content": qtext, "kind": "distinguish", "kb": "distinguish"}]
    # 模型谎报 500 字；转写原文只有 10 字 → 应按 Python 统计判为过短
    analysis = _analysis([_q(1, kind="distinguish", answer_chars=500)])
    tf = _transcript(tmp_path, [{"no": "1", "printed_question": qtext,
                                 "answer": "动量是 mv", "diagrams": []}])
    out = evaluate_student(_FakeClient(analysis), tf, items, tmp_path / "eval", ws=tmp_path)
    res = json.loads(out.read_text(encoding="utf-8"))
    assert res["total_score"] < 100
    assert res["per_question_rules"][0]["kind"] == "distinguish"

"""D126：逐生审核显示原图/转写/批语 + 报告拆分「转写 / 批阅」+ 分步文案。

用户反馈：
1. 点「仅转录」仍显示「AI 批阅」字样；
2. 逐生审核看不到该生作答原图、转写、批阅内容；
3. 报告应包含「转写」与「批阅」两部分（发学生学习对照）。
"""
import json
from pathlib import Path

from assist.grading import drafts as D
from assist.grading import inputs as I
from assist.grading.report import build_report_md
from assist.xxt import grade_store


# ---------------- 转录写入草稿（逐生审核可见） ----------------

def test_save_transcripts_to_drafts(tmp_path):
    """D126：仅转录也要把 AI 转写写入草稿 `ai.transcript`，否则逐生审核什么都看不到。"""
    ws = tmp_path / "ws"
    tdir = ws / "classes/化工25/grading/t1/transcripts"
    tdir.mkdir(parents=True)
    (tdir / "张三.json").write_text(json.dumps(
        {"student": "张三", "markdown": "1. F=ma 得 a=2", "model": "qwen3.7-flash"},
        ensure_ascii=False), encoding="utf-8")
    I.save_plan(ws, "classes/化工25", {
        "taskId": "t1", "classDir": "classes/化工25",
        "students": [{"name": "张三", "workAnswerId": "wa-1", "tag": "t"}]})

    n = D.save_transcripts_to_drafts(ws, class_id="c1", work_id="w1", task_id="t1",
                                     class_dir="classes/化工25", transcripts_dir=tdir)
    assert n == 1
    d = grade_store.read_drafts(ws, "c1", "w1", ws=ws,
                                class_dir="classes/化工25", task_id="t1")
    assert d["wa-1"]["ai"]["transcript"] == "1. F=ma 得 a=2"
    assert d["wa-1"]["ai"]["transcriptModel"] == "qwen3.7-flash"


def test_save_transcripts_does_not_clobber_existing_ai_fields(tmp_path):
    """写转写不得清掉已有 ai.score / ai.comment。"""
    ws = tmp_path / "ws"
    tdir = ws / "classes/A/grading/t1/transcripts"
    tdir.mkdir(parents=True)
    (tdir / "张三.json").write_text(json.dumps(
        {"student": "张三", "markdown": "转写内容"}, ensure_ascii=False), encoding="utf-8")
    grade_store.save_draft_sets(None, "c1", "w1", "张三",
                                ai={"score": 88, "comment": "好"}, ws=ws,
                                class_dir="classes/A", task_id="t1")
    D.save_transcripts_to_drafts(ws, class_id="c1", work_id="w1", task_id="t1",
                                 class_dir="classes/A", transcripts_dir=tdir)
    d = grade_store.read_drafts(ws, "c1", "w1", ws=ws, class_dir="classes/A", task_id="t1")
    assert d["张三"]["ai"]["score"] == 88, "不得清掉已有分数"
    assert d["张三"]["ai"]["comment"] == "好", "不得清掉已有批语"
    assert d["张三"]["ai"]["transcript"] == "转写内容"


def test_save_transcripts_empty_dir_returns_zero(tmp_path):
    ws = tmp_path / "ws"
    assert D.save_transcripts_to_drafts(ws, class_id="c", work_id="w", task_id="t",
                                        class_dir="classes/A",
                                        transcripts_dir=tmp_path / "nope") == 0


# ---------------- 报告结构：转写 + 批阅 ----------------

def _mk_report_files(tmp_path: Path):
    t = tmp_path / "张三.json"
    e = tmp_path / "张三_eval.json"
    t.write_text(json.dumps({"student": "张三",
                             "markdown": "1. 由 F=ma 得 a=2",
                             "model": "qwen3.7-flash"}, ensure_ascii=False), encoding="utf-8")
    e.write_text(json.dumps({"student": "张三", "total_score": 88,
                             "deductions": ["第2题 扣5分"],
                             "feedback_md": "### 第 2 题\n- ❌ **问题：**单位错\n  - **想一想：**量纲是什么？",
                             "model": "deepseek-v4.1-flash"}, ensure_ascii=False), encoding="utf-8")
    return t, e


def test_report_has_transcript_section_first(tmp_path):
    """D126：报告分为「一、AI 转写」+「二、AI 批阅」两部分，转写在前。"""
    t, e = _mk_report_files(tmp_path)
    md = build_report_md(t, e)
    assert "## 一、AI 转写" in md
    assert "## 二、AI 批阅" in md
    assert md.index("## 一、AI 转写") < md.index("## 二、AI 批阅"), "转写应在批阅之前"
    # 转写内容与批语都要在
    assert "由 F=ma 得 a=2" in md
    assert "总分：88 / 100" in md
    assert "想一想" in md, "启发式提问应在批阅部分"
    assert "识别偏差" in md, "应说明转写仅供对照"


def test_report_both_models_listed(tmp_path):
    t, e = _mk_report_files(tmp_path)
    md = build_report_md(t, e)
    assert "qwen3.7-flash" in md and "deepseek-v4.1-flash" in md


def test_report_still_has_score_and_deductions(tmp_path):
    t, e = _mk_report_files(tmp_path)
    md = build_report_md(t, e)
    assert "扣分明细" in md and "第2题 扣5分" in md


# ---------------- D126-FIX：部分失败中止时，已成功的转写也要可见 ----------------

def test_partial_failure_still_persists_successful_transcripts(tmp_path, monkeypatch):
    """回归：转录"部分失败 → 默认中止"时，已成功学生的转写仍必须进草稿。

    原实现只在 step 循环之后写草稿，而 `_run_transcribe` 部分失败会 raise，
    导致「仅转录」最常见的情形（有学生限流/读图失败）逐生审核里一片空白。
    """
    import pytest
    from assist.grading import flow

    ws = tmp_path / "ws"; ws.mkdir()
    tp = ws / "t1.taskpad.json"
    tp.write_text(json.dumps({"id": "t1", "class_dir": "classes/A",
                              "grade": {"steps": ["transcribe"]}}), encoding="utf-8")
    plan = {"taskId": "t1", "classDir": "classes/A", "classId": "c1", "workId": "w1",
            "students": [{"name": "张三", "workAnswerId": "wa1", "images": ["/x/a.jpg"]},
                         {"name": "李四", "workAnswerId": "wa2", "images": ["/x/b.jpg"]}]}

    def fake_batch(client, items, out_dir, **kw):
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / "张三.json"
        out.write_text(json.dumps({"student": "张三", "markdown": "成功转写", "model": "m"},
                                  ensure_ascii=False), encoding="utf-8")
        return {"total": 2, "failed": 1,
                "items": [{"id": "张三", "ok": True, "out": str(out)},
                          {"id": "李四", "ok": False, "error": "429 限流"}]}

    monkeypatch.setattr("assist.grading.transcribe.transcribe_batch", fake_batch)
    monkeypatch.setattr("assist.grading.llm.LLMClient.__init__", lambda self, **k: None)

    with pytest.raises(flow.GradingInputError):
        flow.run_task(tp, ws, plan=plan)

    d = grade_store.read_drafts(ws, "c1", "w1", ws=ws, class_dir="classes/A", task_id="t1")
    assert d.get("wa1", {}).get("ai", {}).get("transcript") == "成功转写", \
        "部分失败中止时，已成功学生的转写也应可见"


def test_md_to_html_no_nameerror_and_has_katex(tmp_path):
    """D126 §3.5：`md_to_html` 曾引用未定义的 A4_CSS/MATHJAX_CDN（一调用就 NameError）。"""
    from assist.grading.report import md_to_html
    html = md_to_html("## 二、AI 批阅\n\n**总分：88 / 100**\n\n- 第 2 题单位错\n")
    assert "AI 批阅" in html and "88 / 100" in html
    assert "<html" in html and "</html>" in html
    assert "__katex" in html or "katex" in html.lower(), "应带 KaTeX 头（公式可渲染）"


# ---------------- D126-FIX：读草稿必须归一化（否则逐生审核一片空白） ----------------

def test_read_drafts_normalizes_legacy_single_set(tmp_path):
    """回归：旧 D85 单套草稿 `{score, comment}` 读出来必须带 `ai.comment`。

    此前 `read_drafts` 直接回原始 JSON，而前端按 `draft.ai.comment` 取值 →
    逐生审核显示「无 AI 批语」；列表页却因 `drafts[k].score` 兜底显示「✓」，
    表现为"已批阅但看不到内容"。
    """
    ws = tmp_path / "ws"
    home = ws / ".runtime" / "xxt"
    legacy = home / "grade-drafts" / "c1"
    legacy.mkdir(parents=True)
    (legacy / "w1.json").write_text(json.dumps(
        {"54761942": {"score": 88.0, "comment": "旧批语", "updatedAt": "x"}},
        ensure_ascii=False), encoding="utf-8")

    d = grade_store.read_drafts_normalized(home, "c1", "w1", ws=ws,
                                           class_dir="classes/A", task_id="t1")
    one = d["54761942"]
    assert one["ai"]["comment"] == "旧批语"
    assert one["ai"]["score"] == 88.0
    assert one["human"] == {} and one["humanMode"] == "none"


def test_read_drafts_normalizes_new_two_set(tmp_path):
    """新布局双套草稿读出来仍保持原样（ai.transcript / human 不丢）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    grade_store.save_draft_sets(None, "c1", "w1", "wa1",
                                ai={"transcript": "转写原文", "comment": "AI 批语"},
                                human={"score": 90, "comment": "人工", "used": True},
                                human_mode="replace", student="张三",
                                ws=ws, class_dir="classes/A", task_id="t1")
    d = grade_store.read_drafts_normalized(ws / ".runtime" / "xxt", "c1", "w1", ws=ws,
                                           class_dir="classes/A", task_id="t1")
    one = d["wa1"]
    assert one["ai"]["transcript"] == "转写原文"
    assert one["ai"]["comment"] == "AI 批语"
    assert one["human"]["comment"] == "人工"
    assert one["humanMode"] == "replace"


def test_save_drafts_from_grading_includes_transcript(tmp_path):
    """D126-FIX：落草稿（save_drafts_from_grading）也要带转写。

    否则"生成报告 → 回读落草稿"这条路径只会写 score/comment，
    逐生审核里就只剩批语、没有转写。
    """
    from assist.grading import drafts as DD
    from assist.grading.flow import grading_dir

    ws = tmp_path / "ws"; ws.mkdir()
    task = {"id": "t1", "class_dir": "classes/A"}
    base = grading_dir(ws, task)
    (base / "evaluations").mkdir(parents=True, exist_ok=True)
    (base / "transcripts").mkdir(parents=True, exist_ok=True)
    (base / "transcripts" / "张三.json").write_text(json.dumps(
        {"student": "张三", "markdown": "1. 由 F=ma 得 a=2", "model": "qwen3.7-flash"},
        ensure_ascii=False), encoding="utf-8")
    (base / "evaluations" / "张三.json").write_text(json.dumps(
        {"student": "张三", "total_score": 88, "feedback_md": "### 第2题\n- ❌ 单位错"},
        ensure_ascii=False), encoding="utf-8")

    rep = DD.save_drafts_from_grading(ws, class_id="c1", work_id="w1", task_id="t1",
                                      class_dir="classes/A", with_report_png=False)
    assert rep.get("ok") is True
    d = grade_store.read_drafts(ws / ".runtime" / "xxt", "c1", "w1", ws=ws,
                                class_dir="classes/A", task_id="t1")
    one = d["张三"]
    assert one["ai"]["transcript"] == "1. 由 F=ma 得 a=2"
    assert one["ai"]["transcriptModel"] == "qwen3.7-flash"
    assert one["ai"]["score"] == 88

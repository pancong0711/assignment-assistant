"""D219：批阅范围（逐生 vs 全局）与“空跑也显示完成”。

现场：
1) 整班批阅超时后 UI 显示失败，但引擎仍在后台跑，最终把全班评完；
2) 教师点逐生「批阅」，看到“全部未批阅学生都被评了”（其实是后台全局任务做的）；
3) 再次点全局批阅：全部已有评阅 → 什么都没做，却显示“✅完成”。

修复：
- 逐生「转写」也必须只处理该生（`_plan_student_images` 遵守 only_students）；
- 评阅产出统计（新评/跳过已有/无题目/失败），CLI 打印 `__GRADE_SUMMARY__`，
  PWA 如实显示“本次没有新评阅”；
- 同一作业范围单实例批阅（serve），PWA 接上正在跑的任务并可取消。
"""
from __future__ import annotations

import json
from pathlib import Path

from assist.grading.flow import _plan_student_images, _run_evaluate


def test_plan_student_images_honours_only_students(tmp_path: Path):
    img = tmp_path / "a.png"
    img.write_bytes(b"x")
    ctx = {
        "plan": {"students": [
            {"name": "学生甲", "images": [str(img)]},
            {"name": "学生乙", "images": [str(img)]},
        ]},
        "only_students": ["学生甲"],
    }
    groups = _plan_student_images(ctx)
    assert list(groups) == ["学生甲"]


def test_plan_student_images_all_when_no_only(tmp_path: Path):
    img = tmp_path / "a.png"
    img.write_bytes(b"x")
    ctx = {"plan": {"students": [
        {"name": "学生甲", "images": [str(img)]},
        {"name": "学生乙", "images": [str(img)]}]}}
    assert set(_plan_student_images(ctx)) == {"学生甲", "学生乙"}


class _FakeClient:
    evaluation_model = "fake"

    def chat(self, *, system_prompt, user_text, model=None, temperature=0.2, **kw):
        return json.dumps({"questions": [{"id": 1, "relevance": "relevant",
                                          "answer_chars": 300, "errors": []}],
                           "has_signature": True}, ensure_ascii=False)


def _mk_transcripts(tmp_path: Path, names):
    d = tmp_path / "transcripts"
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        (d / f"{n}.json").write_text(json.dumps({
            "student": n, "model": "fake",
            "items": [{"no": "1", "printed_question": "题干", "answer": "作答"}]},
            ensure_ascii=False), encoding="utf-8")
    return d


def _ctx(tmp_path, tdir, *, only=None, force=False):
    ev = tmp_path / "eval"
    ev.mkdir(exist_ok=True)
    return {
        "task": {}, "plan": None,
        "items": [{"序号": 1, "content": "题干", "kind": "problems", "kb": "problems"}],
        "transcripts_dir": tdir, "evaluations_dir": ev,
        "journal": tmp_path / "journal.jsonl", "run_id": "r1",
        "only_students": only or [], "force": force, "ws": tmp_path,
        "diag": tmp_path / "diag.jsonl",
    }


def test_evaluate_only_student_scope(tmp_path: Path):
    """逐生点「批阅」只评该生，不得评全班。"""
    tdir = _mk_transcripts(tmp_path, ["学生甲", "学生乙"])
    ctx = _ctx(tmp_path, tdir, only=["学生甲"])
    _run_evaluate(ctx, _FakeClient(), ctx["evaluations_dir"])
    files = {p.stem for p in ctx["evaluations_dir"].glob("*.json")}
    assert files == {"学生甲"}
    assert ctx["evaluate_summary"]["evaluated"] == 1
    assert ctx["evaluate_summary"]["scanned"] == 2


def test_evaluate_summary_counts_skipped_existing(tmp_path: Path):
    """全局批阅时全部已有评阅 → 新评 0、跳过 N（供 UI 如实提示）。"""
    tdir = _mk_transcripts(tmp_path, ["学生甲", "学生乙"])
    ctx = _ctx(tmp_path, tdir)
    for n in ("学生甲", "学生乙"):
        (ctx["evaluations_dir"] / f"{n}.json").write_text("{}", encoding="utf-8")
    _run_evaluate(ctx, _FakeClient(), ctx["evaluations_dir"])
    st = ctx["evaluate_summary"]
    assert st["evaluated"] == 0
    assert st["skippedExisting"] == 2


def test_cli_prints_grade_summary_marker():
    src = (Path(__file__).resolve().parents[1] / "src/assist/cli.py").read_text(
        encoding="utf-8")
    assert "__GRADE_SUMMARY__" in src
    assert "评阅统计：新评" in src


def test_serve_grade_single_instance_contract():
    src = (Path(__file__).resolve().parents[1] / "src/assist/serve.py").read_text(
        encoding="utf-8")
    assert "_GRADE_RUNNING" in src
    assert '_grade_scope_key(' in src
    assert '"stage": "busy"' in src
    assert "该作业已有批阅任务在运行" in src


def test_frontend_has_persist_and_cancel():
    repo = Path(__file__).resolve().parents[2]
    view = (repo / "app/src/components/AiGradingPanel.vue").read_text(encoding="utf-8")
    client = (repo / "app/src/lib/engineClient.ts").read_text(encoding="utf-8")
    assert "grade-job.v1" in view
    assert "cancelGradeJob" in view and "取消任务" in view
    assert "__GRADE_SUMMARY__" in view
    assert "本次没有新评阅" in view
    assert "XxtGradeStart" in client and "kind: 'busy'" in client

"""D194：一键生成报告的中断 / 续做语义。

现场问题：报告生成是**同步 HTTP 请求**（不是后台 job），逐生渲染 PNG；
教师关心「会不会中断」「再点是不是接续」。

设计目标（本测试固化）：
1. 单人失败**不拖垮全班**（其余学生继续生成，结果里列出 failed）；
2. 每完成一人就写 `.progress.json`（中断后能看出做到哪、谁失败）；
3. 再次点击**可续做**：`resume=True` 跳过已有报告的学生；
4. 重复生成**幂等**：内容没变不产生新版本（报告版本 = 内容哈希）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from assist.grading import drafts as D
from assist.grading import report_versions as RV
from assist.xxt import grade_store

CLASS_DIR = "classes/test-class"
CLASS_ID = "1001"
WORK_ID = "w1"
TASK_ID = "pack1"


def _draft(student: str, comment: str, score: float) -> dict:
    return {"student": student,
            "ai": {"score": score, "comment": comment},
            "human": {}, "humanMode": "none", "revision": {}, "revised": False}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    home = tmp_path / "xxt"
    (ws / CLASS_DIR).mkdir(parents=True)
    home.mkdir(parents=True)
    seeds = {"学生甲": _draft("学生甲", "甲批语", 90),
             "学生乙": _draft("学生乙", "乙批语", 80)}
    for key, d in seeds.items():
        grade_store.save_draft_sets(home, CLASS_ID, WORK_ID, key, ai=d["ai"],
                                    student=d["student"], ws=ws,
                                    class_dir=CLASS_DIR, task_id=TASK_ID)
    # 报告渲染不依赖 playwright 的 html→png：替换成直接落盘
    def fake_png(html, out_path, **kw):
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"PNG")
        return p
    monkeypatch.setattr("assist.grading.report.html_to_png", fake_png)
    return ws, home


def _render(ws, home, **kw):
    return D.render_reports_from_drafts(
        ws, class_id=CLASS_ID, work_id=WORK_ID, task_id=TASK_ID,
        class_dir=CLASS_DIR, home=home, **kw)


def test_render_writes_progress_file(env):
    ws, home = env
    rep = _render(ws, home)
    assert rep["ok"] is True and rep["count"] == 2
    prog = D.read_report_progress(ws, class_id=CLASS_ID, work_id=WORK_ID,
                                  task_id=TASK_ID, class_dir=CLASS_DIR)
    assert prog["exists"] is True and prog["state"] == "done"
    assert prog["total"] == 2
    assert sorted(prog["done"]) == ["学生乙", "学生甲"]


def test_single_failure_does_not_abort_whole_class(env, monkeypatch):
    """关键语义：一个人渲染炸了，其他人照样出报告。"""
    ws, home = env
    from assist.grading import report as R
    real = R._mode_report_md

    def flaky(**kw):
        if kw.get("student") == "学生乙":
            raise RuntimeError("模拟渲染失败")
        return real(**kw)

    monkeypatch.setattr(R, "_mode_report_md", flaky)
    rep = _render(ws, home)
    assert rep["partial"] is True and rep["ok"] is False
    assert [x["student"] for x in rep["reports"]] == ["学生甲"]
    assert [x["student"] for x in rep["failed"]] == ["学生乙"]
    prog = D.read_report_progress(ws, class_id=CLASS_ID, work_id=WORK_ID,
                                  task_id=TASK_ID, class_dir=CLASS_DIR)
    assert prog["state"] == "partial"
    assert prog["done"] == ["学生甲"]


def test_rerun_after_failure_resumes_and_fills_gap(env, monkeypatch):
    """中断后续做：再点一次应补齐缺的人，已完成的不重复渲染。"""
    ws, home = env
    from assist.grading import report as R
    real = R._mode_report_md
    monkeypatch.setattr(R, "_mode_report_md",
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("boom"))
                        if kw.get("student") == "学生乙" else real(**kw))
    _render(ws, home)
    monkeypatch.setattr(R, "_mode_report_md", real)
    rep2 = _render(ws, home, resume=True)
    assert rep2["ok"] is True
    assert [x["student"] for x in rep2["reports"]] == ["学生乙"]   # 只补缺的
    assert [x["student"] for x in rep2["skipped"]] == ["学生甲"]   # 已完成的跳过
    prog = D.read_report_progress(ws, class_id=CLASS_ID, work_id=WORK_ID,
                                  task_id=TASK_ID, class_dir=CLASS_DIR)
    assert prog["state"] == "done"


def test_only_rerenders_selected_students(env):
    ws, home = env
    rep = _render(ws, home, only=["学生甲"])
    assert [x["student"] for x in rep["reports"]] == ["学生甲"]


def test_full_rerun_is_idempotent_for_versions(env):
    """不中断的重复点击：内容不变 → 版本号不变、历史不膨胀。"""
    ws, home = env
    _render(ws, home)
    reports_dir = ws / CLASS_DIR / "grading" / TASK_ID / "reports"
    first = {x["student"]: x["version"] for x in RV.read_index(reports_dir)["items"]}
    rep2 = _render(ws, home)
    assert all(x["changed"] is False for x in rep2["reports"])
    hist = RV.read_index(reports_dir)["items"]
    assert len(hist) == len(first) == 2


def test_progress_missing_is_safe(tmp_path):
    prog = D.read_report_progress(tmp_path, class_id="c", work_id="w",
                                  task_id="t", class_dir="classes/c")
    assert prog["ok"] is True and prog["exists"] is False


def test_progress_corrupt_file_is_safe(env):
    ws, _home = env
    root = ws / CLASS_DIR / "grading" / TASK_ID / "reports"
    root.mkdir(parents=True, exist_ok=True)
    (root / ".progress.json").write_text("{坏 json", encoding="utf-8")
    prog = D.read_report_progress(ws, class_id=CLASS_ID, work_id=WORK_ID,
                                  task_id=TASK_ID, class_dir=CLASS_DIR)
    assert prog["ok"] is True and prog["exists"] is False


def test_progress_records_reason_and_mode(env):
    ws, home = env
    _render(ws, home, reason="pwa-render")
    prog = D.read_report_progress(ws, class_id=CLASS_ID, work_id=WORK_ID,
                                  task_id=TASK_ID, class_dir=CLASS_DIR)
    assert prog["reason"] == "pwa-render"
    assert prog["mode"] == "full"
    _render(ws, home, resume=True)
    prog2 = D.read_report_progress(ws, class_id=CLASS_ID, work_id=WORK_ID,
                                   task_id=TASK_ID, class_dir=CLASS_DIR)
    assert prog2["mode"] == "resume"


def test_source_contract_for_d194():
    root = Path(__file__).resolve().parents[1]
    drafts = (root / "src/assist/grading/drafts.py").read_text(encoding="utf-8")
    serve = (root / "src/assist/serve.py").read_text(encoding="utf-8")
    assert "def read_report_progress(" in drafts
    assert "_write_progress(" in drafts
    assert "except Exception as exc:  # noqa: BLE001 —— D194" in drafts
    assert "resume: bool = False" in drafts
    assert "only: \"list[str] | None\" = None" in drafts
    # 同一作业单实例
    assert "_RENDER_RUNNING" in serve and "该作业正在生成报告" in serve
    assert "progressOnly" in serve

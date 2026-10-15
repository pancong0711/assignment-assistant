"""D86 §6：批阅产物 → 本地批阅草稿（含报告 PNG base64）。"""

import base64
import json
from pathlib import Path

from assist.grading import drafts as D
from assist.xxt import grade_store


def _mk_grading(tmp_path: Path, class_dir: str, task_id: str, student: str):
    base = tmp_path / class_dir / "grading" / task_id
    (base / "evaluations").mkdir(parents=True)
    (base / "transcripts").mkdir(parents=True)
    (base / "evaluations" / f"{student}.json").write_text(json.dumps({
        "student": student, "total_score": 88, "tag": "qa",
        "feedback_md": "## 总体评价\n**总分：88 / 100**\n- 优点：思路清晰\n公式 $a=2$"
    }, ensure_ascii=False), encoding="utf-8")
    (base / "transcripts" / f"{student}.json").write_text(json.dumps({
        "student": student, "markdown": "作答内容", "quality": {"handwriting": "工整"}}),
        encoding="utf-8")
    return base


def test_save_drafts_from_grading_maps_wa_and_cuts_markdown(tmp_path: Path):
    class_dir, task_id = "classes/demo", "t1"
    _mk_grading(tmp_path, class_dir, task_id, "学生A")
    # plan 提供 workAnswerId
    (tmp_path / class_dir / "grading" / task_id / "plan.json").write_text(json.dumps({
        "taskId": task_id, "classDir": class_dir,
        "students": [{"name": "学生A", "tag": "qa", "workAnswerId": "wa-1"}]},
        ensure_ascii=False), encoding="utf-8")
    rep = D.save_drafts_from_grading(tmp_path, class_id="C1", work_id="W1", task_id=task_id,
                                     class_dir=class_dir, kind="ai", with_report_png=False,
                                     home=tmp_path)
    assert rep["ok"] and rep["drafts"][0]["key"] == "wa-1"
    d = grade_store.read_drafts(tmp_path, "C1", "W1")["wa-1"]
    assert d["score"] == 88.0
    assert "**" not in d["comment"] and "· 优点" in d["comment"]      # Markdown 格式收敛
    assert d["source"].startswith("ai:")


def test_save_drafts_writes_report_png_base64(tmp_path: Path, monkeypatch):
    class_dir, task_id = "classes/demo", "t2"
    _mk_grading(tmp_path, class_dir, task_id, "学生B")
    # 不依赖浏览器：把 render_report_png 替换为写一个假 PNG
    from assist.grading import report as R

    def fake_png(md, out, **_kw):
        p = Path(out); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
        return p
    monkeypatch.setattr(R, "render_report_png", fake_png)
    rep = D.save_drafts_from_grading(tmp_path, class_id="C1", work_id="W2", task_id=task_id,
                                     class_dir=class_dir, kind="human", with_report_png=True,
                                     home=tmp_path)
    assert rep["drafts"][0]["images"] == 1
    d = grade_store.read_drafts(tmp_path, "C1", "W2")["学生B"]     # 无 plan → 键=姓名
    assert d["source"].startswith("human:")
    assert base64.b64decode(d["images"][0]["data_b64"]).startswith(b"\x89PNG")

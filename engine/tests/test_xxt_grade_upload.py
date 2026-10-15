"""D84：批阅回传领域层纯逻辑回归（无浏览器）。"""

import json
from pathlib import Path

from assist.xxt.grade_upload import find_student_row, _write_receipt, receipt_dir


ROWS = [
    {"name": "张三", "status": "待批阅", "workAnswerId": "111"},
    {"name": "李四", "status": "已批阅", "workAnswerId": "222"},
    {"name": "潘聪（未交）", "status": "", "workAnswerId": ""},
]


def test_find_student_exact_name():
    assert find_student_row(ROWS, "张三")["workAnswerId"] == "111"


def test_find_student_by_work_answer_id():
    assert find_student_row(ROWS, "222")["name"] == "李四"


def test_find_student_substring_fuzzy():
    assert find_student_row(ROWS, "潘聪")["name"] == "潘聪（未交）"


def test_find_student_case_insensitive_and_missing():
    assert find_student_row(ROWS, "  张三 ")["name"] == "张三"
    assert find_student_row(ROWS, "不存在") is None
    assert find_student_row(ROWS, "") is None


def test_find_student_prefers_exact_over_fuzzy():
    rows = [{"name": "张三丰", "workAnswerId": "9"}, {"name": "张三", "workAnswerId": "1"}]
    assert find_student_row(rows, "张三")["workAnswerId"] == "1"


def test_receipt_write_and_dir(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XXT_HOME", str(tmp_path))
    # xxt_home 读 env 优先（与 session 同口径）
    p = _write_receipt("grade-upload", {"ok": True, "score": 85})
    assert p and Path(p).is_file()
    assert "grade-upload" in Path(p).name
    import json
    assert json.loads(Path(p).read_text(encoding="utf-8"))["score"] == 85
    assert receipt_dir().is_dir()


# ---------------- §4：grading 产物 → payload ----------------

def _mk_eval(ws: Path, task_id: str, filename: str, data: dict):
    d = ws / "classes" / "demo" / "grading" / task_id / "evaluations"
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_build_upload_payloads_from_grading(tmp_path: Path):
    from assist.xxt.grade_upload import build_upload_payloads
    task = tmp_path / "task.json"
    task.write_text(json.dumps({"id": "t84", "class_dir": "classes/demo"}), encoding="utf-8")
    _mk_eval(tmp_path, "t84", "学生A.json", {
        "student": "学生A", "total_score": 88, "per_question_scores": [30, 28, 30],
        "feedback_md": "第一行\n第二行", "verdict": "normal"})
    _mk_eval(tmp_path, "t84", "_meta.json", {"note": "应被跳过"})  # 下划线开头跳过
    payloads = build_upload_payloads(tmp_path, task)
    assert len(payloads) == 1
    p = payloads[0]
    assert p["student"] == "学生A" and p["total_score"] == 88.0
    assert p["question_scores"] == [30.0, 28.0, 30.0]
    assert p["comment"].startswith("第一行")


def test_build_upload_payloads_missing_dir(tmp_path: Path):
    from assist.xxt.grade_upload import build_upload_payloads
    task = tmp_path / "task.json"
    task.write_text(json.dumps({"id": "none", "class_dir": "classes/demo"}), encoding="utf-8")
    assert build_upload_payloads(tmp_path, task) == []


def test_find_payload_exact_and_fuzzy():
    from assist.xxt.grade_upload import find_payload
    payloads = [{"student": "张三丰", "total_score": 1}, {"student": "张三", "total_score": 2}]
    assert find_payload(payloads, "张三")["total_score"] == 2
    assert find_payload(payloads, "张三丰")["total_score"] == 1
    assert find_payload(payloads, "不存在") is None
    assert find_payload(payloads, "") is None

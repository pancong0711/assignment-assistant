"""D98-B6：batch 结果回灌（下载 JSONL → evaluations/*.json，含 Python 算分）。"""
import json
from pathlib import Path

from assist.grading.llm_batch import apply_results, parse_output_jsonl

ANALYSIS = {
    "question_match": {"status": True, "note": "匹配"},
    "questions": [{
        "id": 1,
        "reasoning": {"status": "ok", "note": "思路清楚"},
        "correct_points": ["受力分析正确"],
        "errors": [
            {"step": "第2步", "description": "漏了重力", "guidance": "还有哪些力？",
             "deduct": 5, "evidence": "F = ma", "confidence": "high", "why": "漏重力"},
            {"step": "第3步", "description": "字迹不清", "guidance": "再写清楚", "deduct": 5,
             "evidence": "?", "confidence": "low", "why": "模糊"},
        ],
        "confidence": "high", "has_diagram": True,
    }],
    "has_signature": True, "summary": "还行", "guidance": "再想想",
    "strengths": ["步骤清晰"], "weaknesses": ["单位"],
}


def _output_line(cid: str, content: str, status: int = 200) -> str:
    return json.dumps({"id": f"batch_{cid}", "custom_id": cid,
                       "response": {"status_code": status,
                                    "body": {"choices": [{"message": {"content": content}}]}},
                       "error": None}, ensure_ascii=False)


def test_parse_output_jsonl_ok_and_error():
    text = "\n".join([
        _output_line("s1", json.dumps(ANALYSIS, ensure_ascii=False)),
        json.dumps({"id": "x", "custom_id": "s2",
                    "response": {"status_code": 500}, "error": {"message": "bad"}}),
        "not json line",
    ])
    rows = parse_output_jsonl(text)
    assert len(rows) == 2
    assert rows[0]["custom_id"] == "s1" and rows[0]["ok"] is True
    assert rows[1]["custom_id"] == "s2" and rows[1]["ok"] is False


def test_apply_results_writes_evaluations(tmp_path):
    ev = tmp_path / "evaluations"
    tr = tmp_path / "transcripts"; tr.mkdir(parents=True)
    (tr / "s1.json").write_text(json.dumps({"student": "s1", "quality": {"handwriting": "工整"},
                                            "_name_match": True}), encoding="utf-8")
    results = tmp_path / "out.jsonl"
    results.write_text("\n".join([
        _output_line("s1", json.dumps(ANALYSIS, ensure_ascii=False)),
        _output_line("s2", json.dumps(ANALYSIS, ensure_ascii=False)),
        json.dumps({"custom_id": "s3", "response": {"status_code": 500},
                    "error": {"message": "upstream"}}),
    ]) + "\n", encoding="utf-8")

    rep = apply_results(tmp_path, results, evaluated_dir=ev, transcripts_dir=tr,
                        homework_name="物理 第1次")
    assert rep["written"] == 2 and rep["failed"] == 1
    s1 = json.loads((ev / "s1.json").read_text(encoding="utf-8"))
    assert s1["student"] == "s1" and s1["_source"] == "llm_batch"
    # Python 算分：high 错误扣 5，low 不计 → 95
    assert s1["total_score"] == 95, s1["total_score"]
    assert (ev / "s1.md").is_file()
    assert "待教师确认" in (ev / "s1.md").read_text(encoding="utf-8")


def test_apply_results_missing_file(tmp_path):
    rep = apply_results(tmp_path, tmp_path / "nope.jsonl", evaluated_dir=tmp_path)
    assert rep["ok"] is False and "不存在" in rep["error"]

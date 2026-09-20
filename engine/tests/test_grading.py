"""阶段3 批阅链路自测：合成数据 + stub LLM（monkeypatch httpx.post，不起真实网络）。

验证：transcribe → evaluate → report 全链路产物（transcripts/evaluations/reports/
summary.xlsx/_global_report.md）与 journal.jsonl 记录正确。
示例数据一律占位风格（学生A/classA，题目为合成占位文本）。
"""

import json
from pathlib import Path

import pytest

from assist.grading import llm as llm_mod
from assist.grading.flow import expand_items, run_task

ENGINE_DIR = Path(__file__).resolve().parents[1]


class FakeResp:
    def __init__(self, data):
        self._data = data
        self.status_code = 200
        self.text = "fake"

    def json(self):
        return self._data


def _resp_for_messages(messages):
    """按请求形态返回假响应：多模态→转录 JSON；文本→评阅 JSON。"""
    user = messages[-1]["content"]
    if isinstance(user, list):  # 图片请求（transcribe）
        md = ("# 学生A 的作业\n\n## 第1题\n$E = mc^2$\n\n题干（占位）内容已完整抄写。")
        content = json.dumps({"markdown": md, "quality": {
            "handwriting": "工整", "clarity": "清晰", "organization": "整洁"}},
            ensure_ascii=False)
    else:  # 文本评阅（evaluate）
        content = json.dumps({
            "question_match": {"status": True, "note": "题目匹配正常"},
            "questions": [{"id": 1, "reasoning": {"status": "ok", "note": "思路清晰"},
                           "errors": [{"step": "第2步", "description": "单位漏写",
                                       "guidance": "想一想量纲", "deduct": 5}],
                           "has_diagram": True}],
            "has_signature": True, "summary": "整体不错",
            "guidance": "1) 复查单位 2) 补图",
            "strengths": ["公式书写规范"], "weaknesses": ["单位细节"],
        }, ensure_ascii=False)
    return FakeResp({"choices": [{"message": {"content": content}}]})


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    ws = tmp_path / "demo-workspace"
    (ws / "kb").mkdir(parents=True)
    (ws / "classes" / "2026S1-classA" / "roster").mkdir(parents=True)
    # settings.local.json：key 是假占位值，不入库
    (ws / "settings.local.json").write_text(json.dumps({
        "llm": {"base_url": "http://stub.invalid/v1", "api_key": "stub-key-0000",
                "transcription_model": "stub-vision"}}), encoding="utf-8")
    # 合成 kb xlsx：1 题占位 + 伪参考答案
    from openpyxl import Workbook
    wb = Workbook()
    s = wb.active
    s.title = "chap10"
    s.append(["id", "content", "img_path", "page", "related", "type", "solution", "note"])
    s.append(["Q10-1", "占位题干：请推导 $E=mc^2$ 并书写规范。",
              "", 1, "", "", "参考答案占位：能量守恒推导要点。", ""])
    wb.save(ws / "kb" / "problems.xlsx")
    # 学生作业图片（合成"手写感"占位 PNG）
    imgs = ws / "classes" / "2026S1-classA" / "grading" / "task-demo" / "images"
    imgs.mkdir(parents=True)
    from PIL import Image
    for name in ("学生A.png", "学生A-2.png", "学生B.png"):
        Image.new("RGB", (640, 480), (245, 246, 248)).save(imgs / name)
    # 任务包
    task = {
        "id": "2026S1-classA-chap10-1",
        "class_dir": "classes/2026S1-classA",
        "course": "大学物理", "class": "classA", "term": "2026S1",
        "items": [{"kb": "problems", "chap": "chap10", "ids": ["Q10-1"], "tag": "distinguish"}],
        "grade": {"steps": ["transcribe", "evaluate", "report"],
                  "models": {"transcription": "stub-vision", "evaluation": "stub-reason"}},
    }
    task_path = ws / "task-demo.json"
    task_path.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
    # stub LLM：monkeypatch 替换 httpx.post（请求函数）
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(url)
        assert headers["Authorization"].startswith("Bearer "), "应带鉴权头"
        return _resp_for_messages(json["messages"])

    monkeypatch.setattr(llm_mod.httpx, "post", fake_post)
    return ws, task_path, imgs, calls


def test_expand_items_binds_solution(ws):
    w, task_path, imgs, _ = ws
    items = expand_items(w, json.loads(Path(task_path).read_text(encoding="utf-8")))
    assert items and items[0]["solution"], "展开应携带题库 solution（绑定题目收益点）"
    assert items[0]["tag"] == "distinguish"


def test_full_flow_artifacts_and_journal(ws):
    w, task_path, imgs, calls = ws
    rec = run_task(Path(task_path), w, images_dir=imgs)
    bucket = w / "classes" / "2026S1-classA" / "grading" / "2026S1-classA-chap10-1"
    t1 = bucket / "transcripts" / "学生A.json"
    e1 = bucket / "evaluations" / "学生A.json"
    r1 = bucket / "reports" / "学生A.md"
    assert t1.exists() and e1.exists() and r1.exists(), f"产物缺失 in {bucket}"
    assert (bucket / "reports" / "学生A.html").exists()
    assert (bucket / "reports" / "summary.xlsx").exists()
    assert (bucket / "reports" / "_global_report.md").exists()
    # 数据之重组装与批语质量
    ev = json.loads(e1.read_text(encoding="utf-8"))
    assert ev["total_score"] == 95  # 错误1处(扣5)，签名齐
    assert ev["per_question_scores"] == [95]
    assert ev["feedback_md"] and "想一想" in Path(r1).read_text(encoding="utf-8")
    # HTML 带 MathJax
    assert "MathJax" in (bucket / "reports" / "学生A.html").read_text(encoding="utf-8")
    # 多张图并到同一学生（文件名前缀分组）
    assert len(group := list((bucket / "transcripts").glob("*.json"))) == 2  # 学生A/B
    # journal（D8）
    jl = [json.loads(x) for x in (bucket / "journal.jsonl").read_text().splitlines()]
    steps = [r["step"] for r in jl if "step" in r]
    assert {"transcribe", "evaluate", "report"} <= set(steps)
    assert all(r.get("status") in ("ok", "running", "done") for r in jl)
    assert len(calls) >= 3  # 2生转录 + 评阅


def test_rerun_report_only(ws):
    w, task_path, imgs, _ = ws
    run_task(Path(task_path), w, images_dir=imgs)
    rec = run_task(Path(task_path), w, rerun="report")
    assert rec["steps_done"] == ["report"] and rec["status"] == "done"

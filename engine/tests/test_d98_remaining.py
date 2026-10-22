"""D98 收尾：ai-solve 并发、token usage 采集、json-out。"""
import json
from pathlib import Path

from assist.grading.llm import LLMClient


def test_usage_accumulates_and_summary():
    c = LLMClient(settings={"base_url": "x", "api_key": "k", "model": "m"})
    c._record_usage({"usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}})
    c._record_usage({"usage": {"prompt_tokens": 6, "completion_tokens": 2, "total_tokens": 8}})
    c._record_usage({})   # 无 usage 的响应只计 calls
    u = c.usage_summary()
    assert u["prompt_tokens"] == 16 and u["completion_tokens"] == 6
    assert u["calls"] == 3 and u["calls_with_usage"] == 2


def test_ai_solve_concurrent_marks_failures(tmp_path, monkeypatch):
    from assist.grading import solve

    class Fake:
        evaluation_model = "m"

        def chat(self, system_prompt, user_text, step="evaluation"):
            if "BAD" in user_text:
                raise RuntimeError("boom")
            return "解答内容"

    monkeypatch.setattr(solve, "_client", lambda ws, model="": (Fake(), "m"))
    targets = [{"id": f"q{i}", "content": ("BAD" if i == 2 else f"题{i}")} for i in range(5)]
    rep = solve.solve_targets(tmp_path, targets, apply=False, dry_run=False, concurrency=3)
    assert rep["planned"] == 5 and rep["failed"] == 1
    by = {r["id"]: r for r in rep["results"]}
    assert by["q2"]["ok"] is False and "boom" in by["q2"]["error"]
    assert all(by[f"q{i}"]["ok"] for i in (0, 1, 3, 4))


def test_ai_solve_apply_writes_versions(tmp_path, monkeypatch):
    from assist.grading import solve
    from assist.files import solutions

    class Fake:
        evaluation_model = "m"

        def chat(self, system_prompt, user_text, step="evaluation"):
            return "答案"

    monkeypatch.setattr(solve, "_client", lambda ws, model="": (Fake(), "m"))
    (tmp_path / "kb").mkdir()
    rep = solve.solve_targets(tmp_path, [{"id": "q1", "content": "题"}],
                              apply=True, dry_run=False)
    assert rep["written"] == 1
    sol = solutions.read_solutions(tmp_path, "q1")
    assert sol and sol["versions"][0]["text"] == "答案"


def test_notice_send_json_out(tmp_path, monkeypatch):
    """--json-out 把结果写入文件（不真正发送）。"""
    from click.testing import CliRunner
    import assist.xxt.cli as X

    monkeypatch.setattr("assist.xxt.notice.send_notice_from_spec",
                        lambda spec, send=False, storage=None: {"ok": True, "mode": "dry-run",
                                                                "sent": 0})
    from assist.cli import cli
    out = tmp_path / "r.json"
    r = CliRunner().invoke(cli, ["xxt", "notice-send", "--target", "c1:k1:班级甲",
                                 "--title", "t", "--body", "b", "--json-out", str(out)])
    assert r.exit_code == 0, r.output
    assert json.loads(out.read_text(encoding="utf-8"))["ok"] is True

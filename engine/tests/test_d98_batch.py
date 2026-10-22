"""D98-B4：转录 batch + 执行报告（单条失败标记继续、报告落盘、隔离）。"""
import json
from pathlib import Path

from assist.grading.batchrun import run_items, summarize
from assist.grading.transcribe import transcribe_batch


def test_run_items_marks_fail_and_continues(tmp_path):
    items = [{"id": f"s{i}"} for i in range(5)]

    def worker(it):
        if it["id"] == "s2":
            raise RuntimeError("boom")
        return {"ok": True, "out": f"o/{it['id']}"}

    rep = run_items(items, worker, kind="transcribe", concurrency=2, out_dir=tmp_path)
    assert rep["total"] == 5 and rep["failed"] == 1
    by_id = {r["id"]: r for r in rep["items"]}
    assert by_id["s2"]["ok"] is False and "boom" in by_id["s2"]["error"]
    assert all(by_id[f"s{i}"]["ok"] for i in (0, 1, 3, 4))
    assert (tmp_path / "batch-report.json").is_file()
    assert "5" in summarize(rep)


def test_run_items_report_shape(tmp_path):
    rep = run_items([{"id": "a"}], lambda it: {"ok": True, "out": "x"},
                    kind="evaluate", concurrency=1, out_dir=tmp_path)
    d = json.loads((tmp_path / "batch-report.json").read_text(encoding="utf-8"))
    for k in ("kind", "startedAt", "finishedAt", "total", "ok", "failed", "items"):
        assert k in d
    assert d["kind"] == "evaluate" and d["items"][0]["id"] == "a"


def test_transcribe_batch_isolated_requests(tmp_path, monkeypatch):
    """每条 item 单独调用；某条失败不影响其他条。"""
    import assist.grading.transcribe as T
    calls = []

    def fake_student(client, imgs, student, out_dir, model=None):
        calls.append((student, [str(p) for p in imgs]))
        if student == "bad":
            raise RuntimeError("转录失败")
        out = Path(out_dir) / f"{student}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"student": student, "markdown": "x", "_name_match": True}),
                       encoding="utf-8")
        return out

    monkeypatch.setattr(T, "transcribe_student", fake_student)
    for name in ("s1", "bad", "s2"):
        (tmp_path / f"{name}.png").write_bytes(b"img")

    items = [{"id": "s1", "question": "", "images": [str(tmp_path / "s1.png")], "meta": {}},
             {"id": "bad", "question": "", "images": [str(tmp_path / "bad.png")], "meta": {}},
             {"id": "s2", "question": "", "images": [str(tmp_path / "s2.png")], "meta": {}}]
    rep = transcribe_batch(object(), items, tmp_path / "transcripts", concurrency=2)
    assert rep["ok"] == 2 and rep["failed"] == 1
    assert {c[0] for c in calls} == {"s1", "bad", "s2"}
    # 每条只带自己的图片
    for student, imgs in calls:
        assert all(student in p for p in imgs)


def test_transcribe_item_without_images_fails_cleanly(tmp_path):
    from assist.grading.transcribe import transcribe_item
    res = transcribe_item(object(), {"id": "s1", "images": []}, tmp_path)
    assert res["ok"] is False and "无可用图片" in res["error"]

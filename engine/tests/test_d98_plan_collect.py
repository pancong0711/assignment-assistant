"""D98-B7：plan/collect 兜底通道（不调模型、讲清发生了什么、校验回写）。"""
import json
from pathlib import Path

from assist.grading.plan_collect import build_task_list, collect


def _items(tmp_path):
    imgs = []
    for i in range(2):
        p = tmp_path / f"s{i}.png"; p.write_bytes(b"x"); imgs.append(str(p))
    items = [{"id": "s1", "question": "", "images": imgs, "meta": {}},
             {"id": "s2", "question": "", "images": [imgs[0]], "meta": {}}]
    for it in items:
        it["outputPath"] = str(tmp_path / "transcripts" / f"{it['id']}.json")
    return items


def test_build_task_list_states_no_model(tmp_path):
    rep = build_task_list(items=_items(tmp_path), out_dir=tmp_path / "pc",
                          kind="transcribe", prompt_template="{question}\n{images}")
    assert rep["total"] == 2
    assert "不调用任何模型" in rep["notice"]
    assert (tmp_path / "pc" / "task-list.json").is_file()
    # 每生一个任务文件，且只含本生图片
    md1 = (tmp_path / "pc" / "agent-tasks" / "s1.md").read_text(encoding="utf-8")
    md2 = (tmp_path / "pc" / "agent-tasks" / "s2.md").read_text(encoding="utf-8")
    assert md1.count(".png") >= 2 and md2.count(".png") >= 1
    assert "s1.png" in md1


def test_collect_marks_missing_and_bad(tmp_path):
    items = _items(tmp_path)
    rep = build_task_list(items=items, out_dir=tmp_path / "pc", kind="transcribe",
                          prompt_template="{images}")
    tr = tmp_path / "transcripts"; tr.mkdir()
    (tr / "s1.json").write_text(json.dumps({"markdown": "好的转录"}), encoding="utf-8")
    (tr / "s2.json").write_text("{bad json", encoding="utf-8")
    out = collect(task_list=rep, results_dir=tr)
    assert out["total"] == 2 and out["ok"] == 1 and out["failed"] == 1
    by = {i["id"]: i for i in out["items"]}
    assert by["s1"]["status"] == "ok"
    assert by["s2"]["status"] == "fail" and "JSON" in by["s2"]["error"]


def test_collect_flags_missing_markdown(tmp_path):
    items = _items(tmp_path)
    rep = build_task_list(items=items, out_dir=tmp_path / "pc", kind="transcribe",
                          prompt_template="{images}")
    tr = tmp_path / "transcripts"; tr.mkdir()
    (tr / "s1.json").write_text(json.dumps({"quality": {}}), encoding="utf-8")
    out = collect(task_list=rep, results_dir=tr)
    by = {i["id"]: i for i in out["items"]}
    assert by["s1"]["status"] == "fail" and "markdown" in by["s1"]["error"]

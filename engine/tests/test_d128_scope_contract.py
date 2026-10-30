"""D127-FIX：批阅「作用域键」契约回归。

线上事故：点「仅转录」后 transcripts/*.json 已生成，但逐生审核显示"暂无转写内容"。
根因：引擎写草稿用 `task.id`（作业纸 id），前端读草稿用 `packId` → 读写不是同一目录。
本文件把"写入 → 用前端参数读取"这条跨端契约固定下来，防止再次漂移。
"""
import json
from pathlib import Path

from assist.grading import flow
from assist.grading import drafts as D
from assist.xxt import grade_store


def _seed_transcript(ws: Path, scope: str, student: str = "张三",
                     class_dir: str = "classes/A") -> Path:
    tdir = ws / class_dir / "grading" / scope / "transcripts"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / f"{student}.json").write_text(json.dumps(
        {"student": student,
         "items": [{"no": "1", "printed_question": "求加速度",
                    "answer": "a=F/m", "diagrams": []}],
         "model": "m"}, ensure_ascii=False), encoding="utf-8")
    return tdir


# ---------------- 契约 1：写入与读取必须同键 ----------------

def test_transcript_visible_under_pack_scope(tmp_path):
    """作业包模式：引擎按 packId 写，前端按 packId 读 → 必须能看到转写。"""
    ws = tmp_path / "ws"; ws.mkdir()
    pack_id = "pack-2026-10"
    tdir = _seed_transcript(ws, pack_id)
    plan = {"packId": pack_id, "classId": "c1", "workId": "w1",
            "classDir": "classes/A",
            "students": [{"name": "张三", "workAnswerId": "wa1"}]}

    n = flow._persist_transcripts(ws, {"id": "pad-qa", "class_dir": "classes/A"},
                                  plan, tdir)
    assert n == 1
    # 前端实际请求：taskId = packId, classDir = classes/A
    d = grade_store.read_drafts_normalized(ws / ".runtime" / "xxt", "c1", "w1",
                                           ws=ws, class_dir="classes/A",
                                           task_id=pack_id)
    assert d.get("wa1", {}).get("ai", {}).get("transcript"), "逐生审核应能看到转写"


def test_scope_id_equals_grading_dir_key(tmp_path):
    """作用域键必须与 grading_dir 的目录名一致（否则又会出现读写分叉）。"""
    task = {"id": "pad-qa", "class_dir": "classes/A"}
    plan = {"packId": "pack-1"}
    assert flow.grading_scope_id(task, plan) == "pack-1"
    assert flow.grading_key({**task, "pack_id": "pack-1"}) == "pack-1"
    # 没有包时回退作业纸 id（单张作业纸模式）
    assert flow.grading_scope_id(task, None) == "pad-qa"


def test_transcripts_land_in_scope_dir_used_by_grading_dir(tmp_path):
    """写入的 transcripts 目录 == grading_dir(scope) 下的 transcripts（同一棵树）。"""
    ws = tmp_path / "ws"; ws.mkdir()
    task = {"id": "pad-qa", "class_dir": "classes/A", "pack_id": "pack-1"}
    base = flow.grading_dir(ws, task)
    assert base.name == "pack-1"
    assert base == ws / "classes/A/grading/pack-1"


# ---------------- 契约 2：历史目录（padId）仍可读 ----------------

def test_legacy_pad_scope_still_readable(tmp_path):
    """历史草稿写在 grading/<padId>/drafts：按 packId 读不到时应能回落到 padId。"""
    ws = tmp_path / "ws"; ws.mkdir()
    grade_store.save_draft_sets(None, "c1", "w1", "wa1",
                                ai={"transcript": "旧目录转写"},
                                ws=ws, class_dir="classes/A", task_id="pad-qa")
    home = ws / ".runtime" / "xxt"
    # 只按 packId 读 → 空（复现事故）
    assert grade_store.read_drafts_normalized(home, "c1", "w1", ws=ws,
                                              class_dir="classes/A",
                                              task_id="pack-1") == {}
    # 带兼容键 → 可读
    d = grade_store.read_drafts_normalized(home, "c1", "w1", ws=ws,
                                           class_dir="classes/A", task_id="pack-1",
                                           alt_task_ids=["pad-qa"])
    assert d["wa1"]["ai"]["transcript"] == "旧目录转写"


def test_full_flow_then_read_like_pwa(tmp_path, monkeypatch):
    """端到端：run_task（仅有 plan、作业包模式）→ 用前端参数读草稿能看到转写。"""
    ws = tmp_path / "ws"; ws.mkdir()
    pack_id = "pack-1"
    tp = ws / "pad-qa.taskpad.json"
    tp.write_text(json.dumps({"id": "pad-qa", "class_dir": "classes/A",
                              "grade": {"steps": ["transcribe"]}}), encoding="utf-8")
    plan = {"packId": pack_id, "classId": "c1", "workId": "w1",
            "classDir": "classes/A",
            "students": [{"name": "张三", "workAnswerId": "wa1", "images": ["/x/a.jpg"]}]}

    def fake_batch(client, items, out_dir, **kw):
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / "张三.json"
        out.write_text(json.dumps({"student": "张三", "items": [
            {"no": "1", "printed_question": "求加速度", "answer": "a=F/m", "diagrams": []}]},
            ensure_ascii=False), encoding="utf-8")
        return {"total": 1, "failed": 0, "items": [{"id": "张三", "ok": True, "out": str(out)}]}

    monkeypatch.setattr("assist.grading.transcribe.transcribe_batch", fake_batch)
    monkeypatch.setattr("assist.grading.llm.LLMClient.__init__", lambda self, **k: None)

    flow.run_task(tp, ws, plan=plan)

    # 目录必须在包名下
    assert (ws / "classes/A/grading" / pack_id / "transcripts" / "张三.json").is_file()
    d = grade_store.read_drafts_normalized(ws / ".runtime" / "xxt", "c1", "w1",
                                           ws=ws, class_dir="classes/A", task_id=pack_id)
    assert "**题目：** 求加速度" in d["wa1"]["ai"]["transcript"]

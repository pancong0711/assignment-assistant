"""D124：class_dir 注入链路 + 班级名唯一真源 + 班级目录命名体检。

两个独立缺陷：
1. `class_dir` 只给了 plan、没写回 task → `grading_dir()` 拿到空值直接报错
   （用户完成②区关联后仍报 `class_dir=''`）。
2. 目录名用 `students[0].class`（点名册原始字段）而非班级名 → 出现两套目录。
"""
import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from openpyxl import Workbook

from assist import class_dir_audit as CDA
from assist.cli import cli
from assist.grading import flow as F
from assist.files import roster_io


# ---------------- P1：class_dir 注入 ----------------

def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "kb").mkdir(parents=True)
    wb = Workbook(); sh = wb.active; sh.title = "chap04"
    sh.append(["id", "content", "img_path", "page", "related", "type", "solution", "note"])
    sh.append(["c1", "题", "", 1, "", "计算", "", ""])
    wb.save(ws / "kb" / "problems.xlsx")
    (ws / "classes" / "化工25" / "roster").mkdir(parents=True)
    wb2 = Workbook(); r = wb2.active
    r.append(["姓名", "学号", "班级", "tag"])
    r.append(["张三", "01", "2025-化工25班", "t"])       # 学生 class 字段故意与班级名不同
    wb2.save(ws / "classes" / "化工25" / "roster" / "roster.xlsx")
    return ws


def test_run_task_uses_class_dir_from_plan(tmp_path, monkeypatch):
    """taskpad **不含** class_dir 时，run_task 必须从 plan.classDir 注入（否则 grading_dir 崩）。"""
    ws = _mk_ws(tmp_path)
    task = {"id": "t1", "class": "化工25",
            "layout": {"orientation": "portrait", "per_page": 2,
                       "header": {"title": ""}, "footer": {"text": ""}},
            "items": [{"kb": "problems", "chap": "chap04", "ids": ["c1"], "tag": "t"}],
            "watermark": {"enabled": False},
            "grade": {"steps": ["transcribe"]}}
    assert "class_dir" not in task, "本用例前提：taskpad 里没有 class_dir"
    tp = ws / "task.json"
    tp.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")

    captured = {}

    def _fake_run(task_path_, ws_, **kw):
        # run_task 的签名是 (task_path, ws, ...)：真实注入发生在函数内部，
        # 这里只验证 cli 是否把 class_dir 作为关键字传下来
        captured["class_dir"] = kw.get("class_dir")
        captured["plan_class_dir"] = (kw.get("plan") or {}).get("classDir")
        return {"run_id": "x", "steps_done": [], "bucket": str(ws_), "usage": {}}

    monkeypatch.setattr(F, "run_task", _fake_run)
    import assist.cli as C
    monkeypatch.setattr(C, "run_task", _fake_run, raising=False)
    r = CliRunner().invoke(cli, ["grade", "--task", str(tp), "--xxt-class", "co1:c1",
                                 "--work", "w1", "-w", str(ws)])
    assert r.exit_code == 0, r.output
    assert captured.get("class_dir") == "classes/化工25", \
        f"run_task 应收到注入的 class_dir，实际={captured.get('class_dir')!r}"


def test_run_task_injects_class_dir_into_task(tmp_path):
    """直接验证 run_task 内部：plan.classDir 会写进 task，grading_dir 不再报错。"""
    from unittest import mock
    ws = _mk_ws(tmp_path)
    task = {"id": "t1", "grade": {"steps": ["transcribe"]}}
    tp = ws / "task.json"
    tp.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
    seen = {}

    def _fake_grading_dir(ws_, task_):
        seen["class_dir"] = task_.get("class_dir")
        d = Path(ws_) / str(task_["class_dir"]) / "grading" / str(task_["id"])
        d.mkdir(parents=True, exist_ok=True)
        return d

    with mock.patch.object(F, "grading_dir", _fake_grading_dir), \
         mock.patch.object(F, "_run_transcribe", side_effect=RuntimeError("stop-here")):
        with pytest.raises(Exception):
            F.run_task(tp, ws, plan={"classDir": "classes/化工25"})
    assert seen.get("class_dir") == "classes/化工25"


# ---------------- P2：班级名落盘 + 命名体检 ----------------

def test_roster_json_records_class_name(tmp_path):
    ws = tmp_path / "ws"
    roster_io.write_roster(ws, "classes/化工25", [{"name": "张三"}],
                           class_name="化工25", class_id="c1")
    js = ws / "classes/化工25/roster/roster.json"
    d = json.loads(js.read_text(encoding="utf-8"))
    assert d["className"] == "化工25" and d["classId"] == "c1"
    assert d["students"][0]["name"] == "张三"
    # 读回兼容新结构
    got = roster_io.read_roster_file(ws, "classes/化工25")
    assert got["ok"] and got["className"] == "化工25" and got["count"] == 1


def test_read_roster_json_legacy_array(tmp_path):
    """旧结构（纯数组）仍可读。"""
    ws = tmp_path / "ws"
    d = ws / "classes/A/roster"
    d.mkdir(parents=True)
    (d / "roster.json").write_text(json.dumps([{"name": "李四", "tag": "t"}]), encoding="utf-8")
    got = roster_io.read_roster_file(ws, "classes/A")
    assert got["ok"] and got["count"] == 1


def test_audit_detects_misnamed_dir_and_fix(tmp_path):
    ws = tmp_path / "ws"
    bad = ws / "classes" / "2025-化工25班" / "roster"
    bad.mkdir(parents=True)
    (bad / "roster.json").write_text(json.dumps(
        {"className": "化工25", "classId": "c1", "students": []}), encoding="utf-8")
    ok = ws / "classes" / "ok班" / "roster"
    ok.mkdir(parents=True)
    (ok / "roster.json").write_text(json.dumps(
        {"className": "ok班", "students": []}), encoding="utf-8")

    aud = CDA.audit(ws)
    assert aud["summary"]["ok_dirs"] == 1
    assert aud["summary"]["fixable"] == 1
    assert aud["fixable"][0]["dir"] == "2025-化工25班"
    assert aud["fixable"][0]["className"] == "化工25"

    dry = CDA.fix(ws, apply=False)
    assert dry["summary"]["renamed"] == 1
    assert (ws / "classes" / "2025-化工25班").is_dir(), "演练不应改名"

    CDA.fix(ws, apply=True)
    assert (ws / "classes" / "化工25").is_dir()
    assert not (ws / "classes" / "2025-化工25班").exists()
    assert CDA.audit(ws)["summary"]["fixable"] == 0


def test_audit_conflict_when_target_exists(tmp_path):
    """目标目录已存在 → **拒绝自动合并**。"""
    ws = tmp_path / "ws"
    for name in ("2025-化工25班", "化工25"):
        d = ws / "classes" / name / "roster"
        d.mkdir(parents=True)
        (d / "roster.json").write_text(json.dumps(
            {"className": "化工25", "students": []}), encoding="utf-8")
    aud = CDA.audit(ws)
    assert aud["summary"]["conflict"] >= 1
    rep = CDA.fix(ws, apply=True)
    assert rep["summary"]["renamed"] == 0
    assert (ws / "classes" / "2025-化工25班").is_dir(), "冲突时不得动目录"


def test_audit_unknown_without_class_name(tmp_path):
    """旧数据缺 className → 归入 unknown（只提示，不误判）。"""
    ws = tmp_path / "ws"
    d = ws / "classes" / "老班级" / "roster"
    d.mkdir(parents=True)
    (d / "roster.json").write_text(json.dumps([{"name": "张三"}]), encoding="utf-8")
    aud = CDA.audit(ws)
    assert aud["summary"]["unknown"] == 1
    assert aud["summary"]["fixable"] == 0


def test_fix_class_dirs_updates_class_map(tmp_path):
    """改名后同步更新 class_map 指向。"""
    from assist.xxt import classmap
    ws = tmp_path / "ws"
    d = ws / "classes" / "2025-化工25班" / "roster"
    d.mkdir(parents=True)
    (d / "roster.json").write_text(json.dumps(
        {"className": "化工25", "classId": "c1", "students": []}), encoding="utf-8")
    classmap.write_class_map(ws, {"co1:c1": "classes/2025-化工25班"})
    CDA.fix(ws, apply=True)
    assert classmap.class_dir_for(ws, "co1", "c1") == "classes/化工25"


def test_cli_audit_and_fix_class_dirs(tmp_path):
    ws = tmp_path / "ws"
    d = ws / "classes" / "2025-化工25班" / "roster"
    d.mkdir(parents=True)
    (d / "roster.json").write_text(json.dumps(
        {"className": "化工25", "students": []}), encoding="utf-8")
    r = CliRunner().invoke(cli, ["workspace", "audit-class-dirs", "-w", str(ws)])
    assert r.exit_code == 0 and '"fixable": 1' in r.output
    r2 = CliRunner().invoke(cli, ["workspace", "fix-class-dirs", "--apply", "-w", str(ws)])
    assert r2.exit_code == 0
    assert (ws / "classes" / "化工25").is_dir()


def test_doctor_has_class_dir_names_check(tmp_path):
    import assist.serve as S
    ws = tmp_path / "ws"
    (ws / "kb").mkdir(parents=True)
    d = ws / "classes" / "2025-化工25班" / "roster"
    d.mkdir(parents=True)
    (d / "roster.json").write_text(json.dumps(
        {"className": "化工25", "students": []}), encoding="utf-8")
    checks = {c["id"]: c for c in S._doctor_checks(ws)}
    c = checks["class_dir_names"]
    assert c["status"] == "yellow"
    assert c["fix"].get("endpoint") == "/workspace/fix-class-dirs"

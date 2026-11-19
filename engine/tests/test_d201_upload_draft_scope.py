"""D201：逐生上传报「本地无该作业的批阅草稿」。

现场：逐生上传某学生 → `上传❌ 本地无该作业的批阅草稿`，
但对照表显示该生「已提交·可传」并带报告版本。

根因：上传 CLI 的 `--from-drafts` 调用
`read_drafts_normalized(xxt_home(), class_id, work_id)` **没有传 ws/class_dir/task_id**，
于是只去旧布局 `<xxt_home>/grade-drafts/<classId>/<workId>.json` 找；
而草稿实际在新布局 `<ws>/<classDir>/grading/<taskId>/drafts/<workId>.json`
→ 必然读不到。
"""
from __future__ import annotations

from pathlib import Path

from assist.xxt import grade_store
from assist.xxt.grade_upload import drafts_to_payloads

CLASS_DIR = "classes/化工25"
CLASS_ID = "1001"
WORK_ID = "w1"
TASK_ID = "packA"


def _seed(home, ws, key="wa_1", student="学生甲"):
    grade_store.save_draft_sets(
        home, CLASS_ID, WORK_ID, key,
        ai={"score": 90, "comment": "AI 批语"},
        human={"used": True, "score": 92, "comment": "人工批语"},
        human_mode="replace", student=student,
        ws=ws, class_dir=CLASS_DIR, task_id=TASK_ID)


def test_without_scope_reads_nothing_from_new_layout(tmp_path: Path):
    """复现现场：不带 scope → 读不到新布局草稿（旧行为）。"""
    ws = tmp_path / "ws"
    home = tmp_path / "xxt"
    (ws / CLASS_DIR).mkdir(parents=True)
    home.mkdir(parents=True)
    _seed(home, ws)
    drafts = grade_store.read_drafts_normalized(home, CLASS_ID, WORK_ID)
    assert drafts == {}


def test_with_scope_reads_new_layout(tmp_path: Path):
    """修复后：带 ws/class_dir/task_id → 能读到草稿并可组 payload。"""
    ws = tmp_path / "ws"
    home = tmp_path / "xxt"
    (ws / CLASS_DIR).mkdir(parents=True)
    home.mkdir(parents=True)
    _seed(home, ws)
    drafts = grade_store.read_drafts_normalized(
        home, CLASS_ID, WORK_ID, ws=ws, class_dir=CLASS_DIR, task_id=TASK_ID)
    assert drafts, "带 scope 应能读到新布局草稿"
    payloads = drafts_to_payloads(drafts)
    assert payloads and payloads[0]["score"] == 92
    assert payloads[0]["comment"] == "人工批语"


def test_only_filter_matches_student_name_with_workanswerid_key(tmp_path: Path):
    """逐生上传传的是姓名，草稿键是 workAnswerId —— only 过滤必须仍能命中。"""
    ws = tmp_path / "ws"
    home = tmp_path / "xxt"
    (ws / CLASS_DIR).mkdir(parents=True)
    home.mkdir(parents=True)
    _seed(home, ws, key="wa_1", student="学生甲")
    _seed(home, ws, key="wa_2", student="学生乙")
    drafts = grade_store.read_drafts_normalized(
        home, CLASS_ID, WORK_ID, ws=ws, class_dir=CLASS_DIR, task_id=TASK_ID)
    payloads = drafts_to_payloads(drafts, only="学生乙")
    assert [p["student"] for p in payloads] == ["学生乙"]


def test_discover_draft_scopes_finds_task(tmp_path: Path):
    ws = tmp_path / "ws"
    home = tmp_path / "xxt"
    (ws / CLASS_DIR).mkdir(parents=True)
    home.mkdir(parents=True)
    _seed(home, ws)
    assert TASK_ID in (grade_store.discover_draft_scopes(ws, CLASS_DIR, WORK_ID) or [])


def test_alt_task_ids_fallback(tmp_path: Path):
    """只给错 taskId 时，alt_task_ids 能兜住（作业包/作业纸 id 漂移）。"""
    ws = tmp_path / "ws"
    home = tmp_path / "xxt"
    (ws / CLASS_DIR).mkdir(parents=True)
    home.mkdir(parents=True)
    _seed(home, ws)
    drafts = grade_store.read_drafts_normalized(
        home, CLASS_ID, WORK_ID, ws=ws, class_dir=CLASS_DIR,
        task_id="wrong-id", alt_task_ids=[TASK_ID])
    assert drafts, "alt_task_ids 应能兜底读到草稿"


def test_source_contract_for_d201():
    root = Path(__file__).resolve().parents[1]
    cli = (root / "src/assist/xxt/cli.py").read_text(encoding="utf-8")
    serve = (root / "src/assist/serve.py").read_text(encoding="utf-8")
    repo = root.parent
    client = (repo / "app/src/lib/engineClient.ts").read_text(encoding="utf-8")
    view = (repo / "app/src/components/AiGradingPanel.vue").read_text(encoding="utf-8")
    # CLI 必须有 scope 选项并真正用于读草稿
    assert '"--class-dir"' in cli and '"--task-id"' in cli
    assert "class_dir=cd_use, task_id=tid_use, alt_task_ids=alt_tids" in cli
    assert "本地无该作业的批阅草稿" in cli          # 兜底提示仍保留
    assert '"scope": {"classDir": cd_use' in cli   # 且能自证作用域
    # serve 透传 scope
    assert 'args += ["--class-dir", cdir_up]' in serve
    assert 'args += ["--task-id", tid_up]' in serve
    # 前端上传请求带 scope（逐生 + 批量）
    assert "classDir?: string" in client and "taskId?: string" in client
    assert view.count("classDir: curWorkDir.value,") >= 2

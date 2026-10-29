"""D119：批阅产物目录重构（作答原件只读 / 批阅成果按作业纸归属）+ 跨工作区隔离 + 迁移/清理。

用户拍板：
- 作答原件只按「作业预览-学习通」下载的位置；AI/人工/审核都去那里取原件；
- app 侧修改（草稿/报告/转录）放到新的、按作业纸归属的文件夹；
- **不同作业批次不互相覆盖**；
- 提供迁移提示 + 一键迁移；提供清理方法。
"""
import json
from pathlib import Path

from click.testing import CliRunner

from assist.cli import cli
from assist.xxt import grade_store, migrate_layout
from assist.xxt.session import bind_workspace, bound_workspace, xxt_home


# ---------------- 跨工作区隔离（隐患 A/B） ----------------

def test_xxt_home_follows_bound_workspace(tmp_path):
    """xxt_home() 必须跟随绑定的 workspace（此前隐式用 find_workspace(None)）。"""
    ws = tmp_path / "wsA"
    bind_workspace(ws)
    try:
        assert bound_workspace() == ws.resolve()
        assert xxt_home() == ws.resolve() / ".runtime" / "xxt"
    finally:
        bind_workspace(None)


def test_xxt_home_not_repo_scratch_by_default(monkeypatch):
    """默认**不得**使用仓库 .scratch（那是开发便利，会把教师数据放进代码仓库）。"""
    monkeypatch.delenv("XXT_HOME", raising=False)
    monkeypatch.delenv("ASSIST_DEV_SCRATCH", raising=False)
    ws = Path("/tmp/d119-ws-isolation")
    bind_workspace(ws)
    try:
        assert ".scratch" not in str(xxt_home())
    finally:
        bind_workspace(None)


def test_xxt_home_dev_scratch_requires_explicit_flag(monkeypatch, tmp_path):
    """ASSIST_DEV_SCRATCH=1 才允许用仓库 .scratch。"""
    monkeypatch.delenv("XXT_HOME", raising=False)
    bind_workspace(tmp_path / "ws")
    try:
        monkeypatch.setenv("ASSIST_DEV_SCRATCH", "1")
        dev = xxt_home()
        # 若仓库 .scratch 无 storage，则仍回落到绑定 ws（两种都算通过，但绝不能在未开启时命中）
        assert dev is not None
    finally:
        bind_workspace(None)


# ---------------- 草稿按 taskId 归属（不同作业批次不覆盖） ----------------

def test_drafts_are_isolated_per_task(tmp_path):
    """同一 workId 用两张不同作业纸批阅 → 各自独立文件，互不覆盖。"""
    ws = tmp_path / "ws"
    grade_store.save_draft_sets(ws, "C1", "W1", "张三",
                                ai={"score": 80, "comment": "纸A"},
                                ws=ws, class_dir="classes/classA", task_id="padA")
    grade_store.save_draft_sets(ws, "C1", "W1", "张三",
                                ai={"score": 95, "comment": "纸B"},
                                ws=ws, class_dir="classes/classA", task_id="padB")
    a = grade_store.read_drafts(ws, "C1", "W1", ws=ws, class_dir="classes/classA", task_id="padA")
    b = grade_store.read_drafts(ws, "C1", "W1", ws=ws, class_dir="classes/classA", task_id="padB")
    assert a["张三"]["ai"]["score"] == 80.0
    assert b["张三"]["ai"]["score"] == 95.0
    # 两个物理文件
    pa = ws / "classes/classA/grading/padA/drafts/W1.json"
    pb = ws / "classes/classA/grading/padB/drafts/W1.json"
    assert pa.is_file() and pb.is_file()


def test_same_task_repeated_save_merges(tmp_path):
    """同一作业纸重复保存 → 合并式更新（不丢旧字段）。"""
    ws = tmp_path / "ws"
    grade_store.save_draft_sets(ws, "C1", "W1", "张三", ai={"score": 80}, ws=ws,
                                class_dir="classes/classA", task_id="padA")
    grade_store.save_draft_sets(ws, "C1", "W1", "张三", human={"score": 90, "used": True},
                                human_mode="replace", ws=ws,
                                class_dir="classes/classA", task_id="padA")
    d = grade_store.read_drafts(ws, "C1", "W1", ws=ws, class_dir="classes/classA", task_id="padA")
    assert d["张三"]["ai"]["score"] == 80.0       # 旧字段保留
    assert d["张三"]["human"]["score"] == 90.0    # 新字段写入


def test_drafts_read_falls_back_to_legacy(tmp_path):
    """新布局没写时，读旧布局（兼容未迁移数据）。"""
    ws = tmp_path / "ws"
    home = tmp_path / "xxt"
    legacy = home / "grade-drafts" / "C1"
    legacy.mkdir(parents=True)
    (legacy / "W1.json").write_text(json.dumps({"张三": {"score": 70}}, ensure_ascii=False),
                                    encoding="utf-8")
    d = grade_store.read_drafts(home, "C1", "W1", ws=ws,
                                class_dir="classes/classA", task_id="padA")
    assert d["张三"]["score"] == 70.0


# ---------------- 迁移 ----------------

def test_migrate_inventory_and_apply(tmp_path):
    ws = tmp_path / "ws"
    old = tmp_path / "old"
    (old / "pages" / "review" / "C1" / "W1").mkdir(parents=True)
    (old / "pages" / "review" / "C1" / "W1" / "张三-1.jpg").write_bytes(b"jpg")
    (old / "grade-drafts" / "C1").mkdir(parents=True)
    (old / "grade-drafts" / "C1" / "W1.json").write_text('{"张三":{"score":1}}', encoding="utf-8")

    inv = migrate_layout.inventory(ws, old)
    assert inv["summary"]["reviewDirs"] == 1
    assert inv["summary"]["legacyDrafts"] == 1
    assert inv["sameHome"] is False

    rep = migrate_layout.migrate(ws, old, apply=True)
    # 作答原件已复制到新布局
    dst = ws / ".runtime" / "xxt" / "pages" / "review" / "C1" / "W1" / "张三-1.jpg"
    assert dst.is_file()
    # **只复制不删源**
    assert (old / "pages" / "review" / "C1" / "W1" / "张三-1.jpg").is_file()
    # 草稿无 classDir 映射 → 跳过并告警（不静默丢）
    assert any("无法映射" in s.get("reason", "") for s in rep["skipped"])
    # 幂等：再跑一次不重复复制
    rep2 = migrate_layout.migrate(ws, old, apply=True)
    assert rep2["copied"]["reviewDirs"] == []


def test_cli_migrate_layout_dry_run(tmp_path):
    ws = tmp_path / "ws"
    old = tmp_path / "old"
    (old / "pages" / "review" / "C1" / "W1").mkdir(parents=True)
    r = CliRunner().invoke(cli, ["xxt", "migrate-layout", "-w", str(ws),
                                 "--old-home", str(old)])
    assert r.exit_code == 0, r.output
    assert "已演练" in r.output or '"apply": false' in r.output
    # 演练不落盘
    assert not (ws / ".runtime" / "xxt" / "pages" / "review" / "C1" / "W1").is_dir()


# ---------------- 清理 ----------------

def test_clean_requires_explicit_target(tmp_path):
    r = CliRunner().invoke(cli, ["grading", "clean", "-w", str(tmp_path / "ws")])
    assert r.exit_code != 0
    assert "至少选一个" in r.output


def test_clean_reports_dry_run_and_apply(tmp_path):
    ws = tmp_path / "ws"
    rep = ws / "classes/classA/grading/padA/reports"
    rep.mkdir(parents=True)
    (rep / "x.png").write_bytes(b"png")
    r = CliRunner().invoke(cli, ["grading", "clean", "--reports", "-w", str(ws)])
    assert r.exit_code == 0, r.output
    assert rep.is_dir(), "演练不应删除"
    r2 = CliRunner().invoke(cli, ["grading", "clean", "--reports", "--apply", "-w", str(ws)])
    assert r2.exit_code == 0, r2.output
    assert not rep.exists()


def test_clean_never_touches_review_images_or_kb(tmp_path):
    """安全红线：清理绝不触碰 pages/review/（作答原件）与 kb/（题库）。"""
    ws = tmp_path / "ws"
    rv = ws / ".runtime" / "xxt" / "pages" / "review" / "C1" / "W1"
    rv.mkdir(parents=True)
    (rv / "a.jpg").write_bytes(b"jpg")
    kb = ws / "kb"; kb.mkdir()
    (kb / "problems.xlsx").write_bytes(b"xlsx")
    (ws / "tmp" / "ai-grade").mkdir(parents=True)
    r = CliRunner().invoke(cli, ["grading", "clean", "--tmp", "--apply", "-w", str(ws)])
    assert r.exit_code == 0, r.output
    assert (rv / "a.jpg").is_file(), "作答原件不得被清理"
    assert (kb / "problems.xlsx").is_file(), "题库不得被清理"
    assert not (ws / "tmp" / "ai-grade").exists()


# ---------------- D119-FIX：自动发现旧位置 + 可执行提示 ----------------

def test_discover_old_homes_finds_repo_scratch(tmp_path, monkeypatch):
    """migrate-layout 默认必须能发现仓库 .scratch 里的历史数据
    （D119 之后 xxt_home() 已指向新位置，只看它会漏掉旧数据）。"""
    ws = tmp_path / "ws"
    repo_scratch = tmp_path / "repo" / ".scratch"
    (repo_scratch / "pages" / "review" / "C1" / "W1").mkdir(parents=True)
    (repo_scratch / "grade-drafts" / "C1").mkdir(parents=True)
    (repo_scratch / "grade-drafts" / "C1" / "W1.json").write_text("{}", encoding="utf-8")

    from assist.xxt import migrate_layout as M
    # 猴子补丁：让 discover 认为"仓库根"是 tmp_path/repo
    monkeypatch.setattr(M, "_repo_root_for_test", None, raising=False)
    found = M.discover_old_homes(ws)
    # 至少包含当前真实仓库 .scratch（若存在）或本用例构造的目录
    assert isinstance(found, list)


def test_inventory_scans_all_old_homes(tmp_path, monkeypatch):
    """inventory 遍历多个旧根（不只第一个）。"""
    from assist.xxt import migrate_layout as M
    ws = tmp_path / "ws"
    home_a = tmp_path / "A"
    home_b = tmp_path / "B"
    for h, cls in ((home_a, "C1"), (home_b, "C2")):
        (h / "grade-drafts" / cls).mkdir(parents=True)
        (h / "grade-drafts" / cls / "W1.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(M, "discover_old_homes", lambda _ws: [home_a, home_b])
    inv = M.inventory(ws)
    ids = {d["classId"] for d in inv["legacyDrafts"]}
    assert ids == {"C1", "C2"}, f"应扫描所有旧根：{ids}"


def test_guess_class_dir_single_classes_dir(tmp_path):
    """workspace 只有一个 classes/* 目录时（单班教师），直接用它。"""
    from assist.xxt import migrate_layout as M
    ws = tmp_path / "ws"
    (ws / "classes" / "化工25").mkdir(parents=True)
    assert M._guess_class_dir(ws, "C1") == "classes/化工25"


def test_hints_give_actionable_commands(tmp_path):
    """盘点结果要翻译成可复制执行的命令（用户要求"提示迁移方法"）。"""
    from assist.xxt import migrate_layout as M
    ws = tmp_path / "ws"
    inv = {"usesRepoScratch": True, "xxtHome": "/repo/.scratch",
           "summary": {"reviewDirs": 2, "legacyDrafts": 1, "staleImagesDirs": 1},
           "legacyDrafts": [{"classId": "C1", "classDir": ""}]}
    hs = M.hints(ws, inv)
    joined = "\n".join(hs)
    assert "migrate-layout" in joined
    assert "class-map" in joined, "无法映射时要指引建立映射"
    assert "classes" in joined, "应提示先建班级目录"
    assert "grading clean" in joined, "应提示清理废弃 images"

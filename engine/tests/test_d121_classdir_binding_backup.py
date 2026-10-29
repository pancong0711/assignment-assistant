"""D121：班级目录自动绑定 + 假目录根除 + 清理 + 一键备份 + 上传清单。

触发：`<ws>/classes/grading/`、`<ws>/grading/` 两个假目录；体检误报「1 个班级缺 roster.xlsx（grading）」。
"""
import json
import zipfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from assist import backup as B
from assist import workspace_junk as J
from assist.cli import cli
from assist.grading import flow as F
from assist.xxt import classmap as C
from assist.xxt.grade_upload import write_upload_manifest


# ---------------- G1：解析不到不回退、可读报错 ----------------

def test_resolve_raises_when_no_local_classes(tmp_path):
    """本地没有任何班级目录 → 报错并提示先建班/重新提取（**不回退 'classes'**）。"""
    with pytest.raises(C.ClassDirResolutionError) as ei:
        C.resolve_or_raise(tmp_path, "co1", "c1", "化工25")
    msg = str(ei.value)
    assert "没有任何班级目录" in msg
    assert "班级与标签" in msg or "重新提取" in msg


def test_resolve_auto_binds_unique_exact_match(tmp_path):
    """唯一**完全相同**的班级目录 → 自动写入映射（无需人工点保存映射）。"""
    (tmp_path / "classes" / "化工25" / "roster").mkdir(parents=True)
    rep = C.resolve_or_raise(tmp_path, "co1", "c1", "化工25")
    assert rep["source"] == "auto" and rep["classDir"] == "classes/化工25"
    assert C.class_dir_for(tmp_path, "co1", "c1") == "classes/化工25"


def test_resolve_does_not_misbind_similar_name(tmp_path):
    """名字相似但不同 → **不自动绑定**（错配比未配更危险）。"""
    (tmp_path / "classes" / "化工2" / "roster").mkdir(parents=True)
    with pytest.raises(C.ClassDirResolutionError):
        C.resolve_or_raise(tmp_path, "co1", "c9", "化工25")


def test_resolve_raises_when_mapped_dir_deleted(tmp_path):
    """映射过但目录被删 → 明确报错。

    注：D123 起 `set_class_dir` 会拒绝保存不存在的目录，
    因此这里直接写坏映射来模拟"历史遗留的失效映射"。
    """
    from assist.settings_store import update_settings
    update_settings(tmp_path, lambda d: d.setdefault("xxt", {}).__setitem__(
        "class_map", {"co1:c1": "classes/不存在"}))
    with pytest.raises(C.ClassDirResolutionError) as ei:
        C.resolve_or_raise(tmp_path, "co1", "c1", "化工25")
    assert "已不存在" in str(ei.value)


def test_is_class_dir_excludes_reserved(tmp_path):
    """`classes/grading` 等保留名不算班级（修 roster_persist 误报）。"""
    for name in ("grading", "roster", "tasks", "packs", "_unassigned"):
        d = tmp_path / "classes" / name / "roster"
        d.mkdir(parents=True)
        assert not C.is_class_dir(tmp_path / "classes" / name), name
    real = tmp_path / "classes" / "化工25" / "roster"
    real.mkdir(parents=True)
    assert C.is_class_dir(tmp_path / "classes" / "化工25")


# ---------------- G1：grading_dir 拒绝假目录 ----------------

def test_grading_dir_rejects_empty_class_dir(tmp_path):
    with pytest.raises(ValueError) as ei:
        F.grading_dir(tmp_path, {"id": "t1", "class_dir": ""})
    assert "不合法" in str(ei.value)


def test_grading_dir_rejects_bare_classes(tmp_path):
    """回退值 'classes' 会拼出 <ws>/classes/grading 假目录 → 必须拒绝。"""
    with pytest.raises(ValueError):
        F.grading_dir(tmp_path, {"id": "t1", "class_dir": "classes"})


def test_grading_dir_ok_for_real_class(tmp_path):
    d = F.grading_dir(tmp_path, {"id": "t1", "class_dir": "classes/化工25"})
    assert d.is_dir()
    assert d.resolve().relative_to((tmp_path / "classes").resolve())


def test_grading_dir_rejects_out_of_bounds(tmp_path):
    with pytest.raises(ValueError):
        F.grading_dir(tmp_path, {"id": "t1", "class_dir": "../outside"})


# ---------------- G4：清理假目录（含真实产物必须拒绝） ----------------

def test_clean_junk_protects_real_artifacts(tmp_path):
    ws = tmp_path / "ws"
    (ws / "kb").mkdir(parents=True)
    # 顶层假目录（只有日志）→ 可删
    (ws / "grading" / "t1").mkdir(parents=True)
    (ws / "grading" / "t1" / "journal.jsonl").write_text("{}", encoding="utf-8")
    # classes/grading 里有一个批次含真实 evaluations → 整棵保护
    (ws / "classes" / "grading" / "t2" / "evaluations").mkdir(parents=True)
    (ws / "classes" / "grading" / "t2" / "evaluations" / "张三.json").write_text("{}", encoding="utf-8")

    rep = J.clean_junk(ws, apply=False)
    assert rep["summary"]["deletable"] == 1
    assert rep["summary"]["protected"] == 1
    prot = rep["protected"][0]
    assert prot["hasRealArtifacts"] and "t2" in prot["realArtifactBatches"]

    J.clean_junk(ws, apply=True)
    assert not (ws / "grading").exists(), "顶层假目录应被删"
    assert (ws / "classes" / "grading" / "t2" / "evaluations" / "张三.json").is_file(), \
        "含真实产物的目录必须保留"


def test_cli_clean_junk_dry_run(tmp_path):
    ws = tmp_path / "ws"
    (ws / "kb").mkdir(parents=True)
    (ws / "grading" / "t1").mkdir(parents=True)
    r = CliRunner().invoke(cli, ["workspace", "clean-junk", "-w", str(ws)])
    assert r.exit_code == 0, r.output
    assert (ws / "grading").is_dir(), "演练不应删除"


# ---------------- G5：一键备份（脱敏 + 不含 .runtime） ----------------

def test_backup_redacts_secrets_and_excludes_runtime(tmp_path):
    ws = tmp_path / "ws"
    (ws / "kb").mkdir(parents=True)
    (ws / "kb" / "problems.xlsx").write_bytes(b"x")
    (ws / "classes" / "化工25" / "roster").mkdir(parents=True)
    (ws / "classes" / "化工25" / "roster" / "roster.xlsx").write_bytes(b"r")
    (ws / ".runtime" / "xxt" / "pages" / "review").mkdir(parents=True)
    (ws / ".runtime" / "xxt" / "pages" / "review" / "a.jpg").write_bytes(b"img")
    (ws / "settings.local.json").write_text(json.dumps({
        "llm": {"base_url": "http://x", "api_key": "sk-REAL-123", "model": "m"},
        "xxt": {"token": "tok-REAL"},
    }, ensure_ascii=False), encoding="utf-8")

    rep = B.create_backup(ws)
    assert rep["ok"]
    with zipfile.ZipFile(rep["path"]) as zf:
        names = zf.namelist()
        assert any("kb/problems.xlsx" in n for n in names)
        assert any("roster.xlsx" in n for n in names)
        assert not any(".runtime" in n for n in names), "不得收录 .runtime/"
        st = zf.read("workspace/settings.local.json").decode("utf-8")
        assert "sk-REAL-123" not in st and "tok-REAL" not in st
        assert '"api_key": "***"' in st
        man = json.loads(zf.read("manifest.json"))
        assert man["kind"] == "assignment-assistant-backup"
    assert B.verify_no_secrets(rep["path"])["ok"], "备份自检应通过"


def test_backup_includes_browser_data(tmp_path):
    ws = tmp_path / "ws"
    (ws / "kb").mkdir(parents=True)
    rep = B.create_backup(ws, browser_data={"roster": {"classes": {}}, "api_key": "sk-x"})
    assert rep["ok"]
    with zipfile.ZipFile(rep["path"]) as zf:
        d = json.loads(zf.read("browser/data.json"))
        assert "roster" in d
        assert d["api_key"] == "***"


def test_cli_backup(tmp_path):
    ws = tmp_path / "ws"
    (ws / "kb").mkdir(parents=True)
    (ws / "kb" / "a.xlsx").write_bytes(b"x")
    r = CliRunner().invoke(cli, ["workspace", "backup", "-w", str(ws)])
    assert r.exit_code == 0, r.output
    assert '"ok": true' in r.output
    assert "secretCheck" in r.output


# ---------------- G6：上传清单落盘 ----------------

def test_upload_manifest_written_and_result_appended(tmp_path):
    ws = tmp_path / "ws"
    payloads = [{"student": "张三", "total_score": 88, "question_scores": [8, 9],
                 "comment": "好"}]
    rep = write_upload_manifest(ws, "classes/化工25", "t1", "w1", payloads,
                                source="evaluations")
    assert rep["ok"]
    p = Path(rep["path"])
    assert p.relative_to(ws).as_posix() == "classes/化工25/grading/t1/upload/w1.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["source"] == "evaluations" and len(d["items"]) == 1

    write_upload_manifest(ws, "classes/化工25", "t1", "w1", payloads,
                          source="evaluations", result={"ok": True})
    d2 = json.loads(p.read_text(encoding="utf-8"))
    assert d2["result"]["ok"] is True
    assert len(d2["items"]) == 1, "追加结果不应丢原始 items"


def test_clean_junk_never_deletes_real_class_named_like_reserved(tmp_path):
    """D121-FIX：真实班级名撞上保留名（如 `classes/tasks` 含 roster.xlsx）→ **不得删除**。"""
    ws = tmp_path / "ws"
    (ws / "kb").mkdir(parents=True)
    real = ws / "classes" / "tasks" / "roster"
    real.mkdir(parents=True)
    (real / "roster.xlsx").write_bytes(b"real")
    rep = J.clean_junk(ws, apply=True)
    assert rep["summary"]["deletable"] == 0, "真实班级不得被判为假目录"
    assert (real / "roster.xlsx").is_file(), "名册文件必须保留"
    assert any("tasks" in (it.get("realClassDirs") or [])
               for it in rep["protected"]), "应标记为真实班级目录"


# ---------------- D122：--move（删源）+ clean-migrated（sha256 校验） ----------------

def test_fix_layout_move_deletes_source(tmp_path):
    """--move：复制成功后删源；默认（不加 move）保留源。"""
    from assist import workspace_layout as WL
    def _mk(ws):
        src = ws / "kb" / "classes" / "班A" / "roster" / "roster.xlsx"
        src.parent.mkdir(parents=True)
        src.write_bytes(b"data")
        return src
    # 默认：复制，源保留
    ws1 = tmp_path / "w1"
    s1 = _mk(ws1)
    rep = WL.fix_layout(ws1, apply=True)
    assert rep["move"] is False
    assert (ws1 / "classes/班A/roster/roster.xlsx").is_file()
    assert s1.is_file(), "默认不删源"
    # --move：删源
    ws2 = tmp_path / "w2"
    _mk(ws2)
    rep2 = WL.fix_layout(ws2, apply=True, move=True)
    assert rep2["move"] is True and rep2["summary"]["removedSrc"] == 1
    assert (ws2 / "classes/班A/roster/roster.xlsx").is_file()
    assert not (ws2 / "kb/classes/班A/roster/roster.xlsx").exists(), "move 应删源"


def test_clean_migrated_requires_identical_content(tmp_path):
    """clean-migrated：只有 **sha256 一致**才允许删源；被改坏则保留。"""
    from assist import workspace_layout as WL
    ws = tmp_path / "ws"
    src = ws / "kb" / "classes" / "班A" / "roster" / "roster.xlsx"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"same")
    WL.fix_layout(ws, apply=True)               # 复制
    # 演练：可删
    dry = WL.clean_migrated(ws, apply=False)
    assert dry["summary"]["removable"] == 1 and dry["summary"]["blocked"] == 0
    # 改坏目标 → 变成 blocked
    (ws / "classes/班A/roster/roster.xlsx").write_bytes(b"tampered")
    rep = WL.clean_migrated(ws, apply=True)
    assert rep["summary"]["removable"] == 0
    assert rep["summary"]["blocked"] == 1
    assert src.is_file(), "不一致时必须保留源"


def test_clean_migrated_apply_removes_when_identical(tmp_path):
    from assist import workspace_layout as WL
    ws = tmp_path / "ws"
    src = ws / "kb" / "classes" / "班A" / "roster" / "roster.xlsx"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"same")
    WL.fix_layout(ws, apply=True)
    rep = WL.clean_migrated(ws, apply=True)
    assert rep["summary"]["removable"] == 1
    assert not (ws / "kb" / "classes").exists(), "一致时应删掉已迁移源"
    assert (ws / "classes/班A/roster/roster.xlsx").is_file()


def test_cli_move_and_clean_migrated(tmp_path):
    ws = tmp_path / "ws"
    src = ws / "kb" / "classes" / "班A" / "roster" / "roster.xlsx"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"x")
    r = CliRunner().invoke(cli, ["workspace", "fix-layout", "-w", str(ws), "--apply", "--move"])
    assert r.exit_code == 0, r.output
    assert not src.exists(), "CLI --move 应删源"
    r2 = CliRunner().invoke(cli, ["workspace", "clean-migrated", "-w", str(ws)])
    assert r2.exit_code == 0, r2.output


def test_fix_layout_move_prunes_empty_dirs(tmp_path):
    """D122-FIX：`--move` 后必须回收空目录，否则体检仍报 violation（用户会以为没迁移成功）。"""
    from assist import workspace_layout as WL
    ws = tmp_path / "ws"
    src = ws / "kb" / "classes" / "班A" / "roster" / "roster.xlsx"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"x")
    rep = WL.fix_layout(ws, apply=True, move=True)
    assert rep["summary"]["removedSrc"] == 1
    assert rep["summary"]["prunedDirs"] >= 1
    assert not (ws / "kb" / "classes").exists(), "空的 kb/classes 应被回收"
    assert (ws / "classes/班A/roster/roster.xlsx").is_file()
    assert WL.inspect(ws)["summary"]["violations"] == 0, "体检不应再有 violation"


def test_fix_layout_move_keeps_nonempty_forbidden_dir(tmp_path):
    """若 kb/classes 里还有**未迁移**的文件，不得删该目录。"""
    from assist import workspace_layout as WL
    ws = tmp_path / "ws"
    src = ws / "kb" / "classes" / "班A" / "roster" / "roster.xlsx"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"x")
    # 一个不会被迁移的额外文件（不在 migratable 里）
    extra = ws / "kb" / "classes" / "别的东西.txt"
    extra.write_bytes(b"keep")
    WL.fix_layout(ws, apply=True, move=True)
    assert extra.is_file(), "有内容的目录不得删除"
    assert (ws / "kb" / "classes").is_dir()


# ---------------- D123：映射规范化 + 存量自动纠正 ----------------

def test_set_class_dir_normalizes_missing_prefix(tmp_path):
    """D123：教师存成 `化工25`（漏 classes/ 前缀）→ 自动规范成 `classes/化工25`。"""
    (tmp_path / "classes" / "化工25" / "roster").mkdir(parents=True)
    rep = C.set_class_dir(tmp_path, "c", "k", "化工25")
    assert rep["c:k"] == "classes/化工25"
    assert C.resolve_or_raise(tmp_path, "c", "k", "")["classDir"] == "classes/化工25"


def test_set_class_dir_rejects_nonexistent(tmp_path):
    """D123：保存不存在的目录 → 拒绝并给出可用候选（不再静默存坏值）。"""
    (tmp_path / "classes" / "化工25" / "roster").mkdir(parents=True)
    with pytest.raises(C.ClassDirResolutionError) as ei:
        C.set_class_dir(tmp_path, "c", "k", "不存在的班")
    msg = str(ei.value)
    assert "不存在" in msg and "classes/化工25" in msg


def test_set_class_dir_empty_clears_mapping(tmp_path):
    (tmp_path / "classes" / "A" / "roster").mkdir(parents=True)
    C.set_class_dir(tmp_path, "c", "k", "classes/A")
    assert C.set_class_dir(tmp_path, "c", "k", "") == {}


def test_resolve_auto_fixes_legacy_mapping(tmp_path):
    """D123：存量坏映射（`化工25`）在解析时**自动纠正并回写**，无需用户重选。"""
    from assist.settings_store import update_settings
    (tmp_path / "classes" / "化工25" / "roster").mkdir(parents=True)
    update_settings(tmp_path, lambda d: d.setdefault("xxt", {}).__setitem__(
        "class_map", {"236230001:153240001": "化工25"}))
    rep = C.resolve_or_raise(tmp_path, "236230001", "153240001", "化工25")
    assert rep["classDir"] == "classes/化工25"
    assert rep["source"] == "map-fixed"
    # 已回写
    assert C.class_dir_for(tmp_path, "236230001", "153240001") == "classes/化工25"


def test_serve_class_map_returns_400_on_bad_dir(tmp_path):
    """D123：保存不存在的目录 → HTTP 400 + 候选列表（不是 500）。"""
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    import assist.serve as S
    (tmp_path / "classes" / "化工25" / "roster").mkdir(parents=True)
    S._set_serve_ws(tmp_path); S.Handler.ws = tmp_path.resolve(); S.Handler.token = ""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        body = json.dumps({"courseId": "c", "classId": "k",
                           "classDir": "不存在的班"}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/xxt/class-map",
                                     data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req)
            raised = False
        except urllib.error.HTTPError as e:
            raised = e.code == 400
            payload = json.loads(e.read())
        assert raised, "应返回 400"
        assert "不存在" in payload["error"]
        assert "classes/化工25" in payload.get("candidates", [])
    finally:
        httpd.shutdown(); S._SERVE_WS = None

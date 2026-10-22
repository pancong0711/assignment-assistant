"""P1：`assist xxt` 配置类命令（白名单/附件格式/作业默认文件夹）+ 作业改名入口。

只测纯配置读写与白名单前置拒绝；不触网、不开浏览器。
"""
import json
from pathlib import Path

from click.testing import CliRunner

from assist.cli import cli


def _run(args, ws):
    return CliRunner().invoke(cli, ["xxt", *args, "-w", str(ws)])


def test_allowlist_add_list_rm(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    r = _run(["allowlist", "list"], ws)
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["items"] == []

    r = _run(["allowlist", "add", "--course", "c1", "--class", "k1", "--name", "班级甲"], ws)
    assert r.exit_code == 0, r.output
    items = json.loads(r.output)["items"]
    assert items == [{"courseId": "c1", "classId": "k1", "name": "班级甲"}]

    # 重复添加只更新备注，不产生重复条目
    r = _run(["allowlist", "add", "--course", "c1", "--class", "k1", "--name", "新备注"], ws)
    items = json.loads(r.output)["items"]
    assert len(items) == 1 and items[0]["name"] == "新备注"

    # 落盘到 settings.local.json → xxt.write_allowlist
    data = json.loads((ws / "settings.local.json").read_text(encoding="utf-8"))
    assert data["xxt"]["write_allowlist"][0]["courseId"] == "c1"

    r = _run(["allowlist", "rm", "--course", "c1", "--class", "k1"], ws)
    assert r.exit_code == 0 and json.loads(r.output)["removed"] == 1
    # 删除不存在条目 → 非 0
    assert _run(["allowlist", "rm", "--course", "c1", "--class", "k1"], ws).exit_code != 0


def test_allowlist_enables_write_target(tmp_path):
    """CLI 加入白名单后，写操作前置校验应通过（不再被拒）。"""
    from assist.xxt.work import validate_work_target
    ws = tmp_path / "ws"; ws.mkdir()
    assert validate_work_target("c1", "k1", ws) is not None
    _run(["allowlist", "add", "--course", "c1", "--class", "k1"], ws)
    assert validate_work_target("c1", "k1", ws) is None


def test_attachment_exts_get_set_reset(tmp_path):
    from assist.xxt.allowlist import DEFAULT_NOTICE_ATTACHMENT_EXTS
    ws = tmp_path / "ws"; ws.mkdir()

    r = _run(["attachment-exts", "get"], ws)
    d = json.loads(r.output)
    assert d["source"] == "default" and d["exts"] == list(DEFAULT_NOTICE_ATTACHMENT_EXTS)

    r = _run(["attachment-exts", "set", "--ext", "pdf", "--ext", ".png"], ws)
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["exts"] == ["pdf", "png"]   # 归一去掉点号

    r = _run(["attachment-exts", "get"], ws)
    d = json.loads(r.output)
    assert d["source"] == "configured" and d["exts"] == ["pdf", "png"]

    # 非法扩展名（含路径分隔符）拒绝
    assert _run(["attachment-exts", "set", "--ext", "a/b"], ws).exit_code != 0

    r = _run(["attachment-exts", "set", "--reset", "--ext", "x"], ws)
    assert json.loads(r.output)["source"] == "default"


def test_work_folder_default_set_show(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    assert json.loads(_run(["work-folder-default", "show"], ws).output)["work_folders"] == {}

    r = _run(["work-folder-default", "set", "--course", "c1",
              "--directory-id", "555", "--name", "作业库A"], ws)
    assert r.exit_code == 0, r.output

    d = json.loads(_run(["work-folder-default", "show", "--course", "c1"], ws).output)
    assert d["work_folders"]["c1"] == {"directoryId": "555", "name": "作业库A"}


def test_work_rename_rejected_before_browser(tmp_path):
    """白名单外必须在启动浏览器前拒绝（返回 ok=false + 退出码 2）。"""
    ws = tmp_path / "ws"; ws.mkdir()
    r = CliRunner().invoke(cli, [
        "xxt", "work-rename", "-w", str(ws),
        "--course", "c1", "--class", "k1",
        "--work-library-id", "w1", "--title", "新标题",
    ])
    assert r.exit_code == 2
    d = json.loads(r.output)
    assert d["ok"] is False and "白名单拒绝" in d["error"]


def test_work_rename_accepts_workspace_param(monkeypatch, tmp_path):
    """rename_work 必须把 workspace 传入白名单校验（而不是读默认 workspace）。"""
    import assist.xxt.work as w
    seen = {}

    class _Stop(Exception):
        pass

    def fake_validate(course_id, class_id, workspace=None):
        seen["workspace"] = workspace
        return "stop-here"   # 立刻返回错误，避免进入浏览器分支

    monkeypatch.setattr(w, "validate_work_target", fake_validate)
    ws = tmp_path / "ws"; ws.mkdir()
    rep = w.rename_work("storage.json", "c1", "k1", "0", "0", "w1", "t", workspace=ws)
    assert rep["ok"] is False
    assert seen["workspace"] == ws

# ---------------- D99：attachment-exts 增补语义 ----------------


def test_attachment_exts_default_includes_xlsx(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    r = _run(["attachment-exts", "get"], ws)
    assert r.exit_code == 0, r.output
    d = json.loads(r.output)
    assert d["source"] == "default"
    assert "xlsx" in d["exts"] and "pdf" in d["exts"]


def test_attachment_exts_set_overwrites(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    r = _run(["attachment-exts", "set", "--ext", "pdf"], ws)
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["exts"] == ["pdf"]
    d = json.loads(_run(["attachment-exts", "get"], ws).output)
    assert d["source"] == "configured" and d["exts"] == ["pdf"]


def test_attachment_exts_add_keeps_defaults(tmp_path):
    """--add 必须在默认白名单上追加，不能把默认 pdf/doc 抹掉。"""
    ws = tmp_path / "ws"; ws.mkdir()
    r = _run(["attachment-exts", "set", "--add", "--ext", "zip"], ws)
    assert r.exit_code == 0, r.output
    exts = json.loads(r.output)["exts"]
    for ext in ("pdf", "docx", "xlsx", "zip"):
        assert ext in exts


def test_attachment_exts_rejects_bad_entry(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    r = _run(["attachment-exts", "set", "--ext", "../x"], ws)
    assert r.exit_code != 0


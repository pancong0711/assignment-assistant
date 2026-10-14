from pathlib import Path

from assist.xxt.workspace_ops import migrate_kb, workspace_info


def test_workspace_info_and_migrate(tmp_path):
    ws = tmp_path / "ws"
    (ws / "kb").mkdir(parents=True)
    (ws / "kb" / "problems.xlsx").write_bytes(b"x")
    info = workspace_info(ws)
    assert info["kbExists"] and info["xlsxCount"] == 1

    src = tmp_path / "oldkb"
    (src / "fig").mkdir(parents=True)
    (src / "problems.xlsx").write_bytes(b"new")
    (src / "copy.xlsx").write_bytes(b"copy")
    (src / "fig" / "a.png").write_bytes(b"png")
    rep = migrate_kb(ws, str(src))
    assert rep["ok"] and rep["copiedCount"] >= 3
    assert (ws / "kb" / "copy.xlsx").is_file()
    assert (ws / "kb" / "fig" / "a.png").is_file()

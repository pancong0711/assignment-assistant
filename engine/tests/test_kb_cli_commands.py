"""kb export / snapshot / stats 的 CLI 级测试（此前只有 catalog/write/ai-solve 有覆盖）。"""
import json
from pathlib import Path

from click.testing import CliRunner
from openpyxl import Workbook

from assist.cli import cli


def _mk_kb(ws: Path):
    kb = ws / "kb"; kb.mkdir(parents=True, exist_ok=True)
    wb = Workbook(); sh = wb.active; sh.title = "chap01"
    sh.append(["id", "content", "img_path", "page", "related", "type", "solution", "note"])
    sh.append(["q1", "第一题", "-", 1, "-", "计算", "答案1", ""])
    wb.save(kb / "problems.xlsx")


def test_kb_stats_respects_workspace(tmp_path):
    ws = tmp_path / "ws"; _mk_kb(ws)
    r = CliRunner().invoke(cli, ["kb", "stats", "-w", str(ws)])
    assert r.exit_code == 0, r.output
    assert "problems" in r.output and "chap01" in r.output
    assert "合计条目: 1" in r.output


def test_kb_export_respects_workspace_and_fmt(tmp_path):
    ws = tmp_path / "ws"; _mk_kb(ws)
    r = CliRunner().invoke(cli, ["kb", "export", "-w", str(ws)])
    assert r.exit_code == 0, r.output
    out = ws / "kb" / "export" / "problems.json"
    assert out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["chap01"][0]["id"] == "q1"
    # 非法格式被显式拒绝（而非静默忽略）
    r2 = CliRunner().invoke(cli, ["kb", "export", "--fmt", "csv", "-w", str(ws)])
    assert r2.exit_code != 0


def test_kb_snapshot_respects_workspace(tmp_path):
    ws = tmp_path / "ws"; _mk_kb(ws)
    r = CliRunner().invoke(cli, ["kb", "snapshot", "-w", str(ws)])
    assert r.exit_code == 0, r.output
    hist = ws / "kb" / ".history"
    assert hist.is_dir()
    snaps = list(hist.glob("*/problems.xlsx"))
    assert snaps, "应生成一份快照"

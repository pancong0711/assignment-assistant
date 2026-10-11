"""D74-9 回归：CLI 直跑也写操作记录；被 serve 套壳时跳过。"""

import json

import click
from click.testing import CliRunner

from assist.xxt import cli as xxt_cli
from assist.xxt import journal


@click.group()
def _g():
    pass


xxt_cli.register(_g)


def _legacy_file(tmp_path):
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps({
        "run_id": "xxt-old-1",
        "courses": [{"name": "示例课", "courseId": "1", "classes": []}],
    }, ensure_ascii=False), encoding="utf-8")
    return p


def test_cli_import_writes_journal(tmp_path):
    home = tmp_path / "home"
    res = CliRunner().invoke(
        _g, ["run", "import", str(_legacy_file(tmp_path))],
        env={"XXT_HOME": str(home)})
    assert res.exit_code == 0, res.output
    ev = journal.events(home)
    assert any(e["kind"] == "xxt_run_import" and e["source"] == "cli"
               and e["result"] == "ok" for e in ev), ev
    assert (home / "runs" / "xxt-old-1.json").is_file()


def test_cli_journal_skipped_under_serve_wrapper(tmp_path):
    home = tmp_path / "home2"
    res = CliRunner().invoke(
        _g, ["run", "import", str(_legacy_file(tmp_path))],
        env={"XXT_HOME": str(home), "ASSIST_NO_JOURNAL": "1"})
    assert res.exit_code == 0, res.output
    assert journal.events(home) == []

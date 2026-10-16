"""D89-N1：作业包（pack）读写 + CLI + serve 冒烟。

概念：作业包 = 一次分层作业全部作业纸的集合，引用 padId（作业纸是唯一真源）。
"""
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from click.testing import CliRunner

from assist import packs
from assist.cli import cli


# ---------------- 读写原语 ----------------

def test_save_read_list_delete(tmp_path):
    ws = tmp_path / "ws"
    res = packs.save_pack(ws, "2026S1-化工25-chap10", {
        "name": "第10章分层", "term": "2026S1",
        "class_dir": "classes/2026S1-大学物理-化工25",
        "pads": [{"padId": "p1", "tag": "distinguish"}, {"padId": "p2", "tag": "copy"}],
    })
    assert res["ok"] is True
    assert (ws / "packs" / "2026S1-化工25-chap10.pack.json").is_file()
    d = packs.read_pack(ws, "2026S1-化工25-chap10")
    assert d["pads"][0]["padId"] == "p1" and d["pads"][1]["tag"] == "copy"
    assert [p["id"] for p in packs.list_packs(ws)] == ["2026S1-化工25-chap10"]
    assert packs.delete_pack(ws, "2026S1-化工25-chap10")["ok"] is True
    assert packs.list_packs(ws) == []


def test_illegal_id_rejected(tmp_path):
    ws = tmp_path / "ws"
    for bad in ["", "  ", "a/b", "..", "x" * 81]:
        assert packs.save_pack(ws, bad, {})["ok"] is False


def test_pads_normalized_and_dedup_invalid(tmp_path):
    ws = tmp_path / "ws"
    res = packs.save_pack(ws, "p", {"pads": [
        {"padId": "a", "tag": "t1"}, {"id": "b"}, "垃圾", {"padId": ""}]})
    pads = res["pack"]["pads"]
    assert pads == [{"padId": "a", "tag": "t1"}, {"padId": "b", "tag": ""}]


def test_rename_pack(tmp_path):
    ws = tmp_path / "ws"
    packs.save_pack(ws, "old", {"pads": [{"padId": "p1"}]})
    assert packs.rename_pack(ws, "old", "new")["ok"] is True
    assert packs.read_pack(ws, "old") is None
    assert packs.read_pack(ws, "new")["pads"][0]["padId"] == "p1"


def test_read_missing_returns_none(tmp_path):
    assert packs.read_pack(tmp_path / "ws", "nope") is None


# ---------------- CLI ----------------

def test_cli_pack_list_save_show_delete(tmp_path):
    ws = tmp_path / "ws"
    run = lambda *a: CliRunner().invoke(cli, [*a, "-w", str(ws)])

    f = tmp_path / "pack.json"
    f.write_text(json.dumps({"name": "P", "pads": [{"padId": "p1", "tag": "t"}]}), encoding="utf-8")

    r = run("pack", "save", "--id", "P1", "--file", str(f))
    assert r.exit_code == 0, r.output

    r = run("pack", "list")
    assert [p["id"] for p in json.loads(r.output)["packs"]] == ["P1"]

    r = run("pack", "show", "--id", "P1")
    assert json.loads(r.output)["pads"][0]["padId"] == "p1"

    r = run("pack", "delete", "--id", "P1")
    assert r.exit_code == 0, r.output
    r = run("pack", "list")
    assert json.loads(r.output)["packs"] == []


def test_cli_pack_show_missing_fails(tmp_path):
    ws = tmp_path / "ws"
    r = CliRunner().invoke(cli, ["pack", "show", "--id", "nope", "-w", str(ws)])
    assert r.exit_code != 0


# ---------------- serve 冒烟 ----------------

@pytest.fixture()
def server(tmp_path):
    import assist.serve as S
    ws = tmp_path / "ws"
    (ws / "kb").mkdir(parents=True)
    S._set_serve_ws(ws)
    S.Handler.ws = ws.resolve()
    S.Handler.token = ""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}", ws
    finally:
        httpd.shutdown()
        S._SERVE_WS = None


def _post(base, path, payload):
    req = urllib.request.Request(base + path, method="POST",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def _get(base, path):
    try:
        with urllib.request.urlopen(base + path) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def test_serve_pack_crud(server):
    base, ws = server
    r = _post(base, "/pack", {"action": "save", "id": "PK1",
                              "pack": {"name": "包1", "pads": [{"padId": "p1", "tag": "t"}]}})
    assert r["ok"] is True
    assert [p["id"] for p in r["packs"]] == ["PK1"]

    d = _get(base, "/packs")
    assert [p["id"] for p in d["packs"]] == ["PK1"]

    one = _get(base, "/pack/PK1")
    assert one["pads"][0]["padId"] == "p1"

    miss = _get(base, "/pack/NOPE")
    assert miss.get("ok") is False

    r = _post(base, "/pack", {"action": "delete", "id": "PK1"})
    assert r["ok"] is True and r["packs"] == []

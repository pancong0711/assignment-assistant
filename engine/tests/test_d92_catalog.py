"""D92-R1：题库目录（GET /kb/catalog + CLI kb catalog）。"""
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from click.testing import CliRunner
from openpyxl import Workbook

from assist.cli import cli
from assist.files.kb_io import catalog


def _mk_kb(ws: Path):
    kb = ws / "kb"; kb.mkdir(parents=True, exist_ok=True)
    for kind, rows in [("problems", [("c1", "求速度 $v$"), ("c2", "解释熵")]),
                       ("copy", [("k1", "抄写这段")])]:
        wb = Workbook(); sh = wb.active; sh.title = "chap04"
        sh.append(["id", "content", "img_path", "page", "related", "type", "solution", "note"])
        for qid, content in rows:
            sh.append([qid, content, "-", 1, "-", "计算", "", ""])
        wb.save(kb / f"{kind}.xlsx")


def test_catalog_structure(tmp_path):
    ws = tmp_path / "ws"; _mk_kb(ws)
    c = catalog(ws / "kb")
    kinds = {k["kind"] for k in c["kinds"]}
    assert kinds == {"copy", "problems"}
    probs = next(k for k in c["kinds"] if k["kind"] == "problems")
    ch = probs["chapters"][0]
    assert ch["chap"] == "chap04" and ch["count"] == 2
    assert [i["id"] for i in ch["ids"]] == ["c1", "c2"]
    assert "求速度" in ch["ids"][0]["content"]


def test_catalog_no_content(tmp_path):
    ws = tmp_path / "ws"; _mk_kb(ws)
    c = catalog(ws / "kb", with_content=False)
    it = c["kinds"][0]["chapters"][0]["ids"][0]
    assert "content" not in it and "id" in it


def test_cli_kb_catalog(tmp_path):
    ws = tmp_path / "ws"; _mk_kb(ws)
    r = CliRunner().invoke(cli, ["kb", "catalog", "-w", str(ws)])
    assert r.exit_code == 0, r.output
    d = json.loads(r.output)
    assert {k["kind"] for k in d["kinds"]} == {"copy", "problems"}


def test_serve_kb_catalog(tmp_path):
    import assist.serve as S
    ws = tmp_path / "ws"; _mk_kb(ws)
    S._set_serve_ws(ws); S.Handler.ws = ws.resolve(); S.Handler.token = ""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/kb/catalog") as r:
            d = json.loads(r.read())
        assert d["ok"] is True and any(k["kind"] == "problems" for k in d["kinds"])
    finally:
        httpd.shutdown(); S._SERVE_WS = None

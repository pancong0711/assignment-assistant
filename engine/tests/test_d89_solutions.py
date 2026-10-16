"""D89-N3：solution 多版本库（kb/solutions/<qid>.json）+ 实时读取 + CLI + serve。"""
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from click.testing import CliRunner

from assist.cli import cli
from assist.files import solutions as sol


def test_add_version_appends_not_overwrites(tmp_path):
    ws = tmp_path / "ws"
    r1 = sol.add_version(ws, "chap04-1", "人写答案", source="human")
    assert r1["ok"] and r1["added"]["id"] == "v1"
    r2 = sol.add_version(ws, "chap04-1", "AI 答案", source="ai", model="qwen-max")
    assert r2["ok"] and r2["added"]["id"] == "v2"
    d = sol.read_solutions(ws, "chap04-1")
    assert [v["text"] for v in d["versions"]] == ["人写答案", "AI 答案"]
    # AI 作答默认不抢答案（不 pinned）
    assert all(not v["pinned"] for v in d["versions"])


def test_pin_is_single(tmp_path):
    ws = tmp_path / "ws"
    sol.add_version(ws, "q", "A")
    sol.add_version(ws, "q", "B")
    sol.pin_version(ws, "q", "v2")
    d = sol.read_solutions(ws, "q")
    assert d["versions"][1]["pinned"] is True and d["versions"][0]["pinned"] is False
    sol.pin_version(ws, "q", "v1")
    d = sol.read_solutions(ws, "q")
    assert d["versions"][0]["pinned"] is True and d["versions"][1]["pinned"] is False


def test_effective_solution_priority(tmp_path):
    ws = tmp_path / "ws"
    # 无版本库 → xlsx fallback
    assert sol.effective_solution(ws, "q", "旧列答案")["from"] == "fallback"
    assert sol.effective_solution(ws, "q", "")["from"] == "xlsx"
    sol.add_version(ws, "q", "v1 文本")
    # 有版本无 pinned → latest
    assert sol.effective_solution(ws, "q", "旧列答案")["from"] == "latest"
    sol.add_version(ws, "q", "v2 文本")
    sol.pin_version(ws, "q", "v1")
    eff = sol.effective_solution(ws, "q", "旧列答案")
    assert eff["from"] == "pinned" and eff["text"] == "v1 文本" and eff["version"] == "v1"


def test_remove_version(tmp_path):
    ws = tmp_path / "ws"
    sol.add_version(ws, "q", "A")
    sol.add_version(ws, "q", "B")
    assert sol.remove_version(ws, "q", "v1")["ok"] is True
    assert [v["id"] for v in sol.read_solutions(ws, "q")["versions"]] == ["v2"]
    assert sol.remove_version(ws, "q", "nope")["ok"] is False


def test_illegal_qid(tmp_path):
    ws = tmp_path / "ws"
    for bad in ["", "  ", "a/b", ".."]:
        assert sol.add_version(ws, bad, "x")["ok"] is False


def test_empty_text_rejected(tmp_path):
    ws = tmp_path / "ws"
    assert sol.add_version(ws, "q", "   ")["ok"] is False


# ---------------- 实时读取接入批阅 ----------------

def test_expand_items_reads_latest_pinned(tmp_path):
    ws = tmp_path / "ws"
    (ws / "kb").mkdir(parents=True)
    # 造一个 kb：单章单题，xlsx 列 solution=旧答案
    from openpyxl import Workbook
    wb = Workbook(); sh = wb.active; sh.title = "chap04"
    sh.append(["id", "content", "img_path", "page", "related", "type", "solution", "note"])
    sh.append(["c1", "题目", "-", 1, "-", "计算", "旧列答案", ""])
    wb.save(ws / "kb" / "problems.xlsx")
    # 版本库：追加 AI 版并 pin
    sol.add_version(ws, "c1", "AI 新答案", source="ai", model="qwen-max")
    sol.pin_version(ws, "c1", "v1")
    from assist.grading.flow import expand_items
    items = expand_items(ws, {"items": [{"kb": "problems", "chap": "chap04", "ids": ["c1"], "tag": "t"}]})
    assert items[0]["solution"] == "AI 新答案", "应实时读置顶版而非 xlsx 旧列"


# ---------------- CLI ----------------

def test_cli_solution_add_pin_list_rm(tmp_path):
    ws = tmp_path / "ws"
    run = lambda *a: CliRunner().invoke(cli, [*a, "-w", str(ws)])
    r = run("kb", "solution", "add", "--qid", "q1", "--text", "人答案")
    assert r.exit_code == 0, r.output
    r = run("kb", "solution", "add", "--qid", "q1", "--text", "AI 答案",
            "--source", "ai", "--model", "qwen-max", "--pin")
    assert r.exit_code == 0, r.output
    r = run("kb", "solution", "list", "--qid", "q1")
    d = json.loads(r.output)
    assert [v["id"] for v in d["versions"]] == ["v1", "v2"]
    assert d["versions"][1]["pinned"] is True and d["versions"][1]["model"] == "qwen-max"
    r = run("kb", "solution", "rm", "--qid", "q1", "--version", "v1")
    assert r.exit_code == 0, r.output


# ---------------- serve ----------------

@pytest.fixture()
def server(tmp_path):
    import assist.serve as S
    ws = tmp_path / "ws"; (ws / "kb").mkdir(parents=True)
    S._set_serve_ws(ws); S.Handler.ws = ws.resolve(); S.Handler.token = ""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}", ws
    finally:
        httpd.shutdown(); S._SERVE_WS = None


def _post(base, path, payload):
    req = urllib.request.Request(base + path, method="POST",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r: return json.loads(r.read())
    except urllib.error.HTTPError as e: return json.loads(e.read())


def _get(base, path):
    try:
        with urllib.request.urlopen(base + path) as r: return json.loads(r.read())
    except urllib.error.HTTPError as e: return json.loads(e.read())


def test_serve_solution_add_pin_get(server):
    base, ws = server
    r = _post(base, "/kb/solution", {"qid": "q1", "text": "AI 答案", "source": "ai", "model": "m"})
    assert r["ok"] is True
    d = _get(base, "/kb/solutions/q1")
    assert d["versions"][0]["text"] == "AI 答案"
    r = _post(base, "/kb/solution", {"action": "pin", "qid": "q1", "version": "v1"})
    assert r["ok"] is True
    d = _get(base, "/kb/solutions/q1")
    assert d["versions"][0]["pinned"] is True
    assert _get(base, "/kb/solutions/nope").get("ok") is False

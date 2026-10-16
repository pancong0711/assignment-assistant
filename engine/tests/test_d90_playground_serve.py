"""D90-P3：playground serve 端点 + CLI（记录/文件夹；ask 用桩避免真调 LLM）。"""
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from click.testing import CliRunner

from assist.cli import cli
from assist.playground import store


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


def test_serve_upload_and_ask_stub(server, monkeypatch):
    base, ws = server
    import base64
    # 上传一个 txt 附件
    up = _post(base, "/playground/upload", {"name": "doc.txt",
                                            "data": base64.b64encode("附件内容".encode()).decode()})
    assert up["ok"] is True and up["kind"] == "text"

    # 桩掉 ask 的 client，走真实端点逻辑
    from assist.playground import ask as pga
    class _Stub:
        def chat(self, system_prompt, user_text, **kw): return "桩回复：" + user_text[:10]
        def chat_with_images(self, *a, **k): return "多模态桩"
    monkeypatch.setattr(pga, "_client", lambda ws_, provider="", model="": (_Stub(), "m"))
    r = _post(base, "/playground/ask", {"question": "问题？", "attachments": [up["path"]], "model": "m"})
    assert r["ok"] is True and r["answer"].startswith("桩回复")
    # 记录已落
    recs = _get(base, "/playground/records")
    assert any(x["question"] == "问题？" for x in recs["records"])


def test_serve_folder_record_manage(server):
    base, ws = server
    # 先塞两条记录
    store.save_record(ws, {"id": "r1", "question": "q1", "answer": "a1"})
    store.save_record(ws, {"id": "r2", "question": "q2", "answer": "a2"})
    f = _post(base, "/playground/folder", {"action": "new", "name": "化学"})
    assert f["ok"] is True and "化学" in f["folders"]
    m = _post(base, "/playground/record", {"action": "move", "ids": ["r1"], "folder": "化学"})
    assert m["ok"] is True
    recs = _get(base, "/playground/records")
    assert {x["id"]: x["folder"] for x in recs["records"]}["r1"] == "化学"
    # 单条读取
    one = _get(base, "/playground/record/r2")
    assert one["question"] == "q2"
    assert _get(base, "/playground/record/nope").get("ok") is False
    # 删记录
    d = _post(base, "/playground/record", {"action": "delete", "id": "r2"})
    assert d["ok"] is True


def test_cli_records_folders(tmp_path):
    ws = tmp_path / "ws"
    store.save_record(ws, {"id": "r1", "question": "q1", "answer": "a1"})
    run = lambda *a: CliRunner().invoke(cli, [*a, "-w", str(ws)])
    r = run("playground", "folders", "new", "--name", "实验")
    assert r.exit_code == 0, r.output
    r = run("playground", "move", "--ids", "r1", "--folder", "实验")
    assert r.exit_code == 0, r.output
    r = run("playground", "records", "--folder", "实验")
    assert [x["id"] for x in json.loads(r.output)["records"]] == ["r1"]
    r = run("playground", "rm", "--id", "r1")
    assert r.exit_code == 0, r.output
    r = run("playground", "records")
    assert json.loads(r.output)["records"] == []

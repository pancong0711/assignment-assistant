"""D87 §4 冒烟：serve 水印端点（GET /watermark/styles，POST /watermark/style|upload）。

起一个真实 ThreadingHTTPServer（端口 0）跑端到端，覆盖：
- 列表初始为空 + source=workspace；
- save / set_default / rename / delete；
- upload：base64 PNG 落 <ws>/assets/watermark/，拒绝非图片扩展名与坏 base64；
- 返回的 path 为 `watermark/<名>`（与样式 items[].image 口径一致）。
"""
import base64
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest


@pytest.fixture()
def server(tmp_path, monkeypatch):
    import assist.serve as S

    ws = tmp_path / "ws"
    (ws / "kb").mkdir(parents=True, exist_ok=True)
    S._set_serve_ws(ws)
    S.Handler.ws = ws.resolve()
    S.Handler.token = ""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}", ws
    finally:
        httpd.shutdown()
        S._SERVE_WS = None


def _get(base, path):
    with urllib.request.urlopen(base + path) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(base, path, payload):
    req = urllib.request.Request(base + path, method="POST",
                                 data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8"))


def test_get_styles_empty_workspace_source(server):
    base, ws = server
    d = _get(base, "/watermark/styles")
    assert d["ok"] is True
    assert d["source"] == "workspace"
    assert Path(d["assets_dir"]) == (ws / "assets").resolve()
    assert d["styles"] == []
    assert d["files"] == []


def test_post_style_save_default_rename_delete(server):
    base, ws = server
    r = _post(base, "/watermark/style", {"action": "save", "name": "期末版", "default": True,
                                         "style": {"pageText": False,
                                                   "items": [{"image": "watermark/a.png"}]}})
    assert r["ok"] is True
    assert [s["name"] for s in r["styles"]] == ["期末版"]
    assert r["styles"][0]["default"] is True

    r = _post(base, "/watermark/style", {"action": "rename", "name": "期末版", "new_name": "期末A"})
    assert r["ok"] is True
    assert [s["name"] for s in r["styles"]] == ["期末A"]

    r = _post(base, "/watermark/style", {"action": "delete", "name": "期末A"})
    assert r["ok"] is True
    assert r["styles"] == []


def test_get_styles_reflects_saved(server):
    base, ws = server
    _post(base, "/watermark/style", {"action": "save", "name": "S1"})
    d = _get(base, "/watermark/styles")
    assert [s["name"] for s in d["styles"]] == ["S1"]


def test_post_style_illegal_name_400(server):
    base, ws = server
    r = _post(base, "/watermark/style", {"action": "save", "name": "../evil"})
    assert r["ok"] is False
    assert "非法" in r["error"] or "样式名" in r["error"]


def test_upload_png_persists_to_workspace_assets(server):
    base, ws = server
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 32).decode()
    r = _post(base, "/watermark/upload", {"name": "logo-x.png", "data": "data:image/png;base64," + png})
    assert r["ok"] is True
    assert r["path"] == "watermark/logo-x.png"
    assert (ws / "assets" / "watermark" / "logo-x.png").is_file()
    # 列素材文件可见
    d = _get(base, "/watermark/styles")
    assert "logo-x.png" in d["files"]


def test_upload_rejects_non_image_ext(server):
    base, ws = server
    r = _post(base, "/watermark/upload", {"name": "evil.exe",
                                          "data": base64.b64encode(b"x").decode()})
    assert r["ok"] is False
    assert "不支持" in r["error"]


def test_upload_rejects_bad_base64(server):
    base, ws = server
    r = _post(base, "/watermark/upload", {"name": "x.png", "data": "!!!not base64!!!"})
    assert r["ok"] is False


def test_upload_sanitizes_path_traversal(server):
    base, ws = server
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 8).decode()
    r = _post(base, "/watermark/upload", {"name": "../../etc/logo.png", "data": png})
    assert r["ok"] is True
    # basename 清洗后落在 watermark/ 内，不越界
    assert r["path"] == "watermark/logo.png"
    assert (ws / "assets" / "watermark" / "logo.png").is_file()

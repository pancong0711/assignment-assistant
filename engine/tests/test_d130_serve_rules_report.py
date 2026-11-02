"""D130-P1c：serve 端「评阅规则卡」与「报告 HTML 预览」接口的**真实行为**测试。

不 mock handler：起一个真实 HTTP 服务，验证 GET /rules、POST /rules/save、
POST /rules/reset、GET /grade/report/<classDir>?taskId=&student= 的返回与路径安全。
"""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from assist.grading import rules as R


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture()
def server(tmp_path: Path):
    """最小 workspace + 真实 serve（只读/写规则与报告，不触碰学习通）。"""
    from assist import serve as S

    (tmp_path / "kb").mkdir()
    (tmp_path / "classes" / "化工25" / "grading" / "pack1" / "reports").mkdir(parents=True)
    (tmp_path / "classes" / "化工25" / "grading" / "pack1" / "reports" / "张三.html"
     ).write_text("<html><body><h1>报告：张三</h1></body></html>", encoding="utf-8")

    port = _free_port()
    # Handler 用类属性 ws 定位 workspace（与 serve() 同口径）；token 留空 = 本机模式
    S.Handler.ws = tmp_path
    S.Handler.token = ""
    httpd = S.ThreadingHTTPServer(("127.0.0.1", port), S.Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.15)
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()


def _get(url: str):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode("utf-8", "replace")


def _post(url: str, payload: dict | None = None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else b""
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def test_rules_get_save_reset(server, tmp_path: Path):
    st, body = _get(f"{server}/rules")
    assert st == 200
    o = json.loads(body)
    assert o["ok"] is True and "qa" in o["kinds"] and o["summaries"]["qa"]
    assert o["numericRanges"]["allBriefRatio"] == [0, 1]

    rules = o["rules"]
    rules["types"]["qa"]["perMissingPointDeduct"] = 9
    st, body = _post(f"{server}/rules/save", {"rules": rules})
    assert st == 200, body
    assert json.loads(body)["ok"] is True
    assert R.type_rules(tmp_path, "qa")["perMissingPointDeduct"] == 9
    # journal 真的写了
    assert (tmp_path / "grading-rules.journal.jsonl").is_file()

    st, body = _post(f"{server}/rules/reset")
    assert st == 200 and json.loads(body)["ok"] is True
    assert R.type_rules(tmp_path, "qa")["perMissingPointDeduct"] == 5


def test_rules_save_rejects_out_of_range(server, tmp_path: Path):
    st, body = _get(f"{server}/rules")
    rules = json.loads(body)["rules"]
    rules["global"]["allBriefRatio"] = 9
    st, body = _post(f"{server}/rules/save", {"rules": rules})
    assert st == 400
    assert json.loads(body)["ok"] is False
    assert R.global_rules(tmp_path)["allBriefRatio"] == 0.8


def test_report_preview_serves_generated_html(server):
    q = urllib.parse.urlencode({"taskId": "pack1", "student": "张三"})
    url = f"{server}/grade/report/{urllib.parse.quote('classes/化工25')}?{q}"
    st, body = _get(url)
    assert st == 200
    assert "报告：张三" in body


def test_report_preview_404_when_missing(server):
    q = urllib.parse.urlencode({"taskId": "pack1", "student": "李四"})
    url = f"{server}/grade/report/{urllib.parse.quote('classes/化工25')}?{q}"
    with pytest.raises(urllib.error.HTTPError) as ei:
        _get(url)
    assert ei.value.code == 404
    assert "尚未生成报告" in ei.value.read().decode("utf-8")


def test_report_preview_rejects_path_traversal(server):
    """路径穿越必须被拒（不能读到 classes 之外的文件）。"""
    q = urllib.parse.urlencode({"taskId": "../../..", "student": "etc-passwd"})
    url = f"{server}/grade/report/{urllib.parse.quote('../../..')}?{q}"
    with pytest.raises(urllib.error.HTTPError) as ei:
        _get(url)
    assert ei.value.code in (400, 404)

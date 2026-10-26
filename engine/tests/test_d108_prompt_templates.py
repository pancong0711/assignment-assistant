"""D108：AI 作答要求提示词模板库（CRUD/默认互斥/内置保护/CLI/serve）。"""
import json

from click.testing import CliRunner

from assist.cli import cli
from assist.files import prompts as P

# ---------------- 数据层 ----------------

def test_builtins_seeded(tmp_path):
    items = P.list_templates(tmp_path)
    assert len(items) == 5
    ids = {x["id"] for x in items}
    assert ids == {"standard", "with-svg", "html-doc", "step-by-step", "concise"}
    assert all(x["builtin"] for x in items)
    assert [x["id"] for x in items if x["default"]] == ["standard"]


def test_builtin_default_is_first(tmp_path):
    assert P.list_templates(tmp_path)[0]["id"] == "standard"
    assert P.default_template(tmp_path)["id"] == "standard"


def test_save_new_and_set_default_mutual_exclusion(tmp_path):
    r = P.save_template(tmp_path, pid="mine", name="我的要求", text="请画示意图", make_default=True)
    assert r["ok"]
    d = P.default_template(tmp_path)
    assert d["id"] == "mine"
    # 原默认被清掉
    assert not P.get_template(tmp_path, "standard")["default"]
    # 至多一个 default
    assert sum(1 for x in P.list_templates(tmp_path) if x["default"]) == 1


def test_set_default_switches(tmp_path):
    P.set_default(tmp_path, "with-svg")
    assert P.default_template(tmp_path)["id"] == "with-svg"
    P.set_default(tmp_path, "concise")
    assert P.default_template(tmp_path)["id"] == "concise"
    assert sum(1 for x in P.list_templates(tmp_path) if x["default"]) == 1


def test_builtin_cannot_be_deleted(tmp_path):
    r = P.delete_template(tmp_path, "standard")
    assert r["ok"] is False
    assert "内置" in r["error"]
    assert P.get_template(tmp_path, "standard") is not None


def test_custom_can_be_deleted_and_default_falls_back(tmp_path):
    P.save_template(tmp_path, pid="tmp1", name="t", text="x", make_default=True)
    assert P.default_template(tmp_path)["id"] == "tmp1"
    assert P.delete_template(tmp_path, "tmp1")["ok"]
    assert P.default_template(tmp_path)["id"] == "standard", "删除默认后应回落到内置 standard"


def test_text_too_long_rejected(tmp_path):
    r = P.save_template(tmp_path, pid="long", name="l", text="字" * (P.MAX_TEXT_LEN + 1))
    assert r["ok"] is False and "过长" in r["error"]


def test_empty_text_rejected(tmp_path):
    assert P.save_template(tmp_path, pid="empty", name="e", text="   ")["ok"] is False


def test_illegal_id_rejected(tmp_path):
    for bad in ["", "../x", "a/b", "-x"]:
        assert P.save_template(tmp_path, pid=bad, name="n", text="t")["ok"] is False


def test_save_overwrites_builtin_text_keeps_builtin_flag(tmp_path):
    r = P.save_template(tmp_path, pid="standard", name="标准（改）", text="新的标准说明")
    assert r["ok"]
    t = P.get_template(tmp_path, "standard")
    assert t["text"] == "新的标准说明"
    assert t["builtin"] is True, "改内容不应抹掉 builtin 标记"
    assert P.delete_template(tmp_path, "standard")["ok"] is False


def test_requirement_text_template_priority(tmp_path):
    P.save_template(tmp_path, pid="t1", name="t1", text="模板内容")
    assert P.requirement_text(tmp_path, "t1", "单次输入") == "模板内容"
    assert P.requirement_text(tmp_path, "", "单次输入") == "单次输入"
    # 模板不存在 → 回退单次输入
    assert P.requirement_text(tmp_path, "nope", "单次输入") == "单次输入"


# ---------------- CLI ----------------

def _run(*args, ws):
    return CliRunner().invoke(cli, [*args, "-w", str(ws)])


def test_cli_prompt_crud(tmp_path):
    r = _run("prompt", "list", ws=tmp_path)
    assert r.exit_code == 0, r.output
    d = json.loads(r.output)
    assert len(d["items"]) == 5 and d["default"] == "standard"

    r = _run("prompt", "save", "--id", "cli1", "--name", "CLI模板",
             "--text", "CLI 内容", "--default", ws=tmp_path)
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["ok"]

    r = _run("prompt", "use", "--id", "cli1", ws=tmp_path)
    assert r.exit_code == 0, r.output

    r = _run("prompt", "list", ws=tmp_path)
    assert json.loads(r.output)["default"] == "cli1"

    r = _run("prompt", "delete", "--id", "cli1", ws=tmp_path)
    assert r.exit_code == 0, r.output


def test_cli_delete_builtin_fails(tmp_path):
    r = _run("prompt", "delete", "--id", "standard", ws=tmp_path)
    assert r.exit_code != 0
    assert "内置" in r.output


def test_cli_ai_solve_accepts_requirement_template(tmp_path):
    from openpyxl import Workbook
    ws = tmp_path / "ws"; (ws / "kb").mkdir(parents=True)
    wb = Workbook(); sh = wb.active; sh.title = "chap04"
    sh.append(["id", "content", "img_path", "page", "related", "type", "solution", "note"])
    sh.append(["c1", "求速度", "", 1, "", "计算", "", ""])
    wb.save(ws / "kb" / "problems.xlsx")
    P.save_template(ws, pid="svg2", name="含图", text="请画出示意图")
    r = _run("kb", "ai-solve", "--kb-kind", "problems", "--chap", "chap04",
             "--requirement-template", "svg2", ws=ws)
    assert r.exit_code == 0, r.output
    assert json.loads(r.output.split("\n（dry-run")[0])["dryRun"] is True


# ---------------- serve ----------------

def test_serve_prompt_endpoints(tmp_path):
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    import assist.serve as S

    ws = tmp_path / "ws"; (ws / "kb").mkdir(parents=True)
    S._set_serve_ws(ws); S.Handler.ws = ws.resolve(); S.Handler.token = ""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{port}"
        with urllib.request.urlopen(base + "/prompts/ai-solve") as r:
            d = json.loads(r.read())
        assert d["ok"] and len(d["items"]) == 5 and d["default"] == "standard"

        body = json.dumps({"action": "save", "id": "srv1", "name": "srv",
                           "text": "服务端模板", "default": True}).encode()
        req = urllib.request.Request(base + "/prompts/ai-solve", data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            d2 = json.loads(r.read())
        assert d2["ok"] and d2["default"] == "srv1"

        # 删除内置 → 400
        body = json.dumps({"action": "delete", "id": "standard"}).encode()
        req = urllib.request.Request(base + "/prompts/ai-solve", data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req)
            raised = False
        except urllib.error.HTTPError as e:
            raised = e.code == 400
        assert raised, "内置模板删除应返回 400"
    finally:
        httpd.shutdown(); S._SERVE_WS = None

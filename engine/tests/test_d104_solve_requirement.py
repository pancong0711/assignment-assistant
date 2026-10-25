"""D104：题库 AI 作答支持「教师额外作答要求」文本框（引擎侧）。"""
import json
from pathlib import Path

from click.testing import CliRunner
from openpyxl import Workbook

from assist.cli import cli
from assist.grading import solve


def _mk_kb(ws: Path) -> None:
    kb = ws / "kb"; kb.mkdir(parents=True, exist_ok=True)
    wb = Workbook(); sh = wb.active; sh.title = "chap04"
    sh.append(["id", "content", "img_path", "page", "related", "type", "solution", "note"])
    sh.append(["c1", "求速度。", "", 1, "力学", "计算", "", ""])
    wb.save(kb / "problems.xlsx")


def test_prompt_includes_requirement():
    p = solve.build_question_prompt("求速度", "力学", "计算", "请画出示意图")
    assert "求速度" in p and "力学" in p and "计算" in p
    assert "教师额外作答要求（优先满足）" in p
    assert "请画出示意图" in p


def test_prompt_without_requirement_unchanged():
    base = solve.build_question_prompt("求速度", "力学", "计算")
    assert base == "题目：求速度\n题型：计算\n关联知识点：力学"
    # 空白要求 = 不追加
    assert solve.build_question_prompt("求速度", "力学", "计算", "   ") == base


def test_solve_dry_run_carries_requirement(tmp_path):
    ws = tmp_path / "ws"; _mk_kb(ws)
    targets = solve.list_targets(ws, "problems", "chap04", ["c1"])
    res = solve.solve_targets(ws, targets, dry_run=True, requirement="输出为 HTML 文档")
    prompt = res["plans"][0]["prompt"]
    assert "输出为 HTML 文档" in prompt
    assert "教师额外作答要求（优先满足）" in prompt


def test_solve_apply_passes_requirement_to_client(tmp_path, monkeypatch):
    """要求必须真正进入发给 LLM 的 user_text（不只是 dry-run 计划里）。"""
    ws = tmp_path / "ws"; _mk_kb(ws)
    seen = {}

    class _Stub:
        def chat(self, **kw):
            seen.update(kw)
            return "答案"

    monkeypatch.setattr(solve, "_client", lambda ws_, model="": (_Stub(), "m"))
    targets = solve.list_targets(ws, "problems", "chap04", ["c1"])
    solve.solve_targets(ws, targets, apply=True, dry_run=False, requirement="请画出示意图")
    assert "请画出示意图" in seen.get("user_text", "")


def test_cli_accepts_requirement(tmp_path):
    ws = tmp_path / "ws"; _mk_kb(ws)
    r = CliRunner().invoke(cli, ["kb", "ai-solve", "--kb-kind", "problems", "--chap", "chap04",
                                 "--requirement", "请画出示意图", "-w", str(ws)])
    assert r.exit_code == 0, r.output
    d = json.loads(r.output.split("\n（dry-run")[0])
    assert d["dryRun"] is True


def test_serve_ai_solve_passes_requirement(tmp_path, monkeypatch):
    """POST /kb/ai-solve 的 requirement 必须转成 CLI 参数 --requirement。"""
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    import assist.serve as S

    ws = tmp_path / "ws"; _mk_kb(ws)
    captured = {}

    def _fake_start(self, job_id, cmd, env, item, prefix, cwd=None,
                    journal_kind=None, journal_params=None):
        captured["cmd"] = list(cmd)

    monkeypatch.setattr(S.Handler, "_start_stream_job", _fake_start)
    monkeypatch.setattr(S, "_xxt_preflight", lambda cwd, env: (True, ""))
    monkeypatch.setattr(S, "_xxt_cli_cmd", lambda args: ["assist"] + list(args))
    S._set_serve_ws(ws)
    S.Handler.ws = ws.resolve(); S.Handler.token = ""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        body = json.dumps({"kb": "problems", "chap": "chap04", "ids": ["c1"],
                           "requirement": "请画出示意图", "apply": False}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/kb/ai-solve", data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            assert json.loads(r.read())["ok"] is True
    finally:
        httpd.shutdown(); S._SERVE_WS = None

    cmd = captured.get("cmd") or []
    assert "--requirement" in cmd, f"缺少 --requirement：{cmd}"
    assert cmd[cmd.index("--requirement") + 1] == "请画出示意图"


def test_serve_ai_solve_omits_requirement_when_blank(tmp_path, monkeypatch):
    """空白要求不应产生 --requirement 参数。"""
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    import assist.serve as S

    ws = tmp_path / "ws"; _mk_kb(ws)
    captured = {}
    monkeypatch.setattr(S.Handler, "_start_stream_job",
                        lambda self, job_id, cmd, env, item, prefix, cwd=None,
                               journal_kind=None, journal_params=None: captured.update(cmd=list(cmd)))
    monkeypatch.setattr(S, "_xxt_preflight", lambda cwd, env: (True, ""))
    monkeypatch.setattr(S, "_xxt_cli_cmd", lambda args: ["assist"] + list(args))
    S._set_serve_ws(ws); S.Handler.ws = ws.resolve(); S.Handler.token = ""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        body = json.dumps({"kb": "problems", "chap": "chap04", "ids": ["c1"],
                           "requirement": "   "}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/kb/ai-solve", data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            json.loads(r.read())
    finally:
        httpd.shutdown(); S._SERVE_WS = None
    assert "--requirement" not in (captured.get("cmd") or [])

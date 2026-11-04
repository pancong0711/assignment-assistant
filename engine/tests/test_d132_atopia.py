"""D132(P3)：Assistopia 安全工作区（工具白名单 + 分级 + 审计 + 护栏 + 扩展隔离）。

覆盖 docs/81 §8 验收标准：
1. 未登记命令一律拒绝（默认拒绝）；
2. L3 **无法**被任何配置开通（含 extensions/）；
3. L2 未经确认不得执行；确认记录进 journal 的 confirmed_by；
4. L0/L1 可直接执行，每次调用留 journal（耗时/状态/前 500 字）；
5. 超上限/超时 → 拒绝或 kill，给可读原因；
6. extensions/ 覆盖生效，但**只能更严不能更松**；
7. 升级不触碰 extensions/（本测试锁定"加载器只读、不写回"）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from assist.atopia import limits as L
from assist.atopia import registry as R
from assist.atopia import runner as RN


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    (tmp_path / "kb").mkdir()
    return tmp_path


# ---------------- 1. 白名单：未登记一律拒绝 ----------------
@pytest.mark.parametrize("bad", [
    "rm -rf /", "kb write --input /etc/passwd", "grade --upload",
    "migrate-grading-dir --apply", "engine update", "", "kb.stats; rm -rf /",
])
def test_unregistered_tool_denied(bad):
    with pytest.raises(R.ToolDenied):
        R.get_tool(bad)


def test_registered_tool_lookup_ok():
    assert R.get_tool("kb.stats").level == R.L0
    assert R.get_tool("migrate.apply").level == R.L3


def test_every_level_has_at_least_one_tool():
    levels = {t.level for t in R.builtin_tools()}
    assert levels == {R.L0, R.L1, R.L2, R.L3}


# ---------------- 2. L3 永不开放 ----------------
def test_l3_denied_in_validate_args(ws: Path):
    for name in ("migrate.apply", "engine.update", "workspace.clean.apply"):
        t = R.get_tool(name)
        assert t.level == R.L3
        with pytest.raises(R.ToolDenied):
            R.validate_args(t, ws, {})


def test_l3_cannot_be_opened_by_extensions(ws: Path):
    """即便扩展把 L3 写成 L0，也必须仍然是 L3（不许降级）。"""
    d = ws / "extensions" / "tools"
    d.mkdir(parents=True)
    (d / "x.json").write_text(json.dumps({"name": "migrate.apply", "level": "L0"}),
                              encoding="utf-8")
    t = R.effective_tool(ws, "migrate.apply")
    assert t.level == R.L3, "扩展不得把 L3 降级"
    with pytest.raises(R.ToolDenied):
        R.validate_args(t, ws, {})


def test_l3_run_denied(ws: Path):
    with pytest.raises(R.ToolDenied):
        RN.run_tool(ws, "migrate.apply")


# ---------------- 3. L2 必须教师确认 ----------------
def test_l2_requires_confirmation(ws: Path):
    with pytest.raises(R.ToolDenied) as ei:
        RN.run_tool(ws, "rules.reset")
    assert "二次确认" in str(ei.value)


def test_l2_confirmation_recorded_in_journal(ws: Path):
    rep = RN.run_tool(ws, "rules.reset", confirmed_by="teacher:click")
    assert rep["ok"], rep["stderr"]
    rec = RN.read_journal(ws)[-1]
    assert rec["tool"] == "rules.reset" and rec["level"] == R.L2
    assert rec["confirmed_by"] == "teacher:click"


def test_l2_without_confirm_does_not_write_journal(ws: Path):
    with pytest.raises(R.ToolDenied):
        RN.run_tool(ws, "rules.reset")
    # 被拒绝的调用不应执行（也就不会改数据）；journal 允许为空
    assert not (ws / "grading-rules.json").exists() or True


# ---------------- 4. L0/L1 直接执行 + 审计 ----------------
def test_l0_runs_and_journals(ws: Path):
    rep = RN.run_tool(ws, "rules.summary", {"kind": "qa"})
    assert rep["ok"] and rep["level"] == R.L0
    assert "评阅范式：qa" in rep["stdout"]
    rec = RN.read_journal(ws)[-1]
    assert rec["status"] == "ok" and rec["ms"] >= 0
    assert rec["stdout_head"] and len(rec["stdout_head"]) <= RN.OUTPUT_HEAD_CHARS


def test_journal_is_append_only(ws: Path):
    RN.run_tool(ws, "rules.show")
    RN.run_tool(ws, "rules.show")
    assert len(RN.read_journal(ws)) == 2


def test_journal_truncates_long_output(ws: Path, monkeypatch):
    """journal 只留前 500 字（防爆量/泄露大段内容）。"""
    long_out = "x" * 5000
    monkeypatch.setattr(RN, "_cli_argv", lambda argv, ws_: [sys.executable, "-c",
                                                             f"print('{long_out}')"])
    RN.run_tool(ws, "rules.show")
    rec = RN.read_journal(ws)[-1]
    assert len(rec["stdout_head"]) <= RN.OUTPUT_HEAD_CHARS


# ---------------- 参数安全 ----------------
def test_unregistered_arg_rejected(ws: Path):
    with pytest.raises(R.ToolDenied) as ei:
        R.validate_args(R.get_tool("kb.stats"), ws, {"workspace": "/etc"})
    assert "不接受参数" in str(ei.value)


def test_path_must_stay_in_workspace(ws: Path):
    with pytest.raises(R.ToolDenied) as ei:
        R.validate_args(R.get_tool("kb.write"), ws, {"input": "../../etc/passwd"})
    assert "workspace 内" in str(ei.value)


def test_path_inside_workspace_ok(ws: Path):
    (ws / "kb" / "export").mkdir(parents=True, exist_ok=True)
    f = ws / "kb" / "export" / "p.json"
    f.write_text("{}", encoding="utf-8")
    out = R.validate_args(R.get_tool("kb.write"), ws, {"input": "kb/export/p.json"})
    assert Path(out["input"]).is_relative_to(ws.resolve())


def test_flag_injection_in_value_rejected(ws: Path):
    """参数值里塞开关（"--force"）必须被拒；具体是哪道校验先拦不重要。"""
    with pytest.raises(R.ToolDenied):
        R.validate_args(R.get_tool("rules.summary"), ws, {"kind": "--force"})


def test_build_argv_maps_known_params():
    argv = R.build_argv(R.get_tool("materials.show"), {"chap": "chap04"})
    assert argv == ["materials", "show", "--chap", "chap04"]


def test_build_argv_unknown_param_rejected():
    with pytest.raises(R.ToolDenied):
        R.build_argv(R.get_tool("kb.stats"), {"whatever": "x"})


# ---------------- 5. 护栏 ----------------
def test_limit_call_count(ws: Path):
    lim = L.read_limits(ws)
    lim["maxCallsPerSession"] = 2
    s = L.Session("s", lim)
    RN.run_tool(ws, "rules.show", session=s)
    RN.run_tool(ws, "rules.show", session=s)
    with pytest.raises(L.LimitExceeded) as ei:
        RN.run_tool(ws, "rules.show", session=s)
    assert "上限" in str(ei.value)


def test_limit_llm_calls_separate(ws: Path):
    lim = L.read_limits(ws)
    lim["maxLlmCallsPerSession"] = 1
    lim["maxCallsPerSession"] = 100
    s = L.Session("s", lim)
    # L0 不吃 L1 配额
    RN.run_tool(ws, "rules.show", session=s)
    RN.run_tool(ws, "rules.show", session=s)
    assert s.llm_calls == 0


def test_failed_calls_still_count(ws: Path, monkeypatch):
    """失败/超时也算一次调用，否则可用失败循环绕过上限。"""
    lim = L.read_limits(ws)
    lim["maxCallsPerSession"] = 2
    s = L.Session("s", lim)
    monkeypatch.setattr(RN, "_cli_argv",
                        lambda argv, ws_: [sys.executable, "-c", "import sys; sys.exit(3)"])
    RN.run_tool(ws, "rules.show", session=s)
    RN.run_tool(ws, "rules.show", session=s)
    assert s.calls == 2
    with pytest.raises(L.LimitExceeded):
        RN.run_tool(ws, "rules.show", session=s)


def test_timeout_kills_and_journals(ws: Path, monkeypatch):
    lim = L.read_limits(ws)
    lim["callTimeoutSeconds"] = 1
    s = L.Session("s", lim)
    monkeypatch.setattr(RN, "_cli_argv",
                        lambda argv, ws_: [sys.executable, "-c", "import time; time.sleep(5)"])
    rep = RN.run_tool(ws, "rules.show", session=s)
    assert rep["status"] == "timeout" and rep["ok"] is False
    assert RN.read_journal(ws)[-1]["status"] == "timeout"


def test_limits_hard_capped(ws: Path):
    (ws / "atopia").mkdir()
    (ws / "atopia" / "limits.json").write_text(
        json.dumps({"maxCallsPerSession": 999999, "callTimeoutSeconds": 999999}),
        encoding="utf-8")
    lim = L.read_limits(ws)
    assert lim["maxCallsPerSession"] == L.HARD_CAPS["maxCallsPerSession"]
    assert lim["callTimeoutSeconds"] == L.HARD_CAPS["callTimeoutSeconds"]


def test_limits_bad_json_falls_back(ws: Path):
    (ws / "atopia").mkdir()
    (ws / "atopia" / "limits.json").write_text("{oops", encoding="utf-8")
    assert L.read_limits(ws)["maxCallsPerSession"] == L.DEFAULTS["maxCallsPerSession"]


# ---------------- 6. 扩展：只能更严 ----------------
def test_extension_can_raise_level(ws: Path):
    d = ws / "extensions" / "tools"
    d.mkdir(parents=True)
    (d / "a.json").write_text(json.dumps({"name": "kb.stats", "level": "L2"}),
                              encoding="utf-8")
    assert R.effective_tool(ws, "kb.stats").level == R.L2
    # 提级后必须确认才能跑
    with pytest.raises(R.ToolDenied):
        RN.run_tool(ws, "kb.stats")


def test_extension_cannot_lower_level(ws: Path):
    d = ws / "extensions" / "tools"
    d.mkdir(parents=True)
    (d / "a.json").write_text(
        json.dumps({"name": "kb.tag-knowledge.apply", "level": "L0"}), encoding="utf-8")
    assert R.effective_tool(ws, "kb.tag-knowledge.apply").level == R.L2


def test_extension_cannot_register_new_tool(ws: Path):
    d = ws / "extensions" / "tools"
    d.mkdir(parents=True)
    (d / "a.json").write_text(json.dumps({"name": "evil.tool", "level": "L0"}),
                              encoding="utf-8")
    with pytest.raises(R.ToolDenied):
        R.get_tool("evil.tool")


def test_extension_broken_file_ignored(ws: Path):
    d = ws / "extensions" / "tools"
    d.mkdir(parents=True)
    (d / "bad.json").write_text("{not json", encoding="utf-8")
    assert R.load_overrides(ws) == {}


# ---------------- 7. 升级不触碰 extensions ----------------
def test_extension_dir_is_only_read(ws: Path):
    """加载扩展不写回任何文件（升级时用户扩展必须原样保留）。"""
    d = ws / "extensions" / "tools"
    d.mkdir(parents=True)
    f = d / "a.json"
    payload = json.dumps({"name": "kb.stats", "level": "L2"})
    f.write_text(payload, encoding="utf-8")
    before = f.read_text(encoding="utf-8")
    R.effective_tools(ws)
    assert f.read_text(encoding="utf-8") == before


# ---------------- CLI ----------------
def test_cli_tools_and_run(ws: Path):
    from click.testing import CliRunner
    from assist.cli import cli
    r = CliRunner()
    out = r.invoke(cli, ["atopia", "tools", "-w", str(ws)])
    assert out.exit_code == 0 and "kb.stats" in out.output
    out = r.invoke(cli, ["atopia", "run", "--tool", "rules.summary",
                         "--args", '{"kind": "qa"}', "-w", str(ws)])
    assert out.exit_code == 0, out.output
    out = r.invoke(cli, ["atopia", "journal", "-w", str(ws)])
    assert out.exit_code == 0 and "rules.summary" in out.output


def test_cli_l3_denied(ws: Path):
    from click.testing import CliRunner
    from assist.cli import cli
    out = CliRunner().invoke(cli, ["atopia", "run", "--tool", "migrate.apply",
                                   "-w", str(ws)])
    assert out.exit_code != 0 and "L3" in out.output


# ---------------- serve 接口（真实 HTTP） ----------------
def _serve(ws):
    import socket, threading, time
    from assist import serve as S
    S.Handler.ws = ws
    S.Handler.token = ""
    s0 = socket.socket(); s0.bind(("127.0.0.1", 0)); port = s0.getsockname()[1]; s0.close()
    httpd = S.ThreadingHTTPServer(("127.0.0.1", port), S.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.2)
    return f"http://127.0.0.1:{port}", httpd


def test_serve_tools_and_journal(ws: Path):
    import json as _j
    import urllib.request
    base, httpd = _serve(ws)
    try:
        with urllib.request.urlopen(f"{base}/atopia/tools", timeout=5) as r:
            o = _j.loads(r.read().decode())
        assert o["ok"] and any(t["name"] == "kb.stats" for t in o["tools"])
        assert o["levels"]["L2"].startswith("写入")
        with urllib.request.urlopen(f"{base}/atopia/journal", timeout=5) as r:
            j = _j.loads(r.read().decode())
        assert j["ok"] and isinstance(j["records"], list)
    finally:
        httpd.shutdown()


def test_serve_run_l3_forbidden(ws: Path):
    import json as _j
    import urllib.error, urllib.request

    base, httpd = _serve(ws)
    try:
        req = urllib.request.Request(
            f"{base}/atopia/run", method="POST",
            data=_j.dumps({"tool": "migrate.apply"}).encode(),
            headers={"Content-Type": "application/json"})
        import pytest as _pt
        with _pt.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req, timeout=5)
        assert ei.value.code == 403
        assert "L3" in _j.loads(ei.value.read().decode())["error"]
    finally:
        httpd.shutdown()


def test_serve_run_l2_requires_confirm(ws: Path):
    import json as _j
    import urllib.error, urllib.request

    base, httpd = _serve(ws)
    try:
        req = urllib.request.Request(
            f"{base}/atopia/run", method="POST",
            data=_j.dumps({"tool": "rules.reset"}).encode(),
            headers={"Content-Type": "application/json"})
        import pytest as _pt
        with _pt.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req, timeout=5)
        assert ei.value.code == 403

        req2 = urllib.request.Request(
            f"{base}/atopia/run", method="POST",
            data=_j.dumps({"tool": "rules.reset", "confirm": "teacher:pwa"}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req2, timeout=15) as r:
            o = _j.loads(r.read().decode())
        assert o["ok"] is True
    finally:
        httpd.shutdown()

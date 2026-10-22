"""D98：自检报告（doctor --report）——分层定位 + 可执行修复建议。"""
import json
from pathlib import Path

from click.testing import CliRunner

from assist.cli import cli
from assist.selfcheck import build_report, format_human


def _ws(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir(); (ws / "kb").mkdir()
    return ws


def test_report_has_layers(tmp_path):
    rep = build_report(_ws(tmp_path))
    for key in ("summary", "issues", "environment", "config", "capabilities", "data", "artifacts"):
        assert key in rep
    assert rep["schema"] == 1
    for i in rep["issues"]:
        assert {"code", "layer", "level", "message"} <= set(i)


def test_no_backend_reported_as_error(tmp_path):
    rep = build_report(_ws(tmp_path))
    codes = {i["code"] for i in rep["issues"]}
    assert "no_llm_backend" in codes
    assert rep["summary"]["ok"] is False


def test_transcription_command_no_images_is_warning(tmp_path, monkeypatch):
    from assist.grading import providers as P
    ws = _ws(tmp_path)
    P.save_provider(ws, "qwen", provider_type="command", cmd=["qwen"], supports_images=False)
    P.set_stage(ws, "transcription", provider="qwen")
    P.set_stage(ws, "evaluation", provider="qwen")
    rep = build_report(ws)
    by_code = {i["code"]: i for i in rep["issues"]}
    assert "transcription_command_no_images" in by_code
    assert by_code["transcription_command_no_images"]["level"] == "warn"
    # 有可用 command 后端 → no_llm_backend 不应出现
    assert "no_llm_backend" not in by_code


def test_api_provider_without_key_is_error(tmp_path):
    from assist.grading import providers as P
    ws = _ws(tmp_path)
    P.save_provider(ws, "ali", base_url="https://x/v1", api_key=None, model="m")
    P.set_stage(ws, "evaluation", provider="ali")
    rep = build_report(ws)
    codes = {i["code"] for i in rep["issues"]}
    assert "stage_provider_no_key.evaluation" in codes


def test_missing_workspace_reported(tmp_path):
    rep = build_report(tmp_path / "nope")
    assert any(i["code"] == "workspace_missing" for i in rep["issues"])


def test_artifact_failures_surface(tmp_path):
    ws = _ws(tmp_path)
    d = ws / "classes" / "c1" / "grading" / "t1"
    d.mkdir(parents=True)
    (d / "batch-report.json").write_text(json.dumps({
        "kind": "transcribe", "total": 3, "ok": 2, "failed": 1,
        "items": [{"id": "s1", "status": "ok"}, {"id": "s2", "status": "fail",
                                                 "error": "图片模糊"}],
    }, ensure_ascii=False), encoding="utf-8")
    rep = build_report(ws)
    assert rep["artifacts"]["reports"][0]["sampleFailures"][0]["id"] == "s2"
    assert any(i["code"] == "recent_batch_failures" for i in rep["issues"])


def test_cli_report_written_and_exit_code(tmp_path):
    ws = _ws(tmp_path)
    r = CliRunner().invoke(cli, ["doctor", "-w", str(ws), "--report"])
    assert r.exit_code == 1, r.output          # 无后端 → 非 0
    rep = json.loads((ws / "selfcheck-report.json").read_text(encoding="utf-8"))
    assert rep["summary"]["ok"] is False
    assert "自检" in r.output
    # 人类可读里应带修复建议
    assert "→" in r.output


def test_cli_report_json_mode(tmp_path):
    ws = _ws(tmp_path)
    r = CliRunner().invoke(cli, ["doctor", "-w", str(ws), "--report", "--json"])
    d = json.loads(r.output)
    assert d["summary"]["ok"] is False and d["issues"]


def test_format_human_lists_fix():
    rep = build_report("/definitely/missing")
    text = format_human(rep)
    assert "自检" in text and "问题" in text

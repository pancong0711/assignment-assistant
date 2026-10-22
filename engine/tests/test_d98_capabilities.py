"""D98-B2：doctor 能力探测（api/command/batch/agentCli + 推荐路径）。"""
import json

from click.testing import CliRunner

from assist.cli import cli
from assist.grading.providers import capabilities


def test_capabilities_none(tmp_path):
    caps = capabilities(tmp_path)
    assert caps["api"]["available"] is False
    assert caps["command"]["available"] is False
    assert caps["recommendedPath"] in ("command", "subagent-or-manual")


def test_capabilities_api_provider(tmp_path, monkeypatch):
    import assist.grading.providers as P
    monkeypatch.setattr(P, "list_providers", lambda ws=None, mask=True: [
        {"name": "aliyun", "base_url": "https://x/v1", "api_key": "k", "has_key": True,
         "models": [], "batch_support": True, "type": ""},
    ])
    caps = P.capabilities(tmp_path)
    assert caps["api"]["available"] and caps["api"]["providers"] == ["aliyun"]
    assert caps["batch"]["available"] is True
    assert caps["recommendedPath"] == "api"


def test_capabilities_command_provider(tmp_path, monkeypatch):
    import assist.grading.providers as P
    monkeypatch.setattr(P, "list_providers", lambda ws=None, mask=True: [
        {"name": "local", "base_url": "", "api_key": "", "has_key": False,
         "models": [], "batch_support": False, "type": "command"},
    ])
    caps = P.capabilities(tmp_path)
    assert caps["command"]["available"] is True
    assert caps["recommendedPath"] == "command"


def test_doctor_json_has_capabilities(tmp_path):
    r = CliRunner().invoke(cli, ["doctor", "-w", str(tmp_path), "--json"])
    assert r.exit_code == 0, r.output
    d = json.loads(r.output)
    assert "capabilities" in d and "recommendedPath" in d["capabilities"]


def test_warns_when_transcription_uses_command_without_images(tmp_path):
    """转录段用不支持图片的 command provider 时，必须告警（读图会失败）。"""
    from assist.grading import providers as P
    P.save_provider(tmp_path, "qwen", provider_type="command", cmd=["qwen"],
                    supports_images=False)
    P.set_stage(tmp_path, "transcription", provider="qwen")
    caps = P.capabilities(tmp_path)
    codes = [w["code"] for w in caps["warnings"]]
    assert "transcription_command_no_images" in codes


def test_no_warn_when_transcription_uses_api(tmp_path):
    from assist.grading import providers as P
    P.save_provider(tmp_path, "qwen", provider_type="command", cmd=["qwen"],
                    supports_images=False)
    P.save_provider(tmp_path, "vl", base_url="https://x/v1", api_key="k", model="qwen-vl")
    P.set_stage(tmp_path, "transcription", provider="vl")
    P.set_stage(tmp_path, "evaluation", provider="qwen")
    caps = P.capabilities(tmp_path)
    codes = [w["code"] for w in caps["warnings"]]
    assert "transcription_command_no_images" not in codes
    assert "command_no_images" in codes   # 仅信息级提示

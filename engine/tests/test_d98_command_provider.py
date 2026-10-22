"""D98-B3：type=command provider（无 API key 回环外部 agent CLI）。"""
import json
from pathlib import Path

import pytest

from assist.grading.provider_command import (CommandProviderError, build_payload, run_command)


def _echo_prov(tmp_path: Path, mode="stdout-json"):
    """一个假 agent CLI：读 stdin JSON，把 prompt/images 回显为 JSON/文本。"""
    script = tmp_path / "fake_agent.py"
    script.write_text(
        "import sys,json\n"
        "d=json.load(sys.stdin)\n"
        "if bool(d.get('images')):\n"
        "    print(json.dumps({'text':'IMG:'+str(len(d['images']))+':'+d['prompt']}))\n"
        "else:\n"
        "    print(json.dumps({'text':'TEXT:'+d['prompt']}))\n",
        encoding="utf-8")
    return {"cmd": ["python3", str(script)], "output_mode": mode, "timeout_s": 10}


def test_build_payload_isolated():
    p = build_payload(item_id="s1", prompt="学生甲", images=["/a.png"])
    assert p["id"] == "s1" and p["prompt"] == "学生甲" and p["images"] == ["/a.png"]
    assert "学生乙" not in json.dumps(p, ensure_ascii=False)


def test_run_command_stdout_json(tmp_path):
    prov = _echo_prov(tmp_path)
    res = run_command(prov, build_payload(item_id="s1", prompt="你好"))
    assert res["ok"] is True and res["text"] == "TEXT:你好"
    assert res["ms"] >= 0


def test_run_command_passes_images(tmp_path):
    prov = _echo_prov(tmp_path)
    res = run_command(prov, build_payload(item_id="s1", prompt="p", images=["/x.png", "/y.png"]))
    assert res["ok"] is True and res["text"].startswith("IMG:2:")


def test_run_command_stdout_text(tmp_path):
    script = tmp_path / "t.py"
    script.write_text("print('plain-ok')", encoding="utf-8")
    res = run_command({"cmd": ["python3", str(script)], "output_mode": "stdout-text"},
                      build_payload(item_id="s1", prompt="x"))
    assert res["ok"] is True and res["text"] == "plain-ok"


def test_run_command_missing_binary():
    res = run_command({"cmd": ["/definitely/not/exist"]}, build_payload(item_id="s1", prompt="x"))
    assert res["ok"] is False and "命令不存在" in res["error"]


def test_run_command_timeout(tmp_path):
    script = tmp_path / "slow.py"
    script.write_text("import time;time.sleep(5)", encoding="utf-8")
    res = run_command({"cmd": ["python3", str(script)], "timeout_s": 1},
                      build_payload(item_id="s1", prompt="x"))
    assert res["ok"] is False and "超时" in res["error"]


def test_run_command_nonzero_exit(tmp_path):
    script = tmp_path / "fail.py"
    script.write_text("import sys;print('boom',file=sys.stderr);sys.exit(3)", encoding="utf-8")
    res = run_command({"cmd": ["python3", str(script)]}, build_payload(item_id="s1", prompt="x"))
    assert res["ok"] is False and "退出码 3" in res["error"]


def test_llmclient_command_branch(tmp_path, monkeypatch):
    """LLMClient 在 command provider 下不走 HTTP，返回伪 OpenAI 响应。"""
    from assist.grading.llm import LLMClient
    script = tmp_path / "a.py"
    script.write_text(
        "import sys,json;d=json.load(sys.stdin);print(json.dumps({'text':'R:'+d['prompt']}))",
        encoding="utf-8")
    c = LLMClient(settings={"type": "command", "cmd": ["python3", str(script)],
                            "output_mode": "stdout-json", "timeout_s": 10,
                            "base_url": "http://unused", "api_key": "x", "model": "m"})
    out = c.chat(system_prompt="sys", user_text="问题", step="evaluation")
    assert out == "R:问题"


def test_llmclient_command_does_not_leak_previous_context(tmp_path):
    """两次调用 = 两次独立进程，第二次不带第一次内容。"""
    from assist.grading.llm import LLMClient
    script = tmp_path / "a.py"
    script.write_text(
        "import sys,json;d=json.load(sys.stdin);"
        "print(json.dumps({'text':d['prompt']}))", encoding="utf-8")
    c = LLMClient(settings={"type": "command", "cmd": ["python3", str(script)],
                            "output_mode": "stdout-json", "timeout_s": 10,
                            "base_url": "http://unused", "api_key": "x", "model": "m"})
    a = c.chat(system_prompt="s", user_text="学生甲AAA", step="evaluation")
    b = c.chat(system_prompt="s", user_text="学生乙BBB", step="evaluation")
    assert a == "学生甲AAA" and b == "学生乙BBB"
    assert "AAA" not in b and "BBB" not in a


def test_command_mode_defaults_to_agent_current_model(tmp_path):
    """裁决 7：默认不传模型（用 agent 当前模型）；显式 model 才传。"""
    from assist.grading.llm import LLMClient
    seen = {}

    script = tmp_path / "argv.py"
    script.write_text(
        "import sys,json\n"
        "d=json.load(sys.stdin)\n"
        "print(json.dumps({'text':'MODEL='+repr(d.get('model'))}))\n",
        encoding="utf-8")
    # 配置里残留 API 默认模型（deepseek-chat），但 command 模式不应使用
    c = LLMClient(settings={"type": "command", "cmd": ["python3", str(script)],
                            "output_mode": "stdout-json", "timeout_s": 10,
                            "base_url": "http://unused", "api_key": "x",
                            "model": "deepseek-chat"})
    assert c.evaluation_model == "", "command 模式不应套用 API 默认模型"
    out1 = c.chat(system_prompt="s", user_text="q", step="evaluation")
    assert out1 == "MODEL=''", out1
    # 显式指定模型则应传入
    out2 = c.request([{"role": "user", "content": "q"}], model="qwen3-max")
    assert "qwen3-max" in c.extract_text(out2)


def test_llmclient_ws_uses_command_provider(tmp_path):
    """转录/批阅走 LLMClient(ws=ws)：必须识别 type=command（此前只读旧 api_key 配置→失败）。"""
    from assist.grading import providers
    from assist.grading.llm import LLMClient
    providers.save_provider(tmp_path, "local", provider_type="command",
                            cmd=["python3", "-c",
                                 "import sys,json;d=json.load(sys.stdin);"
                                 "print(json.dumps({'text':'CMD:'+d['prompt'][:8]}))"],
                            output_mode="stdout-json", timeout_s=10)
    providers.set_stage(tmp_path, "evaluation", provider="local")
    providers.set_stage(tmp_path, "transcription", provider="local")
    c = LLMClient(ws=tmp_path)
    assert c.provider_type == "command"
    assert c.chat(system_prompt="s", user_text="学生作答ABC", step="evaluation") == "CMD:学生作答ABC"

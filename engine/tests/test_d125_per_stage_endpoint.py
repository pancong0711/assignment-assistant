"""D125：转录不得使用评阅段的 base_url/key（配置错配）+ 分步批阅。

现象：Playground 正常，但 AI 批阅转录报
  `Model is unavailable`（因为 qwen 模型被发往了 opencode 的端点）。
"""
import json
from pathlib import Path
from unittest import mock

import pytest

from assist.grading.llm import LLMAPIError, LLMClient
from assist.settings_store import update_settings, write_secrets


def _mk_ws(tmp_path: Path) -> Path:
    """两段用**不同 provider/base_url/model/key**（正是出问题的配置）。"""
    ws = tmp_path / "ws"
    (ws / "kb").mkdir(parents=True)
    update_settings(ws, lambda d: d.update({"llm": {
        "providers": [
            {"name": "aliyun-official", "base_url": "https://aliyun.example/v1",
             "models": ["qwen3.7-flash"]},
            {"name": "opencode-go", "base_url": "https://opencode.example/v1",
             "models": ["deepseek-v4.1-flash"]},
        ],
        "stages": {
            "transcription": {"provider": "aliyun-official", "model": "qwen3.7-flash"},
            "evaluation": {"provider": "opencode-go", "model": "deepseek-v4.1-flash"},
        },
    }}))
    write_secrets(ws, {"llm": {"providers": {
        "aliyun-official": "KEY-ALIYUN", "opencode-go": "KEY-OPENCODE"}}})
    return ws


def test_transcription_uses_its_own_base_url_and_key(tmp_path):
    """**核心回归**：转录必须发往转录段自己的 base_url/key。"""
    ws = _mk_ws(tmp_path)
    c = LLMClient(ws=ws)
    base, key, model = c._step_base_key("transcription")
    assert base == "https://aliyun.example/v1", f"转录用了错误的 base_url：{base}"
    assert key == "KEY-ALIYUN", f"转录用了错误的 key：{key}"
    assert model == "qwen3.7-flash"


def test_evaluation_uses_its_own_base_url_and_key(tmp_path):
    ws = _mk_ws(tmp_path)
    c = LLMClient(ws=ws)
    base, key, model = c._step_base_key("evaluation")
    assert base == "https://opencode.example/v1"
    assert key == "KEY-OPENCODE"
    assert model == "deepseek-v4.1-flash"


def test_two_stages_never_share_endpoint(tmp_path):
    """两段的 (base, key, model) 必须是各自配套的三元组，不能串。"""
    ws = _mk_ws(tmp_path)
    c = LLMClient(ws=ws)
    t = c._step_endpoint("transcription")
    e = c._step_endpoint("evaluation")
    assert t["provider"] == "aliyun-official" and e["provider"] == "opencode-go"
    assert t["base_url"] != e["base_url"]
    assert t["api_key"] != e["api_key"]


def test_same_provider_both_stages_still_works(tmp_path):
    """两段用同一个 provider 时行为与旧版一致。"""
    ws = tmp_path / "ws"
    (ws / "kb").mkdir(parents=True)
    update_settings(ws, lambda d: d.update({"llm": {
        "providers": [{"name": "p1", "base_url": "https://p1/v1", "models": ["m1", "m2"]}],
        "stages": {"transcription": {"provider": "p1", "model": "m1"},
                   "evaluation": {"provider": "p1", "model": "m2"}}}}))
    write_secrets(ws, {"llm": {"providers": {"p1": "K1"}}})
    c = LLMClient(ws=ws)
    assert c._step_base_key("transcription")[:2] == ("https://p1/v1", "K1")
    assert c._step_base_key("evaluation")[:2] == ("https://p1/v1", "K1")
    assert c._step_base_key("transcription")[2] == "m1"
    assert c._step_base_key("evaluation")[2] == "m2"


def test_deterministic_400_not_retried(tmp_path):
    """400/Model is unavailable 属确定性错误 → **不重试**（只调用 1 次）。"""
    ws = _mk_ws(tmp_path)
    c = LLMClient(ws=ws)
    calls = {"n": 0}

    class _Resp:
        status_code = 400
        text = '{"error":{"type":"server_error","message":"Upstream request failed: Model is unavailable."}}'

        def json(self):
            return {}

    def _fake_post(*a, **kw):  # noqa: ANN002, ANN003
        calls["n"] += 1
        return _Resp()

    with mock.patch("assist.grading.llm.httpx.post", _fake_post):
        with pytest.raises(LLMAPIError) as ei:
            c.chat("sys", "hi", max_tokens=8, step="transcription")
    assert calls["n"] == 1, f"确定性错误不应重试，实际调用 {calls['n']} 次"
    msg = str(ei.value)
    # D125：报错应带定位信息（但不含 key）
    assert "step=transcription" in msg and "base_url=" in msg and "model=" in msg
    assert "KEY-ALIYUN" not in msg and "KEY-OPENCODE" not in msg


def test_error_message_identifies_wrong_endpoint(tmp_path):
    """模拟错配时，报错能指出"哪个 base_url + 哪个 model"。"""
    ws = _mk_ws(tmp_path)
    c = LLMClient(ws=ws)
    with mock.patch("assist.grading.llm.httpx.post",
                    return_value=type("R", (), {"status_code": 400,
                                                "text": "Model is unavailable",
                                                "json": lambda self: {}})()):
        with pytest.raises(LLMAPIError) as ei:
            c.chat("s", "h", model="qwen3.7-flash", max_tokens=8, step="evaluation")
    msg = str(ei.value)
    assert "opencode.example" in msg and "qwen3.7-flash" in msg


# ---------------- 分步批阅 ----------------

def test_cli_steps_option_sets_task_steps(tmp_path):
    """--steps transcribe → 只跑转录（写回 taskpad 的 grade.steps）。"""
    from click.testing import CliRunner

    from assist.cli import cli
    ws = tmp_path / "ws"
    (ws / "kb").mkdir(parents=True)
    task = {"id": "t1", "grade": {"steps": ["transcribe", "evaluate", "report"]}}
    tp = ws / "task.json"
    tp.write_text(json.dumps(task), encoding="utf-8")
    seen = {}

    def _fake_run(task_path_, ws_, **kw):  # noqa: ANN001, ANN003
        seen["steps"] = json.loads(Path(task_path_).read_text())["grade"]["steps"]
        return {"run_id": "x", "steps_done": [], "bucket": str(ws_), "usage": {}}

    with mock.patch("assist.grading.flow.run_task", _fake_run):
        r = CliRunner().invoke(cli, ["grade", "--task", str(tp), "--steps", "transcribe",
                                     "-w", str(ws)])
    assert r.exit_code == 0, r.output
    assert seen["steps"] == ["transcribe"]


def test_cli_steps_rejects_unknown(tmp_path):
    from click.testing import CliRunner

    from assist.cli import cli
    ws = tmp_path / "ws"; (ws / "kb").mkdir(parents=True)
    tp = ws / "task.json"
    tp.write_text(json.dumps({"id": "t"}), encoding="utf-8")
    r = CliRunner().invoke(cli, ["grade", "--task", str(tp), "--steps", "transcribe,bogus",
                                 "-w", str(ws)])
    assert r.exit_code != 0
    assert "未知步骤" in r.output


def test_partial_transcribe_failure_aborts_by_default(tmp_path):
    """D125：转录有学生失败 → 默认**中止**（不用残缺数据跑评阅）。"""
    from assist.grading.flow import GradingInputError, _run_transcribe

    ctx = {"task": {}, "plan": {"students": [{"name": "张三", "images": ["a.jpg"]}]},
           "images_dir": None, "concurrency": 1, "allow_partial": False}
    with mock.patch("assist.grading.transcribe.transcribe_batch",
                    return_value={"ok": True, "failed": 1, "total": 1,
                                  "items": [{"id": "张三", "ok": False, "error": "Model is unavailable"}]}), \
         mock.patch("assist.grading.flow._plan_student_images",
                    return_value={"张三": [Path("a.jpg")]}):
        with pytest.raises(GradingInputError) as ei:
            _run_transcribe(ctx, object(), tmp_path / "tr")
    assert "转录有 1/1 名学生失败" in str(ei.value)
    assert "--allow-partial" in str(ei.value)


def test_partial_transcribe_allowed_with_flag(tmp_path):
    from assist.grading.flow import _run_transcribe

    ctx = {"task": {}, "plan": {"students": [{"name": "张三", "images": ["a.jpg"]}]},
           "images_dir": None, "concurrency": 1, "allow_partial": True}
    with mock.patch("assist.grading.transcribe.transcribe_batch",
                    return_value={"ok": True, "failed": 1, "total": 1,
                                  "items": [{"id": "张三", "ok": False, "error": "x"}]}), \
         mock.patch("assist.grading.flow._plan_student_images",
                    return_value={"张三": [Path("a.jpg")]}):
        out = _run_transcribe(ctx, object(), tmp_path / "tr")
    assert out == []


# ---------------- 兼容性（D82-F 旧覆盖 / 旧单层配置） ----------------

def test_legacy_single_layer_config_still_works(tmp_path):
    """只有旧单层 llm（无 providers/stages）→ 两段共用同一套 base/key/model。"""
    ws = tmp_path / "ws"
    (ws / "kb").mkdir(parents=True)
    update_settings(ws, lambda d: d.update({"llm": {
        "base_url": "https://legacy/v1", "api_key": "K", "model": "m1"}}))
    c = LLMClient(ws=ws)
    for st in ("transcription", "evaluation"):
        assert c._step_base_key(st) == ("https://legacy/v1", "K", "m1")


def test_d82f_stage_override_still_wins(tmp_path):
    """D82-F：`llm.<step>` 的部分字段仍**优先于** stages（不能因 D125 而失效）。"""
    ws = tmp_path / "ws"
    (ws / "kb").mkdir(parents=True)
    update_settings(ws, lambda d: d.update({"llm": {
        "providers": [{"name": "p1", "base_url": "https://p1/v1", "models": ["m1"]}],
        "stages": {"transcription": {"provider": "p1", "model": "m1"},
                   "evaluation": {"provider": "p1", "model": "m1"}},
        "transcription": {"model": "OVERRIDE"}}}))
    write_secrets(ws, {"llm": {"providers": {"p1": "K"}}})
    c = LLMClient(ws=ws)
    assert c._step_base_key("transcription")[2] == "OVERRIDE", "D82-F 覆盖应生效"
    assert c._step_base_key("evaluation")[2] == "m1", "不应影响评阅段"

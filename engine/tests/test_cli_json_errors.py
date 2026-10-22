"""机读错误：ASSIST_JSON_ERRORS=1 时未处理异常/ClickException 转为结构化 JSON。"""
import json
import os
import subprocess
import sys
from pathlib import Path

ENGINE_SRC = str(Path(__file__).resolve().parents[1] / "src")


def _run(args, tmp_path, json_mode=True):
    env = dict(os.environ, PYTHONPATH=ENGINE_SRC, ASSIST_WORKSPACE=str(tmp_path))
    if json_mode:
        env["ASSIST_JSON_ERRORS"] = "1"
    else:
        env.pop("ASSIST_JSON_ERRORS", None)
    return subprocess.run([sys.executable, "-m", "assist.cli", *args],
                          capture_output=True, text=True, env=env, timeout=60)


def test_click_exception_json(tmp_path):
    r = _run(["xxt", "allowlist", "rm", "--course", "c", "--class", "k"], tmp_path)
    assert r.returncode == 1
    d = json.loads(r.stderr.strip().splitlines()[-1])
    assert d["ok"] is False and d["exitCode"] == 1 and d["type"] == "ClickException"


def test_no_such_command_json(tmp_path):
    r = _run(["definitely-not-a-command"], tmp_path)
    assert r.returncode == 2
    d = json.loads(r.stderr.strip().splitlines()[-1])
    assert d["ok"] is False and d["exitCode"] == 2


def test_unhandled_exception_json(tmp_path):
    # 指向一个不可创建的路径，触发 OSError（未处理异常）
    bad = "/proc/should-not-write-here"
    r = _run(["kb", "stats", "-w", bad], tmp_path)
    assert r.returncode == 1
    d = json.loads(r.stderr.strip().splitlines()[-1])
    assert d["ok"] is False and d["exitCode"] == 1
    assert d["type"]  # 具体异常类型


def test_human_mode_keeps_plain_error(tmp_path):
    r = _run(["xxt", "allowlist", "rm", "--course", "c", "--class", "k"],
             tmp_path, json_mode=False)
    assert r.returncode == 1
    assert "白名单中不存在" in r.stderr
    assert not r.stderr.strip().startswith("{")

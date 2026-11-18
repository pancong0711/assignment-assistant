"""D193：Windows GBK 控制台下的 UnicodeEncodeError 与 3.11 语法兼容。

现场：上传批语/成绩时报
  `UnicodeEncodeError: 'gbk' codec can't encode character '\\u2212' in position 965`
批语里有数学减号 `−`(U+2212)。报告已生成，但上传任务在**打印结果 JSON**时崩掉。
"""
from __future__ import annotations

import io
import json
import pathlib
import sys

import assist.cli as cli_mod
import assist.serve as serve

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _gbk_stream():
    buf = io.BytesIO()
    return buf, io.TextIOWrapper(buf, encoding="gbk", errors="strict")


def test_raw_gbk_stream_would_fail_with_minus_sign():
    """先确认现场能复现（防止以后误删保护还“测试通过”）。"""
    buf, stream = _gbk_stream()
    try:
        stream.write(json.dumps({"c": "10 \u2212 2"}, ensure_ascii=False))
        stream.flush()
    except UnicodeEncodeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("GBK 流应无法编码 U+2212（复现前提已变）")


def test_force_utf8_output_makes_gbk_console_safe():
    buf, stream = _gbk_stream()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = stream
    sys.stderr = stream
    try:
        cli_mod._force_utf8_output()
        payload = {"comment": "分数 = 10 \u2212 2 = 8", "emoji": "\U0001F600"}
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        sys.stdout.flush()
        text = buf.getvalue().decode("utf-8")
        assert "\u2212" in text and "\U0001F600" in text
    finally:
        sys.stdout, sys.stderr = old_out, old_err


def test_force_utf8_output_survives_stream_without_reconfigure():
    class _Plain:
        def __init__(self):
            self.written = ""

        def write(self, s):
            self.written += s

    old_out = sys.stdout
    sys.stdout = _Plain()
    try:
        cli_mod._force_utf8_output()  # 不抛异常即可
        sys.stdout.write("\u2212")
        assert sys.stdout.written == "\u2212"
    finally:
        sys.stdout = old_out


def test_xxt_env_forces_utf8_for_cli_subprocess(tmp_path, monkeypatch):
    monkeypatch.setattr(serve, "_ws", lambda: tmp_path)
    env = serve._xxt_env(tmp_path)
    assert env["PYTHONIOENCODING"] == "utf-8:replace"
    assert env["PYTHONUTF8"] == "1"
    # 原有契约不变
    assert env["XXT_HOME"] == str(tmp_path)
    assert env["ASSIST_NO_JOURNAL"] == "1"


def test_stream_job_decodes_child_output_as_utf8():
    src = (ROOT / "src/assist/serve.py").read_text(encoding="utf-8")
    body = src.split("def _start_stream_job(")[1].split("def _start_job(")[0]
    assert 'encoding="utf-8", errors="replace"' in body


def test_main_forces_utf8_before_dispatch():
    src = (ROOT / "src/assist/cli.py").read_text(encoding="utf-8")
    body = src.split("def main():")[1].split("def _alias_assistopia_argv")[0] \
        if "def _alias_assistopia_argv" in src.split("def main():")[1] else src.split("def main():")[1][:1500]
    assert "_force_utf8_output()" in body


def test_sources_parse_under_python311_grammar():
    """引擎声明 requires-python >=3.11：源码必须能在 3.11 语法级别编译。

    现场对应的坏写法是多行 f-string（3.12 才允许）：
        raise click.ClickException(f"...{ 
            detail}")
    在 3.11 下会让**整个 CLI 无法启动**，所有 xxt 命令（含批阅上传）全部失败。
    用 `ast.parse(..., feature_version=(3, 11))` 做与运行版本无关的语法校验。
    """
    import ast
    offenders = []
    for p in (ROOT / "src").rglob("*.py"):
        try:
            ast.parse(p.read_text(encoding="utf-8"), filename=str(p),
                      feature_version=(3, 11))
        except SyntaxError as exc:
            offenders.append(f"{p}:{exc.lineno}: {exc.msg}")
    assert offenders == [], "存在 Python 3.11 无法解析的语法：" + "; ".join(offenders)


def test_cli_upload_summary_roundtrip_with_math_minus():
    """批语含 U+2212 时，结果 JSON 必须能完整序列化/反序列化（上传主链路）。"""
    rep = {"ok": True, "comment": "10 \u2212 2", "score": 8}
    payload = json.dumps(rep, ensure_ascii=False, indent=1)
    assert json.loads(payload)["comment"] == "10 \u2212 2"

"""D64 §22.1 回归：/jobs/<id>/stream 的 SSE 帧必须以真换行结束。

回归背景：帧尾误写 b"\\\\n\\\\n"（字面反斜杠+n）导致 EventSource 解析不出
任何 message/done 事件，安装按钮"闪一下"即回落、安装输出区永远空白。
"""
import re
import types
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class _Log:
    def __getattr__(self, n):
        return lambda *a, **k: None


def _setup(monkeypatch):
    lg = types.ModuleType("loguru")
    lg.logger = _Log()
    monkeypatch.setitem(sys.modules, "loguru", lg)
    from assist import serve as S
    return S


def test_sse_frames_end_with_real_newlines(monkeypatch):
    """special_worker 收尾后读 job['lines'] 应含『合成正确的 SSE 字节流』，
    这里直接校验 Handler 的写帧源码不再包含字面反斜杠 n（防再犯）。"""
    S = _setup(monkeypatch)
    src = Path(S.__file__).read_text(encoding="utf-8")
    bad = re.findall(r'wfile\.write\([^\n]*b"[^"]*\\\\n', src)
    assert not bad, f"SSE 帧尾仍是字面反斜杠n：{bad}"


def test_special_job_produces_done_line(monkeypatch):
    """kb_init（纯 guide 文本 job，不联网）应尽快走完并投递 __DONE__0__。"""
    S = _setup(monkeypatch)
    q = {}
    S.Handler._start_job(None, "jobtest1", "kb_init")
    for _ in range(200):
        import queue as _q
        try:
            job = S._JOBS["jobtest1"]
            line = job["queue"].get_nowait()
        except _q.Empty:
            import time; time.sleep(0.02); continue
        if line.startswith("__DONE__"):
            q["rc"] = line
            break
    assert q.get("rc") == "__DONE__0__"

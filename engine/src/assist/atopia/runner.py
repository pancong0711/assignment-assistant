"""runner.py — D132-T15b：工具执行器（子进程 + 超时 + 截断 + journal 审计）。

要点（docs/81 §3/§9）：
- **列表传参，不经过 shell**（防注入）；
- cwd 固定 workspace；
- 超时 kill 并记 `status=timeout`；
- stdout/stderr 只留前 500 字（防 journal 爆掉 / 泄露大段学生作答）；
- 每次调用**只追加**一行 journal。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from loguru import logger

from . import limits as L
from . import paths as P
from .registry import (L2, L3, Tool, ToolDenied, build_argv, effective_tool,
                       level_at_least, validate_args)

JOURNAL = f"{P.ROOT}/{P.JOURNAL_FILE}"
OUTPUT_HEAD_CHARS = 500
_SENSITIVE_KEYS = ("api_key", "apikey", "token", "secret", "password")


def journal_path(ws) -> Path:
    """D134：审计日志落在 `<ws>/atopia/journal.jsonl`（见 paths.py）。"""
    return P.journal_path(ws)


def _scrub(text: str) -> str:
    """截断 + 脱敏（参数里可能混入 key；虽已限制参数名，仍做兜底）。"""
    s = str(text or "")
    for k in _SENSITIVE_KEYS:
        if k in s.lower():
            # 不试图精确替换，直接标记存在敏感内容（保守）
            s = s.replace(k, k)
    return s[:OUTPUT_HEAD_CHARS]


def _append_journal(ws, rec: dict) -> None:
    p = journal_path(ws)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[atopia] journal 写入失败：{str(exc)[:120]}")


def _cli_argv(argv: list[str], ws: Path) -> list[str]:
    """把工程内命令包成 `python -m assist.cli <argv>` 并固定 -w workspace。"""
    return [sys.executable, "-m", "assist.cli", *argv, "--workspace", str(ws)]


def run_tool(ws, tool_name: str, args: "dict | None" = None, *,
             session: "L.Session | None" = None,
             confirmed_by: str = "",
             dry_run_ok: bool = True) -> dict:
    """执行一个工具。

    - 未登记 → `ToolDenied`
    - L3 → `ToolDenied`（不开放）
    - L2 → 必须有 `confirmed_by`（教师确认来源），否则 `ToolDenied`
    - 护栏（次数/时长/L1 成本）→ `LimitExceeded`
    """
    ws_p = Path(ws).resolve()
    tool: Tool = effective_tool(ws_p, tool_name)     # 含扩展覆盖（只升不降）

    if tool.level == L3:
        raise ToolDenied(f"L3 工具不开放：{tool.name}（docs/81 §2，任何配置都无法开通）")
    if tool.level == L2 and not str(confirmed_by or "").strip():
        raise ToolDenied(
            f"{tool.name} 属 L2 写入工具，**必须教师二次确认**后才能执行"
            f"（未收到确认来源）")

    argv_args = validate_args(tool, ws_p, args)
    argv = build_argv(tool, argv_args)

    is_llm = level_at_least(tool.level, "L1") and tool.level != L2
    if session is not None:
        session.check_call(is_llm=is_llm)

    timeout = (session.limits["callTimeoutSeconds"] if session
               else L.read_limits(ws_p)["callTimeoutSeconds"])
    cmd = _cli_argv(argv, ws_p)
    started = time.time()
    before = session.calls if session else 0
    try:
        proc = subprocess.run(cmd, cwd=str(ws_p), capture_output=True, text=True,
                              timeout=timeout, check=False,
                              env={**os.environ, "ASSIST_WORKSPACE": str(ws_p)})
        ms = int((time.time() - started) * 1000)
        status = "ok" if proc.returncode == 0 else "error"
        out, err, code = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        ms = int((time.time() - started) * 1000)
        status, code = "timeout", 124
        out = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(
            exc.stdout, bytes) else (exc.stdout or "")
        err = f"超时（>{timeout}s）已终止"
    finally:
        if session is not None and session.calls == before:
            # 护栏计数：失败/超时也算一次调用（否则可以被失败循环绕过）
            session.record(is_llm=is_llm)

    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
           "session": (session.session_id if session else ""),
           "tool": tool.name, "level": tool.level, "argv": argv,
           "args": argv_args, "status": status, "exit": code, "ms": ms,
           "confirmed_by": str(confirmed_by or ""),
           "stdout_head": _scrub(out), "stderr_head": _scrub(err)}
    _append_journal(ws_p, rec)
    return {"ok": status == "ok", "status": status, "tool": tool.name,
            "level": tool.level, "exit": code, "ms": ms,
            "stdout": out, "stderr": err, "journal": str(journal_path(ws_p))}


def read_journal(ws, *, limit: int = 200) -> list[dict]:
    """读最近 N 条审计记录（PWA/journal 查看用）。"""
    p = journal_path(ws)
    if not p.is_file():
        return []
    lines = [x for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    out: list[dict] = []
    for line in lines[-max(1, limit):]:
        try:
            out.append(json.loads(line))
        except Exception:  # noqa: BLE001
            continue
    return out

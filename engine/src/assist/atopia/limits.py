"""limits.py — D132-T17：护栏（调用次数 / 时长 / L1 成本 / 预算）。

设计（docs/81 §4）：数值可配，但**有硬顶**——不能配成"无限"，
否则护栏等于没有。硬顶写死在 `HARD_CAPS`。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

LIMITS_FILE = "limits.json"

DEFAULTS = {
    "maxCallsPerSession": 40,
    "maxLlmCallsPerSession": 30,     # L1（会花模型钱）单独计数
    "callTimeoutSeconds": 120,
    "sessionSeconds": 600,
}

# 硬顶（无论怎么配都不超过）
HARD_CAPS = {
    "maxCallsPerSession": 200,
    "maxLlmCallsPerSession": 100,
    "callTimeoutSeconds": 600,
    "sessionSeconds": 3600,
}


class LimitExceeded(RuntimeError):
    """护栏拦截。"""


def limits_path(ws) -> Path:
    return Path(ws).resolve() / "atopia" / LIMITS_FILE


def read_limits(ws) -> dict:
    """读配置；缺失用默认；非法值回落默认并告警；**一律夹到硬顶**。"""
    out = dict(DEFAULTS)
    p = limits_path(ws) if ws is not None else None
    if p is not None and p.is_file():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k in DEFAULTS:
                    if k in raw:
                        try:
                            out[k] = int(raw[k])
                        except (TypeError, ValueError):
                            logger.warning(f"[atopia] limits.{k} 非整数，用默认")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[atopia] {LIMITS_FILE} 解析失败，用默认：{exc}")
    for k, cap in HARD_CAPS.items():
        if out[k] > cap:
            logger.warning(f"[atopia] limits.{k}={out[k]} 超过硬顶 {cap}，已夹住")
            out[k] = cap
        if out[k] <= 0:
            out[k] = DEFAULTS[k]
    return out


@dataclass
class Session:
    """一次 Assistopia 会话的计数与计时（内存态；journal 落盘）。"""
    session_id: str
    limits: dict
    calls: int = 0
    llm_calls: int = 0
    started: float = field(default_factory=time.time)

    def check_call(self, *, is_llm: bool = False) -> None:
        if self.calls >= self.limits["maxCallsPerSession"]:
            raise LimitExceeded(
                f"本次会话调用次数已达上限 {self.limits['maxCallsPerSession']} 次"
                f"（见 docs/81 §4 护栏）")
        if time.time() - self.started > self.limits["sessionSeconds"]:
            raise LimitExceeded(
                f"本次会话已超过时长上限 {self.limits['sessionSeconds']} 秒")
        if is_llm and self.llm_calls >= self.limits["maxLlmCallsPerSession"]:
            raise LimitExceeded(
                f"本次会话会花模型成本的调用已达上限 "
                f"{self.limits['maxLlmCallsPerSession']} 次")

    def record(self, *, is_llm: bool = False) -> None:
        self.calls += 1
        if is_llm:
            self.llm_calls += 1

    def elapsed(self) -> float:
        return time.time() - self.started


def write_limits(ws, patch: dict, *, journal: bool = True) -> dict:
    """教师调整护栏（受**硬顶**约束；非法值拒绝而不是静默接受）。

    docs/81 §4：数值可配，但不能配成"无限"——`HARD_CAPS` 是最后一道闸，
    这里**直接拒绝**超硬顶的请求（而不是夹住后不吭声），让教师知道没生效。
    """
    cur = read_limits(ws)
    bad: list[str] = []
    for k, v in (patch or {}).items():
        if k not in DEFAULTS:
            bad.append(f"未知项：{k}（可选 {', '.join(DEFAULTS)}）")
            continue
        try:
            iv = int(v)
        except (TypeError, ValueError):
            bad.append(f"{k} 必须是整数")
            continue
        if iv <= 0:
            bad.append(f"{k} 必须 > 0")
            continue
        if iv > HARD_CAPS[k]:
            bad.append(f"{k}={iv} 超过硬顶 {HARD_CAPS[k]}（护栏不允许配成无限）")
            continue
        cur[k] = iv
    if bad:
        return {"ok": False, "error": "；".join(bad), "errors": bad}
    p = limits_path(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
    if journal:
        try:
            with (p.parent / "journal.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                                    "action": "limits.write", "patch": patch,
                                    "effective": cur}, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[atopia] limits journal 写入失败：{exc}")
    return {"ok": True, "limits": cur, "file": str(p)}

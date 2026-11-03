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
    return Path(ws).resolve() / "assistopia" / LIMITS_FILE


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
                            logger.warning(f"[assistopia] limits.{k} 非整数，用默认")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[assistopia] {LIMITS_FILE} 解析失败，用默认：{exc}")
    for k, cap in HARD_CAPS.items():
        if out[k] > cap:
            logger.warning(f"[assistopia] limits.{k}={out[k]} 超过硬顶 {cap}，已夹住")
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

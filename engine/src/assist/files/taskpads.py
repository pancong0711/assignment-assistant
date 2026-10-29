"""D120：作业纸（taskpad）落盘 —— 消除"作业包还在、作业纸没了"的悬空引用。

路径契约：
    `<ws>/tasks/<padId>.taskpad.json`

背景：作业纸此前只存浏览器 localStorage；作业包（`<ws>/packs/`）却在磁盘，
pack 里只存 padId 引用 → 换浏览器/清缓存后 pack 变成悬空引用。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from loguru import logger

_SAFE_ID = re.compile(r"[^0-9A-Za-z_\-\u4e00-\u9fff.]")
# D120：单张作业纸落盘上限（防误传超大对象把磁盘写爆；正常作业纸远小于此）
MAX_TASKPAD_BYTES = 8 * 1024 * 1024


def tasks_dir(ws) -> Path:
    d = Path(ws).resolve() / "tasks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_pad_id(raw: str) -> str:
    """作业纸 id → 安全文件名。

    - 只保留安全字符；
    - **`..` 必须彻底消除**（否则可构造 `../evil` 之类路径）；
    - 结尾的点/空格去掉（Windows 不允许）。
    """
    s = _SAFE_ID.sub("_", str(raw or "").strip())
    while ".." in s:
        s = s.replace("..", "_")
    s = s.replace("/", "_").replace("\\", "_").strip(" .")
    return s[:80]


def taskpad_path(ws, pad_id: str) -> "Path | None":
    pid = safe_pad_id(pad_id)
    return tasks_dir(ws) / f"{pid}.taskpad.json" if pid else None


def save_taskpad(ws, pad: dict) -> dict:
    """写单张作业纸（按 pad.id）。"""
    if not isinstance(pad, dict):
        return {"ok": False, "error": "taskpad 必须是对象"}
    pid = safe_pad_id(pad.get("id") or "")
    if not pid:
        return {"ok": False, "error": "缺少作业纸 id"}
    p = taskpad_path(ws, pid)
    if p is None:
        return {"ok": False, "error": "作业纸 id 非法"}
    payload = {**pad, "id": pid,
               "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        body = json.dumps(payload, ensure_ascii=False, indent=1)
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": f"作业纸无法序列化：{exc}"}
    if len(body.encode("utf-8")) > MAX_TASKPAD_BYTES:
        return {"ok": False,
                "error": f"作业纸过大（>{MAX_TASKPAD_BYTES // 1024 // 1024}MB），未写盘"}
    try:
        from ..filelock import atomic_write_text
        atomic_write_text(p, body)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"写作业纸失败 {pid}: {exc}")
        return {"ok": False, "error": str(exc)[:200]}
    return {"ok": True, "path": str(p), "id": pid}


def list_taskpads(ws) -> list[dict]:
    """列出磁盘上的作业纸（供 PWA localStorage 为空时恢复）。"""
    out: list[dict] = []
    for f in sorted(tasks_dir(ws).glob("*.taskpad.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(d, dict):
            d.setdefault("id", f.stem.replace(".taskpad", ""))
            out.append(d)
    return out


def read_taskpad(ws, pad_id: str) -> "dict | None":
    p = taskpad_path(ws, pad_id)
    if p is None or not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except Exception:  # noqa: BLE001
        return None

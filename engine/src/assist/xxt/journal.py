"""D74-9：全局操作记录（JSONL，按月分片，默认保留 6 个月）。

设计：
- 只写本机 `xxt_home()/journal/YYYY-MM.jsonl`，不入库、不上传；
- 记录所有操作（PWA/CLI/引擎），成功与失败都记；
- 参数默认去敏：名单类字段只记数量，不落姓名；
- 每月一个文件，超期自动删除（滚动保留 6 个月）。
"""
from __future__ import annotations

import datetime
import json
import time
from pathlib import Path

DEFAULT_MONTHS = 6
_NAME_KEYS = {"unsubmitted_names", "submitted_names", "students", "names", "roster", "notices"}


def _dir(home=None) -> Path:
    from . import layout
    return layout.journal_dir(home)


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _month(ts: "str | None" = None) -> str:
    return (ts or _now())[:7]


def _sanitize(params) -> dict:
    if not isinstance(params, dict):
        return {}
    out: dict = {}
    for k, v in params.items():
        key = str(k)
        if key in _NAME_KEYS:
            out[key] = f"<{len(v) if isinstance(v, (list, dict)) else '?'} items>"
        elif v is None or isinstance(v, (str, int, float, bool)):
            out[key] = v[:200] if isinstance(v, str) else v
        elif isinstance(v, list):
            out[key] = f"<list {len(v)}>"
        elif isinstance(v, dict):
            out[key] = f"<dict {len(v)}>"
        else:
            out[key] = str(v)[:200]
    return out


def prune(home=None, months: int = DEFAULT_MONTHS) -> list[str]:
    """删除早于当前月 - (months-1) 的月度文件。"""
    d = _dir(home)
    if not d.is_dir():
        return []
    today = datetime.date.today()
    cutoff = (today.replace(day=1) - datetime.timedelta(days=31 * max(0, months - 1))).strftime("%Y-%m")
    removed: list[str] = []
    for f in sorted(d.glob("*.jsonl")):
        if f.stem < cutoff:
            try:
                f.unlink()
                removed.append(str(f))
            except Exception:  # noqa: BLE001
                pass
    return removed


def log_event(kind: str, *, home=None, source: str = "engine", params=None,
              run_id: "str | None" = None, result: str = "ok",
              duration_ms: "int | None" = None, error: str = "",
              extra: "dict | None" = None) -> dict:
    entry = {
        "ts": _now(),
        "kind": str(kind)[:64],
        "source": str(source)[:16],
        "result": "fail" if str(result).lower() in ("fail", "failed", "error") else "ok",
        "run_id": run_id,
        "duration_ms": duration_ms,
        "params": _sanitize(params),
        "error": str(error or "")[:500],
    }
    if isinstance(extra, dict):
        for k, v in extra.items():
            entry.setdefault(str(k), v if isinstance(v, (str, int, float, bool, type(None))) else str(v)[:200])
    d = _dir(home)
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{_month(entry['ts'])}.jsonl"
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    prune(home)
    return entry


def files(home=None) -> list[Path]:
    d = _dir(home)
    return sorted(d.glob("*.jsonl")) if d.is_dir() else []


def events(home=None, start: "str | None" = None, end: "str | None" = None,
           kind: "str | None" = None, limit: int = 500) -> list[dict]:
    """按时间/类型过滤；返回按时间倒序（最新在前）。"""
    out: list[dict] = []
    for f in files(home):
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    e = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                ts = str(e.get("ts") or "")
                if start and ts < start:
                    continue
                if end and ts > end:
                    continue
                if kind and e.get("kind") != kind:
                    continue
                out.append(e)
        except Exception:  # noqa: BLE001
            continue
    out.sort(key=lambda e: str(e.get("ts") or ""), reverse=True)
    return out[: max(1, int(limit))]


def clear(home=None) -> list[str]:
    removed: list[str] = []
    for f in files(home):
        try:
            f.unlink()
            removed.append(str(f))
        except Exception:  # noqa: BLE001
            pass
    return removed


def stats(home=None) -> dict:
    fs = files(home)
    total = 0
    for f in fs:
        try:
            total += f.stat().st_size
        except Exception:  # noqa: BLE001
            pass
    return {"files": len(fs), "bytes": total, "months": DEFAULT_MONTHS}

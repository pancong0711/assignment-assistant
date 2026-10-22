"""D98-B4：通用批量执行 + 执行报告（转录/评阅/playground 共用）。

职责边界：
- **只做编排**：按 items 逐条执行传入的 `worker(item) -> dict`，并发受控；
- **不构造 prompt、不调模型**（由各业务模块提供 worker）；
- 每条独立、结果独立，**单条失败只标记该条**，不中断其余（用户裁决 6）；
- 产出 `batch-report.json`，便于用户/agent 知道"发生了什么"。

报告结构（docs/51 §4.4）：
{
  "kind": "transcribe|evaluate|playground",
  "startedAt": "...", "finishedAt": "...", "ms": 1234,
  "total": 30, "ok": 28, "failed": 2, "concurrency": 3,
  "items": [{"id": "stu001", "status": "ok", "ms": 3210, "out": "...", "usage": {...}},
            {"id": "stu003", "status": "fail", "ms": 900, "error": "...", "images": [...]}]
}
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ..filelock import atomic_write_text


def run_items(items: list[dict], worker, *, kind: str, concurrency: int = 3,
              out_dir: "str | Path | None" = None, emit=None) -> dict:
    """并发执行 items，返回报告 dict（并写 `<out_dir>/batch-report.json`）。

    Args:
        items: 已规范化的 items（见 grading/items.normalize_items）；
        worker: `fn(item) -> dict`，成功应含 `{"ok": True, "out": path, **extra}`，
                失败应含 `{"ok": False, "error": str}`；可抛异常（会被捕获为该条失败）；
        kind: 报告类型标签；
        concurrency: 并发数（默认 3；command provider 建议 2）；
        out_dir: 报告落盘目录（None 则不落盘）；
        emit: 可选进度回调 `emit(line)`。
    """
    cons = max(1, int(concurrency or 3))
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    t0 = time.time()
    results: dict[int, dict] = {}

    def _one(idx: int, item: dict) -> tuple[int, dict]:
        s = time.time()
        try:
            r = worker(item) or {}
            if not isinstance(r, dict):
                r = {"ok": False, "error": f"worker 返回非法类型：{type(r).__name__}"}
        except Exception as exc:  # noqa: BLE001 —— 单条失败不阻断其余
            r = {"ok": False, "error": f"{exc.__class__.__name__}: {str(exc)[:300]}"}
        r.setdefault("ok", False)
        r["id"] = item.get("id")
        r["ms"] = int((time.time() - s) * 1000)
        r["status"] = "ok" if r.get("ok") else "fail"   # 统一状态字段（报告与调用方都用它）
        if r.get("ok") and "out" in r:
            r["out"] = str(r["out"])
        return idx, r

    with ThreadPoolExecutor(max_workers=cons) as ex:
        futs = [ex.submit(_one, i, it) for i, it in enumerate(items)]
        for fut in as_completed(futs):
            idx, r = fut.result()
            results[idx] = r
            if emit:
                tag = "OK" if r.get("ok") else "FAIL"
                emit(f"[{tag}] {r.get('id')} ({r.get('ms')}ms)"
                     + ("" if r.get("ok") else f" {r.get('error')}"))

    ordered = [results[i] for i in range(len(items))]
    ok_n = sum(1 for r in ordered if r.get("ok"))
    report = {
        "kind": str(kind),
        "startedAt": started,
        "finishedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ms": int((time.time() - t0) * 1000),
        "total": len(ordered),
        "ok": ok_n,
        "failed": len(ordered) - ok_n,
        "concurrency": cons,
        "items": ordered,
    }
    if out_dir:
        p = Path(out_dir) / "batch-report.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(p, json.dumps(report, ensure_ascii=False, indent=1))
        report["reportPath"] = str(p)
    return report


def summarize(report: dict) -> str:
    """一行摘要（供 CLI 结尾打印）。"""
    return (f"{report.get('kind')}: {report.get('ok')}/{report.get('total')} 成功，"
            f"{report.get('failed')} 失败，{report.get('ms')}ms"
            + (f"；报告 {report.get('reportPath')}" if report.get("reportPath") else ""))

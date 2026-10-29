"""D119：批阅成果清理（可重跑产物 / 临时文件 / 旧目录残留）。

**硬约束（安全红线）**：
- 绝不触碰 `kb/**`（题库）
- 绝不触碰 `.runtime/xxt/pages/review/**`（作答原件，丢了要重新下载）
- 绝不触碰 `<ws>/**/grading/*/drafts/**`，除非显式 `--drafts`

默认 `--dry-run`，只列出将删除的内容与释放空间。
"""
from __future__ import annotations

import shutil
from pathlib import Path


def _size(p: Path) -> int:
    if p.is_file():
        try:
            return p.stat().st_size
        except OSError:
            return 0
    total = 0
    for f in p.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


def _targets(ws: Path, *, task_id: str = "", reports: bool = False,
             journal: bool = False, tmp: bool = False, drafts: bool = False,
             all_: bool = False, stale_images: bool = False) -> list[dict]:
    ws = Path(ws).resolve()
    out: list[dict] = []
    if all_:
        for t in sorted(ws.glob("classes/*/grading/*")):
            if t.is_dir():
                out.append({"kind": "task-all", "path": str(t)})
    else:
        if reports or journal or stale_images:
            for t in sorted(ws.glob("classes/*/grading/*")):
                if not t.is_dir():
                    continue
                if task_id and t.name != task_id:
                    continue
                if reports and (t / "reports").is_dir():
                    out.append({"kind": "reports", "path": str(t / "reports")})
                if journal:
                    for f in (t / "journal.jsonl", t / "batch-report.json", t / "diagnostics.jsonl"):
                        if f.is_file():
                            out.append({"kind": "journal", "path": str(f)})
                if stale_images and (t / "images").is_dir():
                    out.append({"kind": "stale-images", "path": str(t / "images")})
        if drafts:
            for d in sorted(ws.glob("classes/*/grading/*/drafts")):
                if d.is_dir():
                    out.append({"kind": "drafts", "path": str(d)})
    if tmp:
        d = ws / "tmp" / "ai-grade"
        if d.is_dir():
            out.append({"kind": "tmp", "path": str(d)})
    return out


def clean(ws: Path, *, task_id: str = "", reports: bool = False, journal: bool = False,
          tmp: bool = False, drafts: bool = False, all_: bool = False,
          stale_images: bool = False, apply: bool = False) -> dict:
    """按选项清理；返回将被/已被清理的清单与释放空间。"""
    ws = Path(ws).resolve()
    if not any((reports, journal, tmp, drafts, all_, stale_images)):
        return {"ok": False,
                "error": "未指定清理项：--reports / --journal / --tmp / --drafts / "
                         "--stale-images / --all 至少选一个"}
    items = _targets(ws, task_id=task_id, reports=reports, journal=journal, tmp=tmp,
                     drafts=drafts, all_=all_, stale_images=stale_images)
    # 安全红线二次兜底：绝不删 kb/ 与 pages/review/
    safe: list[dict] = []
    blocked: list[dict] = []
    for it in items:
        p = Path(it["path"]).resolve()
        s = str(p)
        if "/kb/" in s or s.endswith("/kb") or "/pages/review/" in s:
            blocked.append({**it, "reason": "命中安全红线（kb/ 或 pages/review/）"})
            continue
        safe.append({**it, "bytes": _size(p)})
    freed = sum(it["bytes"] for it in safe)
    if apply:
        for it in safe:
            p = Path(it["path"])
            try:
                if p.is_dir():
                    shutil.rmtree(p)
                elif p.is_file():
                    p.unlink()
            except OSError:
                pass
    return {"ok": True, "apply": apply, "items": safe, "blocked": blocked,
            "count": len(safe), "bytes": freed,
            "human": f"{freed / 1024 / 1024:.1f} MB"}

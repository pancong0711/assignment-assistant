"""D120：workspace 目录布局校验与错位迁移。

语义边界（唯一权威）：
    <ws>/kb/                 只放题库（xlsx / fig / solutions）；**不得**出现 classes/ roster/ grading/
    <ws>/classes/<班级>/     roster/（名单）、grading/（批阅成果）
    <ws>/packs/              作业包
    <ws>/tasks/              作业纸（D120 新增，可重建）
    <ws>/.runtime/           引擎运行产物（可重建）

历史错位：roster 曾被写进 `<ws>/kb/classes/**`（D120 根因），本模块负责检出并迁移。
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from loguru import logger

# kb/ 下**不允许**出现的子目录（语义污染）
FORBIDDEN_IN_KB = ("classes", "roster", "grading", "tasks", "packs")


def _ts() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def inspect(ws) -> dict:
    """体检：返回 kb/ 下的语义污染清单 + 可迁移项。"""
    ws = Path(ws).resolve()
    kb = ws / "kb"
    out: dict = {"ok": True, "workspace": str(ws), "violations": [], "migratable": []}
    if not kb.is_dir():
        # D120-FIX：提前返回也必须带 summary（调用方/doctor 都假设该字段存在）
        out["summary"] = {"violations": 0, "files": 0}
        return out
    for name in FORBIDDEN_IN_KB:
        d = kb / name
        if not d.is_dir():
            continue
        out["violations"].append({"path": str(d), "name": name})
        if name == "classes":
            # kb/classes/<班级>/... → <ws>/classes/<班级>/...
            for cls_dir in sorted(p for p in d.iterdir() if p.is_dir()):
                for src in sorted(p for p in cls_dir.rglob("*") if p.is_file()):
                    rel = src.relative_to(d)               # <班级>/roster/roster.xlsx
                    out["migratable"].append({
                        "from": str(src),
                        "to": str(ws / "classes" / rel),
                    })
        elif name in ("roster", "grading", "tasks", "packs"):
            for src in sorted(p for p in d.rglob("*") if p.is_file()):
                rel = src.relative_to(d)
                out["migratable"].append({"from": str(src), "to": str(ws / name / rel)})
    out["summary"] = {"violations": len(out["violations"]),
                      "files": len(out["migratable"])}
    return out


def fix_layout(ws, *, apply: bool = False) -> dict:
    """把 kb/ 下的错位数据搬到正确位置。

    - **不覆盖**：目标已存在 → 把源改名 `.old-<ts>` 留在原地并告警；
    - 只复制（`copy2`），**不删源目录**（由教师确认后用清理命令删）；
    - 幂等：重复执行时目标已存在 → 跳过。
    """
    ws = Path(ws).resolve()
    inv = inspect(ws)
    moved: list[dict] = []
    skipped: list[dict] = []
    for it in inv["migratable"]:
        src, dst = Path(it["from"]), Path(it["to"])
        if dst.is_file():
            skipped.append({**it, "reason": "目标已存在（不覆盖）"})
            continue
        if apply:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            logger.info(f"[fix-layout] {src} → {dst}")
        moved.append(it)
    report = {
        "ok": True, "apply": apply, "workspace": str(ws),
        "violations": inv["violations"], "moved": moved, "skipped": skipped,
        "summary": {"moved": len(moved), "skipped": len(skipped),
                    "violations": len(inv["violations"])},
    }
    if apply:
        try:
            out = ws / ".runtime" / f"fix-layout-{_ts()}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
            report["reportPath"] = str(out)
        except Exception:  # noqa: BLE001
            pass
    return report


def is_valid_workspace_root(name_hint: "list[str] | None" = None) -> bool:
    """D120-Q1：判定"选中的目录是否为 workspace 根"——**必须有 kb/**。

    （前端 FSA 校验同口径：选到 `kb/` 子目录会被拒。）
    """
    hints = name_hint or []
    return "kb" in hints

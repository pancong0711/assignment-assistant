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


def fix_layout(ws, *, apply: bool = False, move: bool = False) -> dict:
    """把 kb/ 下的错位数据搬到正确位置。

    - **不覆盖**：目标已存在 → 跳过并告警；
    - 默认**只复制**（`copy2`），不删源；`move=True` 时改为**迁移后删源**（D122）；
    - 幂等：重复执行时目标已存在 → 跳过。

    `move` 的语义：复制成功后**才**删源文件；任何一步失败不删源。
    空出来的源目录由 ``clean_migrated()`` 统一回收（保持目录结构判断集中在一处）。
    """
    ws = Path(ws).resolve()
    inv = inspect(ws)
    moved: list[dict] = []
    skipped: list[dict] = []
    removed_src: list[str] = []
    for it in inv["migratable"]:
        src, dst = Path(it["from"]), Path(it["to"])
        if dst.is_file():
            skipped.append({**it, "reason": "目标已存在（不覆盖）"})
            continue
        if apply:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if move:
                # 复制成功后才删源：先 copy2（保留元数据），再删源文件
                shutil.copy2(src, dst)
                if not _same_size(src, dst):
                    skipped.append({**it, "reason": "复制后大小不一致，保留源文件"})
                    continue
                try:
                    src.unlink()
                    removed_src.append(str(src))
                except OSError as exc:
                    logger.warning(f"[fix-layout] 删源失败（已复制）：{src}: {exc}")
            else:
                shutil.copy2(src, dst)
            logger.info(f"[fix-layout] {src} → {dst}{'（已删源）' if move else ''}")
        moved.append(it)
    # D122-FIX：--move 删掉源文件后，**空目录也要回收**，否则体检仍报 violation，
    # 用户会误以为"没迁移成功"。只删空目录（rmdir 失败即跳过），不动任何有内容的目录。
    pruned_dirs: list[str] = []
    if apply and move:
        for v in inv["violations"]:
            root = Path(v["path"])
            try:
                for d in sorted((x for x in root.rglob("*") if x.is_dir()),
                                key=lambda x: len(x.parts), reverse=True):
                    if not any(d.iterdir()):
                        d.rmdir()
                        pruned_dirs.append(str(d))
                if root.is_dir() and not any(root.iterdir()):
                    root.rmdir()
                    pruned_dirs.append(str(root))
            except OSError:
                pass
    report = {
        "ok": True, "apply": apply, "move": bool(move), "workspace": str(ws),
        "violations": inv["violations"], "moved": moved, "skipped": skipped,
        "removedSrc": removed_src, "prunedDirs": pruned_dirs,
        "summary": {"moved": len(moved), "skipped": len(skipped),
                    "removedSrc": len(removed_src),
                    "prunedDirs": len(pruned_dirs),
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


def _same_size(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_size == b.stat().st_size
    except OSError:
        return False


def _file_sha(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def clean_migrated(ws, *, apply: bool = False) -> dict:
    """D122：清理「**已迁移完成**」的源文件/目录（`kb/classes/**` 等）。

    判定"可安全删"必须**同时**满足：
    1. 目标文件存在于正确位置；
    2. 且与源文件 **sha256 一致**（不是仅比大小）。

    只有全部文件都满足，才把该源目录列为可删。任何不一致 → 保留并告警。
    """
    ws = Path(ws).resolve()
    inv = inspect(ws)
    removable: list[dict] = []
    blocked: list[dict] = []

    # 按「源目录顶层」聚合：kb/classes/<批次> 等
    by_root: dict[str, list[dict]] = {}
    for it in inv["migratable"]:
        src = Path(it["from"])
        root = src.parents[2] if len(src.parents) >= 3 else src.parent
        by_root.setdefault(str(root), []).append(it)

    for root, items in sorted(by_root.items()):
        bad: list[str] = []
        for it in items:
            src, dst = Path(it["from"]), Path(it["to"])
            if not dst.is_file():
                bad.append(f"{src.name}（目标缺失）")
                continue
            if not src.is_file():
                continue                      # 源已删（之前 move 过）→ 不算问题
            if _file_sha(src) != _file_sha(dst):
                bad.append(f"{src.name}（内容不一致）")
        files = [f for f in Path(root).rglob("*") if f.is_file()] if Path(root).is_dir() else []
        entry = {"path": root, "files": len(files), "bytes": _size_dir(Path(root))}
        if bad:
            blocked.append({**entry, "reason": "；".join(bad[:5])})
        else:
            removable.append(entry)

    if apply:
        for it in removable:
            try:
                shutil.rmtree(it["path"])
                logger.info(f"[clean-migrated] 已删除已迁移源 {it['path']}")
            except OSError as exc:
                logger.warning(f"[clean-migrated] 删除失败 {it['path']}: {exc}")
    report = {
        "ok": True, "apply": apply, "workspace": str(ws),
        "removable": removable, "blocked": blocked,
        "summary": {"removable": len(removable), "blocked": len(blocked),
                    "bytes": sum(it["bytes"] for it in removable)},
    }
    return report


def _size_dir(p: Path) -> int:
    total = 0
    if not p.is_dir():
        return 0
    for f in p.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


def is_valid_workspace_root(name_hint: "list[str] | None" = None) -> bool:
    """D120-Q1：判定"选中的目录是否为 workspace 根"——**必须有 kb/**。

    （前端 FSA 校验同口径：选到 `kb/` 子目录会被拒。）
    """
    hints = name_hint or []
    return "kb" in hints

"""D119：批阅产物目录迁移（旧布局 → 新布局）+ 诊断。

旧布局（分散、口径不一）：
- 作答原件：`<xxt_home>/pages/review/<classId>/<workId>/`（xxt_home 可能是仓库 .scratch！）
- 批阅草稿：`<xxt_home>/grade-drafts/<classId>/<workId>.json`（不区分作业纸）
- AI 产物：  `<ws>/<class_dir>/grading/<taskId>/...`（已在正确位置）

新布局（L1/L2/L3）：
- 作答原件：`<ws>/.runtime/xxt/pages/review/<classId>/<workId>/`（只读、唯一真源）
- 批阅成果：`<ws>/<class_dir>/grading/<taskId>/{drafts,transcripts,evaluations,reports}/`（可写）

安全原则：**只复制不删源**；幂等；先 `--dry-run` 盘点并给出可执行命令。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from loguru import logger


def _safe(s: str) -> bool:
    import re
    return bool(re.fullmatch(r"[0-9A-Za-z\-_]{1,40}", str(s or "")))


def inventory(ws: Path, old_home: "Path | None" = None) -> dict:
    """盘点旧布局现状，返回可读清单（不含任何写操作）。"""
    from .session import xxt_home, bound_workspace
    ws = Path(ws).resolve()
    new_home = ws / ".runtime" / "xxt"
    old = Path(old_home).resolve() if old_home else xxt_home()

    report: dict = {
        "ok": True,
        "workspace": str(ws),
        "boundWorkspace": str(bound_workspace() or ""),
        "xxtHome": str(old),
        "newXxtHome": str(new_home),
        # 隐患 A：xxt_home 落在代码仓库里
        "usesRepoScratch": ".scratch" in old.parts,
        "sameHome": old == new_home,
        "reviewDirs": [],
        "legacyDrafts": [],
        "staleImagesDirs": [],
    }

    # 1) 作答原件目录
    rv = old / "pages" / "review"
    if rv.is_dir():
        for cd in sorted(p for p in rv.iterdir() if p.is_dir()):
            for wd in sorted(p for p in cd.iterdir() if p.is_dir()):
                n_img = sum(1 for f in wd.iterdir()
                            if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
                report["reviewDirs"].append({
                    "classId": cd.name, "workId": wd.name, "images": n_img,
                    "hasManifest": (wd / "students.json").is_file(),
                    "from": str(wd),
                    "to": str(new_home / "pages" / "review" / cd.name / wd.name),
                    "alreadyThere": (new_home / "pages" / "review" / cd.name / wd.name).is_dir(),
                })

    # 2) 旧草稿
    gd = old / "grade-drafts"
    if gd.is_dir():
        for cd in sorted(p for p in gd.iterdir() if p.is_dir()):
            for f in sorted(cd.glob("*.json")):
                report["legacyDrafts"].append({
                    "classId": cd.name, "workId": f.stem,
                    "from": str(f),
                    "classDir": _guess_class_dir(ws, cd.name),
                })

    # 3) 已废弃的 grading/<task>/images（D118 的 WinError 来源）
    for g in sorted(ws.glob("classes/*/grading/*/images")):
        report["staleImagesDirs"].append(str(g))

    report["summary"] = {
        "reviewDirs": len(report["reviewDirs"]),
        "legacyDrafts": len(report["legacyDrafts"]),
        "staleImagesDirs": len(report["staleImagesDirs"]),
    }
    return report


def _guess_class_dir(ws: Path, class_id: str) -> str:
    """尝试把 classId 映射到本地 class_dir（用 classmap；失败返回空）。"""
    try:
        from . import classmap
        r = classmap.resolve_class_dir(Path(ws), "", str(class_id), "")
        return str(r.get("classDir") or "")
    except Exception:  # noqa: BLE001
        return ""


def migrate(ws: Path, old_home: "Path | None" = None, *,
            apply: bool = False) -> dict:
    """执行迁移（幂等；只复制不删源）。

    返回 {ok, apply, copied:{reviewDirs,drafts}, skipped:[...], reportPath}
    """
    ws = Path(ws).resolve()
    inv = inventory(ws, old_home)
    new_home = Path(inv["newXxtHome"])
    copied_dirs: list[dict] = []
    copied_drafts: list[dict] = []
    skipped: list[dict] = []

    # 1) 作答原件
    for it in inv["reviewDirs"]:
        src, dst = Path(it["from"]), Path(it["to"])
        if src == dst:
            skipped.append({**it, "reason": "already in new layout"})
            continue
        if dst.is_dir() and any(dst.iterdir()):
            skipped.append({**it, "reason": "目标已存在（不覆盖）"})
            continue
        if apply:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst, dirs_exist_ok=True)
            logger.info(f"[migrate] 作答原件 {src} → {dst}")
        copied_dirs.append(it)

    # 2) 旧草稿 → grading/<taskId>/drafts/<workId>.json
    for it in inv["legacyDrafts"]:
        src = Path(it["from"])
        class_dir = it.get("classDir") or ""
        if not class_dir:
            skipped.append({**it, "reason": "无法映射 classId → class_dir，保留原地"})
            continue
        # 旧草稿没有 taskId 信息 → 归入 _unassigned/（明确告警，不猜）
        dst = ws / class_dir / "grading" / "_unassigned" / "drafts" / f"{it['workId']}.json"
        if dst.is_file():
            skipped.append({**it, "reason": "目标已存在（不覆盖）"})
            continue
        if apply:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            logger.info(f"[migrate] 草稿 {src} → {dst}")
        copied_drafts.append({**it, "to": str(dst)})

    report = {
        "ok": True, "apply": apply,
        "copied": {"reviewDirs": copied_dirs, "drafts": copied_drafts},
        "skipped": skipped,
        "inventory": inv,
    }
    try:
        out = new_home / "migration-report.json"
        if apply:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
            report["reportPath"] = str(out)
    except Exception:  # noqa: BLE001
        pass
    return report

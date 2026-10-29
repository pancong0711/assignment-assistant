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


def discover_old_homes(ws: Path) -> list[Path]:
    """D119-FIX：自动发现**所有可能**的旧 xxt 根。

    此前 `migrate-layout` 默认只看"当前 xxt_home()"，而 D119 之后它已指向
    `<ws>/.runtime/xxt` —— 于是**发现不了**历史数据（那些还躺在仓库 `.scratch/`
    或旧的 `find_workspace()` 目录里）。本函数把这些位置都列出来，逐个盘点。
    """
    ws = Path(ws).resolve()
    out: list[Path] = []

    def _add(p: "Path | None") -> None:
        if p is None:
            return
        try:
            rp = Path(p).expanduser().resolve()
        except Exception:  # noqa: BLE001
            return
        if rp not in out and rp != (ws / ".runtime" / "xxt"):
            out.append(rp)

    # a) 仓库 .scratch（D119 之前的开发默认）
    repo_root = Path(__file__).resolve().parents[4]
    _add(repo_root / ".scratch")
    # b) 当前 xxt_home()（可能已被 XXT_HOME 指向别处）
    try:
        from .session import xxt_home
        _add(xxt_home())
    except Exception:  # noqa: BLE001
        pass
    # c) 环境变量显式指定
    import os
    if os.environ.get("XXT_HOME"):
        _add(Path(os.environ["XXT_HOME"]))
    # d) 旧 find_workspace() 的 .runtime 与 .runtime/xxt
    try:
        from ..workspace import find_workspace
        fw = Path(find_workspace(None)).resolve()
        _add(fw / ".runtime")
        _add(fw / ".runtime" / "xxt")
    except Exception:  # noqa: BLE001
        pass
    # 只保留"确实有 review/ 或 grade-drafts/"的
    keep: list[Path] = []
    for p_ in out:
        if (p_ / "pages" / "review").is_dir() or (p_ / "grade-drafts").is_dir():
            keep.append(p_)
    return keep


def inventory(ws: Path, old_home: "Path | None" = None) -> dict:
    """盘点旧布局现状，返回可读清单（不含任何写操作）。

    `old_home` 为空时，自动发现**所有**候选旧根（见 discover_old_homes），
    而不是只看当前 xxt_home()。
    """
    from .session import xxt_home, bound_workspace
    ws = Path(ws).resolve()
    new_home = ws / ".runtime" / "xxt"
    old_homes = ([Path(old_home).resolve()] if old_home
                 else (discover_old_homes(ws) or [xxt_home()]))
    old = old_homes[0]

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

    report["oldHomes"] = [str(x) for x in old_homes]

    # 1) 作答原件目录（遍历所有候选旧根）
    for home_x in old_homes:
        rv = home_x / "pages" / "review"
        if not rv.is_dir():
            continue
        for cd in sorted(p for p in rv.iterdir() if p.is_dir()):
            for wd in sorted(p for p in cd.iterdir() if p.is_dir()):
                n_img = sum(1 for f in wd.iterdir()
                            if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
                report["reviewDirs"].append({
                    "classId": cd.name, "workId": wd.name, "images": n_img,
                    "hasManifest": (wd / "students.json").is_file(),
                    "from": str(wd), "fromHome": str(home_x),
                    "to": str(new_home / "pages" / "review" / cd.name / wd.name),
                    "alreadyThere": (new_home / "pages" / "review" / cd.name / wd.name).is_dir(),
                })

    # 2) 旧草稿（遍历所有候选旧根）
    for home_x in old_homes:
        gd = home_x / "grade-drafts"
        if not gd.is_dir():
            continue
        for cd in sorted(p for p in gd.iterdir() if p.is_dir()):
            for f in sorted(cd.glob("*.json")):
                report["legacyDrafts"].append({
                    "classId": cd.name, "workId": f.stem,
                    "from": str(f), "fromHome": str(home_x),
                    "classDir": _guess_class_dir(ws, cd.name),
                    "classDirSource": "classmap" if _guess_class_dir(ws, cd.name) else "none",
                })

    # 3) 已废弃的 grading/<task>/images（D118 的 WinError 来源）
    for g in sorted(ws.glob("classes/*/grading/*/images")):
        report["staleImagesDirs"].append(str(g))

    report["summary"] = {
        "reviewDirs": len(report["reviewDirs"]),
        "legacyDrafts": len(report["legacyDrafts"]),
        "staleImagesDirs": len(report["staleImagesDirs"]),
    }
    # 用户要求"提示迁移方法"：把盘点结果翻成可执行命令
    report["hints"] = hints(ws, report)
    return report


def _guess_class_dir(ws: Path, class_id: str) -> str:
    """尝试把 classId 映射到本地 class_dir。失败返回空。

    途径：① classmap 显式映射；② classmap 按目录名建议（suggest）；
    ③ workspace 里只有**一个** classes/* 目录时，直接用它（常见：单班教师）。
    """
    ws = Path(ws)
    try:
        from . import classmap
        r = classmap.resolve_class_dir(ws, "", str(class_id), "")
        if r.get("classDir"):
            return str(r["classDir"])
    except Exception:  # noqa: BLE001
        pass
    try:
        cands = sorted(p for p in (ws / "classes").glob("*") if p.is_dir())
        if len(cands) == 1:
            return f"classes/{cands[0].name}"
    except Exception:  # noqa: BLE001
        pass
    return ""


def hints(ws: Path, inv: dict) -> list[str]:
    """把盘点结果翻译成**可执行的下一步命令**（用户要求"提示迁移方法"）。"""
    out: list[str] = []
    pull = (inv.get("summary") or {})
    if inv.get("usesRepoScratch"):
        out.append("# ⚠ xxt 根在代码仓库，先迁移："
                   f"\nassist xxt migrate-layout -w <workspace> --old-home {inv.get('xxtHome')} --apply")
    if pull.get("reviewDirs"):
        out.append(f"# 作答原件待迁移 {pull['reviewDirs']} 组 → 追加 --apply 执行"
                   "（只复制，不删源）")
    unmapped = [d for d in (inv.get("legacyDrafts") or []) if not d.get("classDir")]
    mapped = [d for d in (inv.get("legacyDrafts") or []) if d.get("classDir")]
    if mapped:
        out.append(f"# 旧草稿 {len(mapped)} 份可自动映射 class_dir → --apply 迁入 grading/<taskId>/drafts/")
    if unmapped:
        ids = sorted({d["classId"] for d in unmapped})
        out.append(
            f"# ⚠ 旧草稿 {len(unmapped)} 份无法确定 class_dir（classId={', '.join(ids)}）。"
            f"\n#   先建立映射（学习通班级 → 本地班级目录）："
            f"\n#   assist xxt class-map --course <courseId> --class <classId> --dir classes/<班级>"
            f"\n#   然后重跑：assist xxt migrate-layout --apply")
        if not (Path(ws) / "classes").is_dir():
            out.append("#   注意：workspace 里还没有 classes/ 目录 —— 先在「班级与标签」建班并导入名单")
    if pull.get("staleImagesDirs"):
        out.append(f"# 有 {pull['staleImagesDirs']} 个已废弃的 grading/<task>/images/："
                   "\n#   assist grading clean --stale-images --apply")
    return out


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

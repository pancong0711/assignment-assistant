"""D121-G4：识别并清理「假目录」（不是班级、也不是题库的结构）。

假目录成因：
- `task["class_dir"]` 为空串 → `<ws>/grading/`（空串在 Path 拼接中塌掉）
- `class_dir` 解析不到 → 回退 `"classes"` → `<ws>/classes/grading/`

本模块只做**保守**清理：
- 默认演练；
- 逐个目录列出文件与大小；
- **含真实批阅产物**（evaluations/ transcripts/ reports/ 且非空）→ **拒绝删除**并告警。
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from loguru import logger

# 出现这些且有内容 → 视为**真实产物**，禁止自动删
REAL_ARTIFACT_DIRS = ("evaluations", "transcripts", "reports")
# 名册文件：出现即说明该目录是**真实班级**（即使名字撞上保留名，也不能删）
ROSTER_FILES = ("roster.xlsx", "roster.json", "task-package.json")


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


def _has_real_artifacts(d: Path) -> bool:
    for name in REAL_ARTIFACT_DIRS:
        sub = d / name
        if sub.is_dir() and any(f.is_file() for f in sub.rglob("*")):
            return True
    return False


def _looks_like_real_class(d: Path) -> bool:
    """D121-FIX：目录里若有 `roster/roster.xlsx` 等名册文件，视为**真实班级**。

    防的是：真实班级名字撞上保留名（如有人把班级命名为 `tasks`），
    被 clean-junk 误删。真实班级**永远不动**。
    """
    rdir = d / "roster"
    if rdir.is_dir() and any((rdir / n).is_file() for n in ROSTER_FILES):
        return True
    return any((d / n).is_file() for n in ROSTER_FILES)


def find_junk(ws) -> list[dict]:
    """找出所有假目录（返回候选清单，不删除）。"""
    ws = Path(ws).resolve()
    out: list[dict] = []

    def _add(kind: str, p: Path, reason: str) -> None:
        """登记一个假目录候选。

        D121-FIX：**必须按批次判断**，不能只看上层目录——
        `classes/grading/` 整体可能都是假的，但里面某个批次（如 `t2`）
        可能含真实 `evaluations/`。只要**任一子树**含真实产物，整棵就禁止删。
        """
        if not p.is_dir():
            return
        files = [f for f in p.rglob("*") if f.is_file()]
        real_batches = [sub.name for sub in sorted(p.iterdir())
                        if sub.is_dir() and _has_real_artifacts(sub)]
        # 真实班级（有名册）也一并识别，作为"受保护"的一种
        real_classes = [sub.name for sub in sorted(p.iterdir())
                        if sub.is_dir() and _looks_like_real_class(sub)]
        if _looks_like_real_class(p):
            real_classes = [p.name]
        out.append({
            "kind": kind, "path": str(p), "reason": reason,
            "files": len(files), "bytes": _size(p),
            "hasRealArtifacts": bool(real_batches) or bool(real_classes),
            "realArtifactBatches": real_batches,
            "realClassDirs": real_classes,
            "sample": [str(f.relative_to(p)) for f in files[:8]],
        })

    # ① 顶层 <ws>/grading/ —— 新布局永远是 classes/<班级>/grading
    _add("top-grading", ws / "grading", "顶层 grading（新布局应在 classes/<班级>/grading）")
    # ② classes/ 下的保留名目录
    for name in ("grading", "roster", "tasks", "packs", "_unassigned"):
        _add(f"classes-{name}", ws / "classes" / name,
             f"classes/{name} 是保留名，不应作为班级目录")
    return out


def clean_junk(ws, *, apply: bool = False) -> dict:
    """清理假目录（默认演练）。含真实产物的一律跳过。"""
    ws = Path(ws).resolve()
    items = find_junk(ws)
    deletable = [it for it in items if not it["hasRealArtifacts"]]
    # D121-FIX：只要子树里有真实产物就整棵保护（不做"部分删除"，避免残缺）
    protected = [it for it in items if it["hasRealArtifacts"]]
    if apply:
        for it in deletable:
            try:
                shutil.rmtree(it["path"])
                logger.info(f"[clean-junk] 已删除 {it['path']}")
            except OSError as exc:
                logger.warning(f"[clean-junk] 删除失败 {it['path']}: {exc}")
    report = {
        "ok": True, "apply": apply, "workspace": str(ws),
        "deletable": deletable, "protected": protected,
        "summary": {"deletable": len(deletable), "protected": len(protected),
                    "bytes": sum(it["bytes"] for it in deletable)},
    }
    if apply:
        try:
            out = ws / ".runtime" / f"clean-junk-{time.strftime('%Y%m%d-%H%M%S')}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
            report["reportPath"] = str(out)
        except Exception:  # noqa: BLE001
            pass
    return report

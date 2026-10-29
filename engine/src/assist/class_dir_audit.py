"""D124：班级目录命名体检（**兼容期专用**）。

背景：早期版本写回 roster 时用 `students[0].class`（点名册导入的原始班级字段，
如 `2025-化工25班`）作为目录名，而「班级与标签」里班级的**真名**是 `化工25`
→ `classes/` 下出现错误命名的目录。

判据：`classes/<目录名>/roster/roster.json` 里记录的 `className` 才是真名。
- 缺 `className`（旧数据）→ 只提示"请保存一次班级"，不误判；
- 目录名 == className → 正常；
- 不一致且目标目录不存在 → **可一键修正**（改目录名 + 同步 class_map）；
- 不一致且目标目录已存在 → **拒绝自动合并**，要求人工确认。

稳定后可整项移除（届时所有班级都从创建起正确命名）。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from loguru import logger

from .xxt.classmap import RESERVED_CLASS_DIR_NAMES, is_class_dir


def _read_meta(roster_dir: Path) -> dict:
    p = roster_dir / "roster.json"
    if not p.is_file():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return d if isinstance(d, dict) else {}


def audit(ws) -> dict:
    """扫描 classes/*，找出「目录名 != 班级名」的情况。"""
    ws = Path(ws).resolve()
    classes = ws / "classes"
    out: dict = {"ok": True, "workspace": str(ws), "ok_dirs": [], "fixable": [],
                 "conflict": [], "unknown": []}
    if not classes.is_dir():
        out["summary"] = {"ok": 0, "fixable": 0, "conflict": 0, "unknown": 0}
        return out

    for d in sorted(p for p in classes.iterdir() if p.is_dir()):
        if d.name in RESERVED_CLASS_DIR_NAMES:
            continue
        if not is_class_dir(d):
            continue
        meta = _read_meta(d / "roster")
        name = str(meta.get("className") or "").strip()
        entry = {"dir": d.name, "path": str(d), "className": name,
                 "classId": str(meta.get("classId") or "")}
        if not name:
            out["unknown"].append({**entry, "reason": "缺 className 元信息（旧数据）"})
        elif name == d.name:
            out["ok_dirs"].append(entry)
        else:
            target = classes / name
            if target.exists():
                out["conflict"].append({**entry, "target": str(target),
                                        "reason": f"目标目录已存在：classes/{name}（需人工确认）"})
            else:
                out["fixable"].append({**entry, "target": str(target),
                                       "targetRel": f"classes/{name}"})
    out["summary"] = {k: len(out[k]) for k in ("ok_dirs", "fixable", "conflict", "unknown")}
    return out


def fix(ws, *, apply: bool = False) -> dict:
    """把错名目录改成班级名；同步更新 class_map 指向。"""
    ws = Path(ws).resolve()
    rep = audit(ws)
    done: list[dict] = []
    for it in rep["fixable"]:
        src, dst = Path(it["path"]), Path(it["target"])
        if dst.exists():
            continue
        if apply:
            try:
                shutil.move(str(src), str(dst))
                logger.info(f"[class-dir-audit] {src.name} → {dst.name}")
                # 同步 class_map
                cid = it.get("classId") or ""
                if cid:
                    try:
                        from .xxt import classmap
                        cmap = classmap.read_class_map(ws)
                        changed = {k: (it["targetRel"] if v == f"classes/{it['dir']}" else v)
                                   for k, v in cmap.items()}
                        if changed != cmap:
                            classmap.write_class_map(ws, changed)
                    except Exception:  # noqa: BLE001
                        pass
            except OSError as exc:
                logger.warning(f"[class-dir-audit] 重命名失败 {src}: {exc}")
                continue
        done.append(it)
    return {"ok": True, "apply": apply, "renamed": done,
            "conflict": rep["conflict"], "unknown": rep["unknown"],
            "summary": {"renamed": len(done), "conflict": len(rep["conflict"]),
                        "unknown": len(rep["unknown"])}}

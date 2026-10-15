"""D86 §1：学习通班级 ↔ workspace 班级目录 映射（xxt.class_map）。

- 映射落 `settings.local.json → xxt.class_map: {"<courseId>:<classId>": "classes/化工25"}`；
- 自动建议按**文件名**匹配（用户拍板：roster/名单文件名比目录名更准）；
- 只解决"学习通班级 → 本地班级目录"，**与成绩源无关**：成绩单是多源共存+加权，只增不覆盖。
"""
from __future__ import annotations

import re
from pathlib import Path

ROSTER_EXTS = (".xlsx", ".xls", ".csv")


def _norm(s) -> str:
    """归一化用于匹配：去扩展名/空白/常见分隔符，保留中文与字母数字。"""
    t = str(s or "").strip()
    t = re.sub(r"\.(xlsx|xls|csv)$", "", t, flags=re.I)
    t = re.sub(r"[\s_\-+()（）\[\]【】,，、.]+", "", t)
    return t.lower()


def key_of(course_id, class_id) -> str:
    return f"{str(course_id).strip()}:{str(class_id).strip()}"


def read_class_map(ws=None) -> dict:
    from ..settings_store import read_settings
    data = read_settings(ws)
    cmap = ((data.get("xxt") or {}).get("class_map")) or {}
    return {str(k): str(v) for k, v in cmap.items()} if isinstance(cmap, dict) else {}


def write_class_map(ws, mapping: dict) -> dict:
    from ..settings_store import update_settings
    clean = {str(k): str(v) for k, v in (mapping or {}).items() if str(k).strip() and str(v).strip()}

    def _fn(data: dict) -> None:
        xxt = data.setdefault("xxt", {})
        xxt["class_map"] = clean
    update_settings(ws, _fn)
    return clean


def set_class_dir(ws, course_id, class_id, class_dir: str) -> dict:
    cmap = read_class_map(ws)
    cmap[key_of(course_id, class_id)] = str(class_dir).strip()
    return write_class_map(ws, cmap)


def class_dir_for(ws, course_id, class_id) -> str:
    return read_class_map(ws).get(key_of(course_id, class_id), "")


def list_class_candidates(ws) -> list[dict]:
    """扫描 workspace 的班级目录（classes/*）与其 roster 文件名，供匹配建议。"""
    ws = Path(ws)
    out: list[dict] = []
    classes = ws / "classes"
    if not classes.is_dir():
        return out
    for d in sorted(classes.iterdir()):
        if not d.is_dir():
            continue
        rosters: list[str] = []
        rdir = d / "roster"
        if rdir.is_dir():
            rosters = [f.name for f in sorted(rdir.iterdir())
                       if f.is_file() and f.suffix.lower() in ROSTER_EXTS]
        out.append({"classDir": f"classes/{d.name}", "dirName": d.name, "rosters": rosters})
    return out


def suggest_class_dir(ws, class_name: str, limit: int = 5) -> list[dict]:
    """按**文件名**给出候选（含相似度分数）；无命中时退回目录名比较。"""
    want = _norm(class_name)
    if not want:
        return []
    scored: list[dict] = []
    for cand in list_class_candidates(ws):
        best_file, best_score = "", 0.0
        for fn in cand["rosters"]:
            n = _norm(fn)
            if want and (want in n or n in want):
                score = min(len(want), len(n)) / max(len(want), len(n))
                if score > best_score:
                    best_file, best_score = fn, score
        if best_score == 0.0:
            n = _norm(cand["dirName"])
            if want and (want in n or n in want):
                best_score = 0.6 * min(len(want), len(n)) / max(len(want), len(n))
        if best_score > 0:
            scored.append({"classDir": cand["classDir"], "matchedFile": best_file,
                           "score": round(best_score, 3)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


def resolve_class_dir(ws, course_id, class_id, class_name: str = "",
                      auto_write: bool = False) -> dict:
    """先查映射；没有则按文件名建议（auto_write=True 时写入映射）。"""
    mapped = class_dir_for(ws, course_id, class_id)
    if mapped:
        return {"classDir": mapped, "source": "map"}
    cands = suggest_class_dir(ws, class_name)
    if not cands:
        return {"classDir": "", "source": "none", "candidates": []}
    best = cands[0]["classDir"]
    if auto_write and cands[0]["score"] >= 0.999:
        set_class_dir(ws, course_id, class_id, best)
        return {"classDir": best, "source": "auto", "candidates": cands}
    return {"classDir": best, "source": "suggest", "candidates": cands}

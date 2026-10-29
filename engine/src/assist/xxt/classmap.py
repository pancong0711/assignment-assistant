"""D86 §1：学习通班级 ↔ workspace 班级目录 映射（xxt.class_map）。

- 映射落 `settings.local.json → xxt.class_map: {"<courseId>:<classId>": "classes/化工25"}`；
- 自动建议按**文件名**匹配（用户拍板：roster/名单文件名比目录名更准）；
- 只解决"学习通班级 → 本地班级目录"，**与成绩源无关**：成绩单是多源共存+加权，只增不覆盖。
"""
from __future__ import annotations

import re
from pathlib import Path

from loguru import logger

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


def _strip_ext(name: str) -> str:
    import os as _os
    return _os.path.splitext(str(name or ""))[0]


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


# ---------------- D121：班级目录解析（不回退、自动绑定、分级报错） ----------------

# `classes/` 下这些名字是**保留名**，不是班级目录
RESERVED_CLASS_DIR_NAMES = {"grading", "roster", "tasks", "packs", "_unassigned"}


class ClassDirResolutionError(RuntimeError):
    """学习通班级 → 本地班级目录 解析失败（带可执行的下一步动作）。"""


def is_class_dir(p: "Path | str") -> bool:
    """D121-G3：判断某目录是否为**班级目录**。

    判据：是目录 + 不是保留名 + 含 `roster/` 子目录。
    （旧实现把 `classes/` 下所有子目录都当班级 → `classes/grading` 被误判为缺 roster 的班级。）
    """
    from pathlib import Path as _P
    d = _P(p)
    try:
        return (d.is_dir()
                and d.name not in RESERVED_CLASS_DIR_NAMES
                and (d / "roster").is_dir())
    except OSError:
        return False


def list_real_class_dirs(ws) -> list[str]:
    """列出真正的班级目录（相对 workspace，如 `classes/化工25`）。"""
    from pathlib import Path as _P
    root = _P(ws).resolve() / "classes"
    if not root.is_dir():
        return []
    return [f"classes/{p.name}" for p in sorted(root.iterdir()) if is_class_dir(p)]


def resolve_or_raise(ws, course_id: str, class_id: str, class_name: str = "",
                     *, auto_bind: bool = True) -> dict:
    """D121-G1/G2：解析班级目录；**绝不回退成 `"classes"`**。

    行为：
    1. 已有映射且目录存在 → 直接返回；
    2. 已有映射但目录不存在 → 抛错（提示重新关联/重新提取）；
    3. 无映射：若有**唯一精确**匹配（score>=0.999）→ 自动写入映射并返回（auto_bind）；
    4. 无映射且有多个/模糊候选 → 抛错并列出候选；
    5. 无任何候选 → 抛错并提示先建班。

    返回 `{"classDir": "classes/xxx", "source": "map|auto", ...}`。
    """
    from pathlib import Path as _P
    ws_p = _P(ws).resolve()
    cid, kid = str(course_id or ""), str(class_id or "")

    mapped = class_dir_for(ws_p, cid, kid) if cid and kid else ""
    if mapped:
        if (_P(ws_p) / mapped).is_dir():
            return {"classDir": mapped, "source": "map"}
        raise ClassDirResolutionError(
            f"学习通班级 {kid} 关联的本地目录已不存在：{mapped}。"
            f"请在「AI 辅助批阅」② 区重新选择目录并保存，"
            f"或运行 `assist xxt class-map --course {cid} --class {kid} --dir classes/<班级>`；"
            f"也可在学习通重新提取该班级。"
        )

    cands = suggest_class_dir(ws_p, class_name)
    # D121：自动绑定只认「**完全相同**」——目录名与班级名归一后相等，
    # 或 roster 文件名与班级名归一后相等。suggest_class_dir 的 score 是"相似度"，
    # 直接用它会让 classes/化工2 误绑到"化工25"（错配比未配更危险）。
    want = _norm(class_name)
    exact: list[dict] = []
    if want:
        for c in (list_class_candidates(ws_p)):
            names = [_norm(c.get("dirName") or "")] + [_norm(f) for f in c.get("rosters") or []]
            names += [_norm(_strip_ext(f)) for f in c.get("rosters") or []]
            if want in names:
                exact.append({"classDir": c["classDir"], "score": 1.0})
    if auto_bind and len(exact) == 1:
        best = exact[0]["classDir"]
        try:
            set_class_dir(ws_p, cid, kid, best)
        except Exception:  # noqa: BLE001 —— 写映射失败不影响本次解析
            pass
        logger.info(f"[D121] 自动绑定学习通班级 {kid} → {best}")
        return {"classDir": best, "source": "auto", "candidates": cands}

    real = list_real_class_dirs(ws_p)
    if not real:
        raise ClassDirResolutionError(
            f"本地没有任何班级目录，无法定位学习通班级 {kid}"
            + (f"（{class_name}）" if class_name else "")
            + "。请先在「班级与标签」建班并导入名单；"
              "或到「作业预览-学习通」重新提取该班级。"
        )
    if cands:
        names = "、".join(sorted({c["classDir"] for c in cands[:5]}))
        raise ClassDirResolutionError(
            f"学习通班级 {kid}"
            + (f"（{class_name}）" if class_name else "")
            + f" 未绑定本地班级目录。候选：{names}。"
              f"请在「AI 辅助批阅」② 区选择其一并「保存映射」，"
              f"或运行 `assist xxt class-map --course {cid} --class {kid} --dir classes/<班级>`。"
        )
    raise ClassDirResolutionError(
        f"学习通班级 {kid}"
        + (f"（{class_name}）" if class_name else "")
        + f" 未绑定，且按名称匹配不到候选（本地班级：{'、'.join(real[:5])}）。"
          f"请在「AI 辅助批阅」② 区手工选择目录并保存映射。"
    )

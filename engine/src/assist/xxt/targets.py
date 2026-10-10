"""D72 targets 模式：课程/班级勾选清单的规范化与安全校验（纯函数，可测）。"""
from __future__ import annotations

import re

# 学习通 courseId/classId 实测为纯数字串；放宽到字母数字以兼容未来形态。
TARGET_ID_RE = re.compile(r"^[0-9A-Za-z]{1,32}$")


def sanitize_targets(raw) -> "tuple[list[dict] | None, str | None]":
    """把 PWA 勾选结果规整为 `{"courses": [...]}` 可写文件的结构。

    只接受 courseId/classId/name 三个字段；任一 id 非法即整体拒绝，
    避免把任意内容写进引擎侧 targets 文件。
    返回 (targets, None) 或 (None, 错误信息)。
    """
    if not isinstance(raw, list) or not raw:
        return None, "targets 必须是非空数组"
    out: list[dict] = []
    for c in raw:
        if not isinstance(c, dict):
            return None, "targets[] 元素必须是对象"
        cid = str(c.get("courseId") or "").strip()
        if not TARGET_ID_RE.match(cid):
            return None, f"非法 courseId: {cid[:32]!r}"
        classes: list[dict] = []
        for cl in c.get("classes") or []:
            if not isinstance(cl, dict):
                return None, "classes[] 元素必须是对象"
            kid = str(cl.get("classId") or "").strip()
            if not TARGET_ID_RE.match(kid):
                return None, f"非法 classId: {kid[:32]!r}"
            classes.append({"name": str(cl.get("name") or kid)[:80], "classId": kid})
        if not classes:
            continue
        out.append({"name": str(c.get("name") or cid)[:80], "courseId": cid,
                    "classes": classes})
    if not out:
        return None, "未选择任何班级"
    return out, None


# ============ D74-3：发现快照归档 / diff / 清理（纯逻辑，不触网） ============

import datetime
import json
import re as _re
import time as _time
from pathlib import Path


def _targets_path(home=None) -> Path:
    from . import layout
    return layout.targets_json(home)


def _history_dir(home=None) -> Path:
    from . import layout
    return layout.targets_history_dir(home)


def _read_json(path: Path) -> "dict | None":
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


def load_current(home=None) -> "dict | None":
    return _read_json(_targets_path(home))


def history_files(home=None) -> list[Path]:
    """历史快照文件，按 mtime 从旧到新。"""
    d = _history_dir(home)
    if not d.is_dir():
        return []
    return sorted(d.glob("xxt-targets-*.json"), key=lambda p: p.stat().st_mtime)


def prune_history(home=None, keep: int = 5) -> list[str]:
    """只保留最近 keep 份；返回被删除的路径。"""
    files = history_files(home)
    removed: list[str] = []
    while len(files) > max(0, keep):
        f = files.pop(0)
        try:
            f.unlink()
            removed.append(str(f))
        except Exception:  # noqa: BLE001
            pass
    return removed


def archive_current(home=None, keep: int = 5) -> "Path | None":
    """把当前 targets.json 归档到 targets-history/，并按 keep 清理。"""
    cur_path = _targets_path(home)
    if not cur_path.is_file():
        return None
    data = _read_json(cur_path)
    if data is None:
        return None
    d = _history_dir(home)
    d.mkdir(parents=True, exist_ok=True)
    stamp = _re.sub(r"[^0-9A-Za-z]+", "-",
                    str(data.get("discovered_at") or _time.strftime("%Y%m%d-%H%M%S"))).strip("-")
    dest = d / f"xxt-targets-{stamp}.json"
    n = 1
    while dest.exists():
        n += 1
        dest = d / f"xxt-targets-{stamp}-{n}.json"
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    prune_history(home, keep)
    return dest


def latest_history(home=None) -> "dict | None":
    files = history_files(home)
    if not files:
        return None
    return _read_json(files[-1])


def clear_history(home=None) -> list[str]:
    """删除全部历史快照；当前 targets.json 不动。"""
    removed: list[str] = []
    for f in history_files(home):
        try:
            f.unlink()
            removed.append(str(f))
        except Exception:  # noqa: BLE001
            pass
    return removed


def age_seconds(data: "dict | None") -> "int | None":
    """discovered_at（本地时间字符串）距现在的秒数；无法解析返回 None。"""
    if not isinstance(data, dict):
        return None
    ts = str(data.get("discovered_at") or "")
    try:
        dt = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except Exception:  # noqa: BLE001
        return None
    return max(0, int(_time.time() - dt.timestamp()))


def _index(courses) -> dict:
    """展开为 key -> 元信息，key：课程 'c:<courseId>'，班级 'k:<courseId>:<classId>'。"""
    out: dict = {}
    for c in courses or []:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("courseId") or "")
        if not cid:
            continue
        cname = str(c.get("name") or cid)
        out[f"c:{cid}"] = {"kind": "course", "courseId": cid, "name": cname}
        for cl in c.get("classes") or []:
            if not isinstance(cl, dict):
                continue
            kid = str(cl.get("classId") or "")
            if not kid:
                continue
            out[f"k:{cid}:{kid}"] = {
                "kind": "class", "courseId": cid, "courseName": cname,
                "classId": kid, "name": str(cl.get("name") or kid),
            }
    return out


def compute_diff(prev: "dict | None", cur: "dict | None") -> "dict | None":
    """两两快照差异；无上一份快照时返回 None。"""
    if not isinstance(cur, dict):
        return None
    if not isinstance(prev, dict):
        return None
    a, b = _index(prev.get("courses")), _index(cur.get("courses"))
    added = [b[k] for k in sorted(set(b) - set(a))]
    removed = [a[k] for k in sorted(set(a) - set(b))]
    renamed = []
    for k in sorted(set(a) & set(b)):
        if a[k].get("name") != b[k].get("name"):
            renamed.append({**b[k], "old": a[k].get("name"), "new": b[k].get("name")})
    courses_added = [x for x in added if x["kind"] == "course"]
    courses_removed = [x for x in removed if x["kind"] == "course"]
    classes_added = [x for x in added if x["kind"] == "class"]
    classes_removed = [x for x in removed if x["kind"] == "class"]
    return {
        "against_at": prev.get("discovered_at"),
        "courses_added": courses_added,
        "courses_removed": courses_removed,
        "classes_added": classes_added,
        "classes_removed": classes_removed,
        "renamed": renamed,
        "counts": {
            "courses_added": len(courses_added),
            "courses_removed": len(courses_removed),
            "classes_added": len(classes_added),
            "classes_removed": len(classes_removed),
            "renamed": len(renamed),
        },
    }


def targets_view(home=None, keep: int = 5) -> dict:
    """GET /xxt/targets 的统一响应：当前快照 + 与上一份的 diff + 年龄/历史数。"""
    cur = load_current(home)
    if cur is None:
        return {"ok": False, "error": "no targets yet"}
    files = history_files(home)
    prev = _read_json(files[-1]) if files else None
    return {
        "ok": True,
        "discovered_at": cur.get("discovered_at"),
        "courses": cur.get("courses") or [],
        "diff": compute_diff(prev, cur),
        "age_seconds": age_seconds(cur),
        "history_count": len(files),
        "keep": keep,
    }

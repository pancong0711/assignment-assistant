"""snapshots.py — D168 §3：作业包的 roster / 作答名单快照（保证历史可复现）。

## 为什么需要

教师原话（docs/112-D168 §3.1）：
> 如果我们没有批阅完当前作业，换了一个新的作业包的作答图片，所依据的 roster 是不是也要变？
> 想批阅之前的作业时，roster 是否会切回原来的 roster？这关系到批阅依据的 tag。

代码现状（修复前）：
- 批阅时 tag 来自前端传入的 `plan`，**不是**从磁盘读；
- `pack.json` 只记 `pads[{padId, tag, questionCount}]`，**没有学生级 tag 映射**；
- roster 一改，历史批阅依据**不可复现**（`pack.json` 会被覆盖）。

## 落盘位置

    classes/<班>/roster/roster.xlsx          主名单（唯一真源，可变）
    classes/<班>/roster-tags/<packId>.json   按包快照（**本文件负责**）
    classes/<班>/grading/<packId>/submissions.json   作答名单（**本文件负责**）

## 关键决定（docs/112-D168 §3.2）

- **主键用学号**（`number`），姓名只做显示 —— 防改名/重名；
- 快照用**子目录**而非文件名后缀 —— 改包名不失效、便于列目录。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from loguru import logger

TAGS_DIR = "roster-tags"
SUBMISSIONS_FILE = "submissions.json"

SOURCE_RECOMPUTE = "recompute-tags"    # 「重算并打 tag」选了作业包 → 立即写
SOURCE_AUTO_GRADE = "auto-at-grade"    # 批阅时无快照 → 自动补写
SOURCE_MANUAL = "manual-refresh"       # 教师显式刷新


class SnapshotError(RuntimeError):
    """快照操作失败（可读业务错误）。"""


# ---------------- 路径 ----------------

def _class_root(ws, class_dir: str) -> Path:
    """classDir 归一 + 越界校验（必须在 <ws>/classes/ 之下）。"""
    from ..files.roster_io import safe_class_dir
    cd = safe_class_dir(class_dir)
    if not cd:
        raise SnapshotError(f"classDir 非法：{class_dir!r}（应形如 classes/<班级>）")
    root = Path(ws).resolve() / "classes"
    d = Path(ws).resolve() / cd
    try:
        d.resolve().relative_to(root)
    except Exception:  # noqa: BLE001
        raise SnapshotError(f"classDir 越界：{class_dir!r}") from None
    return d


def _safe_pack_id(pack_id: str) -> str:
    """包名做文件名安全化（保留中文；禁路径分隔符与 ..）。"""
    p = str(pack_id or "").strip()
    if not p or p in (".", "..") or "/" in p or "\\" in p:
        raise SnapshotError(f"packId 非法：{pack_id!r}")
    return p


def tags_snapshot_path(ws, class_dir: str, pack_id: str) -> Path:
    return _class_root(ws, class_dir) / TAGS_DIR / f"{_safe_pack_id(pack_id)}.json"


def submissions_path(ws, class_dir: str, pack_id: str) -> Path:
    return (_class_root(ws, class_dir) / "grading" / _safe_pack_id(pack_id)
            / SUBMISSIONS_FILE)


# ---------------- roster-tags 快照 ----------------

def _norm_rows(students) -> list[dict]:
    out: list[dict] = []
    for s in students or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or "").strip()
        if not name:
            continue
        out.append({
            "number": str(s.get("number") or "").strip(),
            "name": name,
            "tag": str(s.get("tag") or "").strip(),
            **({"composite": s["composite"]} if "composite" in s else {}),
        })
    return out


def write_tags_snapshot(ws, class_dir: str, pack_id: str, students,
                        *, source: str = SOURCE_RECOMPUTE,
                        force: bool = False) -> dict:
    """写/更新某作业包的「学生 → tag」快照。

    `force=False` 时**不覆盖已存在**的快照（防止批阅中途把历史依据改掉）；
    返回 {"ok", "path", "count", "created": bool, "skipped": 原因?}。
    """
    p = tags_snapshot_path(ws, class_dir, pack_id)
    rows = _norm_rows(students)
    if not rows:
        return {"ok": False, "error": "名单为空，未写快照（避免覆盖已有快照）"}
    if p.is_file() and not force:
        return {"ok": True, "path": str(p), "count": _count_of(p), "created": False,
                "skipped": "快照已存在（force=true 才覆盖）"}
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "classDir": str(class_dir).strip().strip("/"),
        "packId": str(pack_id),
        "generatedAt": _now(),
        "source": str(source or SOURCE_RECOMPUTE),
        "students": rows,
    }
    _atomic_json(p, payload)
    logger.info(f"[快照] 已写 roster-tags/{pack_id}.json（{len(rows)} 人，source={source}）")
    return {"ok": True, "path": str(p), "count": len(rows), "created": True}


def read_tags_snapshot(ws, class_dir: str, pack_id: str) -> dict:
    """读快照；不存在返回 {"ok": False, "missing": True}（不抛异常）。"""
    p = tags_snapshot_path(ws, class_dir, pack_id)
    if not p.is_file():
        return {"ok": False, "missing": True, "path": str(p)}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"快照损坏：{exc}", "path": str(p)}
    if not isinstance(data, dict):
        return {"ok": False, "error": "快照结构不合法", "path": str(p)}
    data["ok"] = True
    data["path"] = str(p)
    return data


def list_tags_snapshots(ws, class_dir: str) -> list[dict]:
    """列出该班全部包快照（供 UI 显示「哪些包已锁定」）。"""
    d = _class_root(ws, class_dir) / TAGS_DIR
    out: list[dict] = []
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            out.append({"packId": data.get("packId") or f.stem,
                        "generatedAt": data.get("generatedAt") or "",
                        "source": data.get("source") or "",
                        "count": len(data.get("students") or [])})
        except Exception:  # noqa: BLE001 —— 坏文件不影响列其它
            out.append({"packId": f.stem, "generatedAt": "", "source": "broken",
                        "count": 0})
    return out


def diff_against_roster(ws, class_dir: str, pack_id: str) -> dict:
    """快照 vs 当前 roster 的差异（供 UI 提示「roster 已变更」）。

    按**学号**比对（无学号时退化为姓名）；返回
    {"ok", "changed", "added":[{number,name}], "removed":[...], "tagChanged":[...]}。
    """
    from ..files import roster_io
    snap = read_tags_snapshot(ws, class_dir, pack_id)
    if not snap.get("ok"):
        return {"ok": False, "missing": True}
    cur = roster_io.read_roster_file(Path(ws).resolve(), class_dir)
    if not cur.get("ok"):
        return {"ok": False, "error": cur.get("error") or "读当前名单失败"}

    def key_of(s: dict) -> str:
        return str(s.get("number") or "").strip() or f"name:{s.get('name')}"

    old = {key_of(s): s for s in (snap.get("students") or [])}
    new = {key_of(s): s for s in (cur.get("students") or [])}
    added = [{"number": new[k].get("number"), "name": new[k].get("name")}
             for k in new if k not in old]
    removed = [{"number": old[k].get("number"), "name": old[k].get("name")}
               for k in old if k not in new]
    tag_changed = []
    for k in old:
        if k in new and str(old[k].get("tag") or "") != str(new[k].get("tag") or ""):
            tag_changed.append({"number": old[k].get("number"),
                                "name": old[k].get("name"),
                                "from": old[k].get("tag") or "",
                                "to": new[k].get("tag") or ""})
    changed = bool(added or removed or tag_changed)
    return {"ok": True, "changed": changed, "added": added, "removed": removed,
            "tagChanged": tag_changed}


def tag_counts(ws, class_dir: str, pack_id: str) -> dict:
    """快照里的 tag → 人数（提交率的分母）。"""
    snap = read_tags_snapshot(ws, class_dir, pack_id)
    if not snap.get("ok"):
        return {}
    out: dict[str, int] = {}
    for s in (snap.get("students") or []):
        t = str(s.get("tag") or "").strip() or "(未分tag)"
        out[t] = out.get(t, 0) + 1
    return out


# ---------------- submissions.json（作答名单） ----------------

def write_submissions(ws, class_dir: str, pack_id: str, students,
                      *, source: str = "plan",
                      unrecognized: "list[str] | None" = None) -> dict:
    """把「谁交了 + 交了几张图」落盘。

    `students` 每项：{name, number?, tag?, images:[path|name]}；
    `imageCount` 由 images 长度得出（教师 §3.4 要求"记录作答情况含图片张数"）。
    """
    p = submissions_path(ws, class_dir, pack_id)
    rows: list[dict] = []
    for s in students or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or "").strip()
        imgs = [str(x) for x in (s.get("images") or []) if str(x).strip()]
        if not name and not imgs:
            continue
        rows.append({
            "number": str(s.get("number") or "").strip(),
            "name": name,
            "tag": str(s.get("tag") or "").strip(),
            "images": imgs,
            "imageCount": len(imgs),
        })
    if not rows:
        return {"ok": False, "error": "没有可写入的作答记录（未传 students）"}
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "packId": str(pack_id),
        "generatedAt": _now(),
        "source": str(source or "plan"),
        "submitted": rows,
        "unrecognized": [str(x) for x in (unrecognized or []) if str(x).strip()],
    }
    _atomic_json(p, payload)
    logger.info(f"[作答名单] 已写 submissions.json（{len(rows)} 人，source={source}）")
    return {"ok": True, "path": str(p), "count": len(rows),
            "unrecognized": len(payload["unrecognized"])}


def read_submissions(ws, class_dir: str, pack_id: str) -> dict:
    p = submissions_path(ws, class_dir, pack_id)
    if not p.is_file():
        return {"ok": False, "missing": True, "path": str(p)}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"作答名单损坏：{exc}", "path": str(p)}
    data["ok"] = True
    data["path"] = str(p)
    return data


def submit_stats(ws, class_dir: str, pack_id: str) -> dict:
    """提交率统计（docs/112-D168 §3.5）。

    应交 = roster-tags 快照里该 tag 人数；实交 = submissions 里该 tag 人数。
    返回 {"ok", "byTag": {tag: {expected, submitted, rate}}, "total": {...}}。
    """
    expect = tag_counts(ws, class_dir, pack_id)
    sub = read_submissions(ws, class_dir, pack_id)
    if not expect:
        return {"ok": False, "error": "缺少 roster 快照（先在「重算并打 tag」关联本作业包）"}
    if not sub.get("ok"):
        return {"ok": False, "error": "缺少作答名单（submissions.json）"}
    got: dict[str, int] = {}
    for s in (sub.get("submitted") or []):
        t = str(s.get("tag") or "").strip() or "(未分tag)"
        got[t] = got.get(t, 0) + 1
    by_tag: dict[str, dict] = {}
    for t, n in sorted(expect.items()):
        m = got.get(t, 0)
        by_tag[t] = {"expected": n, "submitted": m,
                     "rate": round(m / n, 4) if n else 0.0}
    tot_e = sum(v["expected"] for v in by_tag.values())
    tot_s = sum(v["submitted"] for v in by_tag.values())
    return {"ok": True, "byTag": by_tag,
            "total": {"expected": tot_e, "submitted": tot_s,
                      "rate": round(tot_s / tot_e, 4) if tot_e else 0.0},
            "unrecognized": len(sub.get("unrecognized") or [])}


# ---------------- 内部 ----------------

def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _atomic_json(p: Path, payload: dict) -> None:
    """原子写（先写临时文件再替换，避免读到半截 JSON）。"""
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def _count_of(p: Path) -> int:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return len(d.get("students") or [])
    except Exception:  # noqa: BLE001
        return 0

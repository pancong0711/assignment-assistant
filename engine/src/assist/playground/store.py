"""D90-P1/P2：Playground 记录与文件夹（落 <ws>/playground/）。

- 记录：<ws>/playground/records/<id>.json（问题/答案/附件/provider/model/时间/mode/folder）
- 文件夹：<ws>/playground/folders.json（[名称]）；记录用 folder 字段归属（''=未归类）
设计：文件级落盘（workspace，长期维护/跨设备/去敏）；列表/移动/删除。
"""
from __future__ import annotations

import json
import re
import secrets
import time
from pathlib import Path

from loguru import logger

ROOT = "playground"
DEFAULT_FOLDER = "默认"
_ID_RE = re.compile(r"^[0-9A-Za-z\-_.]{1,80}$")
_FOLDER_RE = re.compile(r"^[^\\/:*?\"<>|]{1,60}$")


def root_dir(ws) -> Path:
    d = Path(ws).resolve() / ROOT
    d.mkdir(parents=True, exist_ok=True)
    return d


def records_dir(ws) -> Path:
    d = root_dir(ws) / "records"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _folders_file(ws) -> Path:
    return root_dir(ws) / "folders.json"


def _safe_id(rid: str) -> str:
    r = str(rid or "").strip()
    return r if r and _ID_RE.match(r) else ""


def _safe_folder(name: str) -> str:
    n = str(name or "").strip()
    if not n:
        return ""
    return n if _FOLDER_RE.match(n) else ""


def new_id() -> str:
    """唯一 id：时间戳 + 4 位随机（避免并发/同秒下的碰撞）。"""
    return (time.strftime("%Y%m%d-%H%M%S") + "-"
            + format(int(time.time() * 1000) % 10000, "04d")
            + secrets.token_hex(2))


# ---------------- 文件夹 ----------------

def list_folders(ws) -> list[str]:
    f = _folders_file(ws)
    if not f.is_file():
        return [DEFAULT_FOLDER]
    try:
        arr = json.loads(f.read_text(encoding="utf-8"))
        out = [str(x) for x in arr if str(x).strip()]
        return out or [DEFAULT_FOLDER]
    except Exception:  # noqa: BLE001
        return [DEFAULT_FOLDER]


def _write_folders(ws, names: list[str]) -> None:
    uniq: list[str] = []
    for n in names:
        n2 = _safe_folder(n)
        if n2 and n2 not in uniq:
            uniq.append(n2)
    if DEFAULT_FOLDER not in uniq:
        uniq.insert(0, DEFAULT_FOLDER)
    _folders_file(ws).write_text(json.dumps(uniq, ensure_ascii=False, indent=1), encoding="utf-8")


def add_folder(ws, name: str) -> dict:
    n = _safe_folder(name)
    if not n:
        return {"ok": False, "error": "文件夹名非法（1..60 字符，不含路径分隔符）"}
    names = list_folders(ws)
    if n not in names:
        names.append(n)
        _write_folders(ws, names)
    return {"ok": True, "folders": list_folders(ws)}


def delete_folder(ws, name: str) -> dict:
    n = _safe_folder(name)
    if n == DEFAULT_FOLDER:
        return {"ok": False, "error": "默认文件夹不可删除"}
    names = [x for x in list_folders(ws) if x != n]
    _write_folders(ws, names)
    # 该夹内记录移回默认
    for rec in list_records(ws):
        if rec.get("folder") == n:
            rec["folder"] = DEFAULT_FOLDER
            save_record(ws, rec)
    return {"ok": True, "folders": list_folders(ws)}


def rename_folder(ws, old: str, new: str) -> dict:
    o, nw = _safe_folder(old), _safe_folder(new)
    if not (o and nw) or o == DEFAULT_FOLDER:
        return {"ok": False, "error": "文件夹名非法/默认夹不可改名"}
    names = [nw if x == o else x for x in list_folders(ws)]
    _write_folders(ws, names)
    for rec in list_records(ws):
        if rec.get("folder") == o:
            rec["folder"] = nw
            save_record(ws, rec)
    return {"ok": True, "folders": list_folders(ws)}


# ---------------- 记录 ----------------

def list_records(ws) -> list[dict]:
    out: list[dict] = []
    for f in sorted(records_dir(ws).glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(d, dict):
            d.setdefault("id", f.stem)
            out.append(d)
    out.sort(key=lambda r: str(r.get("at") or ""), reverse=True)
    return out


def read_record(ws, rid: str) -> "dict | None":
    sid = _safe_id(rid)
    if not sid:
        return None
    p = records_dir(ws) / f"{sid}.json"
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except Exception:  # noqa: BLE001
        return None


def save_record(ws, rec: dict) -> dict:
    rid = _safe_id(str(rec.get("id") or "")) or new_id()
    payload = dict(rec or {})
    payload["id"] = rid
    payload.setdefault("folder", DEFAULT_FOLDER)
    payload.setdefault("at", time.strftime("%Y-%m-%d %H:%M:%S"))
    (records_dir(ws) / f"{rid}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "record": payload}


def delete_record(ws, rid: str) -> dict:
    p = records_dir(ws) / f"{_safe_id(rid)}.json"
    if not p.is_file():
        return {"ok": False, "error": f"记录不存在：{rid}"}
    p.unlink()
    return {"ok": True, "deleted": rid}


def move_records(ws, ids: list[str], folder: str) -> dict:
    f = _safe_folder(folder) or DEFAULT_FOLDER
    n = 0
    for rid in ids or []:
        rec = read_record(ws, rid)
        if not rec:
            continue
        rec["folder"] = f
        save_record(ws, rec)
        n += 1
    return {"ok": True, "moved": n, "folder": f}

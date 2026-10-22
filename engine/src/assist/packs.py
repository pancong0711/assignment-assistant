"""D89-N1：作业包（pack）读写 —— <ws>/packs/<id>.pack.json。

概念（用户拍板）：作业包 = 一次分层作业**全部作业纸的集合**；每张作业纸对应一个 tag/类型；
包**引用** padId（作业纸是唯一真源，包只做组织）；纯设计态（不含发布信息）。

schema（docs/42-D89 §4.1）：
    { id, name, term, class_dir, pads:[{padId, tag}], note, updatedAt, schema:1 }

设计：落盘 workspace（与 kb/assets 一致，便于长期维护/跨设备/去敏）；文件级增删改；
引用悬空（padId 在当前作业纸库找不到）由调用方（PWA）提示，此处只做结构校验。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from loguru import logger

SCHEMA = 1
_ID_RE = re.compile(r"^[^\\/:*?\"<>|]{1,80}$")
PACKS_DIR = "packs"


def packs_dir(ws) -> Path:
    d = Path(ws).resolve() / PACKS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_id(pid: str) -> str:
    p = str(pid or "").strip()
    if not p or p.strip(".") == "" or not _ID_RE.match(p):
        return ""
    return p


def _path(ws, pid: str) -> "Path | None":
    sid = _safe_id(pid)
    return packs_dir(ws) / f"{sid}.pack.json" if sid else None


def _norm_pads(raw) -> list[dict]:
    out: list[dict] = []
    for it in (raw or []):
        if not isinstance(it, dict):
            continue
        pad_id = str(it.get("padId") or it.get("id") or "").strip()
        if not pad_id:
            continue
        out.append({"padId": pad_id, "tag": str(it.get("tag") or "")})
    return out


def list_packs(ws) -> list[dict]:
    out: list[dict] = []
    for f in sorted(packs_dir(ws).glob("*.pack.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(d, dict):
            d.setdefault("id", f.name[: -len(".pack.json")])
            d.setdefault("pads", [])
            out.append(d)
    return out


def read_pack(ws, pid: str) -> "dict | None":
    p = _path(ws, pid)
    if not p or not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except Exception:  # noqa: BLE001
        return None


def save_pack(ws, pid: str, data: dict) -> dict:
    p = _path(ws, pid)
    if not p:
        return {"ok": False, "error": "作业包 id 非法（1..80 字符，不含路径分隔符）"}
    # 边界：--id 与文件内 id 不一致时拒绝（否则会出现「文件 A 里写着 id B」的自相矛盾包）。
    inner_id = str((data or {}).get("id") or "").strip()
    if inner_id and inner_id != str(pid):
        return {"ok": False,
                "error": f"作业包 id 冲突：--id={pid} 与文件内 id={inner_id} 不一致"}
    payload = {
        "schema": SCHEMA,
        "id": str(pid),
        "name": str((data or {}).get("name") or pid).strip() or str(pid),
        "term": str((data or {}).get("term") or ""),
        "class_dir": str((data or {}).get("class_dir") or ""),
        "pads": _norm_pads((data or {}).get("pads")),
        "note": str((data or {}).get("note") or ""),
        "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    from .filelock import atomic_write_text
    atomic_write_text(p, json.dumps(payload, ensure_ascii=False, indent=1))
    return {"ok": True, "pack": payload, "file": str(p)}


def delete_pack(ws, pid: str) -> dict:
    p = _path(ws, pid)
    if not p or not p.is_file():
        return {"ok": False, "error": f"作业包不存在：{pid}"}
    p.unlink()
    return {"ok": True, "deleted": str(pid)}


def rename_pack(ws, old: str, new: str) -> dict:
    src = _path(ws, old)
    if not src or not src.is_file():
        return {"ok": False, "error": f"作业包不存在：{old}"}
    d = read_pack(ws, old) or {}
    d["id"] = str(new)
    res = save_pack(ws, new, d)
    if res.get("ok"):
        src.unlink()
    return res

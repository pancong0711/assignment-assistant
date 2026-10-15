"""D85 §3：本地批阅草稿（人工批阅栏的本地保存）。

存储：`<xxt_home>/grade-drafts/<classId>/<workId>.json`
结构：`{ "<学生key>": {"score": 88, "comment": "文字", "images": [{"name","data_b64"}],
                      "updatedAt": "2026-10-15 15:00:00"} }`
学生 key：`workAnswerId` 优先，回落姓名（与批阅清单同口径；两者都可作为查询键）。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

_SAFE = re.compile(r"[0-9A-Za-z\-_]{1,40}")


def drafts_root(home=None) -> Path:
    if home is None:
        from .session import xxt_home
        home = xxt_home()
    d = Path(home) / "grade-drafts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def draft_file(home, class_id: str, work_id: str) -> "Path | None":
    if not _SAFE.fullmatch(str(class_id)) or not _SAFE.fullmatch(str(work_id)):
        return None
    d = drafts_root(home) / str(class_id)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{work_id}.json"


def read_drafts(home, class_id: str, work_id: str) -> dict:
    p = draft_file(home, class_id, work_id)
    if p is None or not p.is_file():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_draft(home, class_id: str, work_id: str, key: str, *,
               score=None, comment: str = "", comment_text: str = "",
               images: "list[dict] | None" = None, extra: "dict | None" = None) -> dict:
    """写单个学生的本地批阅草稿（合并式更新；score=None 表示不改分数）。"""
    p = draft_file(home, class_id, work_id)
    if p is None:
        return {"ok": False, "error": "非法 classId/workId"}
    k = str(key or "").strip()
    if not k:
        return {"ok": False, "error": "缺少学生 key（workAnswerId 或姓名）"}
    data = read_drafts(home, class_id, work_id)
    cur = data.get(k) if isinstance(data.get(k), dict) else {}
    if score is not None:
        try:
            cur["score"] = float(score)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"分数非法：{score}"}
    if comment:
        cur["comment"] = str(comment)
    if comment_text:
        cur["comment_text"] = str(comment_text)
    if images is not None:
        cur["images"] = [{"name": str(i.get("name") or ""), "data_b64": str(i.get("data_b64") or "")}
                         for i in images if isinstance(i, dict)]
    if extra:
        for kk, vv in extra.items():
            cur[str(kk)] = vv
    cur["updatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
    data[k] = cur
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "key": k, "draft": cur, "file": str(p)}


def delete_draft(home, class_id: str, work_id: str, key: str) -> dict:
    p = draft_file(home, class_id, work_id)
    if p is None or not p.is_file():
        return {"ok": False, "error": "无草稿文件"}
    data = read_drafts(home, class_id, work_id)
    if str(key) not in data:
        return {"ok": False, "error": f"草稿不存在：{key}"}
    data.pop(str(key), None)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "key": str(key)}


def student_key(student: dict) -> str:
    """草稿键：workAnswerId 优先，回落姓名（与批阅清单一致）。"""
    wa = str((student or {}).get("workAnswerId") or "").strip()
    return wa or str((student or {}).get("name") or "").strip()

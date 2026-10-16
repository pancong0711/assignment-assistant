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


def normalize_draft(d: dict) -> dict:
    """D92-R2：把草稿归一为**双套**结构 {ai, human, humanMode, revision, revised}。

    兼容旧单套 {score, comment, comment_text, images, source}：
    source 以 'human' 开头 → 视作人工套，humanMode='replace'；否则视作 ai 套。
    """
    d = d if isinstance(d, dict) else {}
    if isinstance(d.get("ai"), dict) or isinstance(d.get("human"), dict):
        out = dict(d)
        out.setdefault("ai", d.get("ai") if isinstance(d.get("ai"), dict) else {})
        out.setdefault("human", d.get("human") if isinstance(d.get("human"), dict) else {})
        out.setdefault("humanMode", d.get("humanMode") or "none")
        out.setdefault("revision", d.get("revision") if isinstance(d.get("revision"), dict) else {})
        out["revised"] = _is_revised(out)
        return out
    # 旧单套
    src = str(d.get("source") or "")
    payload = {"score": d.get("score"), "comment": d.get("comment") or "",
               "comment_text": d.get("comment_text") or "", "images": d.get("images") or []}
    out = {"ai": {}, "human": {}, "humanMode": "none", "revision": {},
           "student": d.get("student") or "", "tag": d.get("tag") or "",
           "updatedAt": d.get("updatedAt") or ""}
    if src.startswith("human"):
        out["human"] = {**payload, "used": True}
        out["ai"] = {}
        out["humanMode"] = "replace"
    else:
        out["ai"] = payload
    out["source"] = src
    out["revised"] = _is_revised(out)
    return out


def _is_revised(out: dict) -> bool:
    rev = out.get("revision") or {}
    text = str(rev.get("text") or "").strip()
    ai_comment = str((out.get("ai") or {}).get("comment") or "").strip()
    return bool(text) and text != ai_comment


def save_draft_sets(home, class_id: str, work_id: str, key: str, *,
                    ai: "dict | None" = None, human: "dict | None" = None,
                    human_mode: "str | None" = None, revision: "dict | None" = None,
                    student: str = "", tag: str = "") -> dict:
    """D92-R2：写双套草稿（ai/human 各自合并；human_mode 可选；revision 可选）。"""
    p = draft_file(home, class_id, work_id)
    if p is None:
        return {"ok": False, "error": "非法 classId/workId"}
    k = str(key or "").strip()
    if not k:
        return {"ok": False, "error": "缺少学生 key"}
    data = read_drafts(home, class_id, work_id)
    cur = normalize_draft(data.get(k) if isinstance(data.get(k), dict) else {})
    if ai is not None:
        cur["ai"] = {**(cur.get("ai") or {}), **{kk: vv for kk, vv in ai.items() if vv is not None}}
    if human is not None:
        cur["human"] = {**(cur.get("human") or {}), **{kk: vv for kk, vv in human.items() if vv is not None}}
        if human:
            cur["human"]["used"] = True
    if human_mode is not None:
        cur["humanMode"] = str(human_mode or "none")
    if revision is not None:
        cur["revision"] = {**(cur.get("revision") or {}), **revision}
        cur["revision"].setdefault("at", time.strftime("%Y-%m-%d %H:%M:%S"))
    if student:
        cur["student"] = student
    if tag:
        cur["tag"] = tag
    cur["revised"] = _is_revised(cur)
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

"""D79-C：可配置写操作白名单（workspace/settings.local.json）。"""
from __future__ import annotations

import json
from pathlib import Path


def workspace(ws=None) -> Path:
    if ws is not None:
        return Path(ws).resolve()
    try:
        from ..workspace import find_workspace
        return Path(find_workspace(None)).resolve()
    except Exception:
        return Path.cwd().resolve()


def _settings_path(ws=None) -> Path:
    return workspace(ws) / "settings.local.json"


def _read_settings(ws=None) -> dict:
    p = _settings_path(ws)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def read_allowlist(ws=None) -> list[dict]:
    data = _read_settings(ws)
    xxt = data.get("xxt") or {}
    raw = xxt.get("write_allowlist") or []
    out = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        cid = str(it.get("courseId") or "").strip()
        kid = str(it.get("classId") or "").strip()
        if cid and kid:
            out.append({"courseId": cid, "classId": kid, "name": str(it.get("name") or "")})
    return out


def write_allowlist(ws, items: list[dict]) -> list[dict]:
    p = _settings_path(ws)
    data = _read_settings(ws)
    xxt = data.setdefault("xxt", {})
    clean = []
    seen = set()
    for it in items or []:
        cid = str((it or {}).get("courseId") or "").strip()
        kid = str((it or {}).get("classId") or "").strip()
        if not cid or not kid or (cid, kid) in seen:
            continue
        seen.add((cid, kid))
        clean.append({"courseId": cid, "classId": kid, "name": str((it or {}).get("name") or "")})
    xxt["write_allowlist"] = clean
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return clean


def is_allowed(course_id: str, class_id: str, ws=None) -> bool:
    for it in read_allowlist(ws):
        if str(it.get("courseId")) == str(course_id) and str(it.get("classId")) == str(class_id):
            return True
    return False


def work_folder_defaults(ws=None) -> dict:
    data = _read_settings(ws)
    xxt = data.get("xxt") or {}
    raw = xxt.get("work_folders") or {}
    return {str(k): v for k, v in raw.items()} if isinstance(raw, dict) else {}


def set_work_folder_default(ws, course_id: str, directory_id: str, name: str = "") -> dict:
    p = _settings_path(ws)
    data = _read_settings(ws)
    xxt = data.setdefault("xxt", {})
    folders = xxt.setdefault("work_folders", {})
    folders[str(course_id)] = {"directoryId": str(directory_id), "name": str(name)}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return folders[str(course_id)]

# D99：默认白名单扩充 xls/xlsx（2026-10-22 真机矩阵验证：xlsx 与 pdf/docx 同为
# `editor-iframe` 云附件，平台侧无格式限制）。其余 ppt/pptx/zip/txt 走 PWA 勾选扩展。
DEFAULT_NOTICE_ATTACHMENT_EXTS = ["pdf", "doc", "docx", "xls", "xlsx",
                                  "jpg", "jpeg", "png", "webp", "gif"]


def normalize_exts(raw) -> list[str]:
    out: list[str] = []
    for x in raw or []:
        e = str(x or "").strip().lower().lstrip(".")
        if e and e not in out:
            out.append(e)
    return out


def read_notice_attachment_exts(ws=None) -> list[str]:
    data = _read_settings(ws)
    xxt = data.get("xxt") or {}
    raw = xxt.get("notice_attachment_exts")
    if not isinstance(raw, list):
        return list(DEFAULT_NOTICE_ATTACHMENT_EXTS)
    return normalize_exts(raw)


def write_notice_attachment_exts(ws, exts) -> list[str]:
    p = _settings_path(ws)
    data = _read_settings(ws)
    xxt = data.setdefault("xxt", {})
    clean = normalize_exts(exts)
    xxt["notice_attachment_exts"] = clean
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return clean


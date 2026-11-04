"""work.py — D164：Atopia 工作区（`<ws>/atopia/work/<特征名>/`）。

教师诉求：把授课计划/PPT 交给 Atopia → Atopia 解析成 JSON → 教师确认后
「复制到课堂资料」。

**三层目录，各管各的**：
    <ws>/materials/<特征名>/_source/   教师原件（AI 只读，D131 硬规则 1 不变）
    <ws>/atopia/work/<特征名>/_upload/ 教师交给 Atopia 的临时文件
    <ws>/atopia/work/<特征名>/_parsed/ Atopia 解析产物（json + md）
    <ws>/atopia/work/<特征名>/manifest.json

**为什么不让 Atopia 直接写 materials/**：`_source/` 是唯一真源且 AI 永不可写；
破了这条就没有"未被 AI 改过的原件"了。
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from pathlib import Path

from loguru import logger

WORK = "work"
UPLOAD = "_upload"
PARSED = "_parsed"
MANIFEST = "manifest.json"

# 与 materials 上传同一套白名单
UPLOAD_EXTS = {".pptx", ".ppt", ".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg",
               ".md", ".txt", ".markdown"}
MAX_BYTES = 20 * 1024 * 1024


class WorkError(RuntimeError):
    """Atopia 工作区操作失败（可读业务错误）。"""


def work_root(ws) -> Path:
    return Path(ws).resolve() / "atopia" / WORK


def feature_dir(ws, feature: str) -> Path:
    name = str(feature or "").strip().strip("/")
    if not name:
        raise WorkError("特征名不能为空（如 26C1）")
    if name in (".", "..") or "/" in name or "\\" in name:
        raise WorkError(f"特征名非法：{feature!r}")
    return work_root(ws) / name


def ensure_feature(ws, feature: str) -> Path:
    d = feature_dir(ws, feature)
    (d / UPLOAD).mkdir(parents=True, exist_ok=True)
    (d / PARSED).mkdir(parents=True, exist_ok=True)
    return d


def list_features(ws) -> list[str]:
    root = work_root(ws)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir()
                  if p.is_dir() and (p / UPLOAD).is_dir())


def _manifest(ws, feature: str) -> dict:
    p = feature_dir(ws, feature) / MANIFEST
    if not p.is_file():
        return {"feature": feature, "files": [], "parsed": []}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {"feature": feature, "files": [], "parsed": []}
    except Exception:  # noqa: BLE001
        return {"feature": feature, "files": [], "parsed": []}


def _save_manifest(ws, feature: str, data: dict) -> None:
    d = ensure_feature(ws, feature)
    (d / MANIFEST).write_text(json.dumps(data, ensure_ascii=False, indent=1),
                              encoding="utf-8")


def save_uploads(ws, feature: str, items: "list[dict]") -> dict:
    """把教师上传的文件落到 `atopia/work/<特征名>/_upload/`（同名不覆盖）。"""
    d = ensure_feature(ws, feature)
    up = d / UPLOAD
    saved: list[dict] = []
    skipped: list[dict] = []
    man = _manifest(ws, feature)
    for it in (items or [])[:20]:
        raw_name = str((it or {}).get("name") or "").strip()
        name = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._()（）+\- ]", "_",
                      Path(raw_name).name)[:120].strip()
        if not name or name in (".", ".."):
            skipped.append({"name": raw_name, "reason": "文件名非法"})
            continue
        ext = Path(name).suffix.lower()
        if ext not in UPLOAD_EXTS:
            skipped.append({"name": name, "reason": f"扩展名 {ext or '(无)'} 不允许"})
            continue
        b64 = str((it or {}).get("data_b64") or "")
        if not b64:
            skipped.append({"name": name, "reason": "缺少文件内容"})
            continue
        try:
            blob = base64.b64decode(b64, validate=False)
        except Exception as exc:  # noqa: BLE001
            skipped.append({"name": name, "reason": f"base64 解码失败：{exc}"})
            continue
        if len(blob) > MAX_BYTES:
            skipped.append({"name": name, "reason": "超过 20MB"})
            continue
        dest = up / name
        n = 2
        while dest.exists():
            dest = up / f"{Path(name).stem}-{n}{Path(name).suffix}"
            n += 1
        dest.write_bytes(blob)
        saved.append({"name": dest.name, "bytes": len(blob),
                      "sha256": hashlib.sha256(blob).hexdigest()})
    if saved:
        man.setdefault("files", []).extend(
            {**s, "at": time.strftime("%Y-%m-%d %H:%M:%S")} for s in saved)
        _save_manifest(ws, feature, man)
    return {"ok": True, "feature": feature, "saved": saved, "skipped": skipped,
            "dir": str(up)}


def files_of(ws, feature: str) -> list[dict]:
    """列出 `_upload/` 与 `_parsed/` 里的文件。"""
    d = feature_dir(ws, feature)
    out: list[dict] = []
    for label in (UPLOAD, PARSED):
        base = d / label
        if not base.is_dir():
            continue
        for p in sorted((x for x in base.rglob("*") if x.is_file()), key=str):
            try:
                st = p.stat()
            except OSError:
                continue
            out.append({"file": str(p.relative_to(d)).replace("\\", "/"),
                        "name": p.name, "dir": label, "bytes": st.st_size,
                        "mtime": time.strftime("%Y-%m-%d %H:%M:%S",
                                               time.localtime(st.st_mtime))})
    return out


def read_upload_text(ws, feature: str, *, max_chars: int = 60000) -> dict:
    """读 `_upload/` 里**纯文本类**文件的内容（md/txt）。

    PPT/PDF 需先经 `materials.extract` 抽取（见 CLI `materials extract`），
    本函数只负责把已抽好的文本读出来给 AI。
    """
    d = feature_dir(ws, feature)
    up = d / UPLOAD
    parts: list[str] = []
    used: list[str] = []
    if up.is_dir():
        for p in sorted(up.rglob("*")):
            if not p.is_file():
                continue
            if p.suffix.lower() not in (".md", ".txt", ".markdown"):
                continue
            try:
                txt = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            parts.append(f"### {p.name}\n{txt}")
            used.append(p.name)
    text = "\n\n".join(parts)
    truncated = len(text) > max_chars
    return {"ok": True, "feature": feature, "text": text[:max_chars],
            "files": used, "truncated": truncated, "chars": len(text)}


def save_parsed(ws, feature: str, data: dict, *, name: str = "") -> dict:
    """保存解析产物到 `_parsed/`（json + 人可读 md）。"""
    d = ensure_feature(ws, feature)
    fn = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]", "_", name or f"{feature}.json")
    if not fn.endswith(".json"):
        fn += ".json"
    p = d / PARSED / fn
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    man = _manifest(ws, feature)
    man.setdefault("parsed", []).append(
        {"file": fn, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    _save_manifest(ws, feature, man)
    return {"ok": True, "file": str(p.relative_to(d)).replace("\\", "/"),
            "path": str(p)}


def read_parsed(ws, feature: str, name: str) -> dict:
    d = feature_dir(ws, feature)
    p = d / PARSED / Path(str(name)).name
    if not p.is_file():
        raise WorkError(f"解析文件不存在：{name}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise WorkError(f"解析文件损坏：{exc}") from None

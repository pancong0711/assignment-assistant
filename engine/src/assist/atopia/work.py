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


# ============================================================================
# D168-B4：一键解析（工步 0 抽取 → 工步 1 AI 结构化 → 工步 2 教师确认复制）
# ============================================================================

EXTRACTED = "_extracted"     # 工步 0 产物：抽取出的纯文本（**免费**）


def _extract_dir(ws, feature: str) -> Path:
    d = ensure_feature(ws, feature)
    p = d / PARSED / EXTRACTED
    p.mkdir(parents=True, exist_ok=True)
    return p


def extract_uploads(ws, feature: str, *, force: bool = False) -> dict:
    """**工步 0**：把 `_upload/` 里的文档抽成纯文本（确定性，**不花模型钱**）。

    分工（docs/113-D169 §3.2）：
    - PPT/Word → `materials.extract_office`（officecli，回退 soffice）
    - PDF      → `materials.extract_pdf_text`；无文字时 `pdf_to_images` 出页图
    - md/txt   → 直接读
    - 图片     → 记为"需 vision"（工步 1 走多模态）

    产物落 `_parsed/_extracted/<stem>.text.txt`，并返回清单供工步 1 使用。
    """
    from ..files import materials as M

    d = ensure_feature(ws, feature)
    up = d / UPLOAD
    ex = _extract_dir(ws, feature)
    out: list[dict] = []
    errors: list[dict] = []
    if not up.is_dir():
        return {"ok": False, "error": f"没有上传目录：{up}", "files": []}

    for p in sorted(x for x in up.rglob("*") if x.is_file()):
        ext = p.suffix.lower()
        stem = p.stem
        tf = ex / f"{stem}.text.txt"
        try:
            if ext in (".md", ".txt", ".markdown"):
                txt = p.read_text(encoding="utf-8", errors="replace")
                tf.write_text(txt, encoding="utf-8")
                out.append({"file": p.name, "kind": "text", "chars": len(txt),
                            "text_file": str(tf), "images": []})
            elif ext in (".pptx", ".docx", ".xlsx", ".ppt", ".doc", ".xls"):
                rep = M.extract_office(p, tf)
                out.append({"file": p.name, "kind": "office",
                            "chars": int(rep.get("chars") or 0),
                            "slides": rep.get("slides"),
                            "text_file": str(tf), "images": [],
                            "engine": rep.get("engine")})
            elif ext == ".pdf":
                t = M.extract_pdf_text(p, out_dir=ex)
                chars = int(t.get("chars") or 0)
                imgs: list[str] = []
                if chars < 200:          # 扫描件/纯图 PDF：出页图走 vision
                    rep = M.pdf_to_images(p, ex / f"{stem}.pages")
                    imgs = [str(x) for x in (rep.get("images") or [])]
                out.append({"file": p.name, "kind": "pdf", "chars": chars,
                            "text_file": t.get("text_file") or "", "images": imgs,
                            "engine": t.get("engine")})
            elif ext in (".png", ".jpg", ".jpeg"):
                out.append({"file": p.name, "kind": "image", "chars": 0,
                            "text_file": "", "images": [str(p)]})
            else:
                errors.append({"file": p.name, "error": f"不支持的扩展名 {ext}"})
        except Exception as exc:  # noqa: BLE001 —— 单文件失败不影响其它
            errors.append({"file": p.name, "error": f"{type(exc).__name__}: {str(exc)[:200]}"})

    man = _manifest(ws, feature)
    man["extracted"] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "files": out}
    _save_manifest(ws, feature, man)
    total = sum(int(f.get("chars") or 0) for f in out)
    return {"ok": not errors, "feature": feature, "files": out, "errors": errors,
            "chars": total, "dir": str(ex),
            "needVision": [f for f in out if f.get("images")]}


def read_extracted_text(ws, feature: str, *, max_chars: int = 120000) -> dict:
    """读工步 0 的抽取文本（供工步 1 拼 prompt）。"""
    ex = _extract_dir(ws, feature)
    parts: list[str] = []
    used: list[str] = []
    for f in sorted(ex.glob("*.text.txt")):
        try:
            txt = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if txt.strip():
            parts.append(f"===== {f.name.replace('.text.txt', '')} =====\n{txt}")
            used.append(f.name)
    text = "\n\n".join(parts)
    truncated = len(text) > max_chars
    return {"ok": True, "text": text[:max_chars], "chars": len(text),
            "files": used, "truncated": truncated}


def collect_vision_images(ws, feature: str, *, max_images: int = 20) -> list[str]:
    """工步 0 里需要"看图"的图片（扫描 PDF 页图 + 直接上传的图片）。"""
    man = _manifest(ws, feature)
    imgs: list[str] = []
    for f in ((man.get("extracted") or {}).get("files") or []):
        for x in (f.get("images") or []):
            if Path(x).is_file():
                imgs.append(x)
    return imgs[:max_images]


def save_parsed_result(ws, feature: str, data: dict, *, name: str = "") -> dict:
    """工步 1 产物落 `_parsed/<名称>.json`（**只是建议**，进 materials 仍需教师确认）。"""
    res = save_parsed(ws, feature, data, name=name or f"{feature}.json")
    man = _manifest(ws, feature)
    man.setdefault("parsedMeta", []).append(
        {"file": res.get("file"), "at": time.strftime("%Y-%m-%d %H:%M:%S"),
         "counts": {k: len(v) if isinstance(v, list) else 1
                    for k, v in (data or {}).items()}})
    _save_manifest(ws, feature, man)
    return res


# 内置任务 → 期望的输出键（用于取"主要数组"）
_TASK_PRIMARY_KEY = {
    "knowledge-outline": "knowledge",
    "chapter-tag": "tags",
    "example-extract": "examples",
}


def parse_with_task(client, ws, feature: str, *, task_id: str = "",
                    model: "str | None" = None, max_chars: int = 120000,
                    extra_context: str = "") -> dict:
    """**工步 1**：用某个 `atopia-task` 模板把抽取文本交给模型，产出结构化 JSON。

    - 不传 `task_id` → 用该类的**默认模板**；默认模板 `text` 为空 → 报错（无内置任务可用）；
    - 文本为空但有待看图 → 走多模态（扫描件/照片）；
    - 产物只落 `_parsed/`，**绝不**直接写 `materials/`（D131 硬规则）。
    """
    from ..files import prompts as P
    from ..grading.transcribe import parse_llm_json

    ws_path = Path(ws).resolve()
    tpl = None
    if task_id:
        tpl = P.get_template(ws_path, task_id, "atopia-task")
    else:
        tpl = P.default_template(ws_path, "atopia-task")
    if not tpl:
        return {"ok": False, "error": f"找不到任务模板：{task_id or '(默认)'}"}
    body = str(tpl.get("text") or "").strip()
    if not body:
        return {"ok": False, "error": f"任务模板 {tpl.get('id')} 没有提示词内容"}

    src = read_extracted_text(ws_path, feature, max_chars=max_chars)
    images = collect_vision_images(ws_path, feature)
    if not src["text"].strip() and not images:
        return {"ok": False,
                "error": ("没有可解析的内容：请先跑「① 抽取」，或确认上传的文件里"
                          "有文本/可渲染的页图（扫描 PDF 需要 poppler）。")}

    user_parts = [body, "", "【文档内容】"]
    if src["text"].strip():
        user_parts.append(src["text"])
        if src.get("truncated"):
            user_parts.append("\n【注意】文本过长已截断，只提供前面部分；"
                              "如遗漏较多请拆分文档后重跑。")
    else:
        user_parts.append("（本批资料以图片/扫描件为主，请**依据所附图片**抽取）")
    if extra_context.strip():
        user_parts.append("\n【教师补充说明】\n" + extra_context.strip())
    prompt = "\n".join(user_parts)

    try:
        if images:
            raw = client.chat_with_images(
                system_prompt="这是大学物理课程资料整理，内容完全学术。只输出严格 JSON。",
                user_text=prompt, image_paths=images, model=model,
                temperature=0.2, max_tokens=8192, step="materials")
        else:
            raw = client.chat(
                system_prompt="这是大学物理课程资料整理，内容完全学术。只输出严格 JSON。",
                user_text=prompt, model=model, temperature=0.2,
                response_format={"type": "json_object"}, max_tokens=8192,
                step="materials")
        data = parse_llm_json(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[atopia 解析] 模型调用失败：{exc}")
        return {"ok": False, "error": str(exc)[:300]}
    if not isinstance(data, dict):
        return {"ok": False, "error": "模型返回的不是 JSON 对象"}

    primary = _TASK_PRIMARY_KEY.get(str(tpl.get("id") or ""), "")
    items = data.get(primary) if primary else None
    saved = save_parsed_result(ws_path, feature, data, name=f"{feature}.json")
    return {"ok": True, "taskId": tpl.get("id"), "taskName": tpl.get("name"),
            "primaryKey": primary,
            "count": len(items) if isinstance(items, list) else 0,
            "file": saved.get("file"), "path": saved.get("path"),
            "chars": src.get("chars"), "vision": bool(images),
            "truncated": bool(src.get("truncated")), "data": data}

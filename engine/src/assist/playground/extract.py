"""D90-P1：附件抽取 —— 图片 → data-url；文档（pdf/docx/txt/md/csv）→ 文本。

白名单 + basename 清洗（防路径穿越）；旧版二进制 .doc 不支持解析，提示转 docx/pdf。
不引新依赖：
- pdf → pypdf（已有依赖）；
- docx → 解压 word/document.xml 抽 <w:t>；
- txt/md/csv/json → 直读（限制大小）。
"""
from __future__ import annotations

import base64
import io
import re
import zipfile
from pathlib import Path

from loguru import logger

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
DOC_TEXT_EXTS = {".txt", ".md", ".csv", ".json", ".log", ".tex"}
PDF_EXTS = {".pdf"}
DOCX_EXTS = {".docx"}
LEGACY_DOC_EXTS = {".doc"}
ALLOWED_EXTS = IMAGE_EXTS | DOC_TEXT_EXTS | PDF_EXTS | DOCX_EXTS | LEGACY_DOC_EXTS

_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp"}

MAX_TEXT_CHARS = 200_000
MAX_FILE_BYTES = 30 * 1024 * 1024


def kind_of(name: str) -> str:
    ext = Path(str(name)).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in PDF_EXTS:
        return "pdf"
    if ext in DOCX_EXTS:
        return "docx"
    if ext in LEGACY_DOC_EXTS:
        return "doc"
    if ext in DOC_TEXT_EXTS:
        return "text"
    return ""


def is_allowed(name: str) -> bool:
    return Path(str(name)).suffix.lower() in ALLOWED_EXTS


def _safe_name(name: str) -> str:
    base = Path(str(name or "")).name
    return re.sub(r"[^\w.\-一-鿿]", "_", base)[:120] or "file"


def save_upload(ws: Path, name: str, data_b64: str, *, subdir: str = "") -> dict:
    """base64 附件 → <ws>/.runtime/playground/uploads/<subdir>/<文件名>。"""
    if not is_allowed(name):
        return {"ok": False, "error": f"不支持的附件类型：{Path(name).suffix or '(无扩展名)'}"}
    raw = data_b64
    if isinstance(raw, str) and raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        blob = base64.b64decode(raw, validate=True)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"base64 解码失败：{exc}"}
    if not blob:
        return {"ok": False, "error": "附件内容为空"}
    if len(blob) > MAX_FILE_BYTES:
        return {"ok": False, "error": f"附件过大（>{MAX_FILE_BYTES // 1024 // 1024}MB）"}
    import time as _t
    d = Path(ws).resolve() / ".runtime" / "playground" / "uploads"
    if subdir:
        d = d / _safe_name(subdir)
    d.mkdir(parents=True, exist_ok=True)
    fn = _safe_name(name)
    p = d / fn
    p.write_bytes(blob)
    return {"ok": True, "name": fn, "kind": kind_of(fn), "bytes": len(blob),
            "path": str(p)}


def _pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except Exception as exc:  # noqa: BLE001
        return f"[pdf 解析不可用：{exc}]"
    try:
        reader = PdfReader(str(path))
        out = []
        for pg in reader.pages:
            out.append(pg.extract_text() or "")
        return "\n".join(out)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"pdf 抽取失败: {type(exc).__name__}")
        return f"[pdf 解析失败：{type(exc).__name__}]"


def _docx_text(path: Path) -> str:
    """解压 docx，从 word/document.xml 抽 <w:t> 文本（段落用换行分隔）。"""
    try:
        with zipfile.ZipFile(str(path)) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
    except Exception as exc:  # noqa: BLE001
        return f"[docx 解析失败：{type(exc).__name__}]"
    # 段落结束 → 换行；文本节点 → 内容
    xml = re.sub(r"</w:p>", "\n", xml)
    parts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml, flags=re.S)
    text = "".join(parts)
    # 还原 XML 实体
    text = (text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", '"').replace("&apos;", "'"))
    return text


def extract_text(path: Path) -> str:
    """文档 → 文本（pdf/docx/txt/md/csv…）。图片/不支持的 → 空串。"""
    p = Path(path)
    if not p.is_file():
        return ""
    ext = p.suffix.lower()
    if ext in PDF_EXTS:
        return _pdf_text(p)[:MAX_TEXT_CHARS]
    if ext in DOCX_EXTS:
        return _docx_text(p)[:MAX_TEXT_CHARS]
    if ext in LEGACY_DOC_EXTS:
        return "[旧版 .doc 不支持直接解析：请另存为 .docx 或 .pdf 后再试]"
    if ext in DOC_TEXT_EXTS:
        try:
            return p.read_text(encoding="utf-8", errors="ignore")[:MAX_TEXT_CHARS]
        except Exception as exc:  # noqa: BLE001
            return f"[文本读取失败：{type(exc).__name__}]"
    return ""


def to_data_url(path: Path) -> str:
    p = Path(path)
    mime = _MIME.get(p.suffix.lower(), "image/jpeg")
    b64 = base64.b64encode(p.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def build_attachment_block(paths: list[str | Path]) -> tuple[list[str], list[str], list[str]]:
    """把附件路径分组：返回 (image_paths, doc_texts, notes)。

    doc_texts 已含文件名前缀（供拼进 user 文本）；notes 为提示（如 .doc 不支持/解析失败）。
    """
    images: list[str] = []
    texts: list[str] = []
    notes: list[str] = []
    for it in paths:
        p = Path(it)
        if not p.is_file():
            notes.append(f"附件不存在：{p.name}")
            continue
        k = kind_of(p.name)
        if k == "image":
            images.append(str(p))
        elif k in ("pdf", "docx", "text"):
            body = extract_text(p)
            if body.strip():
                texts.append(f"【附件：{p.name}】\n{body}")
            else:
                notes.append(f"附件无可抽取文本：{p.name}")
        elif k == "doc":
            notes.append(f"旧版 .doc 不支持直接解析：{p.name}（请转 docx/pdf）")
        else:
            notes.append(f"不支持的附件类型：{p.name}")
    return images, texts, notes

"""materials.py — D131(P2)：课堂资料库 `<ws>/materials/<chap>/`。

布局（docs/79 §2，定稿）：
    <ws>/materials/
      <chap>/
        _source/          教师原件（**只读不改**，唯一真源）
        _extract/         引擎抽取缓存（可删，自动重建）
        索引.json         抽取清单（引擎写，别手改）
        知识点清单.md     教师确认后的生效清单
        知识点清单.ai.json AI 建议（未经确认不生效）
        知识点清单.journal.jsonl

为什么独立成目录、不平铺在 kb/ 下：`kb/` 只放题库（D120 `FORBIDDEN_IN_KB`），
资料跨班共享也不该挂到 `classes/<班>/` 下（换班/多班会重复且找不到）。

抽取链路（docs/79 §4，均本机实测）：
- pptx/docx/xlsx → `officecli view <f> text --json`（首选）→ soffice 转 PDF → PDF 链路（回退）
- pdf → `pdftoppm` 逐页 PNG（给多模态）＋ `pdftotext`（纯文本兜底）
- 图片 → 直接给多模态；md/txt → 直读

**增量**：以 sha256 判定，文件没变就不重复抽取（省时间/省 token）。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

from loguru import logger

ROOT = "materials"
SOURCE = "_source"
EXTRACT = "_extract"
INDEX = "索引.json"
KNOW_MD = "知识点清单.md"
KNOW_AI = "知识点清单.ai.json"
KNOW_JOURNAL = "知识点清单.journal.jsonl"
TRASH = "_trash"
# D155：资料类型（只影响 `_source/<类型>/` 子目录与索引标注）
KINDS = {"plan": "授课计划", "ppt": "PPT/讲义", "textbook": "教材", "other": "其他"}          # D134-T3：remove 的回收站（**不真删**）
UPLOAD_EXTS = {".pptx", ".ppt", ".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg",
               ".md", ".txt", ".markdown"}
UPLOAD_MAX_BYTES = 20 * 1024 * 1024
UPLOAD_MAX_ITEMS = 20

TEXT_LIKE = {".md", ".txt", ".markdown"}
IMAGE_LIKE = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
OFFICE_LIKE = {".pptx", ".docx", ".xlsx", ".ppt", ".doc", ".xls"}
PDF_LIKE = {".pdf"}


class MaterialsError(RuntimeError):
    """课堂资料处理失败（可读的业务错误，CLI 直接展示）。"""


# ---------------- 路径与布局 ----------------
def materials_root(ws) -> Path:
    return Path(ws).resolve() / ROOT


def chap_dir(ws, chap: str) -> Path:
    name = str(chap or "").strip().strip("/")
    if not name:
        raise MaterialsError("章节名不能为空（应与题库 sheet 名一致，如 chap04）")
    if name in (".", "..") or "/" in name or "\\" in name:
        raise MaterialsError(f"章节名非法：{chap!r}")
    return materials_root(ws) / name


def ensure_chap(ws, chap: str) -> Path:
    """创建章节骨架（幂等）。教师也可手工建目录后直接放文件。"""
    d = chap_dir(ws, chap)
    (d / SOURCE).mkdir(parents=True, exist_ok=True)
    (d / EXTRACT).mkdir(parents=True, exist_ok=True)
    return d


def list_chaps(ws) -> list[str]:
    root = materials_root(ws)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir()
                  if p.is_dir() and (p / SOURCE).is_dir())


def index_path(ws, chap: str) -> Path:
    return chap_dir(ws, chap) / INDEX


def read_index(ws, chap: str) -> dict:
    p = index_path(ws, chap)
    if not p.is_file():
        return {"version": 1, "chap": str(chap), "sources": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"version": 1, "chap": str(chap),
                                                    "sources": []}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[资料] {p.name} 解析失败（{str(exc)[:80]}），按空索引处理")
        return {"version": 1, "chap": str(chap), "sources": []}


def write_index(ws, chap: str, data: dict) -> Path:
    p = index_path(ws, chap)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


# ---------------- 工具 ----------------
def sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def which(cmd: str) -> "str | None":
    return shutil.which(cmd)


def _run(cmd: list[str], *, timeout: int = 180) -> "tuple[int, str, str]":
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           check=False)
        return r.returncode, r.stdout or "", r.stderr or ""
    except FileNotFoundError:
        return 127, "", f"命令不存在：{cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"命令超时（>{timeout}s）：{' '.join(cmd[:2])}"


def list_sources(ws, chap: str) -> list[Path]:
    d = chap_dir(ws, chap) / SOURCE
    if not d.is_dir():
        return []
    return sorted((p for p in d.rglob("*") if p.is_file() and not p.name.startswith(".")),
                  key=lambda p: str(p))


def _norm_source_rel(raw: str) -> str:
    """把 `_source/plan/a.pptx`、`plan/a.pptx` 统一为 `_source/plan/a.pptx`。"""
    s = str(raw or "").strip().replace("\\", "/").lstrip("/")
    if not s:
        return ""
    if not s.startswith(f"{SOURCE}/"):
        s = f"{SOURCE}/{s}"
    return s


def resolve_source_selection(ws, chap: str, files: "list[str] | tuple[str, ...] | None" = None
                             ) -> "tuple[list[Path], list[str]]":
    """D228：把教师选中的文件解析成 `_source/` 下的真实路径。

    支持三种写法：`_source/plan/a.pptx`、`plan/a.pptx`、唯一的 `a.pptx`。
    选中列表为空 = 全部文件。返回 `(paths, missing_labels)`。
    """
    d = chap_dir(ws, chap)
    base = (d / SOURCE).resolve()
    all_paths = list_sources(ws, chap)
    if not files:
        return all_paths, []
    by_rel = {str(p.relative_to(d)).replace("\\", "/"): p for p in all_paths}
    by_name: dict[str, list[Path]] = {}
    for p in all_paths:
        by_name.setdefault(p.name, []).append(p)
    out: list[Path] = []
    missing: list[str] = []
    seen: set[str] = set()
    for raw in files:
        rel = _norm_source_rel(raw)
        if not rel:
            continue
        # 路径穿越红线：解析后必须仍在 `_source/` 内。
        candidate = (d / rel).resolve()
        try:
            candidate.relative_to(base)
        except ValueError:
            raise MaterialsError(f"资料路径非法（必须位于 _source/）：{raw!r}")
        p = by_rel.get(rel)
        if p is None and rel.count("/") == 1:
            hits = by_name.get(rel[len(SOURCE) + 1:], [])
            if len(hits) == 1:
                p = hits[0]
        if p is None or not p.is_file():
            missing.append(rel)
            continue
        key = str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out, missing


def files_of(ws, chap: str, *, include_trash: bool = False) -> list[dict]:
    """D134-T3b：列出 `_source/` 里的原件（文件名/大小/时间/sha/类型）。

    只读操作；**不修改**任何文件。`include_trash=True` 时一并列出回收站里的。
    """
    d = chap_dir(ws, chap)
    idx = read_index(ws, chap)
    idx_by_file = {str(s.get("file")): s for s in (idx.get("sources") or [])
                   if isinstance(s, dict) and s.get("file")}
    out: list[dict] = []
    dirs = [(SOURCE, d / SOURCE)]
    if include_trash:
        dirs.append((f"{SOURCE}/{TRASH}", d / SOURCE / TRASH))
    for label, base in dirs:
        if not base.is_dir():
            continue
        for p in sorted((x for x in base.rglob("*") if x.is_file()
                         and not x.name.startswith(".")), key=lambda x: str(x)):
            try:
                st = p.stat()
                rel = str(p.relative_to(d)).replace("\\", "/")
                entry = {"file": rel,
                         "name": p.name, "dir": label,
                         "kindDir": (p.parent.name if p.parent != (d / SOURCE)
                                     else ""),
                         "bytes": st.st_size,
                         "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
                         "kind": classify(p)}
                if label == SOURCE:
                    entry["sha256"] = sha256_of(p)
                    src = idx_by_file.get(rel) or {}
                    ex = src.get("extract") or {}
                    entry["indexed"] = bool(src)
                    entry["extracted"] = bool(ex)
                    entry["extractMode"] = str(ex.get("engine") or "")
                    entry["extractChars"] = int(ex.get("chars") or 0)
                    entry["extractImages"] = len(ex.get("images") or [])
                    entry["extractedAt"] = str(src.get("mtime") or "")
                    tr = ex.get("transcript") if isinstance(ex.get("transcript"), dict) else {}
                    entry["transcribed"] = bool(tr)
                    entry["transcriptChars"] = int((tr or {}).get("chars") or 0)
                    entry["transcriptPages"] = int((tr or {}).get("pages") or 0)
                    entry["transcriptPagesTotal"] = int((tr or {}).get("pages_total") or 0)
                    entry["transcriptEngine"] = str((tr or {}).get("engine") or "")
                    entry["transcriptFailedPages"] = list((tr or {}).get("failedPages") or [])
                out.append(entry)
            except OSError as exc:
                out.append({"file": str(p.name), "dir": label,
                            "error": str(exc)[:120]})
    return out


def save_uploads(ws, chap: str, items: "list[dict]", *, kind: str = "") -> dict:
    """D134-T3a：把 PWA base64 上传的附件落到 `_source/`（**同名不覆盖**）。

    items: `[{name, data_b64}]`。
    安全约束（docs/83 §4 T3a / §6）：
    - 扩展名白名单（`UPLOAD_EXTS`），其余一律拒收（不收 .exe/.sh/.zip 等）；
    - 单文件 ≤ `UPLOAD_MAX_BYTES`，一次最多 `UPLOAD_MAX_ITEMS` 个；
    - 文件名清洗（去掉路径分隔符/控制字符）；
    - **同名不覆盖**：自动改名为 `name-2.ext`、`name-3.ext` …；
    - 只写 `_source/`，不碰 `_extract/` 与知识点清单。
    """
    import base64
    import re as _re

    d = ensure_chap(ws, chap)
    # D155：按资料类型落 `_source/<类型>/`（kind 为空 = 直接落 `_source/`，兼容旧行为）
    k = str(kind or "").strip()
    src = (d / SOURCE / k) if k in KINDS else (d / SOURCE)
    src.mkdir(parents=True, exist_ok=True)
    saved: list[dict] = []
    skipped: list[dict] = []
    for it in (items or [])[:UPLOAD_MAX_ITEMS]:
        raw_name = str((it or {}).get("name") or "").strip()
        # 只保留安全字符；去掉任何路径成分（防 ../ 写出 _source/）
        name = _re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._()（）+\- ]", "_",
                       Path(raw_name).name)[:120].strip()
        if not name or name in (".", ".."):
            skipped.append({"name": raw_name, "reason": "文件名非法"})
            continue
        ext = Path(name).suffix.lower()
        if ext not in UPLOAD_EXTS:
            skipped.append({"name": name,
                            "reason": f"扩展名 {ext or '(无)'} 不在允许列表"
                                      f"（{' '.join(sorted(UPLOAD_EXTS))}）"})
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
        if len(blob) > UPLOAD_MAX_BYTES:
            skipped.append({"name": name,
                            "reason": f"超过大小上限 {UPLOAD_MAX_BYTES // (1024 * 1024)}MB"})
            continue
        # 同名不覆盖：自动加序号（教师原件永不被静默替换）
        dest = src / name
        n = 2
        while dest.exists():
            dest = src / f"{Path(name).stem}-{n}{Path(name).suffix}"
            n += 1
        try:
            dest.write_bytes(blob)
        except OSError as exc:
            skipped.append({"name": name, "reason": f"写入失败：{exc}"})
            continue
        saved.append({"name": dest.name, "requested": name,
                      "file": str(dest.relative_to(d)).replace("\\", "/"),
                      "kind": k, "bytes": len(blob), "renamed": dest.name != name})
    return {"ok": True, "chap": chap, "saved": saved, "skipped": skipped,
            "source": str(src)}


def remove_source(ws, chap: str, file_name: str) -> dict:
    """D134-T3c：把 `_source/` 里的文件**移入回收站** `_source/_trash/`（不真删）。

    为什么不真删：`_source/` 是教师原件（唯一真源，D131 硬规则 1）；
    误删不可恢复。移入回收站可人工找回，且教师能看到"哪些被移走过"。
    """
    import shutil as _sh

    d = chap_dir(ws, chap)
    src = d / SOURCE
    rel = str(file_name or "").strip().replace("\\", "/").lstrip("/")
    if not rel:
        raise MaterialsError("文件名不能为空")
    target = (src / rel)
    try:
        target = target.resolve()
        target.relative_to(src.resolve())
    except Exception:  # noqa: BLE001
        raise MaterialsError(f"文件必须位于 {SOURCE}/ 内：{file_name!r}") from None
    if not target.is_file():
        raise MaterialsError(f"文件不存在：{rel}")
    trash = src / TRASH
    trash.mkdir(parents=True, exist_ok=True)
    dest = trash / target.name
    n = 2
    while dest.exists():
        dest = trash / f"{target.stem}-{n}{target.suffix}"
        n += 1
    _sh.move(str(target), str(dest))
    return {"ok": True, "moved": rel,
            "to": str(dest.relative_to(d)).replace("\\", "/"),
            "hint": "已移入回收站（未删除）；需要时从 _source/_trash/ 移回"}


def restore_source(ws, chap: str, file_name: str) -> dict:
    """D135：把回收站里的文件**移回 `_source/`**（与 remove 对称，不覆盖）。

    `file_name` 可写回收站内的名字（`a.pdf`）或带目录（`_trash/a.pdf`）。
    目标同名已存在时自动 `-2`（教师原件永不被静默替换）。
    """
    import shutil as _sh

    d = chap_dir(ws, chap)
    src = d / SOURCE
    trash = src / TRASH
    rel = str(file_name or "").strip().replace("\\", "/").lstrip("/")
    if rel.startswith(f"{SOURCE}/"):
        rel = rel[len(SOURCE) + 1:]
    if rel.startswith(f"{TRASH}/"):
        rel = rel[len(TRASH) + 1:]
    if not rel:
        raise MaterialsError("文件名不能为空")
    target = (trash / rel)
    try:
        target = target.resolve()
        target.relative_to(trash.resolve())
    except Exception:  # noqa: BLE001
        raise MaterialsError(f"文件必须位于 {SOURCE}/{TRASH}/ 内：{file_name!r}") from None
    if not target.is_file():
        raise MaterialsError(f"回收站中没有该文件：{rel}")
    dest = src / target.name
    n = 2
    while dest.exists():
        dest = src / f"{target.stem}-{n}{target.suffix}"
        n += 1
    _sh.move(str(target), str(dest))
    return {"ok": True, "restored": rel,
            "to": str(dest.relative_to(d)).replace("\\", "/"),
            "renamed": dest.name != target.name}


def classify(p: Path) -> str:
    s = p.suffix.lower()
    if s in PDF_LIKE:
        return "pdf"
    if s in OFFICE_LIKE:
        return "office"
    if s in IMAGE_LIKE:
        return "image"
    if s in TEXT_LIKE:
        return "text"
    return "unknown"


# ---------------- 抽取：office ----------------
def _officecli_release(p: Path) -> None:
    """强制 officecli 释放驻留缓存。

    **实测坑**：officecli 会为打开过的文档起驻留进程；文件被外部替换后
    （教师资格改完 PPT 重新放入 `_source/`），`view` 仍返回**旧内容**。
    不释放会导致"明明改了 PPT，抽出来还是老的"这种极难排查的问题。
    """
    try:
        _run(["officecli", "close", str(p)], timeout=30)
    except Exception:  # noqa: BLE001 —— 释放失败不影响主流程
        pass


def _extract_pptx_python(p: Path) -> "dict | None":
    """D171-T6：纯 Python 抽 pptx（python-pptx）。失败返回 None。"""
    try:
        from pptx import Presentation
    except ImportError:
        return None
    try:
        prs = Presentation(str(p))
        parts: list[str] = []
        for i, slide in enumerate(prs.slides, start=1):
            texts: list[str] = []
            for shape in slide.shapes:
                if not getattr(shape, "has_text_frame", False):
                    continue
                t = str(shape.text_frame.text or "").strip()
                if t:
                    texts.append(t)
            if texts:
                parts.append(f"--- slide {i} ---\n" + "\n".join(texts))
        text = "\n\n".join(parts).strip()
        return {"engine": "python-pptx", "slides": len(prs.slides),
                "chars": len(text), "text": text}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[资料] python-pptx 抽取失败：{str(exc)[:120]}")
        return None


def _extract_docx_python(p: Path) -> "dict | None":
    """D171-T6：纯 Python 抽 docx（python-docx，含表格）。失败返回 None。"""
    try:
        import docx
    except ImportError:
        return None
    try:
        d = docx.Document(str(p))
        parts: list[str] = [str(x.text or "").strip()
                            for x in d.paragraphs if str(x.text or "").strip()]
        for tb in d.tables:
            for row in tb.rows:
                cells = [str(c.text or "").strip() for c in row.cells]
                if any(cells):
                    parts.append("\t".join(cells))
        text = "\n".join(parts).strip()
        return {"engine": "python-docx", "slides": None,
                "chars": len(text), "text": text}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[资料] python-docx 抽取失败：{str(exc)[:120]}")
        return None


def extract_office(p: Path, out_txt: Path) -> dict:
    """pptx/docx/xlsx → 纯文本。

    D171-T6：降级链改为 **纯 Python 优先**——
        ① python-pptx / python-docx / openpyxl（无需任何外部二进制）
        ② officecli（若已安装，质量通常更好）
        ③ soffice 转 PDF 再抽文本
        ④ 全部失败 → 可读错误

    为什么改：教师机器上通常**没有** officecli 与 LibreOffice，
    原来直接报「没有安装 officecli」→ 抽取功能不可用。
    """
    ext = p.suffix.lower()
    py_rep = None
    if ext == ".pptx":
        py_rep = _extract_pptx_python(p)
    elif ext == ".docx":
        py_rep = _extract_docx_python(p)
    if py_rep and py_rep.get("chars"):
        out_txt.parent.mkdir(parents=True, exist_ok=True)
        out_txt.write_text(py_rep["text"], encoding="utf-8")
        return {"engine": py_rep["engine"], "slides": py_rep.get("slides"),
                "chars": py_rep["chars"], "text_file": str(out_txt)}
    if which("officecli"):
        # 先释放可能存在的驻留缓存，确保读到**当前**文件内容（见 _officecli_release）
        _officecli_release(p)
        rc, out, err = _run(["officecli", "view", str(p), "text", "--json"])
        if rc == 0 and out.strip():
            try:
                data = json.loads(out)
                slides = (((data or {}).get("data") or {}).get("slides") or [])
                parts: list[str] = []
                for s in slides:
                    idx = s.get("index")
                    texts = s.get("texts") or []
                    if isinstance(texts, str):
                        texts = [texts]
                    body = "\n".join(str(t) for t in texts if str(t).strip())
                    if body.strip():
                        parts.append(f"--- slide {idx} ---\n{body}" if idx else body)
                text = "\n\n".join(parts).strip()
                if text:
                    out_txt.parent.mkdir(parents=True, exist_ok=True)
                    out_txt.write_text(text, encoding="utf-8")
                    return {"engine": "officecli", "slides": len(slides),
                            "chars": len(text), "text_file": str(out_txt)}
            except (json.JSONDecodeError, AttributeError):
                # 非 JSON 输出：退化为纯文本
                if out.strip():
                    out_txt.parent.mkdir(parents=True, exist_ok=True)
                    out_txt.write_text(out, encoding="utf-8")
                    return {"engine": "officecli(text)", "slides": None,
                            "chars": len(out), "text_file": str(out_txt)}
        logger.warning(f"[资料] officecli 抽取失败（rc={rc}）：{err[:200]}")
    # 回退：soffice 转 PDF
    if which("soffice"):
        pdf = out_txt.parent / (p.stem + ".pdf")
        out_txt.parent.mkdir(parents=True, exist_ok=True)
        rc, _o, err = _run(["soffice", "--headless", "--convert-to", "pdf",
                            str(p), "--outdir", str(pdf.parent)])
        if rc == 0 and pdf.is_file():
            rep = extract_pdf_text(pdf)
            if rep.get("chars"):
                text = Path(rep["text_file"]).read_text(encoding="utf-8")
                out_txt.write_text(text, encoding="utf-8")
                return {"engine": "soffice→pdftotext", "slides": rep.get("pages"),
                        "chars": len(text), "text_file": str(out_txt)}
        logger.warning(f"[资料] soffice 回退失败：{err[:200]}")
    raise MaterialsError(
        f"无法抽取 {p.name}：Python 库（python-pptx/python-docx）、officecli、"
        f"LibreOffice 均不可用或失败。"
        f"请把该文件另存为 PDF 再放入 _source/，或重跑 start 脚本补齐依赖。")


# ---------------- 抽取：pdf ----------------
def extract_pdf_text(pdf: Path, *, out_dir: "Path | None" = None) -> dict:
    """pdf → 纯文本（pdftotext）。返回 {engine, pages, chars, text_file}。"""
    out_dir = Path(out_dir) if out_dir else pdf.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    txt = out_dir / (pdf.stem + ".text.txt")
    if which("pdftotext"):
        rc, _o, err = _run(["pdftotext", "-layout", str(pdf), str(txt)])
        if rc == 0 and txt.is_file():
            text = txt.read_text(encoding="utf-8", errors="replace")
            pages = text.count("\f") + 1 if text else 0
            return {"engine": "pdftotext", "pages": pages, "chars": len(text),
                    "text_file": str(txt)}
        logger.warning(f"[资料] pdftotext 失败：{err[:160]}")
    return {"engine": None, "pages": 0, "chars": 0, "text_file": ""}


def pdf_to_images(pdf: Path, out_dir: Path, *, dpi: int = 150,
                  max_pages: int = 60) -> dict:
    """pdf → 逐页 PNG（多模态用）。返回 {engine, images:[...], pages}。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    if not which("pdftoppm"):
        return {"engine": None, "images": [], "pages": 0,
                "error": "未安装 pdftoppm（poppler-utils），无法渲染 PDF 为图片"}
    prefix = out_dir / pdf.stem
    rc, _o, err = _run(["pdftoppm", "-png", "-r", str(dpi),
                        "-f", "1", "-l", str(int(max_pages)),
                        str(pdf), str(prefix)])
    if rc != 0:
        return {"engine": None, "images": [], "pages": 0,
                "error": f"pdftoppm 失败：{err[:200]}"}
    imgs = sorted(out_dir.glob(pdf.stem + "-*.png"))
    return {"engine": "pdftoppm", "images": [str(p) for p in imgs], "pages": len(imgs)}


# ---------------- 抽取总入口（增量） ----------------
def extract_chap(ws, chap: str, *, force: bool = False,
                 files: "list[str] | tuple[str, ...] | None" = None) -> dict:
    """抽取某章节资料 → 写 `索引.json` + `_extract/`（sha256 增量）。

    D228：`files` 非空时只处理选中文件；未选中的已抽取条目原样保留，
    因此教师更新一个 PPT 后只需重抽该文件，不必全章重跑。
    """
    d = ensure_chap(ws, chap)
    ex = d / EXTRACT
    old = {s.get("file"): s for s in (read_index(ws, chap).get("sources") or [])
           if isinstance(s, dict)}
    selected_paths, missing = resolve_source_selection(ws, chap, files)
    selected_rels = {str(p.relative_to(d)).replace("\\", "/") for p in selected_paths}
    out_sources: list[dict] = []
    skipped, errors = [], []
    # 只抽选中文件时：保留未选中的旧索引项（且只保留源文件仍存在的项）。
    if files:
        for rel, prev in old.items():
            if rel in selected_rels:
                continue
            if (d / rel).is_file():
                out_sources.append(prev)
    for rel in missing:
        errors.append({"file": rel, "error": "未找到该原件（检查是否已上传/路径是否正确）"})
    for p in selected_paths:
        rel = str(p.relative_to(d)).replace("\\", "/")
        sha = sha256_of(p)
        prev = old.get(rel)
        if (not force) and prev and prev.get("sha256") == sha and prev.get("extract"):
            out_sources.append(prev)
            skipped.append(rel)
            continue
        kind = classify(p)
        stem = p.stem
        try:
            if kind == "office":
                rep = extract_office(p, ex / f"{stem}.text.txt")
            elif kind == "pdf":
                t = extract_pdf_text(p, out_dir=ex)
                imgs = pdf_to_images(p, ex / f"{stem}.pages")
                rep = {"engine": t.get("engine") or imgs.get("engine"),
                       "pages": t.get("pages") or imgs.get("pages"),
                       "chars": t.get("chars", 0),
                       "text_file": t.get("text_file", ""),
                       "images": imgs.get("images") or []}
                if not rep["chars"] and not rep["images"]:
                    raise MaterialsError(
                        f"无法抽取 {p.name}：pdftotext/pdftoppm 均不可用。"
                        f"请安装 poppler-utils。")
            elif kind == "text":
                txt = p.read_text(encoding="utf-8", errors="replace")
                tf = ex / f"{stem}.text.txt"
                ex.mkdir(parents=True, exist_ok=True)
                tf.write_text(txt, encoding="utf-8")
                rep = {"engine": "read-text", "chars": len(txt), "text_file": str(tf)}
            elif kind == "image":
                rep = {"engine": "image", "chars": 0, "images": [str(p)]}
            else:
                raise MaterialsError(
                    f"不支持的资料类型：{p.name}（支持 pptx/docx/xlsx/pdf/图片/md/txt）")
            out_sources.append({"file": rel, "kind": kind, "bytes": p.stat().st_size,
                                "sha256": sha,
                                "mtime": time.strftime("%Y-%m-%d %H:%M:%S",
                                                       time.localtime(p.stat().st_mtime)),
                                # 与 docs/79 §3 schema 一致：抽取信息**嵌在 extract 下**
                                # （增量判定读 prev["extract"]，扁平化会让它永远为空）
                                "extract": rep})
        except MaterialsError as exc:
            errors.append({"file": rel, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001 —— 单个文件失败不影响其它
            errors.append({"file": rel, "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
    total_chars = sum(int((s.get("extract") or {}).get("chars") or 0)
                      for s in out_sources)
    idx = {"version": 1, "chap": str(chap),
           "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
           "sources": out_sources,
           "summary": {"files": len(out_sources), "chars": total_chars,
                       "slides": sum(int((s.get("extract") or {}).get("slides") or 0)
                                     for s in out_sources)}}
    write_index(ws, chap, idx)
    return {"ok": not errors, "chap": str(chap), "index": str(index_path(ws, chap)),
            "sources": len(out_sources), "selected_files": len(selected_paths),
            "skipped_unchanged": skipped,
            "skipped_unselected": [r for r in old if r not in selected_rels]
                                  if files else [],
            "chars": total_chars, "errors": errors}


# ---------------- D230：图片型资料转写（本地 OCR / 多模态） ----------------
_TRANSCRIPT_ENGINES = ("auto", "local", "vision")
_TESS_LANGS: "str | None" = None


def _transcript_key(rel: str) -> str:
    s = str(rel or "").replace("\\", "/")
    if s.startswith(f"{SOURCE}/"):
        s = s[len(SOURCE) + 1:]
    return Path(s).with_suffix("").as_posix().replace("/", "__")


def transcript_paths(ws, chap: str, rel: str) -> "tuple[Path, Path]":
    d = chap_dir(ws, chap)
    key = _transcript_key(rel)
    return (d / EXTRACT / f"{key}.transcript.json",
            d / EXTRACT / f"{key}.transcript.md")


def _read_text_path(p: Path, d: Path) -> str:
    if not str(p or "").strip():
        return ""
    q = Path(p)
    if not q.is_file():
        q = d / str(p)
    if not q.is_file():
        return ""
    return q.read_text(encoding="utf-8", errors="replace")


def _tesseract_languages() -> str:
    """优先中英混合；当前 tesseract 未装 chi_sim 时退化为 eng。"""
    global _TESS_LANGS
    if _TESS_LANGS is not None:
        return _TESS_LANGS
    langs = "eng"
    rc, out, _err = _run(["tesseract", "--list-langs"], timeout=20)
    if rc == 0 and "chi_sim" in out:
        langs = "chi_sim+eng"
    _TESS_LANGS = langs
    return langs


def _ocr_page_tesseract(image_path: Path) -> dict:
    """单页本地 OCR；返回 {text, engine, error}。"""
    if not which("tesseract"):
        return {"text": "", "engine": "", "error": "未安装 tesseract"}
    langs = _tesseract_languages()
    rc, out, err = _run(["tesseract", str(image_path), "stdout",
                         "-l", langs, "--psm", "6"], timeout=180)
    if rc != 0:
        return {"text": "", "engine": "tesseract",
                "error": f"tesseract 失败：{err[:200]}"}
    return {"text": str(out or "").strip(), "engine": "tesseract", "error": ""}


def _parse_vision_pages(raw: str, page_numbers: "list[int]") -> "dict[int, str]":
    """解析多模态转写结果中的 `--- page N ---`；无分隔时单页直接采用。"""
    import re as _re
    text = str(raw or "").strip()
    if not text:
        return {}
    if len(page_numbers) == 1:
        return {int(page_numbers[0]): text}
    pat = _re.compile(r"(?im)^\s*[-#*]*\s*page\s*(\d+)\s*[-#*:：]*\s*$")
    hits = list(pat.finditer(text))
    out: dict[int, str] = {}
    for i, m in enumerate(hits):
        try:
            page = int(m.group(1))
        except Exception:  # noqa: BLE001
            continue
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        body = text[m.end():end].strip()
        if body:
            out[page] = body
    return out


def _vision_transcribe_batch(client, image_paths: "list[Path]", page_numbers: "list[int]",
                             *, rel: str, model: "str | None") -> dict:
    """多模态转写一批页图；返回 {page: text} 或抛异常。"""
    nums = "、".join(str(x) for x in page_numbers)
    prompt = (
        f"这是课堂资料「{rel}」的第 {nums} 页图片。"
        "请逐页转写页面上的全部教学内容，要求：\n"
        "1. 保留页标记，严格输出 `--- page N ---`，每页一段；\n"
        "2. 文字、公式、定义、定理、例题题干尽量完整；公式用 LaTeX；\n"
        "3. 示意图不要臆造内容，用「[示意图：...]」简短描述；\n"
        "4. 看不清的字符写「[不清]」，不要编造；\n"
        "5. 只输出转写正文，不要额外解释。"
    )
    raw = client.chat_with_images(
        system_prompt="这是大学物理课堂资料转写，内容完全学术。只输出逐页转写文本。",
        user_text=prompt, image_paths=[str(x) for x in image_paths],
        model=model or None, temperature=0.1, max_tokens=8192,
        step="transcription")
    parsed = _parse_vision_pages(raw, page_numbers)
    if not parsed:
        raise MaterialsError("AI 转写返回为空或未按 `--- page N ---` 分页")
    return parsed


def transcribe_chap_file(client, ws, chap: str, rel: str, *, engine: str = "auto",
                         provider: str = "", model: str = "",
                         force: bool = False, pages_per_call: int = 4,
                         max_pages: int = 60) -> dict:
    """D230：把单个图片型资料的页图转写为可审查文本。

    - `engine=auto`：先本地 tesseract OCR，缺失/过短页再走多模态；
    - `engine=local`：只用 tesseract；
    - `engine=vision`：只用多模态视觉模型；
    - 结果落 `_extract/<文件>.transcript.json/.md`，并写回 `索引.json`。
    """
    engine = str(engine or "auto").strip().lower()
    if engine not in _TRANSCRIPT_ENGINES:
        raise MaterialsError(f"未知转写引擎：{engine}（可选 auto/local/vision）")
    d = chap_dir(ws, chap)
    idx = read_index(ws, chap)
    src = next((s for s in (idx.get("sources") or [])
                if isinstance(s, dict) and str(s.get("file") or "") == rel), None)
    if not src:
        raise MaterialsError(f"文件尚未抽取：{rel}")
    ex = src.get("extract") or {}
    p = d / rel
    if not p.is_file():
        raise MaterialsError(f"原件不存在：{rel}")
    # 有可靠文字层时不默认转写（明确 force 才重做）。
    text_layer = _read_text_path(str(ex.get("text_file") or ""), d)
    if text_layer.strip() and len(text_layer.strip()) >= _VISION_TEXT_THRESHOLD and not force:
        return {"ok": True, "skipped": True, "file": rel,
                "reason": f"已有文字层（{len(text_layer.strip())} 字），无需图片转写",
                "chars": len(text_layer.strip())}
    images: list[Path] = []
    for one in (ex.get("images") or [])[:max(1, int(max_pages))]:
        ip = Path(str(one))
        if not ip.is_file():
            ip2 = d / str(one)
            if ip2.is_file():
                ip = ip2
        if ip.is_file():
            images.append(ip)
    if not images:
        return {"ok": False, "file": rel,
                "error": "没有可转写的页图；请先抽取该文件"}
    json_path, md_path = transcript_paths(ws, chap, rel)
    existing: dict = {}
    if json_path.is_file() and not force:
        try:
            old = json.loads(json_path.read_text(encoding="utf-8"))
            if old.get("sourceSha256") == str(src.get("sha256") or ""):
                existing = old
        except Exception:  # noqa: BLE001
            existing = {}
    page_map: dict[int, dict] = {}
    for x in (existing.get("pages") or []):
        if not isinstance(x, dict):
            continue
        try:
            pn = int(x.get("page"))
        except Exception:  # noqa: BLE001
            continue
        if str(x.get("text") or "").strip():
            page_map[pn] = dict(x)
    page_numbers = list(range(1, len(images) + 1))
    missing = [n for n in page_numbers if n not in page_map]
    errors: list[dict] = []
    used_engines: set[str] = set()
    if engine in ("auto", "local"):
        t_ok = bool(which("tesseract"))
        if not t_ok and engine == "local":
            errors.append({"page": 0, "error": "未安装 tesseract，无法执行本地 OCR"})
        if t_ok:
            for n in list(missing):
                rep = _ocr_page_tesseract(images[n - 1])
                if rep.get("text"):
                    page_map[n] = {"page": n, "image": images[n - 1].name,
                                   "text": rep["text"], "engine": "tesseract",
                                   "error": ""}
                    used_engines.add("tesseract")
                    missing.remove(n)
                elif rep.get("error"):
                    errors.append({"page": n, "error": rep["error"]})
    if engine == "vision" or (engine == "auto" and missing):
        if client is None:
            errors.append({"page": 0, "error": "未配置视觉模型，无法执行 AI 转写"})
        else:
            batch_n = max(1, int(pages_per_call))
            for i in range(0, len(missing), batch_n):
                batch = missing[i:i + batch_n]
                try:
                    got = _vision_transcribe_batch(
                        client, [images[n - 1] for n in batch], batch,
                        rel=rel, model=model or None)
                except Exception as exc:  # noqa: BLE001
                    errors.extend({"page": n, "error": str(exc)[:400]} for n in batch)
                    continue
                for n in batch:
                    txt = str(got.get(n) or "").strip()
                    if txt:
                        page_map[n] = {"page": n, "image": images[n - 1].name,
                                       "text": txt, "engine": "vision", "error": ""}
                        used_engines.add("vision")
                    else:
                        errors.append({"page": n, "error": "AI 未返回该页转写"})
    pages_out = [page_map[n] for n in sorted(page_map)]
    total_chars = sum(len(str(x.get("text") or "")) for x in pages_out)
    failed_pages = sorted({int(e.get("page") or 0) for e in errors if e.get("page")})
    if not pages_out:
        return {"ok": False, "file": rel, "engine": engine,
                "errors": errors, "failedPages": failed_pages,
                "pages_total": len(images), "chars": 0,
                "error": "没有转写出任何文字"}
    engine_name = ("mixed" if len(used_engines) > 1 else
                   (next(iter(used_engines)) if used_engines else engine))
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S")
    data = {"version": 1, "chap": str(chap), "file": rel,
            "sourceSha256": str(src.get("sha256") or ""),
            "engine": engine_name, "provider": provider, "model": model,
            "pages_total": len(images), "pages": pages_out,
            "errors": errors, "failedPages": failed_pages,
            "chars": total_chars, "generatedAt": generated_at}
    md_lines = [f"# 课堂资料转写：{rel}", "",
                f"> 引擎：{engine_name}；页数：{len(pages_out)}/{len(images)}；"
                f"字数：{total_chars}；生成于 {generated_at}", ""]
    for x in pages_out:
        md_lines += [f"--- page {x.get('page')} ---", "",
                     str(x.get("text") or "").strip(), ""]
    ex_dir = d / EXTRACT
    ex_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    transcript_meta = {
        "engine": engine_name, "provider": provider, "model": model,
        "text_file": str(md_path), "chars": total_chars,
        "pages": len(pages_out), "pages_total": len(images),
        "failedPages": failed_pages, "generatedAt": generated_at,
        "sourceSha256": str(src.get("sha256") or ""),
    }
    src.setdefault("extract", {})["transcript"] = transcript_meta
    write_index(ws, chap, idx)
    return {"ok": not failed_pages, "partial": bool(failed_pages),
            "file": rel, "engine": engine_name, "chars": total_chars,
            "pages": len(pages_out), "pages_total": len(images),
            "failedPages": failed_pages, "errors": errors,
            "transcript": str(md_path), "provider": provider, "model": model}


def transcribe_materials(client, ws, chap: str,
                         files: "list[str] | tuple[str, ...] | None" = None, *,
                         engine: str = "auto", provider: str = "",
                         model: str = "", force: bool = False,
                         pages_per_call: int = 4, max_pages: int = 60) -> dict:
    """D230：按文件转写图片型资料；支持多选/全选与失败页重跑。"""
    selected_paths, missing = resolve_source_selection(ws, chap, files)
    d = chap_dir(ws, chap)
    results: list[dict] = []
    errors: list[dict] = [{"file": x, "error": "未找到该原件"} for x in missing]
    for p in selected_paths:
        rel = str(p.relative_to(d)).replace("\\", "/")
        try:
            results.append(transcribe_chap_file(
                client, ws, chap, rel, engine=engine, provider=provider,
                model=model, force=force, pages_per_call=pages_per_call,
                max_pages=max_pages))
        except MaterialsError as exc:
            results.append({"ok": False, "file": rel, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            results.append({"ok": False, "file": rel,
                            "error": f"{type(exc).__name__}: {str(exc)[:400]}"})
    bad = [r for r in results if not r.get("ok")]
    return {"ok": not errors and not bad, "chap": str(chap),
            "engine": engine, "provider": provider, "model": model,
            "files": results, "transcribed": sum(1 for r in results if r.get("chars")),
            "skipped": sum(1 for r in results if r.get("skipped")),
            "errors": errors + [{"file": r.get("file"), "error": r.get("error")}
                                for r in bad if r.get("error")]}


def read_source_text(ws, chap: str, *, max_chars: int = 0,
                     files: "list[str] | tuple[str, ...] | None" = None) -> dict:
    """汇总本章抽取文本（供 AI 抽取知识点）。D228：可按 files 只读选中文件。"""
    idx = read_index(ws, chap)
    d = chap_dir(ws, chap)
    wanted = {_norm_source_rel(x) for x in (files or []) if str(x or "").strip()}
    parts: list[str] = []
    files_n = 0
    names: list[str] = []
    transcript_files: list[str] = []
    for s in idx.get("sources") or []:
        rel = str(s.get("file") or "")
        if wanted and rel not in wanted:
            continue
        ex = s.get("extract") or {}
        tr = ex.get("transcript") if isinstance(ex.get("transcript"), dict) else {}
        # D230：优先使用独立转写文本；没有转写时才回退原始文字层。
        tf = str((tr or {}).get("text_file") or ex.get("text_file") or "")
        if not tf:
            continue
        p = Path(tf)
        if not p.is_file():
            p = d / tf
        if not p.is_file():
            continue
        txt = p.read_text(encoding="utf-8", errors="replace")
        if txt.strip():
            parts.append(f"===== {s.get('file')} =====\n{txt}")
            files_n += 1
            names.append(rel)
            if tr:
                transcript_files.append(rel)
    text = "\n\n".join(parts)
    truncated = False
    if max_chars and len(text) > max_chars:
        text = text[:max_chars]
        truncated = True
    return {"text": text, "chars": len(text), "files": files_n,
            "fileNames": names, "transcriptFiles": transcript_files,
            "truncated": truncated,
            "has_index": bool((idx.get("sources") or []))}


# 文本少于该字数、且有页图 → 认为"文字不足，需要看图"
_VISION_TEXT_THRESHOLD = 200
# 单次最多送多少张图（控 token/成本；超出部分在 notes 里提示教师）
_VISION_MAX_IMAGES = 20


def read_source_images(ws, chap: str, *, max_images: int = _VISION_MAX_IMAGES,
                       files: "list[str] | tuple[str, ...] | None" = None) -> dict:
    """汇总可送多模态的图片（PDF 页图 + 教师直接放的图片）。

    D228：可按 files 只读取选中文件的图片；只返回盘上仍存在的图片。
    """
    idx = read_index(ws, chap)
    d = chap_dir(ws, chap)
    wanted = {_norm_source_rel(x) for x in (files or []) if str(x or "").strip()}
    out: list[str] = []
    for s in idx.get("sources") or []:
        rel = str(s.get("file") or "")
        if wanted and rel not in wanted:
            continue
        ex = s.get("extract") or {}
        cand = list(ex.get("images") or [])
        for one in cand:
            p = Path(str(one))
            if not p.is_file():
                p2 = d / str(one)
                if not p2.is_file():
                    continue
                p = p2
            out.append(str(p))
    # 稳定排序（页序：lecture02-1.png, -2, -10 需按数字排）
    import re as _re

    def _key(path: str):
        name = Path(path).name
        nums = _re.findall(r"\d+", name)
        return (str(Path(path).parent), [int(n) for n in nums], name)

    out = sorted(dict.fromkeys(out), key=_key)
    return {"images": out, "count": len(out), "max_images": max_images}


# ---------------- T21a：AI 抽取「本章知识点 + 逻辑关系」 ----------------
KNOWN_PROMPT = """你是大学物理教研组老师。下面是一门课的**课堂资料文本**（授课 PPT / 讲义 / 授课计划）。
请抽出这一章学生应当掌握的**知识点**及其**逻辑关系**，供教师核对后作为作业批阅依据。

【要求】
1. `knowledge`：知识点术语，用规范物理概念名（如 动量守恒、完全弹性碰撞、安培环路定理），
   **不要**写成整句、不要带题号；
2. 每条必须给 `evidence`：**引用资料中的原话或页/幻灯片编号**，不得凭空编造；
   `importance`：core=本章核心必考 / supporting=支撑性（公式变形、单位、特例）；
3. `topic`：**每个术语必须给**一个"章内主题"（同一章里的内容块，如 碰撞问题、动量定理、
   刚体转动），用于把同章分散的术语归类；**不要**写成章名（chapter 另给），
   也不要凭空编造——只能从资料里的章节标题/小节/幻灯片分组归纳；
4. `logic`：知识点之间的先后/推导关系（`from` → `to`），`note` 说明依据；
5. 若资料里已给出「已标注知识点」，**优先原样沿用**其中的术语；
6. 术语 5–20 个；宁可少而准，不要凑数。

【输出格式（严格 JSON）】
{
  "knowledge": [
    {"term": "动量守恒", "aliases": ["动量守恒定律"], "importance": "core",
     "topic": "动量定理",
     "evidence": "第 5 页：系统所受合外力为零时总动量守恒"}
  ],
  "logic": [{"from": "牛顿第三定律", "to": "动量守恒", "note": "作用力反作用力等大反向"}],
  "notes": "抽取时的注意事项（如某页是纯图无法取文）；没有则留空"
}"""

CHUNK_CHARS = 12000


def build_knowledge_prompt(text: str, *, chap: str, terms: "list[str] | None" = None) -> str:
    parts = [KNOWN_PROMPT, f"【章节】{chap}"]
    if terms:
        parts.append("【已标注知识点（优先沿用）】\n" + "、".join(terms[:80]))
    parts.append(f"【课堂资料文本】\n{text}")
    return "\n\n".join(parts)


def suggest_knowledge(client, ws, chap: str, *, model: "str | None" = None,
                      max_chars: int = 60000,
                      max_images: int = _VISION_MAX_IMAGES,
                      files: "list[str] | tuple[str, ...] | None" = None) -> dict:
    """读抽取文本 → LLM 抽知识点 → 写 `知识点清单.ai.json`（**不**生成生效 .md）。

    D228：`files` 非空时只基于选中文件识别知识点；适合教师逐文件排查/多选。
    """
    from ..grading.transcribe import parse_llm_json
    from ..grading.vocab import load_vocab

    selected = [_norm_source_rel(x) for x in (files or []) if str(x or "").strip()]
    selected = list(dict.fromkeys(selected))
    idx = read_index(ws, chap)
    idx_files = {str(s.get("file")) for s in (idx.get("sources") or [])
                 if isinstance(s, dict) and s.get("file")}
    if selected:
        missing = [x for x in selected if x not in idx_files]
        if missing:
            raise MaterialsError(
                "以下选中文件还没有抽取结果，请先点「① 抽取选中文件」或运行 "
                f"`assist materials extract --chap {chap} --file ...`：\n- "
                + "\n- ".join(missing))
    src = read_source_text(ws, chap, max_chars=max_chars, files=selected or None)
    # D131 补漏：图片型/扫描型 PDF 抽不到文字（`pdftotext` 给空），但 `pdftoppm`
    # 已把页图渲染出来。此时必须走**多模态**，否则"能抽取但 AI 看不到内容"。
    vision = read_source_images(ws, chap, max_images=max_images, files=selected or None)
    if not src["text"].strip() and not vision["images"]:
        where = ("选中的文件" if selected else f"章节 {chap}")
        raise MaterialsError(
            f"{where} 没有可用的抽取文本或页图。请先 "
            f"`assist materials extract --chap {chap}`" +
            (f" --file ..." if selected else "") +
            f"，并确认文件在 {chap_dir(ws, chap) / SOURCE}。")
    try:
        vocab_terms = [t.get("term") for t in load_vocab(ws).get("terms", []) if t.get("term")]
    except Exception:  # noqa: BLE001
        vocab_terms = []
    # D230：已有独立转写文本时优先用文本（即使图片还在）；否则纯图片资料才走多模态直读。
    has_transcript = bool(src.get("transcriptFiles"))
    use_vision = (bool(vision["images"]) and not has_transcript
                  and len(src["text"].strip()) < _VISION_TEXT_THRESHOLD)
    if use_vision:
        imgs = vision["images"][:vision["max_images"]]
        prompt = build_knowledge_prompt(
            src["text"] or "（本章资料以图片/扫描件为主，文字很少；请**依据所附图片**抽取）",
            chap=chap, terms=vocab_terms)
        n_total = len(vision["images"])
        n_used = len(imgs)
        prompt += ("\n\n【重要】本章资料主要是图片/扫描件：请仔细看所附每一页图片，"
                   "把图中出现的公式、定义、示意图所表达的物理概念都纳入知识点，"
                   "`evidence` 请注明「第 N 页/图」。")
        if n_total > n_used:
            # 不静默截断：明确告诉教师"只看了一部分"，避免以为覆盖全章
            prompt += (f"\n【注意】本章共 {n_total} 张页图，本次仅提供了前 {n_used} 张；"
                       f"如后半部分另有知识点，请用 `--max-images` 调大后重跑。")
        raw = client.chat_with_images(
            system_prompt="这是大学物理教学资料整理，内容完全学术。只输出严格 JSON。",
            user_text=prompt, image_paths=imgs, model=model,
            temperature=0.2, max_tokens=8192, step="materials")
    else:
        prompt = build_knowledge_prompt(src["text"], chap=chap, terms=vocab_terms)
        raw = client.chat(
            system_prompt="这是大学物理教学资料整理，内容完全学术。只输出严格 JSON。",
            user_text=prompt, model=model, temperature=0.2,
            response_format={"type": "json_object"}, max_tokens=8192, step="materials")
    data = parse_llm_json(raw)
    if not isinstance(data, dict):
        raise MaterialsError("AI 返回的不是 JSON 对象")
    knowledge = []
    for k in (data.get("knowledge") or []):
        if not isinstance(k, dict):
            continue
        term = str(k.get("term") or "").strip()
        if not term:
            continue
        knowledge.append({"term": term,
                          "aliases": [str(a).strip() for a in (k.get("aliases") or [])
                                      if str(a).strip()],
                          "importance": str(k.get("importance") or "supporting"),
                          # D138：章内主题（AI 归纳；缺失则空，渲染时归入「其他」）
                          "topic": str(k.get("topic") or "").strip(),
                          "evidence": str(k.get("evidence") or "")})
    out = {"version": 1, "chap": str(chap), "term_count": len(knowledge),
           "knowledge": knowledge,
           "logic": [x for x in (data.get("logic") or []) if isinstance(x, dict)],
           "notes": str(data.get("notes") or ""),
           "source": {"files": src["files"], "fileNames": src.get("fileNames") or [],
                      "transcriptFiles": src.get("transcriptFiles") or [],
                      "chars": src["chars"], "truncated": src["truncated"],
                      "selected": selected,
                      # 审计：本次是"纯文本"还是"看图"抽取（教师据此判断可信度）
                      "mode": "vision" if use_vision else "text",
                      "images_used": (len(vision["images"][:vision["max_images"]])
                                      if use_vision else 0)},
           "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S")}
    p = chap_dir(ws, chap) / KNOW_AI
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    out["file"] = str(p)
    return out


# ---------------- T21b：教师确认 → 生效清单 ----------------
_TOPIC_OTHER = "其他"


def render_knowledge_md(data: dict) -> str:
    chap = str(data.get("chap") or "")
    lines = [f"# 本章知识点清单（{chap}）", "",
             "> 本文件是**批阅依据**（`summary` 类作业会据此核对是否讲到）。",
             "> 由 AI 抽取、教师确认生成；可直接手工编辑，AI 不会覆盖。", ""]
    ks = [k for k in (data.get("knowledge") or []) if isinstance(k, dict)]
    core = [k for k in ks if str(k.get("importance")) == "core"]
    supp = [k for k in ks if str(k.get("importance")) != "core"]

    def _group(items: list[dict]) -> list[tuple[str, list[dict]]]:
        """D138：按 `topic` 分组（两层分类：章 → 主题 → 术语）。

        组顺序按**首次出现**（保持 AI/教师给的顺序，可读性更好）；
        无 topic 的条目归入「其他」，**排在最后**——绝不丢。
        """
        buckets: dict[str, list[dict]] = {}
        for k in items:
            t = str(k.get("topic") or "").strip() or _TOPIC_OTHER
            buckets.setdefault(t, []).append(k)
        named = [(t, v) for t, v in buckets.items() if t != _TOPIC_OTHER]
        other = [(t, v) for t, v in buckets.items() if t == _TOPIC_OTHER]
        return named + other

    def _render(items: list[dict], *, bold: bool) -> list[str]:
        out: list[str] = []
        has_topic = any(str(k.get("topic") or "").strip() for k in items)
        if not has_topic:
            # 完全没有主题信息：保持旧格式（无 ### 小节），旧文件/旧数据不受影响
            for k in items:
                ev = f" —— _{k['evidence']}_" if k.get("evidence") else ""
                al = f"（别名：{'、'.join(k['aliases'])}）" if k.get("aliases") else ""
                term = f"**{k.get('term')}**" if bold else str(k.get("term"))
                out.append(f"- {term}{al}{ev}")
            out.append("")
            return out
        for topic, group in _group(items):
            out.append(f"### {topic}")
            for k in group:
                ev = f" —— _{k['evidence']}_" if k.get("evidence") else ""
                al = f"（别名：{'、'.join(k['aliases'])}）" if k.get("aliases") else ""
                term = f"**{k.get('term')}**" if bold else str(k.get("term"))
                out.append(f"- {term}{al}{ev}")
            out.append("")
        return out

    if core:
        lines += ["## 核心知识点（必考）", ""] + _render(core, bold=True)
    if supp:
        lines += ["## 支撑知识点", ""] + _render(supp, bold=False)
    logic = [x for x in (data.get("logic") or []) if isinstance(x, dict)]
    if logic:
        lines += ["## 逻辑关系", ""]
        for x in logic:
            note = f"（{x.get('note')}）" if x.get("note") else ""
            lines.append(f"- {x.get('from')} → {x.get('to')}{note}")
        lines.append("")
    if data.get("notes"):
        lines += ["## 抽取备注", "", str(data["notes"]), ""]
    lines += ["---", f"*共 {len(ks)} 个知识点 · 生成于 {data.get('generatedAt') or ''}*"]
    return "\n".join(lines).strip() + "\n"


def confirm_knowledge(ws, chap: str, *, force: bool = False) -> dict:
    """把 `知识点清单.ai.json` 固化为生效的 `知识点清单.md`（AI **不**覆盖已有 .md）。"""
    d = chap_dir(ws, chap)
    ai = d / KNOW_AI
    if not ai.is_file():
        raise MaterialsError(f"没有待确认的 AI 建议：{ai.name} 不存在。"
                             f"请先运行 `assist materials suggest --chap {chap}`。")
    md = d / KNOW_MD
    if md.is_file() and not force:
        return {"ok": False, "error": f"{KNOW_MD} 已存在（AI 不覆盖教师已确认清单）",
                "hint": "确需覆盖请加 --force（旧版会记入 journal）", "file": str(md)}
    data = json.loads(ai.read_text(encoding="utf-8"))
    old = md.read_text(encoding="utf-8") if md.is_file() else ""
    md.write_text(render_knowledge_md(data), encoding="utf-8")
    _journal(d, {"action": "confirm", "chap": str(chap),
                 "terms": [k.get("term") for k in (data.get("knowledge") or [])],
                 "replaced_existing": bool(old), "ts": _ts()})
    return {"ok": True, "file": str(md), "terms": len(data.get("knowledge") or [])}


def _journal(d: Path, rec: dict) -> None:
    try:
        with (d / KNOW_JOURNAL).open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[资料] journal 写入失败：{str(exc)[:120]}")


def _ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def read_knowledge_md(ws, chap: str) -> str:
    """读生效清单（`summary` 批阅用）；没有则返回空串。"""
    try:
        p = chap_dir(ws, chap) / KNOW_MD
    except MaterialsError:
        return ""
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


def knowledge_terms(ws, chap: str) -> list[str]:
    """生效清单里的知识点术语（供与题库 `related` 比对/批阅提示）。

    D138：兼容两种格式——旧的扁平列表（`## 核心知识点` 下直接 `- 术语`）与
    新的按主题分节（`### 主题` 下的 `- 术语`）。只认 `- `/`* ` 行，
    `###` 是分节标题**不是**术语。
    """
    md = read_knowledge_md(ws, chap)
    terms: list[str] = []
    in_logic = False
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("## "):
            # 进入「逻辑关系」段后不再把 `- A → B` 当术语（旧实现靠 "→" 过滤）
            in_logic = "逻辑关系" in s
            continue
        if not s.startswith(("- ", "* ")):
            continue
        if in_logic:
            continue
        s = s[2:].split("——")[0].split("（")[0].strip()
        s = s.strip("*").strip()
        if s and "→" not in s and s not in terms:
            terms.append(s)
    return terms


def knowledge_topics(ws, chap: str) -> dict[str, list[str]]:
    """D138：生效清单 → `{主题: [术语...]}`（报告按主题分组用）。

    无 `###` 分节（旧格式）时，全部术语归到 `"其他"`。
    """
    md = read_knowledge_md(ws, chap)
    out: dict[str, list[str]] = {}
    cur = _TOPIC_OTHER
    in_logic = False
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("### "):
            cur = s[4:].strip() or _TOPIC_OTHER
            out.setdefault(cur, [])
            continue
        if s.startswith("## "):
            in_logic = "逻辑关系" in s
            continue
        if not s.startswith(("- ", "* ")) or in_logic:
            continue
        t = s[2:].split("——")[0].split("（")[0].strip().strip("*").strip()
        if t and "→" not in t:
            out.setdefault(cur, []).append(t)
    return out


# ---------------- D229：抽取详情与识别诊断 ----------------
def extract_info(ws, chap: str, file_name: str, *, preview_chars: int = 6000) -> dict:
    """查看单个原件「抽取出了什么」：元数据 + 文本预览 + 图片清单。

    PWA 的「抽取信息」弹窗使用；只读，不调用模型。
    """
    rel = _norm_source_rel(file_name)
    idx = read_index(ws, chap)
    src = next((s for s in (idx.get("sources") or [])
                if isinstance(s, dict) and str(s.get("file") or "") == rel), None)
    out: dict = {"ok": True, "chap": chap, "file": rel}
    if not src:
        out.update({"ok": False, "indexed": False,
                    "error": "该文件还没有抽取结果。请先抽取该文件。"})
        return out
    d = chap_dir(ws, chap)
    ex = src.get("extract") or {}
    p = d / rel
    out.update({
        "indexed": True,
        "exists": p.is_file(),
        "kind": str(src.get("kind") or ""),
        "bytes": int(src.get("bytes") or (p.stat().st_size if p.is_file() else 0)),
        "mtime": str(src.get("mtime") or ""),
        "sha256": str(src.get("sha256") or ""),
        "engine": str(ex.get("engine") or ""),
        "chars": int(ex.get("chars") or 0),
        "slides": int(ex.get("slides") or 0) if ex.get("slides") is not None else 0,
        "pages": int(ex.get("pages") or 0),
        "imageCount": len(ex.get("images") or []),
    })
    # 文本预览：兼容绝对路径与相对章节目录两种历史写法。
    tf = str(ex.get("text_file") or "")
    if tf:
        tp = Path(tf)
        if not tp.is_file():
            tp = d / tf
        if tp.is_file():
            txt = tp.read_text(encoding="utf-8", errors="replace")
            out["textFile"] = str(tp.relative_to(d)).replace("\\", "/") if tp.is_relative_to(d) else tp.name
            out["textPreview"] = txt[:max(1, int(preview_chars))]
            out["textTruncated"] = len(txt) > int(preview_chars)
            out["textCharsTotal"] = len(txt)
    # D230：若已做图片转写，单独展示转写文本预览与元数据。
    tr = ex.get("transcript") if isinstance(ex.get("transcript"), dict) else {}
    if tr:
        out["transcript"] = {
            "engine": str(tr.get("engine") or ""),
            "chars": int(tr.get("chars") or 0),
            "pages": int(tr.get("pages") or 0),
            "pagesTotal": int(tr.get("pages_total") or 0),
            "failedPages": list(tr.get("failedPages") or []),
            "generatedAt": str(tr.get("generatedAt") or ""),
            "provider": str(tr.get("provider") or ""),
            "model": str(tr.get("model") or ""),
            "textFile": str(tr.get("text_file") or ""),
        }
        ttp = Path(str(tr.get("text_file") or ""))
        if not ttp.is_file():
            ttp = d / str(tr.get("text_file") or "")
        if ttp.is_file():
            ttxt = ttp.read_text(encoding="utf-8", errors="replace")
            out["transcriptPreview"] = ttxt[:max(1, int(preview_chars))]
            out["transcriptTruncated"] = len(ttxt) > int(preview_chars)
    # 图片清单（PDF 页图/直接图片）：只回文件名与存在性，避免暴露整段绝对路径。
    imgs = []
    for one in (ex.get("images") or []):
        ip = Path(str(one))
        if not ip.is_file():
            ip2 = d / str(one)
            if ip2.is_file():
                ip = ip2
        imgs.append({"name": ip.name, "exists": ip.is_file()})
    out["images"] = imgs
    return out


def source_selection_diagnostics(ws, chap: str,
                                 files: "list[str] | tuple[str, ...] | None" = None) -> dict:
    """D229：不调用模型的识别前诊断——选中文件、抽取文本、页图、可识别性。"""
    selected_paths, missing_physical = resolve_source_selection(ws, chap, files)
    selected = [str(p.relative_to(chap_dir(ws, chap))).replace("\\", "/")
                for p in selected_paths]
    idx = read_index(ws, chap)
    idx_files = {str(s.get("file")) for s in (idx.get("sources") or [])
                 if isinstance(s, dict) and s.get("file")}
    missing_indexed = [x for x in selected if x not in idx_files]
    src = read_source_text(ws, chap, files=selected or None)
    vision = read_source_images(ws, chap, files=selected or None)
    text = str(src.get("text") or "").strip()
    images = list(vision.get("images") or [])
    transcript_files = src.get("transcriptFiles") or []
    mode = ("vision" if (images and not transcript_files
                         and len(text) < _VISION_TEXT_THRESHOLD)
            else ("text" if text else "none"))
    warnings: list[str] = []
    if missing_physical:
        warnings.append("有选中原件不存在：" + "、".join(missing_physical))
    if missing_indexed:
        warnings.append("有选中文件尚未抽取：" + "、".join(missing_indexed))
    if not text and not images:
        warnings.append("选中范围没有可用文本或页图，先抽取后再识别。")
    if text and len(text) >= 50000:
        warnings.append(f"文本约 {len(text)} 字，可能接近模型上下文上限；建议只选 1–2 个文件分批识别。")
    if images and len(images) > _VISION_MAX_IMAGES:
        warnings.append(f"页图共 {len(images)} 张，本次最多送 {_VISION_MAX_IMAGES} 张。")
    needs_transcription = bool(images) and not text and not transcript_files
    if needs_transcription:
        warnings.append(
            "当前资料没有文字层也没有转写文本，将直接走视觉模型；建议先执行「转写选中文件」"
            "以便核对转写内容并降低识别失败风险。")
    return {
        "ok": not missing_physical and not missing_indexed and bool(text or images),
        "chap": chap,
        "selectedFiles": selected,
        "selectedCount": len(selected),
        "missingPhysical": missing_physical,
        "missingIndexed": missing_indexed,
        "textFiles": src.get("fileNames") or [],
        "transcriptFiles": transcript_files,
        "chars": len(text),
        "imageCount": len(images),
        "mode": mode,
        "needsTranscription": needs_transcription,
        "warnings": warnings,
    }

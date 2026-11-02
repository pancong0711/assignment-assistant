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


def extract_office(p: Path, out_txt: Path) -> dict:
    """pptx/docx/xlsx → 纯文本。首选 officecli，回退 soffice→pdf→pdftoppm/pdftotext。"""
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
        f"无法抽取 {p.name}：officecli 与 LibreOffice 均不可用或失败。"
        f"请安装 officecli（推荐），或先把该文件另存为 PDF 再放入 _source/。")


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
def extract_chap(ws, chap: str, *, force: bool = False) -> dict:
    """抽取某章节全部资料 → 写 `索引.json` + `_extract/`（sha256 增量）。"""
    d = ensure_chap(ws, chap)
    ex = d / EXTRACT
    old = {s.get("file"): s for s in (read_index(ws, chap).get("sources") or [])
           if isinstance(s, dict)}
    out_sources: list[dict] = []
    skipped, errors = [], []
    for p in list_sources(ws, chap):
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
            "sources": len(out_sources), "skipped_unchanged": skipped,
            "chars": total_chars, "errors": errors}


def read_source_text(ws, chap: str, *, max_chars: int = 0) -> dict:
    """汇总本章全部抽取文本（供 AI 抽取知识点）。返回 {text, chars, files, missing}。"""
    idx = read_index(ws, chap)
    d = chap_dir(ws, chap)
    parts: list[str] = []
    files = 0
    for s in idx.get("sources") or []:
        tf = str((s.get("extract") or {}).get("text_file") or "")
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
            files += 1
    text = "\n\n".join(parts)
    truncated = False
    if max_chars and len(text) > max_chars:
        text = text[:max_chars]
        truncated = True
    return {"text": text, "chars": len(text), "files": files,
            "truncated": truncated,
            "has_index": bool((idx.get("sources") or []))}


# ---------------- T21a：AI 抽取「本章知识点 + 逻辑关系」 ----------------
KNOWN_PROMPT = """你是大学物理教研组老师。下面是一门课的**课堂资料文本**（授课 PPT / 讲义 / 授课计划）。
请抽出这一章学生应当掌握的**知识点**及其**逻辑关系**，供教师核对后作为作业批阅依据。

【要求】
1. `knowledge`：知识点术语，用规范物理概念名（如 动量守恒、完全弹性碰撞、安培环路定理），
   **不要**写成整句、不要带题号；
2. 每条必须给 `evidence`：**引用资料中的原话或页/幻灯片编号**，不得凭空编造；
   `importance`：core=本章核心必考 / supporting=支撑性（公式变形、单位、特例）；
3. `logic`：知识点之间的先后/推导关系（`from` → `to`），`note` 说明依据；
4. 若资料里已给出「已标注知识点」，**优先原样沿用**其中的术语；
5. 术语 5–20 个；宁可少而准，不要凑数。

【输出格式（严格 JSON）】
{
  "knowledge": [
    {"term": "动量守恒", "aliases": ["动量守恒定律"], "importance": "core",
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
                      max_chars: int = 60000) -> dict:
    """读抽取文本 → LLM 抽知识点 → 写 `知识点清单.ai.json`（**不**生成生效 .md）。"""
    from ..grading.transcribe import parse_llm_json
    from ..grading.vocab import load_vocab

    src = read_source_text(ws, chap, max_chars=max_chars)
    if not src["text"].strip():
        raise MaterialsError(
            f"章节 {chap} 没有可用的抽取文本。请先 `assist materials extract --chap {chap}`，"
            f"并把 PPT/PDF 放进 {chap_dir(ws, chap) / SOURCE}。")
    try:
        vocab_terms = [t.get("term") for t in load_vocab(ws).get("terms", []) if t.get("term")]
    except Exception:  # noqa: BLE001
        vocab_terms = []
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
                          "evidence": str(k.get("evidence") or "")})
    out = {"version": 1, "chap": str(chap), "term_count": len(knowledge),
           "knowledge": knowledge,
           "logic": [x for x in (data.get("logic") or []) if isinstance(x, dict)],
           "notes": str(data.get("notes") or ""),
           "source": {"files": src["files"], "chars": src["chars"],
                      "truncated": src["truncated"]},
           "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S")}
    p = chap_dir(ws, chap) / KNOW_AI
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    out["file"] = str(p)
    return out


# ---------------- T21b：教师确认 → 生效清单 ----------------
def render_knowledge_md(data: dict) -> str:
    chap = str(data.get("chap") or "")
    lines = [f"# 本章知识点清单（{chap}）", "",
             "> 本文件是**批阅依据**（`summary` 类作业会据此核对是否讲到）。",
             "> 由 AI 抽取、教师确认生成；可直接手工编辑，AI 不会覆盖。", ""]
    ks = [k for k in (data.get("knowledge") or []) if isinstance(k, dict)]
    core = [k for k in ks if str(k.get("importance")) == "core"]
    supp = [k for k in ks if str(k.get("importance")) != "core"]
    if core:
        lines += ["## 核心知识点（必考）", ""]
        for k in core:
            ev = f" —— _{k['evidence']}_" if k.get("evidence") else ""
            al = f"（别名：{'、'.join(k['aliases'])}）" if k.get("aliases") else ""
            lines.append(f"- **{k.get('term')}**{al}{ev}")
        lines.append("")
    if supp:
        lines += ["## 支撑知识点", ""]
        for k in supp:
            ev = f" —— _{k['evidence']}_" if k.get("evidence") else ""
            lines.append(f"- {k.get('term')}{ev}")
        lines.append("")
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
    """生效清单里的知识点术语（供与题库 `related` 比对/批阅提示）。"""
    md = read_knowledge_md(ws, chap)
    terms: list[str] = []
    for line in md.splitlines():
        s = line.strip()
        if not s.startswith(("- ", "* ")):
            continue
        s = s[2:].split("——")[0].split("（")[0].strip()
        s = s.strip("*").strip()
        if s and "→" not in s and s not in terms:
            terms.append(s)
    return terms

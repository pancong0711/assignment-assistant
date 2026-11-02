"""vocab.py — D130-T8：**受控知识点词表** `<ws>/knowledge-terms.json`。

用途（docs/78 §3.7）：
- 由题库 `related` 列**自动汇总** + 人工维护（别名、停用）；
- 标注知识点时**优先选词表内术语**（避免同义漂移：动量守恒 / 动量守恒定律 / 动量守恒律）；
- 也是未来 `summary` 接入课堂资料（P2）的中间层。

schema:
    {"version": 1,
     "terms": [{"term": "动量守恒", "source": "human|ai|kb",
                "aliases": ["动量守恒定律"], "chapter": "chap04",
                "count": 3, "updatedAt": "..."}]}

设计约束：
- 只做**扁平**术语（知识点层级暂不做，docs/78 §7）；
- 汇总时**不删除**人工维护的术语与别名；
- 词表本身不改题库（写题库在 T6 `kb tag-knowledge`）。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from loguru import logger

VOCAB_FILE = "knowledge-terms.json"
MAX_TERM_LEN = 40
MAX_TERMS = 2000

# 分隔符标准化：中文逗号/分号/顿号/斜杠 → 英文逗号（术语归一前置步骤，docs/78 §3.6）
_SEP_RE = re.compile(r"[，;；、/|]+")


def vocab_path(ws) -> Path:
    return Path(ws).resolve() / VOCAB_FILE


def split_terms(raw: str) -> list[str]:
    """把 `related` 字段拆成术语列表（先标准化分隔符，再去空白/去重）。"""
    t = _SEP_RE.sub(",", str(raw or ""))
    out: list[str] = []
    for x in t.split(","):
        x = x.strip().strip("。.").strip()
        if x and x not in out:
            out.append(x)
    return out


def join_terms(terms: list[str]) -> str:
    """术语列表 → 题库 `related` 列写法（英文逗号，无空格）。"""
    seen: list[str] = []
    for x in terms or []:
        x = str(x or "").strip()
        if x and x not in seen:
            seen.append(x)
    return ",".join(seen)


def empty_vocab() -> dict:
    return {"version": 1, "terms": []}


def load_vocab(ws) -> dict:
    """读词表；缺失返回空词表（**不**落盘——词表由 T6/T8 显式生成）。"""
    p = vocab_path(ws)
    if not p.is_file():
        return empty_vocab()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("terms"), list):
            raise ValueError("结构不合法")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[词表] {p.name} 解析失败（{str(exc)[:80]}），按空词表处理")
        return empty_vocab()
    data.setdefault("version", 1)
    data["terms"] = [t for t in data["terms"] if isinstance(t, dict) and t.get("term")]
    return data


def save_vocab(ws, vocab: dict) -> Path:
    p = vocab_path(ws)
    terms = []
    for t in (vocab.get("terms") or []):
        term = str(t.get("term") or "").strip()
        if not term:
            continue
        terms.append({"term": term,
                      "source": str(t.get("source") or "human"),
                      "aliases": [str(a).strip() for a in (t.get("aliases") or [])
                                  if str(a).strip()],
                      "chapter": str(t.get("chapter") or ""),
                      "count": int(t.get("count") or 0),
                      "updatedAt": str(t.get("updatedAt") or "")})
    terms = terms[:MAX_TERMS]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"version": int(vocab.get("version") or 1), "terms": terms},
                            ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def term_index(vocab: dict) -> dict[str, dict]:
    """term / alias（小写）→ 词条。供对齐与"是否已在词表"判断。"""
    idx: dict[str, dict] = {}
    for t in (vocab.get("terms") or []):
        idx[str(t.get("term")).strip().lower()] = t
        for a in (t.get("aliases") or []):
            idx.setdefault(str(a).strip().lower(), t)
    return idx


def canonical(vocab: dict, term: str) -> str:
    """把别名映射到词表正名；不在词表则原样返回（去空白）。"""
    t = str(term or "").strip()
    hit = term_index(vocab).get(t.lower())
    return str(hit.get("term")) if hit else t


def harvest(ws, *, write: bool = False) -> dict:
    """从题库 `related` 列**自动汇总**词表（`kb` 来源）。

    - 人工/已有词条的 term、aliases、source 保留（不被 AI/kb 覆盖）；
    - 只补齐新术语与计数；
    - `write=False` 时只返回建议（dry-run）。
    """
    from ..files.kb_io import read_kb
    kb_data = read_kb(Path(ws).resolve() / "kb")
    counts: dict[str, dict] = {}
    for kind, chapters in (kb_data or {}).items():
        if not isinstance(chapters, dict):
            continue
        for chap, entries in chapters.items():
            for e in (entries or []):
                if not isinstance(e, dict):
                    continue
                for term in split_terms(str(e.get("related") or "")):
                    key = term.lower()
                    rec = counts.setdefault(key, {"term": term, "count": 0, "chapter": chap,
                                                   "kind": kind})
                    rec["count"] += 1
    vocab = load_vocab(ws)
    idx = term_index(vocab)
    added, updated = [], []
    for key, rec in counts.items():
        hit = idx.get(key)
        if hit is not None:
            hit["count"] = int(rec["count"])
            hit["updatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
            updated.append(hit["term"])
        else:
            term = rec["term"][:MAX_TERM_LEN]
            vocab["terms"].append({"term": term, "source": "kb", "aliases": [],
                                   "chapter": rec["chapter"], "count": int(rec["count"]),
                                   "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S")})
            idx[term.lower()] = vocab["terms"][-1]
            added.append(term)
    vocab["terms"].sort(key=lambda t: (-int(t.get("count") or 0), str(t.get("term"))))
    out = {"ok": True, "added": added, "updated": updated,
           "total": len(vocab["terms"]), "write": bool(write),
           "file": str(vocab_path(ws))}
    if write:
        save_vocab(ws, vocab)
    out["terms"] = vocab["terms"]
    return out


def add_term(ws, term: str, *, aliases: "list[str] | None" = None,
             source: str = "human") -> dict:
    """人工新增/更新一个术语（同义词合并到 aliases）。"""
    term = str(term or "").strip()
    if not term:
        return {"ok": False, "error": "术语不能为空"}
    if len(term) > MAX_TERM_LEN:
        return {"ok": False, "error": f"术语过长（≤{MAX_TERM_LEN} 字）"}
    vocab = load_vocab(ws)
    idx = term_index(vocab)
    hit = idx.get(term.lower())
    if hit is None:
        hit = {"term": term, "source": source, "aliases": [], "chapter": "",
               "count": 0, "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S")}
        vocab["terms"].append(hit)
    for a in (aliases or []):
        a = str(a or "").strip()
        if a and a != hit["term"] and a not in hit["aliases"]:
            hit["aliases"].append(a)
    hit["updatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_vocab(ws, vocab)
    return {"ok": True, "term": hit, "file": str(vocab_path(ws))}

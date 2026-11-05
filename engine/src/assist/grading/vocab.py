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

D138（docs/88）：两层分类 `chapter`（章）→ `topic`（章内的"块"）→ `term`。
**不做** `parent/child` 树、不做 DAG（docs/85 方案 B 被采纳）。

设计约束：
- 只做**两层**分类（章 + 主题）；无 `topic` 时按章归组；
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


# ---------------- D168：别名归并 + 标签（docs/112-D168 §4.1） ----------------
# 问题：`动量守恒` / `动量守恒定律` / `动量守恒律` 是同一概念，
# 但 split_terms 只做分隔符标准化 → 统计时被拆成 4 个条目 → 共现与失误率失真。
# 解决：词表 term 自带 aliases，统计前先把别名归一到规范名。


def alias_map(vocab: dict) -> dict[str, str]:
    """构造「别名/规范名 → 规范名」映射（大小写不敏感，去空白）。

    规范名本身也映射到自己，便于统一调用。
    """
    out: dict[str, str] = {}
    for t in (vocab or {}).get("terms") or []:
        if not isinstance(t, dict):
            continue
        term = str(t.get("term") or "").strip()
        if not term:
            continue
        out[_norm_key(term)] = term
        for a in (t.get("aliases") or []):
            al = str(a or "").strip()
            # 别名冲突时**保留先出现的**（并告警）——不静默改写，避免调试困难
            if al and _norm_key(al) not in out:
                out[_norm_key(al)] = term
    return out


def _norm_key(s: str) -> str:
    """比较用的归一键：去空白 + 小写（中文大小写无影响，英文术语有效）。"""
    return re.sub(r"\s+", "", str(s or "")).lower()


def resolve_canonical(term: str, amap: dict[str, str]) -> str:
    """把一个术语归一到规范名；不在词表里的原样返回。

    注意：与既有 `canonical(vocab, term)`（按 term 查词条 dict）**不是同一个东西**，
    这里只做「别名 → 规范名」的字符串映射。
    """
    t = str(term or "").strip()
    return amap.get(_norm_key(t), t)


def normalize_terms(terms: "list[str]", vocab: dict,
                    *, keep_unknown: bool = True) -> "tuple[list[str], list[str]]":
    """术语列表 → (规范术语列表, 词表外术语列表)。

    - 别名 → 规范名（去重、保序）；
    - `keep_unknown=True` 时词表外术语原样保留（默认；统计侧再决定要不要）。

    **词表为空时全部视为"已认可"**（D168 修正）：空词表意味着"还没建立词表"，
    此时把所有术语都打进 `unknown` 会让统计**完全空白**——那是错的。
    只有"建立了词表但术语不在其中"才算词表外。
    """
    amap = alias_map(vocab)
    known: set[str] = {_norm_key(v) for v in amap.values()}
    vocab_empty = not known
    out: list[str] = []
    unknown: list[str] = []
    for t in terms or []:
        raw = str(t or "").strip()
        if not raw:
            continue
        c = resolve_canonical(raw, amap)
        if vocab_empty or _norm_key(c) in known:
            if c not in out:
                out.append(c)
        else:
            if keep_unknown and raw not in out:
                out.append(raw)
            if raw not in unknown:
                unknown.append(raw)
    return out, unknown


def split_terms_normalized(raw: str, vocab: dict,
                           *, keep_unknown: bool = True) -> "tuple[list[str], list[str]]":
    """`split_terms` + 别名归并（统计入口统一用它）。"""
    return normalize_terms(split_terms(raw), vocab, keep_unknown=keep_unknown)


def term_tags(vocab: dict) -> dict[str, list[str]]:
    """术语 → 标签列表（如 ["模型"] / ["例"] / ["数学"]）。

    与 2508 `考点词表.yaml` 的 `tags` 对齐（docs/110 §1）。
    """
    out: dict[str, list[str]] = {}
    for t in (vocab or {}).get("terms") or []:
        if not isinstance(t, dict):
            continue
        term = str(t.get("term") or "").strip()
        if not term:
            continue
        tags = [str(x).strip() for x in (t.get("tags") or []) if str(x).strip()]
        if tags:
            out[term] = tags
    return out


def add_alias(ws, term: str, alias: str, *, source: str = "human") -> dict:
    """给某术语追加一个别名（教师/AI 归一后调用）。

    术语不存在时先创建（source 标传入值）。返回 {ok, term, aliases}。
    """
    term_s = str(term or "").strip()
    alias_s = str(alias or "").strip()
    if not term_s or not alias_s:
        return {"ok": False, "error": "term 与 alias 都不能为空"}
    if _norm_key(term_s) == _norm_key(alias_s):
        return {"ok": False, "error": "别名与规范名相同，无需添加"}
    data = load_vocab(ws)
    by_term = {str(t.get("term")): t for t in data["terms"]}
    t = by_term.get(term_s)
    if t is None:
        # 别名已被别的术语占用 → 拒绝（避免歧义）
        amap = alias_map(data)
        owner = amap.get(_norm_key(alias_s))
        if owner and owner != term_s:
            return {"ok": False,
                    "error": f"别名「{alias_s}」已属于术语「{owner}」，不能同时属于「{term_s}」"}
        t = {"term": term_s, "aliases": [alias_s], "source": source,
             "count": 0, "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S")}
        data["terms"].append(t)
    else:
        aliases = [str(a).strip() for a in (t.get("aliases") or []) if str(a).strip()]
        if alias_s in aliases:
            return {"ok": True, "term": term_s, "aliases": aliases, "unchanged": True}
        amap = alias_map(data)
        owner = amap.get(_norm_key(alias_s))
        if owner and owner != term_s:
            return {"ok": False,
                    "error": f"别名「{alias_s}」已属于术语「{owner}」"}
        aliases.append(alias_s)
        t["aliases"] = aliases
        t["updatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_vocab(ws, data)
    return {"ok": True, "term": term_s,
            "aliases": [str(a) for a in (t.get("aliases") or [])]}


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
    # D132-T18：叠加 <ws>/extensions/knowledge-terms.json（按 term 合并，扩展优先）
    try:
        from ..atopia import extensions as E
        # knowledge-terms.json 直接在 <ws>/ 下 → 其父目录就是 workspace 根
        ext = E.vocab_override(p.parent)
        if ext and isinstance(ext.get("terms"), list):
            by_term = {str(t.get("term")): t for t in data["terms"] if t.get("term")}
            for t in ext["terms"]:
                if isinstance(t, dict) and t.get("term"):
                    by_term[str(t["term"])] = t
            data["terms"] = list(by_term.values())
    except Exception:  # noqa: BLE001 —— 扩展异常不影响词表读取
        pass
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
                      # D138：章内"块"（可选）；空串表示未归类
                      "topic": str(t.get("topic") or "").strip(),
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
                                   "chapter": rec["chapter"], "topic": "",
                                   "count": int(rec["count"]),
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
             source: str = "human", topic: "str | None" = None,
             chapter: "str | None" = None) -> dict:
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
               "topic": "", "count": 0,
               "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S")}
        vocab["terms"].append(hit)
    # D138：topic / chapter 只在**显式传入**时改（None = 保持原值，不误清空）
    if topic is not None:
        hit["topic"] = str(topic or "").strip()
    if chapter is not None:
        hit["chapter"] = str(chapter or "").strip()
    for a in (aliases or []):
        a = str(a or "").strip()
        if a and a != hit["term"] and a not in hit["aliases"]:
            hit["aliases"].append(a)
    hit["updatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_vocab(ws, vocab)
    return {"ok": True, "term": hit, "file": str(vocab_path(ws))}

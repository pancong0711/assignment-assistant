"""termnorm.py — D130-T7：**知识点术语归一**（提议 → 教师勾选 → 执行 → 可回滚）。

口径（docs/78 §3.6）：
- AI **只提议**等价组 + 置信度，**默认不全选**；语义不同者显式警示且默认不勾；
- 教师勾选确认后才执行（CLI 用 `--apply --mapping`，PWA 用同一 mapping 结构）；
- 执行前展示影响面；执行后写**变更日志**，可 `--rollback` 回滚；
- 归一前先做**分隔符标准化**（`，`/`;`/`、`/`；` → `,`）。

为什么不做成"一键全并"：误合并会把两个不同考点并成一个，直接污染统计口径与后续
批阅术语提示；回滚日志是最后一道保险。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from loguru import logger

LOG_FILE = "kb/knowledge-normalize-log.jsonl"


def normalize_delimiters(raw: str) -> str:
    """分隔符标准化（归一前置步骤）。"""
    from .vocab import join_terms, split_terms
    return join_terms(split_terms(raw))


def collect_terms(kb_data: dict) -> dict[str, dict]:
    """汇总题库里出现过的全部术语（标准化后）→ {term: {count, chapters}}。"""
    from .vocab import split_terms
    out: dict[str, dict] = {}
    for kind, chapters in (kb_data or {}).items():
        if not isinstance(chapters, dict):
            continue
        for chap, entries in chapters.items():
            for e in (entries or []):
                if not isinstance(e, dict):
                    continue
                for t in split_terms(str(e.get("related") or "")):
                    rec = out.setdefault(t, {"count": 0, "chapters": [], "kind": kind})
                    rec["count"] += 1
                    if chap not in rec["chapters"]:
                        rec["chapters"].append(chap)
    return out


NORMALIZE_PROMPT = """你在整理大学物理题库的「知识点」标签术语。
下面是题库里出现过的全部知识点术语及其出现次数。请找出**语义等价**（同一个物理概念的不同叫法）的术语组。

【严格判定标准】
- 只有**所指概念完全相同**才能归为一组（例：「动量守恒」与「动量守恒定律」等价）；
- **语义不同的一律不得合并**（例：「动量守恒」与「动量定理」不同；「弹性碰撞」与「完全弹性碰撞」需谨慎，
  若题库语境一致可合并，但要在 warning 中标明）；
- 拿不准的**不要合并**，或合并但把 `confidence` 打到 0.6 以下并在 `warning` 说明。

【输出格式（严格 JSON）】
{
  "groups": [
    {"canonical": "建议保留的正名", "members": ["别名1", "别名2"],
     "confidence": 0.95, "reason": "为什么等价",
     "warning": "语义风险说明；无风险留空字符串"}
  ]
}
只输出确实需要合并的组；不需要合并的术语不要出现在输出里。"""


def propose_groups(client, terms: dict[str, dict], *, model: str | None = None) -> dict:
    """调 LLM 提议等价组（**只提议**，不改数据）。"""
    from .transcribe import parse_llm_json
    listing = "\n".join(f"- {t}（出现 {v['count']} 次）"
                        for t, v in sorted(terms.items(), key=lambda x: -x[1]["count"]))
    # D151：术语归一 system prompt 可被模板覆盖（不选模板 = 内置）
    from ..files.prompts import system_prompt_env
    _sys = system_prompt_env(
        "termnorm", "这是大学物理题库术语整理工作，内容完全学术。只输出严格 JSON。")
    raw = client.chat(
        system_prompt=_sys,
        user_text=f"{NORMALIZE_PROMPT}\n\n【题库术语】\n{listing}",
        model=model, temperature=0.1,
        response_format={"type": "json_object"}, max_tokens=4096, step="termnorm")
    data = parse_llm_json(raw)
    groups = data.get("groups") if isinstance(data, dict) else None
    clean: list[dict] = []
    for g in (groups or []):
        if not isinstance(g, dict):
            continue
        canonical = str(g.get("canonical") or "").strip()
        members = [str(m).strip() for m in (g.get("members") or []) if str(m).strip()]
        if not canonical or not members:
            continue
        # 正名本身也应视为组内成员，但执行时只替换别名 → 正名
        members = [m for m in members if m != canonical]
        if not members:
            continue
        try:
            conf = float(g.get("confidence"))
        except Exception:  # noqa: BLE001
            conf = 0.0
        clean.append({"canonical": canonical, "members": members,
                      "confidence": round(conf, 2),
                      "reason": str(g.get("reason") or ""),
                      "warning": str(g.get("warning") or ""),
                      # 默认**不全选**：低置信或带警示的默认不勾（教师可手动改）
                      "selected": bool(conf >= 0.9 and not str(g.get("warning") or "").strip())})
    return {"groups": clean, "terms": terms}


def build_mapping(groups: "list[dict]", selected: "list[dict] | None" = None) -> dict[str, str]:
    """等价组 → {别名: 正名}。

    - 传 `selected` → 只用这些组；
    - 否则用 `selected=True` 的组；
    - **若没有任何组带 selected 字段**（例如教师手写的 mapping 文件），
      视为"全部勾选"——手写文件的意图就是执行，静默产出空映射会让教师以为命令坏了。
    """
    if selected is not None:
        use = selected
    elif any("selected" in g for g in groups):
        use = [g for g in groups if g.get("selected")]
    else:
        use = list(groups)
    mapping: dict[str, str] = {}
    for g in use:
        canonical = str(g.get("canonical") or "").strip()
        if not canonical:
            continue
        for m in (g.get("members") or []):
            m = str(m).strip()
            if m and m != canonical:
                mapping[m] = canonical
    return mapping


def impact(ws, mapping: dict[str, str]) -> dict:
    """展示**影响面**：哪些题、哪一章、会把什么改成什么（执行前后对比）。"""
    from ..files.kb_io import read_kb
    from .vocab import join_terms, split_terms
    kb_data = read_kb(Path(ws).resolve() / "kb")
    affected: list[dict] = []
    for kind, chapters in (kb_data or {}).items():
        if not isinstance(chapters, dict):
            continue
        for chap, entries in chapters.items():
            for e in (entries or []):
                if not isinstance(e, dict):
                    continue
                terms = split_terms(str(e.get("related") or ""))
                if not terms:
                    continue
                new_terms = [mapping.get(t, t) for t in terms]
                new_terms = list(dict.fromkeys(new_terms))
                if new_terms != terms:
                    affected.append({"kb": kind, "chap": chap, "qid": str(e.get("id") or ""),
                                     "before": join_terms(terms),
                                     "after": join_terms(new_terms)})
    return {"count": len(affected), "items": affected,
            "mapping": mapping,
            "terms_before": len(set(sum((split_terms(x["before"]) for x in affected), []))),
            "terms_after": len(set(sum((split_terms(x["after"]) for x in affected), [])))}


def apply_mapping(ws, mapping: dict[str, str], *, dry_run: bool = False) -> dict:
    """执行归一（写题库 xlsx + 变更日志）。"""
    from ..files import kb_io
    from .vocab import join_terms, split_terms
    if not mapping:
        return {"ok": False, "error": "mapping 为空：没有勾选任何等价组"}
    imp = impact(ws, mapping)
    if dry_run:
        return {"ok": True, "dry_run": True, **imp}
    kb_dir = Path(ws).resolve() / "kb"
    snap = kb_io.snapshot(kb_dir)
    changed = 0
    by_kind: dict[str, dict] = {}
    for it in imp["items"]:
        by_kind.setdefault(it["kb"], {}).setdefault(it["chap"], []).append(it)
    for kind, chapters in by_kind.items():
        xlsx = kb_dir / f"{kind}.xlsx"
        if not xlsx.is_file():
            continue
        kb_data = kb_io.read_xlsx(xlsx, kb_dir) if kind != "translation" \
            else kb_io.read_translation(xlsx, kb_dir)
        for chap, items in chapters.items():
            want = {it["qid"]: it["after"] for it in items}
            for e in (kb_data.get(chap) or []):
                qid = str(e.get("id") or "")
                if qid in want:
                    e["related"] = want[qid]
                    changed += 1
        kb_io.write_chapters_preserving(xlsx, kb_data)
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "mapping": mapping,
           "changed": changed, "snapshot": [str(x) for x in snap],
           "items": imp["items"]}
    log = Path(ws).resolve() / LOG_FILE
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"ok": True, "changed": changed, "log": str(log),
            "snapshot": rec["snapshot"], "items": imp["items"]}


def last_log(ws) -> "dict | None":
    log = Path(ws).resolve() / LOG_FILE
    if not log.is_file():
        return None
    lines = [x for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
    return json.loads(lines[-1]) if lines else None


def rollback(ws, *, dry_run: bool = False) -> dict:
    """按**最后一条**变更日志回滚（把 after 改回 before）。"""
    from ..files import kb_io
    rec = last_log(ws)
    if not rec:
        return {"ok": False, "error": "没有可回滚的变更日志"}
    reverse: dict[str, str] = {}
    for it in rec.get("items") or []:
        for before_t, after_t in zip(str(it.get("before") or "").split(","),
                                     str(it.get("after") or "").split(",")):
            if before_t and after_t and before_t != after_t:
                reverse.setdefault(after_t, before_t)
    if not reverse:
        return {"ok": False, "error": "日志里没有可反向映射"}
    if dry_run:
        return {"ok": True, "dry_run": True, "reverse": reverse,
                "items": rec.get("items")}
    kb_dir = Path(ws).resolve() / "kb"
    kb_io.snapshot(kb_dir)
    changed = 0
    by_kind: dict[str, dict] = {}
    for it in rec.get("items") or []:
        by_kind.setdefault(it["kb"], {}).setdefault(it["chap"], []).append(it)
    for kind, chapters in by_kind.items():
        xlsx = kb_dir / f"{kind}.xlsx"
        if not xlsx.is_file():
            continue
        kb_data = kb_io.read_xlsx(xlsx, kb_dir) if kind != "translation" \
            else kb_io.read_translation(xlsx, kb_dir)
        for chap, items in chapters.items():
            want = {it["qid"]: it["before"] for it in items}
            for e in (kb_data.get(chap) or []):
                qid = str(e.get("id") or "")
                if qid in want:
                    e["related"] = want[qid]
                    changed += 1
        kb_io.write_chapters_preserving(xlsx, kb_data)
    logger.info(f"[术语归一] 已回滚 {changed} 题")
    return {"ok": True, "rolled_back": changed, "reverse": reverse}

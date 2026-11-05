"""related_tidy.py — D166：「AI 再整理」知识点。

教师诉求（docs/109 §2.3）：现有关联知识点可能重复、同义漂移、粒度不一，
需要 AI 做**归一 / 合并 / 拆分**，但**必须教师逐题确认**后才生效。

三条硬口径（docs/109 §5）：
1. `pinned_by=human` 的题默认**跳过**（教师手工标的，AI 不碰；除非显式 force）；
2. 词表术语优先（词表外的保留并标记 `vocabMisses`，提示教师补词表）；
3. **不自动改**答案文本里的【知识点】行（历史版本可追溯，改了会失真）。

设计原则：**纯函数产出建议，不落盘**；落盘走 `rubric.apply_related`（自动快照 + 版本）。
"""
from __future__ import annotations

from loguru import logger

TIDY_PROMPT = """你是一位大学物理教研组老师，正在**整理题库的知识点标注**。

你的任务：把下面每道题的现有知识点做整理，输出**规范后的知识点列表**。

【整理规则】
1. **同义合并**：同一概念的不同写法合并为一个（如「动量守恒律」→「动量守恒」）；
2. **优先使用受控词表术语**（若给了词表，尽量从词表里选；词表没有的才保留原词）；
3. **保留原意**：不要凭空增加题目没涉及的知识点，也不要删掉确实考到的；
4. **粒度一致**：同一层级的术语不要一题粗一题细（如「力学」太粗，「斜抛运动水平方向速度」太细）；
5. **不重复**：同一术语只出现一次；
6. **数量合理**：每题 2–6 个为宜（原题标注本来就很少时不要硬凑）。

【输出格式（严格 JSON）】
{{
  "items": [
    {{"qid": "题号原样返回",
      "terms": ["整理后的知识点1", "整理后的知识点2"],
      "merged_from": ["被合并掉的旧写法"],
      "dropped": ["被删除的旧术语（连同理由见 note）"],
      "note": "一句话说明改了什么；没改就写「无需调整」"}}
  ]
}}

只输出上面这个 JSON，不要任何解释文字。"""


def build_tidy_prompt(questions: "list[dict]", vocab_terms: "list[str] | None" = None) -> str:
    """构造再整理 prompt：题目 + 现有知识点 + 受控词表。"""
    parts = [TIDY_PROMPT]
    if vocab_terms:
        parts.append("【受控词表（优先从中选词）】\n" + "、".join(vocab_terms[:80]))
    lines = []
    for q in questions:
        terms = [str(t).strip() for t in (q.get("terms") or []) if str(t).strip()]
        lines.append(f"- qid: {q.get('qid')}\n  题目：{str(q.get('content') or '')[:200]}\n"
                     f"  现有知识点：{'、'.join(terms) if terms else '（空）'}")
    parts.append("【待整理的题目】\n" + "\n".join(lines))
    return "\n\n".join(parts)


def collect_targets(ws, kb_data: dict, *, kind: str, chap: str,
                    ids: "list[str] | None" = None,
                    force: bool = False) -> dict:
    """挑出待整理的题目；跳过教师锁定的（除非 force）。"""
    from . import rubric as RB

    want = {str(i) for i in (ids or []) if str(i).strip()}
    todo, skipped = [], []
    for qid_kind, chapters in (kb_data or {}).items():
        if kind and qid_kind != kind:
            continue
        for chap_name, entries in (chapters or {}).items():
            if chap and chap_name != chap:
                continue
            for e in (entries or []):
                qid = str(e.get("id") or "").strip()
                if not qid:
                    continue
                if want and qid not in want:
                    continue
                related = str(e.get("related") or "")
                if RB.is_pinned_by_human(ws, qid_kind, chap_name, qid) and not force:
                    skipped.append({"kb": qid_kind, "chap": chap_name, "qid": qid,
                                    "reason": "教师已锁定（pinned_by=human）"})
                    continue
                terms = [t for t in related.replace("，", ",").replace("、", ",")
                         .split(",") if t.strip()]
                todo.append({"kb": qid_kind, "chap": chap_name, "qid": qid,
                             "content": str(e.get("content") or ""),
                             "related": related,
                             "terms": [t.strip() for t in terms]})
    return {"todo": todo, "skipped": skipped}


def build_diff(old_terms: "list[str]", new_terms: "list[str]",
               merged_from: "list[str] | None" = None,
               dropped: "list[str] | None" = None) -> dict:
    """计算一题的差异（供前端 diff 表逐题勾选）。"""
    old_s = [str(t).strip() for t in (old_terms or []) if str(t).strip()]
    new_s = [str(t).strip() for t in (new_terms or []) if str(t).strip()]
    added = [t for t in new_s if t not in old_s]
    removed = [t for t in old_s if t not in new_s]
    return {"before": old_s, "after": new_s, "added": added, "removed": removed,
            "merged_from": list(merged_from or []), "dropped": list(dropped or []),
            "changed": bool(added or removed)}


def tidy_related(client, ws, *, kind: str, chap: str, ids: "list[str] | None" = None,
                 force: bool = False, model: "str | None" = None,
                 max_questions: int = 40) -> dict:
    """让 AI 整理知识点，**只产出建议**（不落盘）。

    返回 {ok, items:[{qid, kb, chap, diff, note}], skipped, planned, error?}
    """
    from ..files import kb_io
    from . import rubric as RB
    from .transcribe import parse_llm_json
    from .vocab import load_vocab

    ws_path = __import__("pathlib").Path(ws).resolve()
    kb_data = kb_io.read_kb(ws_path / "kb")
    picked = collect_targets(ws_path, kb_data, kind=kind, chap=chap, ids=ids, force=force)
    todo = picked["todo"][:max_questions]
    if not todo:
        return {"ok": True, "items": [], "skipped": picked["skipped"], "planned": 0,
                "note": "没有需要整理的题目（可能都被教师锁定了）"}
    try:
        vocab_terms = [str(t.get("term")).strip()
                       for t in (load_vocab(ws_path).get("terms") or []) if t.get("term")]
    except Exception:  # noqa: BLE001
        vocab_terms = []
    prompt = build_tidy_prompt(todo, vocab_terms)
    try:
        raw = client.chat(
            system_prompt="这是大学物理教研工作，内容完全学术。只输出严格 JSON。",
            user_text=prompt, model=model, temperature=0.2,
            response_format={"type": "json_object"}, max_tokens=4096, step="rubric")
        data = parse_llm_json(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[知识点整理] LLM 失败：{exc}")
        return {"ok": False, "error": str(exc)[:300], "items": [],
                "skipped": picked["skipped"], "planned": len(todo)}

    by_qid = {str(t["qid"]): t for t in todo}
    items = []
    for it in (data.get("items") or []):
        if not isinstance(it, dict):
            continue
        qid = str(it.get("qid") or "").strip()
        src = by_qid.get(qid)
        if not src:
            continue
        new_terms = [str(x).strip() for x in (it.get("terms") or []) if str(x).strip()]
        diff = build_diff(src["terms"], new_terms, it.get("merged_from"), it.get("dropped"))
        items.append({"qid": qid, "kb": src["kb"], "chap": src["chap"],
                      "diff": diff, "note": str(it.get("note") or "")})
    return {"ok": True, "items": items, "skipped": picked["skipped"],
            "planned": len(todo), "vocabTerms": len(vocab_terms),
            "returned": len(items)}


def apply_tidy(ws, items: "list[dict]", *, source: str = "ai") -> dict:
    """把教师勾选的整理结果写回（追加版本 + 自动快照）。"""
    from . import rubric as RB

    updates = []
    for it in (items or []):
        if not isinstance(it, dict):
            continue
        qid = str(it.get("qid") or "").strip()
        kb = str(it.get("kb") or "").strip()
        chap = str(it.get("chap") or "").strip()
        terms = it.get("terms")
        if not (qid and kb and chap) or not isinstance(terms, list):
            continue
        updates.append({
            "kb": kb, "chap": chap, "qid": qid,
            "related": ",".join(str(t).strip() for t in terms if str(t).strip()),
            "meta": {"source": source, "note": str(it.get("note") or "AI 再整理")},
        })
    if not updates:
        return {"ok": True, "written": 0, "note": "没有可写入的条目"}
    return RB.apply_related(ws, updates)

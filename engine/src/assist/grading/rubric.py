"""rubric.py — D130-T5/T6：AI 生成**评阅要点** + 知识点标注。

两件事，一次调用产出（省 token、且要点与知识点天然对齐）：
1. **评阅要点**（rubric）：参考解答 / 评阅要点 / 知识点 / 示意图要求
   → 写入答案版本库 `<ws>/kb/solutions/<scope>.json`，**source=ai、默认不置顶**；
   教师确认后 `kb solution pin` 才成为生效答案（验收 5）。
2. **知识点标注**（related）：写回题库 xlsx `related` 列 + sidecar `related_meta`
   （验收 6：为空可写、非空不覆盖、pinned_by=human 后 AI 不碰）。

设计口径（docs/78 §3.5）：
- `copy` / `summary` **不生成**要点（`rules.rubric_enabled`）——以原文/课堂资料为唯一依据；
- 生成要点的 prompt **带上该题型的规则摘要**（`rules.rule_summary`），
  保证要点粒度与扣分方式匹配（要点描述"该答什么"，规则描述"缺了怎么扣"）；
- `related_meta` **不进 xlsx**（不动表结构），存 `<ws>/kb/knowledge-meta.json`。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from loguru import logger

META_FILE = "knowledge-meta.json"


# ---------------- related_meta sidecar ----------------
def meta_path(ws) -> Path:
    return Path(ws).resolve() / "kb" / META_FILE


def read_meta(ws) -> dict:
    p = meta_path(ws)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[知识点] {p.name} 解析失败（{str(exc)[:80]}），按空处理")
        return {}


def write_meta(ws, meta: dict) -> Path:
    p = meta_path(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def _meta_key(kb: str, chap: str, qid: str) -> str:
    return f"{kb}__{chap}__{qid}"


def get_meta(ws, kb: str, chap: str, qid: str) -> dict:
    return read_meta(ws).get(_meta_key(kb, chap, qid)) or {}


def set_meta(ws, kb: str, chap: str, qid: str, patch: dict) -> dict:
    meta = read_meta(ws)
    key = _meta_key(kb, chap, qid)
    cur = {**(meta.get(key) or {}), **patch}
    cur["updatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
    meta[key] = cur
    write_meta(ws, meta)
    return cur


def is_pinned_by_human(ws, kb: str, chap: str, qid: str) -> bool:
    return str(get_meta(ws, kb, chap, qid).get("pinned_by") or "") == "human"


# ---------------- prompt（要点生成与评阅共用规则摘要） ----------------
RUBRIC_PROMPT = """你是一位大学物理教研组老师，正在为**批阅**做准备。
请针对下面这道题，产出"参考答案 + 评阅要点 + 知识点 + 示意图要求"。

【最重要的原则】
- 评阅要点描述的是「**学生该答到什么**」，不是"怎么扣分"（扣分由系统按规则自动做）；
- 要点必须**可判定**：能直接对照学生作答判断"答到/没答到"，不要写"理解深刻"这类主观话；
- 要点粒度跟下面给出的题型规则一致（例如规则按"每缺一个要点 −5"，要点就不要写成 20 条）。

{rule_summary}

【输出格式（严格 JSON，不要输出其他内容）】
{{
  "reference_solution": "规范参考解答（含关键步骤，公式用 LaTeX：行内 $...$、行间 $$...$$）",
  "rubric_points": [
    {{"point": "该答到的要点（一句话）", "weight": 1}}
  ],
  "knowledge": ["知识点术语（物理概念名，如 动量守恒、完全弹性碰撞）"],
  "diagram": {{"required": true, "description": "题目要求画什么图；不要求则 required=false"}}
}}

要求：
- `reference_solution` 面向教师核对，可完整；学生报告中另有人工/AI 批语，不会直接展示该答案；
- `rubric_points` 按重要性排序，**3–8 条为宜**；
- `knowledge` 用规范术语，2–5 个；若题目已带「已标注知识点」，**优先原样沿用**；
- `diagram.required` 只在题干明确要求画图时才为 true。

【JSON 转义（必须遵守）】
- LaTeX 反斜杠在 JSON 字符串里必须写成两个反斜杠（例：frac 要写成双反斜杠 + frac）；
- 只写一个反斜杠会变成非法转义或控制字符，公式会显示成乱码。"""


def build_rubric_prompt(*, ws, kind: str, content: str, solution: str = "",
                        related: str = "", vocab_terms: "list[str] | None" = None) -> str:
    """生成要点 prompt：题目 + **该题型规则摘要** + 术语约束（docs/78 §3.2）。"""
    from .rules import normalize_kind, rule_summary
    k = normalize_kind(kind)
    parts = [RUBRIC_PROMPT.format(rule_summary=rule_summary(ws, k)),
             f"【题型】{k}",
             f"【题目】\n{content}"]
    if solution.strip():
        parts.append(f"【题库现有参考答案（可修正/补全，但不要偏离题意）】\n{solution.strip()}")
    if related.strip():
        parts.append(f"【本题库已标注知识点（优先原样沿用）】\n{related.strip()}")
    if vocab_terms:
        parts.append("【受控词表（优先从中选取术语）】\n" + "、".join(vocab_terms[:60]))
    return "\n\n".join(parts)


RUBRIC_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "grading_rubric",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "reference_solution": {"type": "string"},
                "rubric_points": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"point": {"type": "string"},
                                       "weight": {"type": "number"}},
                        "required": ["point", "weight"],
                        "additionalProperties": False,
                    },
                },
                "knowledge": {"type": "array", "items": {"type": "string"}},
                "diagram": {
                    "type": "object",
                    "properties": {"required": {"type": "boolean"},
                                   "description": {"type": "string"}},
                    "required": ["required", "description"],
                    "additionalProperties": False,
                },
            },
            "required": ["reference_solution", "rubric_points", "knowledge", "diagram"],
            "additionalProperties": False,
        },
    },
}


def rubric_to_text(sol: dict) -> str:
    """把要点结构渲染成可读文本（写进答案版本库，批阅时进 prompt）。"""
    lines: list[str] = []
    ref = str(sol.get("reference_solution") or "").strip()
    if ref:
        lines += ["【参考解答】", ref, ""]
    pts = [p for p in (sol.get("rubric_points") or []) if isinstance(p, dict)]
    if pts:
        lines.append("【评阅要点】（逐条判定学生是否答到）")
        for i, p in enumerate(pts, start=1):
            lines.append(f"{i}. {str(p.get('point') or '').strip()}")
    dg = sol.get("diagram") or {}
    if dg.get("required"):
        lines.append(f"\n【示意图要求】{str(dg.get('description') or '').strip()}")
    ks = [str(x).strip() for x in (sol.get("knowledge") or []) if str(x).strip()]
    if ks:
        lines.append("\n【知识点】" + "，".join(ks))
    return "\n".join(lines).strip()


# ---------------- T5：生成要点并写入答案版本库（不置顶） ----------------
def generate_rubric(client, *, ws, kind: str, content: str, solution: str = "",
                    related: str = "", model: str | None = None) -> dict:
    """调 LLM 生成要点结构（**纯函数**，不落盘；便于 CLI 与测试复用）。"""
    from .llm import LLMAPIError
    from .transcribe import parse_llm_json
    from .vocab import load_vocab
    vocab_terms = []
    try:
        vocab_terms = [t.get("term") for t in load_vocab(ws).get("terms", []) if t.get("term")]
    except Exception:  # noqa: BLE001
        vocab_terms = []
    prompt = build_rubric_prompt(ws=ws, kind=kind, content=content, solution=solution,
                                 related=related, vocab_terms=vocab_terms)
    system = ("这是大学物理教研工作，内容完全学术。你是命题与评阅经验丰富的物理教师，"
              "只输出严格 JSON。")
    try:
        raw = client.chat(system_prompt=system, user_text=prompt, model=model,
                          temperature=0.2, response_format=RUBRIC_SCHEMA,
                          max_tokens=4096, step="rubric")
    except LLMAPIError as exc:
        if "schema" in str(exc).lower() or "response_format" in str(exc).lower():
            raw = client.chat(system_prompt=system, user_text=prompt, model=model,
                              temperature=0.2, response_format={"type": "json_object"},
                              max_tokens=4096, step="rubric")
        else:
            raise
    return parse_llm_json(raw)


def save_rubric_version(ws, *, kb: str, chap: str, qid: str, rubric: dict,
                        model: str = "", pin: bool = False) -> dict:
    """把要点写入答案版本库（source=ai，**默认不置顶**，验收 5）。"""
    from ..files import solutions as sol
    text = rubric_to_text(rubric)
    if not text:
        return {"ok": False, "error": "要点为空（模型未给出参考解答/要点）"}
    res = sol.add_version(ws, qid, text, source="ai", model=model, kb=kb, chap=chap,
                          pin=bool(pin))
    if res.get("ok"):
        res["text"] = text
        res["rubric"] = rubric
    return res


# ---------------- T6：知识点标注（四种粒度 + only-empty/force/dry-run） ----------------
def select_questions(kb_data: dict, *, kinds: "list[str] | None" = None,
                     chaps: "list[str] | None" = None,
                     ids: "list[str] | None" = None) -> list[dict]:
    """按粒度挑题：全部 / 某(些)类型 / 章节 / 具体题目。

    返回 [{kb, chap, qid, content, solution, related}]。
    """
    kinds_l = [str(k) for k in (kinds or []) if str(k).strip()]
    chaps_l = [str(c) for c in (chaps or []) if str(c).strip()]
    ids_l = {str(i) for i in (ids or []) if str(i).strip()}
    out: list[dict] = []
    for kind, chapters in (kb_data or {}).items():
        if kinds_l and kind not in kinds_l:
            continue
        if not isinstance(chapters, dict):
            continue
        for chap, entries in chapters.items():
            if chaps_l and chap not in chaps_l:
                continue
            for e in (entries or []):
                if not isinstance(e, dict):
                    continue
                qid = str(e.get("id") or "")
                if ids_l and qid not in ids_l:
                    continue
                out.append({"kb": kind, "chap": chap, "qid": qid,
                            "content": str(e.get("content") or ""),
                            "solution": str(e.get("solution") or ""),
                            "related": str(e.get("related") or "")})
    return out


def plan_tagging(ws, targets: list[dict], *, only_empty: bool = True,
                 force: bool = False) -> dict:
    """判定每题**该不该被 AI 标注**（验收 6 的三条口径全在这里）。

    返回 {"todo": [...], "skipped": [...]}，skipped 带原因。
    """
    todo, skipped = [], []
    for t in targets:
        qid, kb, chap = t["qid"], t["kb"], t["chap"]
        if not qid:
            skipped.append({**t, "reason": "无题号"})
            continue
        if is_pinned_by_human(ws, kb, chap, qid):
            skipped.append({**t, "reason": "教师已锁定（pinned_by=human）"})
            continue
        has = bool(str(t.get("related") or "").strip())
        if has and not force:
            # 非空**不覆盖**（验收 6）；教师确实要重标时显式 --force
            skipped.append({**t, "reason": "已有知识点（不覆盖；需 --force）"})
            continue
        if not only_empty and has and force:
            pass  # --force 已在上方放行，此处仅为可读性保留分支语义
        todo.append(t)
    return {"todo": todo, "skipped": skipped}


def apply_related(ws, updates: "list[dict]") -> dict:
    """把 [{kb, chap, qid, related, meta}] 写回题库 xlsx（保留样式）+ sidecar meta。

    写盘前自动快照（kb_io.snapshot），便于回滚。
    """
    from ..files import kb_io
    if not updates:
        return {"ok": True, "written": 0}
    kb_dir = Path(ws).resolve() / "kb"
    snap = kb_io.snapshot(kb_dir)
    by_kind: dict[str, dict[str, dict[str, str]]] = {}
    for u in updates:
        by_kind.setdefault(u["kb"], {}).setdefault(u["chap"], {})[str(u["qid"])] = u
    written = 0
    for kind, chapters in by_kind.items():
        xlsx = kb_dir / f"{kind}.xlsx"
        if not xlsx.is_file():
            logger.warning(f"[知识点] 题库文件不存在，跳过：{xlsx.name}")
            continue
        kb_data = kb_io.read_xlsx(xlsx, kb_dir) if kind != "translation" \
            else kb_io.read_translation(xlsx, kb_dir)
        for chap, qmap in chapters.items():
            entries = kb_data.get(chap) or []
            for e in entries:
                qid = str(e.get("id") or "")
                if qid in qmap:
                    e["related"] = qmap[qid]["related"]
                    if qmap[qid].get("meta"):
                        set_meta(ws, kind, chap, qid, qmap[qid]["meta"])
                    written += 1
            kb_data[chap] = entries
        kb_io.write_chapters_preserving(xlsx, kb_data)
    return {"ok": True, "written": written,
            "snapshot": [str(x) for x in snap]}

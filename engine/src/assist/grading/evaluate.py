"""evaluate.py — 文本评阅：转录 Markdown → 结构化发现 → Python 算分。

迁移自 _legacy/2601playwright/src/llm/evaluator.py：
- ANALYSIS_PROMPT 原样迁移（苏格拉底式、不直接给答案、"只发现不算分"）；
- 标签差异化指令逐段迁移（copy/copySp/copyOnly 只查完整性 等）；
- score_from_analysis / build_feedback_md 函数级搬运；
- 合并升级（本阶段核心收益点）：可绑定作业纸题目 —— 任务包展开的 items
  （每题 content/solution/tag）一并进入 prompt；同时把旧版
  "question_match 检查"升级为明确的 verdict: "suspected-substitution"
  （顶替嫌疑：学生转录内容与任务包题目无关）。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from loguru import logger

from .llm import LLMAPIError, LLMClient
from .transcribe import parse_llm_json

# ---- 迁移自 _legacy/2601playwright/src/llm/evaluator.py ANALYSIS_PROMPT ----
ANALYSIS_PROMPT = """这是大学物理作业评阅，内容完全学术，请基于物理知识进行专业评阅。

你是一位大学物理助教。请逐题分析学生作业，输出结构化发现。

评分流程（你只负责发现，不负责算分）：
1. 检查作业纸是否与题目匹配（防止学生答非所问）
2. 每题分别分析：推理思路是否完整，是否有计算错误
3. 检查每题是否画了示意图
4. 检查是否有签名

输出格式（严格 JSON，不要其他内容）：
```json
{
  "question_match": {"status": true, "note": "题目匹配正常"},
  "questions": [
    {
      "id": 1,
      "reasoning": {"status": "ok", "note": "思路清晰"},
      "errors": [
        {
          "step": "第2步",
          "description": "描述错误",
          "guidance": "引导性问题，不要直接给答案",
          "deduct": 5
        }
      ],
      "has_diagram": true
    }
  ],
  "has_signature": true,
  "summary": "整体评价",
  "guidance": "给学生2-3个启发性问题，引导他自己发现错误",
  "strengths": ["优点"],
  "weaknesses": ["不足"]
}
```

各项说明：
- reasoning.status: "ok" 思路完整 | "brief" 过于简略
- errors[].guidance: 苏格拉底式追问，不直接给答案
- errors[].deduct: 每处扣5分
- has_diagram: 每题是否画了示意图
- has_signature: 是否有签名
- question_match.status 为 false 表示学生作答与给定题目无关（答非所问/顶替作业）；
  此时 questions 可为空列表，note 中说明判断依据。"""

# ---- 标签差异化指令：逐段迁移自 evaluator.evaluate_markdown ----
_TAG_INSTRUCTIONS = {
    ("copy", "copyonly", "copysp", "punish"): (  # punish（期末补作业）沿用"完整性自查"规则并放宽

        "[学生标签: 抄写题] 该作业包含抄写类题目。请结合题干要求逐题评阅：\n"
        "- 抄写类题目 → 根据题干要求检查抄写是否完整（题干要求抄什么，就检查什么是否抄全），"
        "不评价公式推导、计算正确性、逻辑推理、小数点精度等\n"
        "- 其他题目 → 按标准方式评阅（推理思路、计算过程、示意图等）\n"
        "注意：有些题目要求抄写的是课本原文（如公式、定理、表格等），请根据题干描述检查对应内容"
        "是否完整抄写，不要因为学生抄写的是原文而非例题而误判为不完整。"),
    ("summary",): "[本题为总结题] 请侧重评价归纳是否准确、概念理解是否正确，对计算细节适当放宽要求。",
    ("translation",): "[本题为翻译题] 请检查翻译是否准确、术语使用是否正确。",
    ("innovation",): "[本题为创新题] 请评价创意和独立思考，对格式适当放宽。",
    ("distinguish",): "[本题为辨析题] 请检查概念区分是否清晰、论证是否合理。",
}


def tag_instruction(tag: str) -> str:
    """按分层标签返回评阅侧重指令（迁移自 evaluator.evaluate_markdown）。"""
    lower = (tag or "").lower()
    for keys, ins in _TAG_INSTRUCTIONS.items():
        if lower in keys:
            return ins
    return ""


def _kinds_of(items: list[dict]) -> list[str]:
    """本题作业涉及的 kind（保序去重）。"""
    from .rules import normalize_kind
    seen: list[str] = []
    for it in items or []:
        k = normalize_kind(it.get("kind") or it.get("kb") or it.get("tag") or "problems")
        if k not in seen:
            seen.append(k)
    return seen or ["problems"]


def build_user_prompt(items: list[dict], markdown_text: str, student: str = "",
                      ws=None) -> str:
    """构造绑定题目的评阅 prompt（D130：**按题目来源分型**）。

    items: 任务包展开的 [{序号, content, solution?, tag, kind?}]。
    `ws`：workspace（用于读 `<ws>/grading-rules.json` 的规则摘要与受控词表）；
    为 None 时用内置默认规则（测试/离线场景）。

    D130 变更（相对 D127）：
    - 去重后的**每个 kind** 各给一段「评阅范式 + 规则摘要 + 输出要求」；
    - 每题标注 `来源` 与知识点（T11：要求模型优先沿用题库术语）；
    - 去掉旧版"整份只用第一个 tag 的指令"的写法（混合来源作业会串规则）。
    """
    from .prompts import (EVIDENCE_INSTRUCTION, kind_instruction, kind_output_hint,
                          knowledge_instruction)
    parts: list[str] = []
    kinds = _kinds_of(items)
    if student:
        parts.append(f"学生：{student}")

    # ---- 按 kind 注入：评阅范式 + 规则摘要（与生成要点共用同一份） ----
    for k in kinds:
        parts.append(kind_instruction(ws, k))
        hint = kind_output_hint(k)
        if hint:
            parts.append(hint)

    # ---- 题库知识点术语（T11）：全份作业汇总一次，避免每题重复 ----
    related_all: list[str] = []
    for it in items or []:
        for term in str(it.get("related") or "").replace("，", ",").split(","):
            term = term.strip()
            if term and term not in related_all:
                related_all.append(term)
    vocab: list[str] = []
    if ws is not None:
        try:
            from .vocab import load_vocab
            vocab = [t.get("term") for t in load_vocab(ws).get("terms", []) if t.get("term")]
        except Exception:  # noqa: BLE001 —— 词表缺失不影响评阅
            vocab = []
    parts.append(knowledge_instruction(",".join(related_all), vocab))

    # D131-T21c：summary 题若本章有教师确认的课堂资料清单 → 作为批阅依据。
    # 没有清单时完全不加（保持 D130 行为：不报错、不降级扣分）。
    if "summary" in kinds and ws is not None:
        try:
            from ..files import materials as _mat
            chaps = {str(it.get("chap") or "") for it in (items or [])
                     if str(it.get("kind") or "") == "summary"}
            from .prompts import summary_fallback_block, summary_knowledge_block
            from .rules import summary_fallback
            block_parts: list[str] = []
            has_materials = False
            for c in sorted(x for x in chaps if x):
                terms = _mat.knowledge_terms(ws, c)
                md = _mat.read_knowledge_md(ws, c)
                b = summary_knowledge_block(terms, md)
                if b:
                    block_parts.append(b)
                    has_materials = True
            if has_materials:
                # D134-T4：**有资料时不叠加保底口径**（避免双重扣分/口径打架）
                parts.append("\n\n".join(block_parts))
            else:
                # D134-T4：无任何本章资料 → 保底口径（四维判定 + 降级可见）
                fb = summary_fallback(ws)
                fb_block = summary_fallback_block(fb)
                if fb_block:
                    parts.append(fb_block)
        except Exception:  # noqa: BLE001 —— 清单缺失/损坏不影响评阅
            logger.debug("读取课堂资料知识点清单失败", exc_info=True)

    q_lines = []
    for it in items:
        n = it.get("序号") or it.get("index") or "?"
        from .rules import normalize_kind
        k = normalize_kind(it.get("kind") or it.get("kb") or it.get("tag") or "problems")
        line = (f"第{n}题（来源: {it.get('kb') or k}；评阅范式: {k}；"
                f"标签: {it.get('tag', '') or '—'}）：\n{it.get('content', '')}")
        rel = str(it.get("related") or "").strip()
        if rel:
            line += f"\n本题库已标注知识点（优先沿用）：{rel}"
        q_lines.append(line)
        if it.get("solution"):
            q_lines.append(f"参考答案/解题要点（仅用于核对，勿向学生透露）：\n{it['solution']}")
    # D127：先判题目，再评阅（两条指令都必须给到模型）
    parts.append(
        "【第一步：判断题目是否对应】\n"
        "先核对学生转写中的题目/作答所针对的题目，是否就是下面这份**作业纸题目**：\n"
        "- 一致 → question_match.match = true；\n"
        "- 不一致（题号对不上/题干完全不同/像是另一份作业或学生自制作业纸）→ match = false，"
        "并在 evidence 中**逐字引用**学生转写里的题目片段，在 reason 中说明差异；\n"
        "- 学生没抄题目只有作答 → 按作答内容推断，证据不足时 match = true，"
        "但 reason 注明「学生未抄题目，按作答内容推断」。\n"
        "**判断只看题目本身，不受作答对错影响。**")
    if q_lines:
        parts.append("【作业纸题目】\n\n" + "\n\n".join(q_lines))
    parts.append(EVIDENCE_INSTRUCTION)
    parts.append(f"【学生转写（含题目与作答）】\n{markdown_text}")
    return "\n\n".join(parts)


def analyze(client: LLMClient, user_prompt: str, model: str | None = None,
            max_tokens: int = 8192, *, strict_schema: bool = True) -> dict:
    """调用 LLM 得到结构化分析 JSON。

    D98-B5：优先用 `json_schema`（严格结构，含 evidence/confidence）；
    provider 不支持 schema 时**自动回退** `json_object`（并记 warning）。
    截断时 max_tokens 翻倍重试（迁移自 evaluator.evaluate_markdown）。
    """
    from .prompts import EVALUATION_SCHEMA
    _mt = max_tokens
    use_schema = strict_schema
    for _ in range(4):
        rf = EVALUATION_SCHEMA if use_schema else {"type": "json_object"}
        try:
            raw = client.chat(system_prompt=ANALYSIS_PROMPT, user_text=user_prompt,
                              model=model, temperature=0.2, response_format=rf,
                              max_tokens=_mt, step="evaluation")
            return parse_llm_json(raw)
        except LLMAPIError as e:
            # 部分 provider 不支持 json_schema（400/参数错误）→ 回退 json_object 再试一次
            msg = str(e)
            if use_schema and ("schema" in msg.lower() or "response_format" in msg.lower()
                               or "400" in msg):
                logger.warning("provider 不支持 json_schema，回退 json_object 重试")
                use_schema = False
                continue
            raise
        except json.JSONDecodeError as e:
            if "Unterminated string" in str(e) and _mt < 262144:
                _mt = min(_mt * 2, 262144)
                logger.warning(f"评阅JSON截断，max_tokens 翻倍至 {_mt} 重试")
                time.sleep(1)
                continue
            raise RuntimeError(f"评阅JSON解析失败: {e}") from e
    raise RuntimeError("评阅JSON解析失败: 翻倍重试耗尽")


# ---- 算分：D130 按题目来源分派（errorCount / missingPoints / checklist / lengthBased） ----
def _counted_errors(q: dict, g: dict) -> tuple[list[dict], int]:
    """过滤低置信度错误（默认不计分，D98-B5）；返回 (计入的错误, 低置信度条数)。"""
    errors = [e for e in (q.get("errors") or []) if isinstance(e, dict)]
    if g.get("countLowConfidence"):
        return errors, 0
    counted = [e for e in errors if str(e.get("confidence") or "high").lower() != "low"]
    return counted, len(errors) - len(counted)


def _q_kind(q: dict) -> str:
    from .rules import normalize_kind
    return normalize_kind(q.get("kind") or q.get("kb") or "problems")


def _text_len(text: str) -> int:
    """作答字数：去掉空白后计数（中文按字，英文按字符，忽略 Markdown 记号影响小）。"""
    t = re.sub(r"\s+", "", str(text or ""))
    t = re.sub(r"[*_#>`$]", "", t)
    return len(t)


def _q_deduction(q: dict, t: dict, g: dict) -> tuple[float, list[str], list[str]]:
    """按题型算出**本题**扣分。返回 (扣分, 扣分明细, 适用规则名)。

    明细直接进报告（教师可核对"为什么扣这 5 分"）；扣分数值在这里算好返回，
    **不做字符串反解析**（反解析会因措辞调整而静默算错）。
    """
    mode = str(t.get("mode") or "errorCount")
    cap = float(t.get("perQuestionCap") or g.get("perQuestionCap") or 20)
    steps: list[str] = []
    rules: list[str] = []
    pts = 0.0

    # 通用：过程简略（全局 briefProcessDeduct）。**由 Python 统一扣**，
    # 不信模型自报的 deduct（否则规则卡改数值对模型无效）。
    brief = float(g.get("briefProcessDeduct") or 0)
    if str((q.get("reasoning") or {}).get("status") or "") == "brief" and brief > 0:
        pts += brief
        steps.append(f"过程简略缺关键步骤 −{brief:g}")

    if mode == "errorCount":
        per = float(t.get("perErrorDeduct") or 5)
        counted, low_n = _counted_errors(q, g)
        d = min(len(counted) * per, cap)
        if d > 0:
            extra = f"（另有 {low_n} 处低置信度未计）" if low_n else ""
            steps.append(f"错误 {len(counted)} 处 × {per:g} = −{d:g}{extra}")
            pts += d
        rules.append("errorCount")

    elif mode == "missingPoints":
        per = float(t.get("perMissingPointDeduct") or 5)
        kps = [k for k in (q.get("key_points") or []) if isinstance(k, dict)]
        missing = [k for k in kps if not k.get("answered")]
        d = min(len(missing) * per, cap)
        if d > 0:
            names = "、".join(str(k.get("point") or "要点") for k in missing[:6])
            steps.append(f"未答到 {len(missing)} 个评阅要点 × {per:g} = −{d:g}：{names}")
            pts += d
        if t.get("requireDiagram") and q.get("has_diagram") is False:
            dd = float(t.get("missingDiagramDeduct") or 5)
            if dd > 0:
                steps.append(f"缺示意图 −{dd:g}")
                pts += dd
        rules.append("missingPoints")

    elif mode == "checklist":
        raw: dict = {}
        for key in ("copied", "covered"):
            v = q.get(key)
            if isinstance(v, dict):
                for k2, v2 in v.items():
                    if isinstance(v2, bool) and str(k2) not in raw:
                        raw[str(k2)] = v2
        items = [str(x) for x in (t.get("checklist") or [])]
        miss = [k for k in items if raw.get(k) is False]
        # D134-T4：summary 走**保底口径**（`summary_basis != "materials"`）时，
        # 缺项**不扣分**（没有课堂资料就没资格判"漏了什么"），只可能扣"过简"。
        basis = str(q.get("summary_basis") or "").strip().lower()
        fb = (t.get("fallback") or {}) if isinstance(t.get("fallback"), dict) else {}
        heuristic = bool(fb.get("enabled", True)) and basis != "materials"
        if heuristic and fb:
            per = float(fb.get("missingItemDeduct") or 0)
            if miss and per <= 0:
                steps.append(f"保底口径：未完成 {len(miss)} 项（缺项不扣分）：{'、'.join(miss)}")
        else:
            per = float(t.get("perMissingItemDeduct") or 5)
        d = min(len(miss) * per, cap) if per > 0 else 0.0
        if d > 0:
            steps.append(f"未完成 {len(miss)} 项 × {per:g} = −{d:g}：{'、'.join(miss)}")
            pts += d
        # 「总结过于简略」：仅保底口径下计分（字数以转写原文重算，不信模型自报）
        if heuristic and fb:
            min_chars = int(fb.get("minChars") or 0)
            fb_deduct = float(fb.get("minCharsDeduct") or 0)
            n_chars = _text_len(str(q.get("answer_text") or ""))
            if not n_chars and isinstance(q.get("answer_chars"), int):
                n_chars = int(q["answer_chars"])
            if min_chars > 0 and fb_deduct > 0 and n_chars < min_chars:
                steps.append(f"总结过于简略（{n_chars} 字 < {min_chars} 字） −{fb_deduct:g}")
                pts += fb_deduct
        rules.append("checklist")

    elif mode == "lengthBased":
        # 基准 = 题目字数 × factor，下限保护 max(factor×题长, floor)（docs/78 §3.3）
        q_chars = _text_len(str(q.get("question_text") or ""))
        factor = float(t.get("lengthFactor") or 3)
        floor_chars = float(t.get("lengthFloorChars") or 60)
        base_len = max(factor * q_chars, floor_chars)
        a_chars = q.get("answer_chars")
        if not isinstance(a_chars, int):
            a_chars = _text_len(str(q.get("answer_text") or ""))
        rel = str(q.get("relevance") or "relevant").lower()
        d = 0.0
        if rel == "irrelevant":
            d = float(t.get("irrelevantDeduct") or 20)
            if d > 0:
                steps.append(f"作答与题目无关 −{d:g}")
        elif base_len > 0:
            r = a_chars / base_len
            # 阈值**升序**遍历：低于多个档时取**最严的一档**（<50% 应得 −10，而不是 −5）
            tiers = sorted(((float(k), float(v)) for k, v in
                            (t.get("shortRatioDeduct") or {}).items()), key=lambda x: x[0])
            for thr, val in tiers:
                if r < thr:
                    d = val
                    break
            if d > 0:
                steps.append(f"作答 {a_chars} 字 / 基准 {base_len:g} 字（{r * 100:.0f}%） −{d:g}")
        if t.get("logicErrorExempt", True) and (q.get("errors") or []):
            steps.append("逻辑问题按规定不扣分，已转为启发式提问")
        pts += d
        rules.append("lengthBased")

    return min(pts, cap + brief), steps, rules


def _aggregate_summary_meta(result: dict, analysis: dict) -> None:
    """D134-T4：把 summary 题的**评阅依据**与**遗漏知识点**汇总到结果（两条路径共用）。

    - `knowledge_missing[]`：仅资料口径下模型才填（保底口径下必为空）；
    - `summary_basis`：`materials`（有课堂资料）| `heuristic`（通用保底粗判）。
      **降级必须可见**，学生报告里会据此加一段说明。
    """
    km: list[str] = []
    for q in (analysis.get("questions") or []):
        for k in (q.get("knowledge_missing") or []):
            k = str(k or "").strip()
            if k and k not in km:
                km.append(k)
    if km:
        result["knowledge_missing"] = km
    bases = {str(q.get("summary_basis") or "").strip().lower()
             for q in (analysis.get("questions") or []) if q.get("summary_basis")}
    bases.discard("")
    if bases:
        result["summary_basis"] = "materials" if bases == {"materials"} else "heuristic"


def score_from_analysis(analysis: dict, quality: dict | None = None,
                        items: "list[dict] | None" = None, ws=None) -> dict:
    """D130：按**题目来源**分派扣分算法（不再一刀切"每错 −5"）。

    - items 提供每题 kind/题面（与 analysis.questions 按 id/序号对齐）；
    - ws 提供 `<ws>/grading-rules.json`；为 None 用默认规则；
    - 向后兼容：不传 items 时所有题按 `problems / errorCount`（= 旧行为）。

    全局规则（docs/78 §3.3）：
    - 过程简略逐题 −briefProcessDeduct（Python 统一扣，不信模型自报 deduct）；
    - **≥allBriefRatio 的题都简略 → 总分一次性 −allBriefDeduct**（不逐题累计）；
    - 缺签名 / 书写规范 / 总分底线沿用旧规则。
    """
    from .rules import global_rules, normalize_kind
    g = global_rules(ws)
    item_by_no: dict[str, dict] = {}
    for it in (items or []):
        keys = {str(it.get("序号") or ""), str(it.get("no") or ""), str(it.get("id") or "")}
        for k in keys:
            if k:
                item_by_no[k] = it

    score = 100.0
    deductions: list[str] = []
    per_q_rule: list[dict] = []
    q_list = [q for q in (analysis.get("questions") or []) if isinstance(q, dict)]
    brief_n = 0

    per_question_raw: list[float] = []
    for q in q_list:
        qid = q.get("id", 0)
        it = item_by_no.get(str(qid)) or {}
        # 每题 kind：模型标注 > 任务包 item > 默认 problems
        kind = normalize_kind(it.get("kind") or it.get("kb") or q.get("kind") or "problems")
        t = dict(DEFAULT_TYPE_RULES(kind))
        if ws is not None:
            from .rules import type_rules
            t.update(type_rules(ws, kind))
        # 摄取题面/作答（长度档需要；预览/回灌时可能已带）
        if it.get("content") and not q.get("question_text"):
            q = {**q, "question_text": str(it.get("content"))}
        if it.get("kind") and not q.get("kind"):
            q["kind"] = it.get("kind")
        if str((q.get("reasoning") or {}).get("status") or "") == "brief":
            brief_n += 1
        d, steps, rules = _q_deduction(q, t, g)
        per_question_raw.append(d)
        if d > 0:
            score -= d
            deductions.append(f"第{qid}题 扣{d:g}分（{'；'.join(steps)}）")
        per_q_rule.append({"id": qid, "kind": kind, "source": it.get("kb") or kind,
                           "rules": rules, "deduct": d, "detail": steps})

    # 全局惩戒：≥80% 题目"过程简略" → 总分一次性 −5
    ratio = float(g.get("allBriefRatio") or 0.8)
    all_brief = bool(q_list) and (brief_n / len(q_list)) >= ratio
    all_brief_deduct = 0.0
    if all_brief:
        all_brief_deduct = float(g.get("allBriefDeduct") or 0)
        if all_brief_deduct > 0:
            score -= all_brief_deduct
            deductions.append(
                f"整体过程简略（{brief_n}/{len(q_list)} 题，≥{ratio * 100:.0f}%）"
                f" −{all_brief_deduct:g}（一次性）")

    # 缺示意图：**不再**按"题数 × 5"另算（qa/copy/summary 已在题型内计，
    # problems 的缺图属提示不扣分）——保留全局放宽逻辑给旧调用方兼容
    if not g.get("countLowConfidence"):
        pass

    if not analysis.get("has_signature", True):
        d = float(g.get("noSignatureDeduct") or 0)
        if d > 0:
            score -= d
            deductions.append(f"无签名 −{d:g}")

    if quality:
        hw_bad = sum(1 for k, bad in (("handwriting", "潦草"), ("clarity", "模糊"),
                                      ("organization", "杂乱"))
                     if quality.get(k) == bad)
        d = min(hw_bad * 5, float(g.get("writingDeduct") or 0))
        if d > 0:
            score -= d
            deductions.append(f"书写规范问题 −{d:g}")

    floor = float(g.get("floor") or 0)
    final_score = max(floor, round(score)) if q_list else int(floor)

    # 每题分数：均分基线 → 逐题扣 → 差值法回吞全局扣分（保持旧口径）
    per_question_scores: list[float] = []
    if q_list:
        base = 100 // len(q_list)
        remainder = 100 % len(q_list)
        raw_scores = []
        for idx, q in enumerate(q_list):
            s = base + (1 if idx < remainder else 0)
            s -= per_question_raw[idx]
            raw_scores.append(max(0.0, float(s)))
        raw_total = sum(raw_scores)
        diff = raw_total - final_score
        if diff > 0:
            for i in range(len(raw_scores) - 1, -1, -1):
                if diff <= 0:
                    break
                take = min(diff, raw_scores[i])
                raw_scores[i] -= take
                diff -= take
        per_question_scores = [max(0, round(s)) for s in raw_scores]

    return {
        "total_score": final_score,
        "per_question_scores": per_question_scores,
        "deductions": deductions,
        "strengths": analysis.get("strengths", []),
        "weaknesses": analysis.get("weaknesses", []),
        "summary": analysis.get("summary", ""),
        "guidance": analysis.get("guidance", ""),
        # D130：逐题来源/适用规则/扣分明细（报告"本题来源 + 适用规则"用）
        "per_question_rules": per_q_rule,
        "all_brief": all_brief,
    }


def DEFAULT_TYPE_RULES(kind: str) -> dict:
    """默认题型规则（不读 ws；供 score_from_analysis 无 ws 时用）。"""
    from .rules import DEFAULT_RULES, normalize_kind
    return dict(DEFAULT_RULES["types"][normalize_kind(kind)])


# ---- 批语 Markdown：函数级搬运自 evaluator.build_feedback_md ----
def build_feedback_md(result: dict, student_name: str = "学生",
                      homework_name: str = "", analysis: dict | None = None) -> str:
    lines: list[str] = []
    t = f"# 作业批阅报告：{homework_name}" if homework_name else "# 作业批阅报告"
    lines += [t, f"**学生：{student_name}**", "---", "## 评分",
              f"**总分：{result.get('total_score', '?')} / 100**"]
    for d in result.get("deductions", []):
        lines.append(f"- {d}")
    low_items: list[str] = []
    for q in (analysis or result.get("analysis", {})).get("questions", []):
        lines += ["", f"### 第 {q.get('id', '?')} 题"]
        rn = q.get("reasoning", {}).get("note", "")
        if rn:
            lines.append(f"**思路：**{rn}")
        # 做对之处
        for cp in q.get("correct_points") or []:
            lines.append(f"- ✅ **做对：**{cp}")
        errors = q.get("errors") or []
        for e in errors:
            conf = str(e.get("confidence") or "high").lower()
            if conf == "low":
                # 低置信度：只在"不确定项"里提示，不计分
                low_items.append(f"第 {q.get('id', '?')} 题：{e.get('description', '')}"
                                 + (f"（依据：{e.get('evidence')}）" if e.get("evidence") else ""))
                continue
            desc = e.get("description", "")
            lines.append(f"- ❌ **问题：**{desc}")
            if e.get("why"):
                lines.append(f"  - **为什么：**{e['why']}")
            if e.get("evidence"):
                lines.append(f"  - **你的原文：**`{e['evidence']}`")
            if e.get("guidance"):
                lines.append(f"  - **想一想：**{e['guidance']}")
        if not q.get("has_diagram", True):
            lines.append("- 提示：缺少示意图，请补上。")
    if str(result.get("summary_basis") or "") == "heuristic":
        lines += ["", "---", "## 关于总结题",
                  "本次总结题按**通用标准**评阅（未结合本堂课授课资料），"
                  "因此只检查是否归纳了知识点、是否有公式或推导、"
                  "示意图是否给出、篇幅是否过短，**不判断漏掉了哪些具体知识点**。"]
    # 整体引导
    g = (analysis or result.get("analysis", {})).get("guidance", result.get("guidance", ""))
    if g:
        lines += ["", "---", "## 整体思考", g]
    for s in result.get("strengths", []):
        lines.append(f"- 值得肯定：{s}")
    # D98-B5：低置信度"不确定项"单列（未计入扣分，供教师复核）
    if low_items:
        lines += ["", "---", "## 待教师确认（AI 低置信度，未计分）"]
        lines += [f"- {x}" for x in low_items]
    lines += ["", "---", "*AI 辅助批阅*"]
    return "\n".join(lines)


def _answer_text_of(t_data: dict, qid) -> str:
    """从结构化转写里取某题的学生作答原文（按题号匹配；兼容 str/int 题号）。"""
    want = str(qid).strip()
    for it in (t_data.get("items") or []):
        if not isinstance(it, dict):
            continue
        no = str(it.get("no") or "").strip()
        if no and no == want:
            return str(it.get("answer") or "")
    return ""


def _enrich_questions(analysis: dict, items: "list[dict] | None", t_data: dict) -> None:
    """就地补 `question_text` / `answer_text` / `kind`（供按题型计分）。"""
    from .rules import normalize_kind
    item_by_no: dict[str, dict] = {}
    for it in (items or []):
        for k in (str(it.get("序号") or ""), str(it.get("no") or ""),
                  str(it.get("id") or "")):
            if k:
                item_by_no[k] = it
    for q in (analysis.get("questions") or []):
        if not isinstance(q, dict):
            continue
        qid = q.get("id")
        it = item_by_no.get(str(qid)) or {}
        if not q.get("question_text"):
            q["question_text"] = str(it.get("content") or "")
        if not q.get("kind"):
            q["kind"] = normalize_kind(it.get("kind") or it.get("kb") or "problems")
        if not q.get("answer_text"):
            txt = _answer_text_of(t_data, qid)
            if txt:
                q["answer_text"] = txt
                # 以转写原文为准：模型自报的 answer_chars 不可信（可能整体估算/幻觉），
                # 有原文时一律用原文重算（长度档扣分依赖该数值）。
                q["answer_chars"] = _text_len(txt)


def evaluate_student(client: LLMClient, transcript_file: Path, items: list[dict],
                     out_dir: Path, homework_name: str = "",
                     model: str | None = None, ws=None) -> Path:
    """评阅一份转录 → evaluations/<student>.json + .md 批语。

    D130：`ws` 用于读 `<ws>/grading-rules.json`（规则卡改数值后**新批阅**生效）
    与受控知识点词表；为 None 时用内置默认规则。
    """
    t_data = json.loads(Path(transcript_file).read_text(encoding="utf-8"))
    student = t_data.get("student") or Path(transcript_file).stem
    # D127：结构化转写 → 渲染成"题目/作答/示意图"分明的 markdown 再喂给评阅
    from .transcribe import transcript_to_markdown
    markdown_text = transcript_to_markdown(t_data)
    quality = t_data.get("quality")

    analysis = analyze(client, build_user_prompt(items, markdown_text, student, ws=ws),
                       model=model)
    # D130：把**题面**与**学生作答原文**注入每题（长度档需要题长；qa 缺图判定也可能用到），
    # 模型自报的 answer_chars 只作参考，Python 以转写原文为准（防模型少报字数）。
    _enrich_questions(analysis, items, t_data)

    # D127：题目一致性**交给 LLM 判断**（prompt 已要求先判题目再评阅）。
    # 兼容 status / match 两种字段；只做教师侧提示，不自动扣分（用户拍板）。
    match = analysis.get("question_match", {}) or {}
    if "match" in match:
        substitution = (match.get("match") is False)
    else:
        substitution = (match.get("status") is False)
    result = score_from_analysis(analysis, quality=quality, items=items, ws=ws)
    result["analysis"] = analysis
    if quality:
        result["quality"] = quality
    if substitution:
        result["verdict"] = "suspected-substitution"
        # D127：**不再**写进 deductions（会出现在学生报告正文里，等于给学生贴标签）。
        # 仅保留在 evaluations/*.json + 教师侧提示，供人工确认是否为学生自制作业纸。
        logger.warning(f"[{student}] 题目与作业纸不一致：{match.get('reason') or match.get('note')}")
    else:
        result["verdict"] = "normal"
    result["question_match"] = match

    result["feedback_md"] = build_feedback_md(result, student, homework_name,
                                              analysis=analysis)
    result.update({
        "student": student,
        "homework": homework_name,
        "model": model or client.evaluation_model,
        "version": "assist-engine 0.1.0 (migrated from 2601playwright v0.3.0)",
        "_eval_version": 1,
        "timestamp": time.strftime("%Y-%m-%d %H:%M"),
        "_name_match": t_data.get("_name_match", True),
        # D127 审计：本次评阅实际使用的作业纸与题号（便于事后核对"是否用对了作业纸"）
        "audit": {
            "pad_id": str((items[0] or {}).get("padId") or "") if items else "",
            "question_numbers": [str(it.get("序号") or "") for it in (items or [])],
            "question_count": len(items or []),
        },
    })
    # D127：汇总本份作答中出现的知识点（供教师总结报告聚合，无需再给题目做标注）
    _ks: list[str] = []
    for _q in (analysis.get("questions") or []):
        for _e in (_q.get("errors") or []):
            for _k in (_e.get("knowledge") or []):
                _k = str(_k or "").strip()
                if _k and _k not in _ks:
                    _ks.append(_k)
    result["knowledge"] = _ks
    # D131-T21c + D134-T4：summary 题的遗漏知识点与评阅依据（共用汇总函数）
    _aggregate_summary_meta(result, analysis)


    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{student}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if result.get("feedback_md"):
        out.with_suffix(".md").write_text(result["feedback_md"], encoding="utf-8")
    if substitution:
        logger.warning(f"[{student}] 疑似顶替作业（与任务包题目无关）：{match.get('note')}")
    if not result["_name_match"]:
        logger.warning(f"[{student}] 转录姓名可能不匹配，请人工复核")
    return out


# ---------------- D98-B6：batch 结果回灌（下载的 JSONL → evaluations/*.json） ----------------

def build_result_from_analysis(analysis: dict, *, student: str, quality: "dict | None" = None,
                               homework_name: str = "", model: str = "",
                               name_match: bool = True, items=None, ws=None) -> dict:
    """把**单条 analysis**变成与 evaluate_student 同结构的评阅结果（供 batch 回灌）。

    D130：`items`/`ws` 与 `evaluate_student` 同口径（按题目来源分派扣分）。
    """
    match = analysis.get("question_match", {}) if isinstance(analysis, dict) else {}
    # D127：与 evaluate_student 同口径 —— 只记 verdict 供教师侧提示，**不写进 deductions**
    # （写进去就会出现在学生报告正文里，等于给学生贴"顶替"标签）。
    substitution = (match.get("match") is False) if "match" in match \
        else (match.get("status") is False)
    result = score_from_analysis(analysis or {}, quality=quality, items=items, ws=ws)
    result["analysis"] = analysis
    if quality:
        result["quality"] = quality
    result["verdict"] = "suspected-substitution" if substitution else "normal"
    result["question_match"] = match
    result["feedback_md"] = build_feedback_md(result, student, homework_name, analysis=analysis)
    result["feedback_md"] = build_feedback_md(result, student, homework_name,
                                              analysis=analysis or {})
    # D134-T4：与 evaluate_student 同口径（summary 依据 / 遗漏知识点）
    _aggregate_summary_meta(result, analysis or {})
    result["feedback_md"] = build_feedback_md(result, student, homework_name,
                                              analysis=analysis or {})
    result.update({
        "student": student,
        "homework": homework_name,
        "model": model,
        "_source": "llm_batch",
        "_eval_version": 2,
        "timestamp": time.strftime("%Y-%m-%d %H:%M"),
        "_name_match": bool(name_match),
    })
    return result


def write_result(result: dict, out_dir: Path) -> Path:
    """把评阅结果写为 evaluations/<student>.json + .md。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{result['student']}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if result.get("feedback_md"):
        out.with_suffix(".md").write_text(result["feedback_md"], encoding="utf-8")
    return out

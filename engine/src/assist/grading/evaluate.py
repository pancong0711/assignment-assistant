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


def build_user_prompt(items: list[dict], markdown_text: str, student: str = "") -> str:
    """构造绑定题目的评阅 prompt（阶段3核心升级）。

    items: 任务包展开的 [{序号, content, solution?, tag}]（solution 尽力从题库取）。
    """
    parts: list[str] = []
    base = ""
    for it in items:
        ins = tag_instruction(it.get("tag", ""))
        if ins and ins not in base:
            base = (base + "\n\n" + ins) if base else ins
    if base:
        parts.append(base)
    if student:
        parts.append(f"学生：{student}")

    q_lines = []
    for it in items:
        n = it.get("序号") or it.get("index") or "?"
        line = f"第{n}题（标签: {it.get('tag', 'qa') or 'qa'}）：\n{it.get('content', '')}"
        rel = str(it.get("related") or "").strip()
        if rel:
            line += f"\n关联知识点（供参考）：{rel}"
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
    from .prompts import EVIDENCE_INSTRUCTION
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


# ---- 算分：函数级搬运自 evaluator.score_from_analysis ----
def score_from_analysis(analysis: dict, quality: dict | None = None) -> dict:
    """按 2601 规则计算最终分数（每答扣分上限 20、缺图/签名/书写全局扣分）。"""
    score = 100.0
    deductions: list[str] = []

    for q in analysis.get("questions", []):
        if not isinstance(q, dict):
            continue
        q_id = q.get("id", 0)
        q_deduct = 0
        if q.get("reasoning", {}).get("status") == "brief":
            q_deduct += 10
        errors = q.get("errors", [])
        # D98-B5：confidence=low 的错误只提示、不扣分（防幻觉误伤）
        counted = [e for e in errors if str(e.get("confidence") or "high").lower() != "low"]
        q_deduct += min(len(counted) * 5, 20)
        q_deduct = min(q_deduct, 20)
        if q_deduct > 0:
            score -= q_deduct
            brief = "+" if q.get("reasoning", {}).get("status") == "brief" else ""
            low_n = len(errors) - len(counted)
            extra = f"，另有{low_n}处低置信度未计" if low_n > 0 else ""
            deductions.append(f"第{q_id}题 扣{q_deduct}分（推理{brief}错误{len(counted)}处{extra}）")

    dia_cnt = sum(1 for q in analysis.get("questions", []) if not q.get("has_diagram", True))
    q_count = len(analysis.get("questions", []))
    if q_count > 1 and dia_cnt > 0:
        dia_cnt = max(0, dia_cnt - 1)  # 放宽：允许多题作业最多 1 题缺示意图
    dia_deduct = min(dia_cnt * 5, 10)
    if dia_deduct > 0:
        score -= dia_deduct
        deductions.append(f"缺少示意图，-{dia_deduct}分")

    if not analysis.get("has_signature", True):
        score -= 5
        deductions.append("无签名，-5分")

    if quality:
        hw_score = sum(5 for k, bad in (("handwriting", "潦草"), ("clarity", "模糊"),
                                        ("organization", "杂乱"))
                       if quality.get(k) == bad)
        hw_deduct = min(hw_score, 5)
        if hw_deduct > 0:
            score -= hw_deduct
            deductions.append(f"书写规范问题，-{hw_deduct}分")

    final_score = max(40, round(score)) if analysis.get("questions") else 40

    # 每题分数：均分基线 → 逐题扣 → 差值法回吞全局扣分（迁移自 score_from_analysis）
    q_list = analysis.get("questions", [])
    per_question_scores: list[float] = []
    if q_list:
        base = 100 // len(q_list)
        remainder = 100 % len(q_list)
        raw_scores = []
        for idx, q in enumerate(q_list):
            s = base + (1 if idx < remainder else 0)
            if q.get("reasoning", {}).get("status") == "brief":
                s -= 10
            _errs = [e for e in q.get("errors", [])
                     if str(e.get("confidence") or "high").lower() != "low"]
            s -= min(len(_errs) * 5, 20)
            raw_scores.append(max(0, s))
        raw_total = sum(raw_scores)
        diff = raw_total - final_score
        if diff > 0:
            for i in range(len(raw_scores) - 1, -1, -1):
                if diff <= 0:
                    break
                take = min(diff, raw_scores[i])
                raw_scores[i] -= take
                diff -= take
        per_question_scores = [max(0, s) for s in raw_scores]

    return {
        "total_score": final_score,
        "per_question_scores": per_question_scores,
        "deductions": deductions,
        "strengths": analysis.get("strengths", []),
        "weaknesses": analysis.get("weaknesses", []),
        "summary": analysis.get("summary", ""),
        "guidance": analysis.get("guidance", ""),
    }


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


def evaluate_student(client: LLMClient, transcript_file: Path, items: list[dict],
                     out_dir: Path, homework_name: str = "",
                     model: str | None = None) -> Path:
    """评阅一份转录 → evaluations/<student>.json + .md 批语。"""
    t_data = json.loads(Path(transcript_file).read_text(encoding="utf-8"))
    student = t_data.get("student") or Path(transcript_file).stem
    # D127：结构化转写 → 渲染成"题目/作答/示意图"分明的 markdown 再喂给评阅
    from .transcribe import transcript_to_markdown
    markdown_text = transcript_to_markdown(t_data)
    quality = t_data.get("quality")

    analysis = analyze(client, build_user_prompt(items, markdown_text, student), model=model)

    # D127：题目一致性**交给 LLM 判断**（prompt 已要求先判题目再评阅）。
    # 兼容 status / match 两种字段；只做教师侧提示，不自动扣分（用户拍板）。
    match = analysis.get("question_match", {}) or {}
    if "match" in match:
        substitution = (match.get("match") is False)
    else:
        substitution = (match.get("status") is False)
    result = score_from_analysis(analysis, quality=quality)
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
                               name_match: bool = True) -> dict:
    """把**单条 analysis**变成与 evaluate_student 同结构的评阅结果（供 batch 回灌）。"""
    match = analysis.get("question_match", {}) if isinstance(analysis, dict) else {}
    # D127：与 evaluate_student 同口径 —— 只记 verdict 供教师侧提示，**不写进 deductions**
    # （写进去就会出现在学生报告正文里，等于给学生贴"顶替"标签）。
    substitution = (match.get("match") is False) if "match" in match \
        else (match.get("status") is False)
    result = score_from_analysis(analysis or {}, quality=quality)
    result["analysis"] = analysis
    if quality:
        result["quality"] = quality
    result["verdict"] = "suspected-substitution" if substitution else "normal"
    result["question_match"] = match
    result["feedback_md"] = build_feedback_md(result, student, homework_name, analysis=analysis)
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

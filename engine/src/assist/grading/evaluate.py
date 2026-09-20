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

from .llm import LLMClient
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
    ("copy", "copyonly", "copysp"): (
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
        q_lines.append(f"第{n}题（标签: {it.get('tag', 'qa') or 'qa'}）：\n{it.get('content', '')}")
        if it.get("solution"):
            q_lines.append(f"参考答案/解题要点（仅用于核对，勿向学生透露）：\n{it['solution']}")
    if q_lines:
        parts.append("作业纸题目（学生作业应逐题对应以下题目，若对不上请把 "
                     "question_match.status 设为 false）：\n\n" + "\n\n".join(q_lines))
    parts.append(f"学生答案（转录）：\n{markdown_text}")
    return "\n\n".join(parts)


def analyze(client: LLMClient, user_prompt: str, model: str | None = None,
            max_tokens: int = 8192) -> dict:
    """调用 LLM 得到结构化分析 JSON（截断翻倍重试，迁移自 evaluator.evaluate_markdown）。"""
    _mt = max_tokens
    for _ in range(4):
        try:
            raw = client.chat(system_prompt=ANALYSIS_PROMPT, user_text=user_prompt,
                              model=model, temperature=0.2,
                              response_format={"type": "json_object"},
                              max_tokens=_mt)
            return parse_llm_json(raw)
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
        q_deduct += min(len(errors) * 5, 20)
        q_deduct = min(q_deduct, 20)
        if q_deduct > 0:
            score -= q_deduct
            brief = "+" if q.get("reasoning", {}).get("status") == "brief" else ""
            deductions.append(f"第{q_id}题 扣{q_deduct}分（推理{brief}错误{len(errors)}处）")

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
            s -= min(len(q.get("errors", [])) * 5, 20)
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
    for q in (analysis or result.get("analysis", {})).get("questions", []):
        lines += ["", f"### 第 {q.get('id', '?')} 题"]
        rn = q.get("reasoning", {}).get("note", "")
        if rn:
            lines.append(f"**思路：**{rn}")
        for e in q.get("errors", []):
            if e.get("guidance"):
                lines.append(f"- **想一想：**{e['guidance']}")
        if not q.get("has_diagram", True):
            lines.append("- 提示：缺少示意图，请补上。")
    # 整体引导
    g = (analysis or result.get("analysis", {})).get("guidance", result.get("guidance", ""))
    if g:
        lines += ["", "---", "## 整体思考", g]
    for s in result.get("strengths", []):
        lines.append(f"- 值得肯定：{s}")
    lines += ["", "---", "*AI 辅助批阅*"]
    return "\n".join(lines)


def evaluate_student(client: LLMClient, transcript_file: Path, items: list[dict],
                     out_dir: Path, homework_name: str = "",
                     model: str | None = None) -> Path:
    """评阅一份转录 → evaluations/<student>.json + .md 批语。"""
    t_data = json.loads(Path(transcript_file).read_text(encoding="utf-8"))
    student = t_data.get("student") or Path(transcript_file).stem
    markdown_text = t_data.get("markdown", "") or ""
    quality = t_data.get("quality")

    analysis = analyze(client, build_user_prompt(items, markdown_text, student), model=model)

    # 顶替嫌疑判定（旧 evaluator 的 question_match 检查升级为显式 verdict）
    match = analysis.get("question_match", {})
    substitution = (match.get("status") is False)
    result = score_from_analysis(analysis, quality=quality)
    result["analysis"] = analysis
    if quality:
        result["quality"] = quality
    if substitution:
        result["verdict"] = "suspected-substitution"
        result["deductions"] = list(result["deductions"]) + [
            f"顶替嫌疑：{match.get('note', '学生作答与作业纸题目无关')}"]
    else:
        result["verdict"] = "normal"

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
    })

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

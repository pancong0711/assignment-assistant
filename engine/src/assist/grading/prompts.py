"""D86 §4：两段式提示词与两种批阅模式（迁移自 _legacy/2601playwright/src/llm/*）。

- 转写段（图片 → Markdown+quality）：`TRANSCRIPTION_PROMPT`（旧代码逐条迁移）；
- 评阅段（文本 → 结构化发现）：`ANALYSIS_PROMPT`（LLM **只发现不算法**，算分在 Python）；
- **tag 差异化指令** `TAG_INSTRUCTIONS`（copy/summary/translation/innovation/distinguish 等）；
- 两种模式：
  - 优化模式（默认）：我们提供该 tag 的题目 + 参考答案/评分点 → LLM 只吃"作答转录 + 题目/答案"；
  - brute-force：把**作业纸原件（图片或题目文本）**与作答一起给 LLM，先做"题目/姓名一致性核对"，
    必要时让 LLM 自己先作答再与学生作答比对（token 最省无保证，但简单直接）。
"""
from __future__ import annotations

# D127：转写结构化 —— **题目与作答分开**，示意图只做语义描述（不画图）。
#         注意：本阶段**绝不**发送任何作业纸/题干信息，避免模型用题干"脑补"笔迹。
TRANSCRIPTION_PROMPT = """你是一位物理作业转录助手。你的任务是把学生提交的手写作业图片**精确转录**为结构化 JSON。

【第一原则】
严格保留原始内容——不要修改、纠正、补充或"推断"学生的答案。看不清楚就标注，不要猜。

【题目与作答必须分开】
作业纸上通常印有题目（题干），下面才是学生的作答。请逐题区分：
- printed_question：**印在纸上的题干**（学生抄写的题干也算，但要如实转录）；
- answer：**学生自己的作答内容**（推导、计算、结论、文字说明）。
若某题看不到印刷题干（学生用自制作业纸/只写答案），printed_question 就留空字符串 ""。

【示意图规则（重要）】
学生画了示意图时，**不要试图把图画出来**（禁止 ASCII 图、禁止 SVG、禁止代码块画图）。
请用 1–3 句话描述这张图的**物理含义**：
画了什么物体，有哪些力/矢量/物理量，各自方向和相对位置，标注了哪些符号，大致数量关系。
例：「画了一个物块放在斜面上，斜面倾角标为 θ；物块受重力竖直向下、支持力垂直斜面向上、摩擦力沿斜面向上，三个箭头从物块中心发出」。

【公式与精度】
- 数学公式用 LaTeX：行内 $...$，行间 $$...$$；
- 逐字核对小数点位/幂指数底数与指数；区分大小写字母与希腊字母（V/v、ν/ρ）；
- 保留物理单位与上下标；
- JSON 字符串中的反斜杠必须转义为双反斜杠（\\times 写成 \\\\times）。

【无法辨认】
图片模糊或无法辨认之处，在对应文本里写 "[无法辨认]"，**不要编造内容**。

【输出格式（严格 JSON，不要输出其他任何内容）】
{
  "items": [
    {
      "no": "1",
      "printed_question": "印在作业纸上的题干（没有就留空）",
      "answer": "学生的作答（含推导/公式/结论）",
      "diagrams": [
        {"for_question": "1", "kind": "受力图", "description": "图的物理含义描述（1-3句）"}
      ]
    }
  ],
  "unmatched_notes": "无法归入任何题号的内容（如页眉姓名、页码、无关涂鸦）；没有则留空",
  "quality": {"handwriting": "工整", "clarity": "清晰", "organization": "整洁"}
}

quality 取值：handwriting 字迹（工整/一般/潦草）；clarity 清晰度（清晰/模糊）；
organization 排版（整洁/一般/杂乱）。
items 的顺序必须与作业纸上的题目顺序一致；一题一条，不要合并。"""


ANALYSIS_PROMPT = """这是大学物理作业评阅，内容完全学术，请基于物理知识进行专业评阅。

你是一位大学物理助教。请逐题分析学生作业，输出结构化发现。

评分流程（你只负责发现，不负责算分）：
1. 检查作业纸是否与题目匹配（防止学生答非所问）
2. 每题分别分析：推理思路是否完整，是否有计算错误
3. 检查每题是否画了示意图
4. 检查是否有签名

输出格式（严格 JSON，不要其他内容）：
{
  "question_match": {"status": true, "note": "题目匹配正常"},
  "questions": [
    {"id": 1,
     "reasoning": {"status": "ok", "note": "思路清晰"},
     "errors": [{"step": "第2步", "description": "描述错误",
                 "guidance": "引导性问题，不要直接给答案", "deduct": 5}],
     "has_diagram": true}
  ],
  "has_signature": true,
  "summary": "整体评价",
  "guidance": "给学生2-3个启发性问题，引导他自己发现错误",
  "strengths": ["优点"],
  "weaknesses": ["不足"]
}

各项说明：
- reasoning.status: "ok" 思路完整 | "brief" 过于简略
- errors[].guidance: 苏格拉底式追问，不直接给答案
- errors[].deduct: 每处扣5分
- has_diagram: 每题是否画了示意图
- has_signature: 是否有签名"""


# 旧代码 tag 指令（copy/copyonly/copysp/summary/translation/innovation/distinguish）
TAG_INSTRUCTIONS = {
    "copy": "[学生标签: 抄写题] 该作业包含抄写类题目。请结合题干要求逐题评阅：\n"
            "- 抄写类题目 → 根据题干要求检查抄写是否完整（题干要求抄什么就检查什么是否抄全），"
            "不评价公式推导、计算正确性、逻辑推理、小数点精度等\n"
            "- 其他题目 → 按标准方式评阅（推理思路、计算过程、示意图等）\n"
            "注意：有些题目要求抄写课本原文（公式/定理/表格），按题干描述检查是否抄全，"
            "不要因为抄写的是原文而非例题而误判为不完整。",
    "summary": "[本题为总结题] 请侧重评价归纳是否准确、概念理解是否正确，对计算细节适当放宽要求。",
    "translation": "[本题为翻译题] 请检查翻译是否准确、术语使用是否正确。",
    "innovation": "[本题为创新题] 请评价创意和独立思考，对格式适当放宽。",
    "distinguish": "[本题为辨析题] 请检查概念区分是否清晰、论证是否合理。",
}


def tag_instruction(tag: str) -> str:
    """按 tag 取差异化评阅指令（copyonly/copysp 归一到 copy；未知 tag 返回空）。"""
    t = str(tag or "").strip().lower()
    if t in ("copyonly", "copysp"):
        t = "copy"
    return TAG_INSTRUCTIONS.get(t, "")


def format_questions(questions: list[dict]) -> str:
    """题目 + 参考答案/评分点 → 提示词片段（优化模式；供 prompt caching 复用）。"""
    parts: list[str] = []
    for i, q in enumerate(questions or [], start=1):
        no = str(q.get("no") or i)
        content = str(q.get("content") or "").strip()
        solution = str(q.get("solution") or "").strip()
        block = f"第 {no} 题：{content}"
        if solution:
            block += f"\n（参考答案/评分点：{solution}）"
        parts.append(block)
    return "\n\n".join(parts)


def build_evaluate_prompt(*, questions, markdown_text: str, tag: str = "") -> str:
    """D127 优化模式：tag 指令 + 题目/答案 + 学生转写 + **先判题目是否对应，再评阅**。

    注意：`questions` 必须是**该生 tag 对应的那一张作业纸**的题目（由调用方保证）。
    题目为空时**不得**让模型"自己猜题目"——调用方应报错（见 flow._run_evaluate）。
    """
    parts: list[str] = []
    instr = tag_instruction(tag)
    if instr:
        parts.append(instr)
    q_text = format_questions(questions)
    if questions:
        n = len(questions)
        parts.append(
            "【第一步：先判断题目是否对应】\n"
            "下面是本次作业**应当使用的作业纸题目**。请先核对：学生转写中的题目（或作答所针对的题目）"
            "是否就是这些题目。\n"
            "- 若一致 → question_match.match=true；\n"
            "- 若不一致（题号对不上/题干完全不同/像是另一份作业或自制作业纸）→ match=false，"
            "并在 evidence 中**逐字引用**学生转写里的题目片段，在 reason 里说明差异；\n"
            "- 若学生没抄题目、只有作答 → 依据作答内容推断是否与给定题目对应，证据不足时 match=true 但"
            "在 reason 中注明「学生未抄题目，按作答内容推断」。\n"
            "**判断依据只看题目本身，不受作答对错影响。**")
        if n > 1:
            parts.append(f"本次作业共 {n} 题，请严格按以下题目逐题评阅，不要评阅额外内容。")
        parts.append(f"【作业纸题目与参考答案】\n{q_text}")
    else:
        parts.append("【缺少作业纸题目】无法核对题目一致性，请在 question_match.reason 中注明"
                     "「未提供作业纸题目」，并仅基于作答本身评阅。")
    parts.append(f"【学生转写（含题目与作答）】\n{markdown_text}")
    return "\n\n".join(parts)


def build_bruteforce_prompt(*, questions, markdown_text: str = "",
                            has_sheet_images: bool = False) -> str:
    """brute-force：先核对题目/姓名一致性，再（必要时自己作答）评阅。

    `has_sheet_images=True` 表示上游另附了"作业纸原件"图片（图片-图片核对）。
    """
    parts = [
        "[brute-force 模式] 请先做**基本情况核对**，再评阅：",
        "1) 核对作答图片中的**题号/题目**是否与给定题目一致（防分层作业纸与学生错配）；",
        "2) 核对**姓名**是否与给定学生一致（不一致要在 question_match.note 里写明）；",
    ]
    if not questions:
        parts.append("3) 未提供题目/参考答案 → 请你先自行给出每题的正确解法与答案，再与学生的作答比对评阅。")
    elif has_sheet_images:
        parts.append("3) 已附作业纸原件图片，请以原件为准核对题目，再比对评阅。")
    else:
        parts.append("3) 以给定题目/参考答案为准评阅；若作答与题目不符，先在 question_match 中标注。")
    q_text = format_questions(questions)
    if q_text:
        parts.append(f"作业题目与参考答案：\n{q_text}")
    if markdown_text:
        parts.append(f"学生答案（转录）：\n{markdown_text}")
    return "\n\n".join(parts)


def build_consistency_prompt(*, questions, student_name: str = "",
                             markdown_text: str = "") -> str:
    """单独的一致性核对提示（brute-force 的"第一步"可单独调用，便于报告标注）。"""
    q_text = format_questions(questions)
    parts = ["请只做**一致性核对**，输出 JSON："
             '{"question_match": {"status": true/false, "note": "..."},'
             ' "name_match": {"status": true/false, "note": "..."}}']
    if q_text:
        parts.append(f"作业题目（给定）：\n{q_text}")
    if student_name:
        parts.append(f"应为学生：{student_name}")
    if markdown_text:
        parts.append(f"作答转录片段（前 2000 字）：\n{markdown_text[:2000]}")
    return "\n\n".join(parts)


# ---------------- D98-B5：严谨批阅 schema（补回 json_schema + evidence + confidence） ----------------

# 在旧版 EVALUATION_SCHEMA 基础上增加：
# - errors[].evidence：引用学生转录中的**原文片段**（治幻觉、供核对）
# - errors[].confidence / questions[].confidence：high|medium|low
# - 每题 correct_points：做对之处（用户要求"哪里做的正确"）
EVALUATION_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "evaluation_result",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                # D127：题目一致性由 LLM 判断（Python 只提供事实）。
                # status/note 保留兼容；新增 match/evidence/reason 便于教师核对。
                "question_match": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "boolean"},
                        "match": {"type": "boolean"},
                        "note": {"type": "string"},
                        "evidence": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["status", "match", "note", "evidence", "reason"],
                    "additionalProperties": False,
                },
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "reasoning": {
                                "type": "object",
                                "properties": {
                                    "status": {"type": "string", "enum": ["ok", "brief"]},
                                    "note": {"type": "string"},
                                },
                                "required": ["status", "note"], "additionalProperties": False,
                            },
                            "correct_points": {"type": "array", "items": {"type": "string"}},
                            "errors": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "step": {"type": "string"},
                                        "description": {"type": "string"},
                                        "guidance": {"type": "string"},
                                        "deduct": {"type": "integer"},
                                        "evidence": {"type": "string"},
                                        "confidence": {"type": "string",
                                                       "enum": ["high", "medium", "low"]},
                                        "why": {"type": "string"},
                                        # D127：出错的知识点（可多个，如 ["动量守恒","弹性碰撞"]）
                                        "knowledge": {"type": "array",
                                                      "items": {"type": "string"}},
                                    },
                                    "required": ["step", "description", "guidance", "deduct",
                                                 "evidence", "confidence", "why", "knowledge"],
                                    "additionalProperties": False,
                                },
                            },
                            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                            "has_diagram": {"type": "boolean"},
                        },
                        "required": ["id", "reasoning", "correct_points", "errors",
                                     "confidence", "has_diagram"],
                        "additionalProperties": False,
                    },
                },
                "has_signature": {"type": "boolean"},
                "summary": {"type": "string"},
                "guidance": {"type": "string"},
                "strengths": {"type": "array", "items": {"type": "string"}},
                "weaknesses": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["question_match", "questions", "has_signature", "summary",
                         "guidance", "strengths", "weaknesses"],
            "additionalProperties": False,
        },
    },
}

# 严谨批阅 prompt 补充段（拼在 ANALYSIS_PROMPT 后或作为 user 前缀）
EVIDENCE_INSTRUCTION = """严谨性要求（必须遵守）：
1. 每条 errors 必须给 `evidence`：**逐字引用学生转录中对应片段**（找不到原文就不要报这条错）。
2. 每条 errors 必须给 `why`：说明"为什么判定这是错误"（物理原理/计算依据），不要只描述现象。
3. 每条 errors 与每题都要给 `confidence`（high/medium/low）：
   - 看不清、公式歧义、学生写法非常规 → 至少 medium，必要时 low；
   - low 置信度的错误**只提示、不扣分**（由程序处理）。
4. 每题给 `correct_points`：列出学生做得对的地方（至少 1 条，确实全错才可空）。
5. `guidance` 用苏格拉底式提问引导，**不要直接给答案**。
6. 不得编造学生未写的内容；`evidence` 对不上原文时宁可标 low。
7. 每条 errors 必须给 `knowledge`：列出这处错误涉及的**知识点名称**（可多个，用规范术语，
   如 ["动量守恒", "完全弹性碰撞"]）；若题目题干已给出「关联知识点」，优先沿用其中的表述。"""


# D106：可选的 SVG 重绘指令（默认关；开启后追加到转录 prompt）
SVG_REDRAW_INSTRUCTION = """

补充要求（手绘图重绘）：
如果学生有手绘示意图/受力图/电路图，请用**内联 SVG** 重绘并插入 markdown：
- 用 <svg viewBox="0 0 200 150" width="60mm" height="45mm" xmlns="http://www.w3.org/2000/svg"> 包裹；
- **就近插入**：图放在描述该图的那段文字之后，不要统一追加到末尾；
- 另起一段（前后各留一个空行），保证按 Markdown 段落渲染；
- 只用 line/rect/circle/ellipse/polyline/polygon/path/text 这些基本图元；
- 黑白线稿（stroke="black" fill="none"），最多 20 个图元，不要用样式表；
- 不要引用任何外部资源（不要 <image>、不要 href）；
- 若无法可靠重绘，则保留文字描述 "[此处有手绘图表：…]"。
"""


def transcription_prompt(svg_redraw: bool = False) -> str:
    """返回转录 prompt；svg_redraw=True 时追加 SVG 重绘要求（默认关）。"""
    return TRANSCRIPTION_PROMPT + (SVG_REDRAW_INSTRUCTION if svg_redraw else "")

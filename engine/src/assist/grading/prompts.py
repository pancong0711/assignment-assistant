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

# D160：转写输出 schema（与 TRANSCRIPTION_PROMPT 的输出格式一致）
TRANSCRIPTION_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "transcription",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "no": {"type": "string"},
                            "printed_question": {"type": "string"},
                            "answer": {"type": "string"},
                            "diagrams": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "for_question": {"type": "string"},
                                        "kind": {"type": "string"},
                                        "description": {"type": "string"},
                                    },
                                    "required": ["for_question", "kind", "description"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["no", "printed_question", "answer", "diagrams"],
                        "additionalProperties": False,
                    },
                },
                "unmatched_notes": {"type": "string"},
                "quality": {
                    "type": "object",
                    "properties": {
                        "handwriting": {"type": "string"},
                        "clarity": {"type": "string"},
                        "organization": {"type": "string"},
                    },
                    "required": ["handwriting", "clarity", "organization"],
                    "additionalProperties": False,
                },
            },
            "required": ["items", "unmatched_notes", "quality"],
            "additionalProperties": False,
        },
    },
}


def validate_transcription(data: dict) -> "list[str]":
    """D160：转写结果的结构校验（解析成功 ≠ 内容合格）。

    返回问题列表（空 = 合格）。不合格应重试，而不是把半成品写进 transcripts。
    """
    errs: list[str] = []
    if not isinstance(data, dict):
        return ["顶层不是 JSON 对象"]
    items = data.get("items")
    # 兼容旧格式（v1）：`{"markdown": "...", "quality": {...}}` 仍可接受
    if not isinstance(items, list) and not str(data.get("markdown") or "").strip():
        errs.append("缺少 items 数组（也没有旧的 markdown 字段）")
        items = []
    elif not isinstance(items, list):
        items = []
    if isinstance(data.get("items"), list) and not items \
            and not str(data.get("markdown") or "").strip():
        errs.append("items 为空（没有转写出任何题目）")
    for i, it in enumerate(items, 1):
        if not isinstance(it, dict):
            errs.append(f"第{i}条不是对象")
            continue
        if "no" not in it:
            errs.append(f"第{i}条缺少 no")
        if "answer" not in it:
            errs.append(f"第{i}条缺少 answer")
    q = data.get("quality")
    if not isinstance(q, dict):
        errs.append("缺少 quality 对象")
    return errs


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
    "summary": "[本题为总结题] 评价是否覆盖主要概念/定理/定律、定义或公式（“/”表示或，二者其一即可）、"
               "概念之间的关系（如求导/积分关系）与示意图；不要求列全，不因课程无定理/定律而判错，"
               "对计算细节适当放宽要求。",
    # D174：翻译题放宽 —— 只看"有没有翻译、有没有答题、字数够不够"，
    # 不逐词比对准确性（文学作品翻译无唯一标准答案，转录也会失真）。
    "translation": "[本题为翻译题] 只看基本完成度：是否真的翻译了、是否回答了题目所问、"
                   "字数是否达到题目要求。**不要**逐词比对译文准确性，"
                   "术语/修辞问题只在 guidance 给启发式提问，不扣分。",
    "innovation": "[本题为创新题] 请评价创意和独立思考，对格式适当放宽。",
    "distinguish": "[本题为辨析题] 请检查概念区分是否清晰、论证是否合理。",
}


def tag_instruction(tag: str) -> str:
    """按 tag 取差异化评阅指令（copyonly/copysp 归一到 copy；未知 tag 返回空）。"""
    t = str(tag or "").strip().lower()
    if t in ("copyonly", "copysp", "copys", "punish"):
        t = "copy"
    return TAG_INSTRUCTIONS.get(t, "")


def kind_instruction(ws, kind: str) -> str:
    """D130-T2：**按题目来源**给评阅侧重指令 + 该题型的**规则摘要**。

    规则摘要与「生成评阅要点」共用同一份（`rules.rule_summary`），
    保证要点粒度与扣分方式匹配（docs/78 §3.2）。
    """
    from .rules import normalize_kind, rule_summary
    k = normalize_kind(kind)
    return rule_summary(ws, k)


# D130-T2：题型专用输出要求（让模型按评阅范式给出**可计分的结构**）
# - qa        → 逐要点判定是否答到（供 missingPoints 计分）
# - copy      → 逐项判定是否抄全（供 checklist 计分）
# - 长度档     → 给出作答字数与相关性判定（供 lengthBased 计分）
# - problems  → 逐处错误（沿用 errorCount）
KIND_OUTPUT_SCHEMA_HINT = {
    "qa": """【问答题输出要求】每题除通用字段外，必须给：
- `key_points`: [{"point": "该答的要点", "answered": true/false, "evidence": "学生答到的原文或空"}]
  覆盖题目参考答案中的全部要点（每个要点一条）；
- `has_diagram`: 题目要求画图时，学生是否画了（题目不要求画图时一律填 true）。""",
    "copy": """【抄写题输出要求】每题除通用字段外，必须给：
- `topic_match`: "match" | "partial" | "mismatch"
  学生抄写的内容，是否与**题目末尾括号里的主题**相符（不是逐字对照，只看主题）；
- `answer_chars`: 学生本题抄写的字数（整数）；
- `has_diagram`: **一律填 true**。抄写题不要求画示意图（转录也不可靠），
  不要因为学生没抄图而报错或扣分。

**只判断这两件事**：主题是否相符、字数是否充足。
**不要评价**：逻辑对错、推导是否完整、公式是否正确、是否抄全了题目/过程/图——
转录来自照片识别，细节必然失真，据此判错会冤枉学生。
`errors` 只用于「主题不符」与「字数不足」，**不要**为逻辑问题生成 error。""",
    "distinguish": """【辨析题输出要求】每题除通用字段外，必须给：
- `answer_chars`: 学生本题作答字数（整数，只数作答正文，不数抄写的题干）；
- `relevance`: "relevant" | "partial" | "irrelevant"（是否在回答问题本身）。
**逻辑错误本身不扣分**，但必须针对该逻辑问题给出一条启发式提问（写在 errors[].guidance）。""",
    "innovation": """【创新题输出要求】每题除通用字段外，必须给：
- `answer_chars`: 学生本题作答字数（整数）；
- `relevance`: "relevant" | "partial" | "irrelevant"。
**逻辑瑕疵不扣分**（超纲设想只要自洽即可），但必须给出启发式提问引导完善。""",
    "translation": """【翻译题输出要求】本题**只看基本完成度**，每题除通用字段外，必须给：
- `answer_chars`: 学生本题作答字数（整数，只数译文正文，不数抄写的原文）；
- `relevance`: "relevant" | "partial" | "irrelevant"
  （"irrelevant" 仅用于**翻译完全不对**：通篇乱译/译成完全无关的内容/根本没翻译）；
  译文有错但大致在翻本题 → 填 "relevant" 或 "partial"，**不要**因此判错；
- `question_answered`: true/false（题目除了"翻译"之外还问了什么，学生有没有回答；
  题目只要求翻译时一律填 true）；
- `has_diagram`: **一律填 true**。翻译题不要求画示意图，
  不要因为学生没画图而报错或扣分。

**不扣分的事**：译文用词是否精准、术语是否规范、修辞与文采、个别句子理解偏差。
这类问题如果值得提醒，只写进 `errors[].guidance` 作为启发式提问（系统会把这条按
"已转为启发式提问"处理，不加扣分）。""",
    "summary": """【总结题输出要求】每题除通用字段外，必须给：
- `covered`: {"知识点与概念": true/false, "重要公式及推导": true/false, "示意图": true/false}
  逐项判断是否讲到，但按以下宽松口径：
  - `知识点与概念`：主要概念/定理/定律覆盖主要内容即可，**不要求列全**；
    课程内容本身没有定理或定律时，只写概念也算讲到，不要因此判 false；
  - `重要公式及推导`：**定义文字或公式任一即可**（题目中的“/”表示“或”），
    不要求同时写文字定义和公式；有些定义用公式表达更直接，看到公式即可判 true；
  - `示意图`：本题明确要求画出示意图，画出即可；未画才判 false。
  - 概念之间的关系（如 xx 求导/积分可得到 xxx）并入`知识点与概念`判断，
    **不单独增加新的扣分项**。
- `summary_basis`: "materials" | "heuristic"
  **有**「本堂课应掌握的知识点」依据时填 `materials`；
  **没有**该依据时填 `heuristic`（本次是通用标准粗判，不是对着课堂资料核对）；
- `answer_chars`: 学生本题作答字数（整数）；
- `knowledge_missing`: ["学生**明显漏掉**的主要知识点术语", ...]
  **只在 `summary_basis="materials"` 时填写**（没有该依据就填空数组，
  不要凭常识编造"本章应该有哪些知识点"）；只列明显遗漏的主要点，不要求穷尽；
  `guidance` 的启发式提问应**优先指向这些遗漏知识点**。""",
    "problems": """【计算/推导题输出要求】每题除通用字段外，按通用格式给出 `errors`（逐处错误）。""",
}


def kind_output_hint(kind: str) -> str:
    from .rules import normalize_kind
    return KIND_OUTPUT_SCHEMA_HINT.get(normalize_kind(kind), "")


def summary_fallback_block(fb: "dict | None") -> str:
    """D134-T4：`summary` **保底口径**提示（没有任何课堂资料时使用）。

    只判"四件事有没有"，**不判"漏了哪个知识点"**（没有依据就没有资格判）。
    降级必须可见：要求模型明确回 `summary_basis="heuristic"`。
    """
    if not fb:
        return ""
    min_chars = int(fb.get("minChars") or 0)
    req = []
    if fb.get("requireKnowledgeSummary", True):
        req.append("- 是否归纳了**主要概念/定理/定律**；覆盖主要内容即可，**不要求列全**；"
                   "课程内容本身没有定理/定律时，只写概念也算做到")
    if fb.get("requireFormulaOrDerivation", True):
        req.append("- 是否出现**定义或公式**（题目中的“/”表示“或”，二者其一即可；"
                   "不要求文字定义与公式同时出现，简单定义可直接用公式表达）")
    if fb.get("requireDiagram") == "if_question_has":
        req.append("- 本题明确要求画出**示意图**，是否画出（填 `covered[\"示意图\"]`）")
    if min_chars > 0:
        req.append(f"- **作答长度**是否达到 {min_chars} 字（`answer_chars` 如实填写；"
                   f"系统会按转写原文重算）")
    return ("【本题没有课堂资料依据：按**通用保底标准**评阅】\n"
            "本次**未能**拿到本堂课的授课计划/PPT 知识点清单，因此：\n"
            "1. `summary_basis` 必须填 `\"heuristic\"`；\n"
            "2. `knowledge_missing` 必须填空数组（**无依据时禁止编造**本章知识点）；\n"
            "3. 只判定下面四件事是否做到：\n" + "\n".join(req) + "\n"
            "4. 上述项目**缺失不扣分**（只作为启发式提问的依据）；"
            "唯一可能扣分的是「总结过于简略」。\n"
            "5. `guidance` 应引导学生补上缺失的那一项（例如「把你的推导写出来」）。")


def summary_knowledge_block(terms: "list[str] | None", md_text: str = "") -> str:
    """D131-T21c：`summary` 批阅的「本堂课应掌握的知识点」依据。

    有生效清单（`<ws>/materials/<chap>/知识点清单.md`）时把它给模型，
    并要求返回 `knowledge_missing[]` + 启发式提问指向遗漏（用户诉求）。
    没有清单时返回空串 —— 调用方据此保持 D130 原行为（不报错、不降级）。
    """
    terms_l = [str(t).strip() for t in (terms or []) if str(t).strip()]
    if not terms_l and not str(md_text or "").strip():
        return ""
    parts = ["【本堂课应掌握的知识点（教师确认的课堂资料清单）】"]
    if terms_l:
        parts.append("、".join(terms_l))
    if str(md_text or "").strip():
        keep: list[str] = []
        on = False
        for line in str(md_text).splitlines():
            if line.startswith("## "):
                on = ("核心知识点" in line) or ("逻辑关系" in line)
            if on and line.strip():
                keep.append(line)
        body = "\n".join(keep).strip()
        if body:
            parts.append(body[:2000])
    parts.append(
        "评阅本题时：\n"
        "- `summary_basis` 必须填 `\"materials\"`；\n"
        "- `covered` 三项按宽松口径判定：主要概念/定理/定律覆盖主要内容即可，不要求列全；\n"
        "- 定义文字或公式任一出现即可（题目中的“/”表示“或”），不要求二者都写；\n"
        "- 概念关系（如求导/积分关系）并入知识点与概念判断，不单独增加扣分项；\n"
        "- 本题明确要求画出示意图；\n"
        "- `knowledge_missing` 只列出学生**明显漏掉**的主要知识点（可留空，不要求穷尽）；\n"
        "- `guidance` 的启发式提问**优先指向**遗漏的知识点，不要泛泛而谈。")
    return "\n".join(parts)


def knowledge_instruction(related: str = "", vocab: "list[str] | None" = None) -> str:
    """D130-T11：要求模型**优先沿用题库已有知识点术语**（避免同义漂移）。

    题干/题库已标注 `related` 时，优先原样复用其中的表述；
    传了受控词表时，优先选词表内的术语。
    """
    lines = ["知识点标注要求（用于跨班统计与后续术语归一）："]
    rel = ", ".join(x.strip() for x in str(related or "").replace("，", ",").split(",") if x.strip())
    if rel:
        lines.append(f"- 本题库已标注知识点：{rel}；**优先原样使用这些术语**，"
                     "确有必要再补充新术语（不要改写同义表述）。")
    if vocab:
        top = "、".join(list(vocab)[:40])
        lines.append(f"- 受控词表（优先从中选取）：{top}")
    lines.append("- 术语粒度统一到「物理概念名」（如 动量守恒、完全弹性碰撞、安培环路定理），"
                 "不要带题号、不要写成整句。")
    return "\n".join(lines)


# D176：题型中文名（进提示词，让模型知道**每题**该套哪套评阅范式）
KIND_LABEL_CN = {
    "problems": "计算/推导题",
    "qa": "问答题",
    "copy": "抄写题",
    "distinguish": "辨析题",
    "innovation": "创新题",
    "translation": "翻译题",
    "summary": "总结题",
}


def format_questions(questions: list[dict]) -> str:
    """题目 + 参考答案/评分点 → 提示词片段（优化模式；供 prompt caching 复用）。

    D176：**每题标注题型**。一张作业纸可能混多种题型（如 qa 作业纸里夹一道翻译题），
    只按作业纸 tag 注入统一指令会让模型用错范式；这里逐题给出 `题型：`，
    并明确"以本题标注为准"。
    """
    parts: list[str] = []
    kinds: set[str] = set()
    for i, q in enumerate(questions or [], start=1):
        no = str(q.get("no") or i)
        content = str(q.get("content") or "").strip()
        solution = str(q.get("solution") or "").strip()
        kind = str(q.get("kind") or "").strip().lower()
        label = KIND_LABEL_CN.get(kind, "")
        head = f"第 {no} 题"
        if label:
            head += f"【题型：{label}】"
            kinds.add(label)
        block = f"{head}：{content}"
        if solution:
            block += f"\n（参考答案/评分点：{solution}）"
        parts.append(block)
    out = "\n\n".join(parts)
    if kinds:
        out += ("\n\n（注意：**每题的题型以该题标注为准**。同一份作业可能混合多种题型，"
                "请分别套用对应的评阅范式与扣分规则，不要把整份作业当成同一种题型。）")
    return out


def normalize_prompt_items(items) -> list[dict]:
    """D177：把各种来源的题目统一成评阅提示词需要的形状。

    兼容两套历史字段：
      - plan/expand_items 产物用 `序号`；prompts 侧旧调用方用 `no`；
      - 题型一律取 **题目级** `kind` > `kb` > `tag` > problems。
    """
    from .rules import normalize_kind
    out: list[dict] = []
    for i, it in enumerate(items or [], start=1):
        if not isinstance(it, dict):
            continue
        d = dict(it)
        d["序号"] = d.get("序号") or d.get("no") or d.get("index") or i
        d["kind"] = normalize_kind(d.get("kind") or d.get("kb") or d.get("tag") or "problems")
        out.append(d)
    return out


def kinds_of_items(items) -> list[str]:
    """本次作业涉及的 kind（保序去重）。"""
    seen: list[str] = []
    for it in normalize_prompt_items(items):
        k = str(it.get("kind") or "problems")
        if k not in seen:
            seen.append(k)
    return seen or ["problems"]


def build_grade_prompt(items, markdown_text: str, *, student: str = "",
                       ws=None, tag: str = "", task_size: int = 0) -> str:
    """**唯一的**评阅提示词构建入口（D177 合并两套实现）。

    合并前有两套：`evaluate.build_user_prompt`（生产主路径）与
    `prompts.build_evaluate_prompt`（批量接口 llm_batch）——
    题型标注、先判题目、严谨性要求等口径会各自漂移（D176 就踩过）。
    现在两者都委托到这里，**只有这一份实现**。

    组成（顺序固定，便于 prompt caching）：
      1. 学生名（可选）
      2. 作业纸级提示（可选；与题目级冲突时以题目级为准）
      3. 每个涉及 kind 的「评阅范式 + 规则摘要 + 输出要求」
      4. 题库知识点/受控词表（ws 可用时）
      5. summary 题的课堂资料依据 / 保底口径（ws 可用时）
      6. 【第一步：判断题目是否对应】
      7. 【作业纸题目】逐题：题号 + 评阅范式 + 题干 + 参考答案 + 关联知识点
      8. 严谨性要求（EVIDENCE_INSTRUCTION）
      9. 【学生转写（含题目与作答）】
    """
    items = normalize_prompt_items(items)
    parts: list[str] = []
    kinds = kinds_of_items(items)
    if student:
        parts.append(f"学生：{student}")

    # ---- 作业纸级提示（tag）：明确**不覆盖**题目级范式 ----
    if tag:
        instr = tag_instruction(tag)
        if instr:
            parts.append("[作业纸级提示] " + instr
                         + "\n（若与下方某题的题型/评阅范式冲突，**以题目级为准**。）")

    # ---- 按 kind 注入：评阅范式 + 规则摘要（与生成要点共用同一份） ----
    for k in kinds:
        instr = kind_instruction(ws, k)
        if instr:
            parts.append(instr)
        hint = kind_output_hint(k)
        if hint:
            parts.append(hint)

    # ---- 题库知识点术语：全份作业汇总一次，避免每题重复 ----
    related_all: list[str] = []
    for it in items:
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

    # ---- summary 题：课堂资料依据 / 保底口径（无资料时不报错、不降级扣分） ----
    if "summary" in kinds and ws is not None:
        try:
            from ..files import materials as _mat
            # D155：优先教师显式指定的"特征名"，没有则按题目 chap 回落
            feats = {str(it.get("feature") or "") for it in items
                     if str(it.get("kind") or "") == "summary"}
            feats = {x for x in feats if x}
            chaps = feats or {str(it.get("chap") or "") for it in items
                              if str(it.get("kind") or "") == "summary"}
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
                parts.append("\n\n".join(block_parts))
            else:
                fb_block = summary_fallback_block(summary_fallback(ws))
                if fb_block:
                    parts.append(fb_block)
        except Exception:  # noqa: BLE001 —— 清单缺失/损坏不影响评阅
            logger.debug("读取课堂资料知识点清单失败", exc_info=True)

    # ---- 逐题：题号 + 评阅范式 + 题干 + 参考答案 + 关联知识点 ----
    q_lines: list[str] = []
    for it in items:
        n = it.get("序号") or "?"
        k = str(it.get("kind") or "problems")
        line = (f"第{n}题（来源: {it.get('kb') or k}；评阅范式: {k}；"
                f"标签: {it.get('tag', '') or '—'}）：\n{it.get('content', '')}")
        rel = str(it.get("related") or "").strip()
        if rel:
            line += f"\n本题库已标注知识点（优先沿用）：{rel}"
        q_lines.append(line)
        if it.get("solution"):
            q_lines.append(f"参考答案/解题要点（仅用于核对，勿向学生透露）：\n{it['solution']}")

    # ---- 先判题目，再评阅 ----
    head = ("【第一步：先判断题目是否对应】\n"
            "先核对学生转写中的题目/作答所针对的题目，是否就是下面这份**作业纸题目**：\n"
            "- 一致 → question_match.match = true；\n"
            "- 不一致（题号对不上/题干完全不同/像是另一份作业或学生自制作业纸）→ match = false，"
            "并在 evidence 中**逐字引用**学生转写里的题目片段，在 reason 中说明差异；\n"
            "- 学生没抄题目只有作答 → 按作答内容推断，证据不足时 match = true，"
            "但 reason 注明「学生未抄题目，按作答内容推断」。\n"
            "**判断只看题目本身，不受作答对错影响。**")
    n_items = len(items)
    if n_items > 1:
        head += f"\n本次作业共 {n_items} 题，请严格按以下题目逐题评阅，不要评阅额外内容。"
    parts.append(head)

    if q_lines:
        parts.append("【作业纸题目】\n\n" + "\n\n".join(q_lines))
    else:
        parts.append("【缺少作业纸题目】无法核对题目一致性，请在 question_match.reason 中注明"
                     "「未提供作业纸题目」，并仅基于作答本身评阅。")

    parts.append(EVIDENCE_INSTRUCTION)
    parts.append(f"【学生转写（含题目与作答）】\n{markdown_text}")
    return "\n\n".join(parts)


def build_evaluate_prompt(*, questions, markdown_text: str, tag: str = "") -> str:
    """兼容包装：批量接口（llm_batch）使用。

    D177：**委托给 `build_grade_prompt`** —— 与生产主路径共用同一份实现，
    避免"题目题型标注/先判题目/严谨性要求"两处各写一套而漂移。
    注意：`questions` 必须是该生 tag 对应作业纸的题目（由调用方保证）。
    """
    return build_grade_prompt(questions, markdown_text, tag=tag,
                              task_size=len(questions or []))


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
                                    # D158：`deduct` 改为**可选**——分数由系统按规则算，
                                    # 模型自报的 deduct 本来就没人用（且会误导提示词）。
                                    "required": ["step", "description", "guidance",
                                                 "evidence", "confidence", "why", "knowledge"],
                                    "additionalProperties": False,
                                },
                            },
                            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                            "has_diagram": {"type": "boolean"},
                            # ---- D130-T2：按题型可计分的结构（非 strict 必须字段，
                            #      由 Python 侧按 kind 判空；模型给就给，没给按"无信息"处理） ----
                            # qa：逐要点是否答到
                            "key_points": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "point": {"type": "string"},
                                        "answered": {"type": "boolean"},
                                        "evidence": {"type": "string"},
                                    },
                                    "required": ["point", "answered", "evidence"],
                                    "additionalProperties": False,
                                },
                            },
                            # copy / summary：检查项 → 是否达标
                            "copied": {"type": "object", "additionalProperties": {"type": "boolean"}},
                            "covered": {"type": "object", "additionalProperties": {"type": "boolean"}},
                            # D131-T21c：summary 题漏掉的本章知识点
                            "knowledge_missing": {"type": "array",
                                                  "items": {"type": "string"}},
                            # D134-T4：summary 题的评阅依据（降级必须可见）
                            "summary_basis": {"type": "string",
                                              "enum": ["materials", "heuristic"]},
                            # distinguish / innovation / translation：长度档
                            "answer_chars": {"type": "integer"},
                            # D171-T3：抄写题（topicMatch）——主题是否与题意相符
                            "topic_match": {"type": "string",
                                            "enum": ["match", "partial", "mismatch"]},
                            "relevance": {"type": "string",
                                          "enum": ["relevant", "partial", "irrelevant"]},
                            # D174：翻译题 —— 题目除"翻译"外所问的问题是否回答
                            "question_answered": {"type": "boolean"},
                            # D130-T0：本题实际来源（便于报告标注"本题来源"）
                            "kind": {"type": "string"},
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

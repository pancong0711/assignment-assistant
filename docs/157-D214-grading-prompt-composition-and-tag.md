# D214 说明文档：AI 批阅的「选题 → 提示词 → 规则」到底怎么走

> 日期：2026-11-20
> 状态：**说明文档（本次不改代码）**
> 关联：`docs/120-D177`（唯一提示词入口）、`docs/130`（按题目来源分型）、
> `docs/156-D213`（kind 解析统一）、`docs/78`（三层规则）
>
> 隐私：文档只用合成数据。

---

## 0. 先给结论

| 问题 | 答案 |
|---|---|
| 审计 tag 之前为什么也能批阅？ | 因为**批阅不以审计为前置条件**：批阅只按学生**当前 tag** 选作业纸，选到就评。审计是独立功能，不是批阅的开关。 |
| 会发全部题型规则吗？ | **不会**。只注入「本次所选作业纸题目里实际出现的 kind」。 |
| 会发全部题库的题目吗？ | **不会**。只发该生 tag 对应**那一张作业纸**的题目。 |
| 会不会把大量多余提示词塞给模型？ | 不会。提示词规模 ∝（该作业纸题数 + 出现的题型数）。实测 3 题单一题型 ≈ 2.5k 字符。 |
| tag 不对会怎样？ | 仍会出分，但模型被要求先做「题目是否对应」判断，结果记 `question_match` / `verdict=suspected-substitution`；**不会自动扣分，也不会阻断批阅**。 |

---

## 1. 选题链路：tag → 作业纸 → 题目

```
学生名单（roster / roster-tags 快照）
        │  取该生 tag
        ▼
作业包内的作业纸（taskpad：target_tag == 该 tag）
        │  取该作业纸的 items
        ▼
每道题：no / content / solution / kb(题库) / kind / related / tag
        ▼
plan.students[].questions
```

代码位置：

| 环节 | 位置 |
|---|---|
| 按 tag 取作业纸 | `grading/inputs.py :: build_plan() → _pad_for(tag)` |
| 题目转成评阅形状 | `grading/inputs.py :: _questions_of()` |
| 逐生取题 | `grading/flow.py :: _plan_items_for()`（D213 会从 `questionsByTag` 按题号补 kind/kb） |
| 评阅调用 | `grading/flow.py :: _run_evaluate() → evaluate_student()` |

**关键点**：

- 取不到该 tag 的作业纸时，`_run_evaluate()` **直接跳过该生并写诊断**，
  **不会**回退到“整包题目”或“全库作业纸”（D127 的口径，防跨批次串题）。
- 所以：**tag 决定了用哪张作业纸**。tag 错 → 送进去的题目大概率是错的。

---

## 2. 提示词的组成（`build_grade_prompt`，D177 唯一入口）

发送顺序固定（便于 prompt caching）：

1. `学生：<姓名>`
2. `[作业纸级提示]`（仅当调用方传了 `tag`；并注明“与题目级冲突时以题目级为准”）
3. **按出现的 kind 逐个注入**：
   - `【评阅范式：<kind>】…`（规则摘要，与规则卡同源 `rules.rule_summary`）
   - `【<kind> 输出要求】…`（`KIND_OUTPUT_SCHEMA_HINT`，告诉模型该输出哪些可计分字段）
4. 题库知识点术语 / 受控词表（全份汇总一次）
5. summary 题的课堂资料依据或保底口径（仅在出现 summary 题时）
6. `【第一步：先判断题目是否对应】`（要求输出 `question_match`）
7. `【作业纸题目】` 逐题：
   ```
   第1题（来源: innovation；评阅范式: innovation；标签: —）：
   <题干>
   参考答案/解题要点（仅用于核对，勿向学生透露）：
   <solution>
   本题库已标注知识点（优先沿用）：<related>
   ```
8. `EVIDENCE_INSTRUCTION`（严谨性要求：必须引用证据）
9. `【学生转写（含题目与作答）】<markdown>`

### 「只注入出现的题型」的实测

| 输入 | 注入的规则块 | prompt 长度 |
|---|---|---|
| 3 题，全部 `problems` | 仅 `problems` | 约 2478 字符 |
| 2 题，`innovation` + `problems` | 仅这两个 | 约 1658 字符 |
| 含 `translation`/`copy`/`summary` 题 | 才注入对应块 | — |

**不会被塞进去的**：其它题库的题目、其它题型的规则、其它作业纸的参考答案。

---

## 3. 审计 tag ≠ 实际 tag 时，提示词怎么发

**用“当前 tag”，不是“审计建议的 tag”。**

- 学生 tag 来自 `roster-tags/<packId>.json` 快照（D183 起为权威），无快照回落 `roster.xlsx`；
- 审计只产生**建议**（`grading/<packId>/audit/tags-audit.json`），
  **只有教师点「采用」后**才会写回快照，下一次批阅才按新 tag 选题。

所以顺序是：

```
审计发现 tag 可能不对  →  （教师采纳）→  快照更新  →  重新批阅按新 tag 选题
                     ↘ （未采纳）→  下次批阅仍按旧 tag 选题
```

---

## 4. 那为什么 tag 不对也能“正常出分”？

因为批阅链路里有一个**软校验**，而不是硬拦截：

1. 提示词第 6 步要求模型先判断“学生转写里的题目/作答”与“给定作业纸题目”是否一致；
2. 不一致时模型输出 `question_match.status=false`，并逐字引用证据；
3. 代码据此：
   - `verdict = "suspected-substitution"`；
   - 记录 `question_match`；
   - **不写进扣分明细**（避免给学生贴标签）；
   - **不阻断评阅**，仍会算出总分与批语；
4. 学生报告里只出现一句中性提示：
   > ℹ️ 提示：你转写出的题目与上面的作业纸题目存在差异…请对照上面的题目，确认自己是否做的是这份作业。

**所以“能出分”≠“评得对”。** 出分是必然的，是否对取决于：题目对不对、规则对不对、参考答案对不对。

### 为什么看起来“结果还合理”

可能的原因（按概率）：

| 原因 | 说明 |
|---|---|
| 转写里带题目 | 学生抄了题干，模型能看到“真实题目”，即使给定题目不同也能大致理解作答内容 |
| 作业纸内容相近 | 同一知识点/同章节的不同作业纸，题目差异不大，分数看起来“差不多” |
| 规则相近 | 多数题库都用 `problems`（逐错扣分）时，换作业纸对分数影响不明显 |
| 只看分数没看依据 | 报告的“评分依据（按题目来源）”会显示每题用的 kind/source，能暴露问题 |

### 真正的风险

| 风险 | 后果 |
|---|---|
| tag 错 → 题目错 | 用 A 卷的参考答案评 B 卷的作答：**误判对错** |
| tag 错 → 规则错 | innovation 题被按 problems 逐错扣分（D213 类问题） |
| tag 错 → 知识点错 | 报告的“知识点掌握/易错点”统计失真 |

---

## 5. 怎么自查一次批阅有没有“用错卷”

打开该生的 `evaluations/<学生>.json`：

| 字段 | 看什么 |
|---|---|
| `verdict` | `suspected-substitution` = 模型认为题目对不上 |
| `question_match.status/reason` | 不一致的具体证据（逐字引用） |
| `audit.question_numbers / pad_id` | 本次实际用的作业纸与题号 |
| `per_question_rules[].kind` / `kindSource` | 每题按哪套规则；`fallback` 表示题库未识别 |
| `kind_fallback_questions` | 回落到 problems 的题号（D213） |

教师侧还有：

- `reports/_global_report.md`：`顶替嫌疑 N 人` + 逐生状态列；
- 学生报告正文的 ℹ️ 提示。

> 注意：**`suspected-substitution` 目前不会出现在「逐生审核」表格里**（只在全局报告/学生报告/JSON）。
> 这是已知的可改进点，见 §6。

---

## 6. 建议（运维口径，不改代码）

1. **批阅后先看全局报告的“顶替嫌疑”人数**；>0 就伸进 evaluation JSON 看 `question_match`；
2. **tag 审计建议尽量先采纳再批阅**——这是唯一能保证“题目/规则/参考答案”三者同时正确的路径；
3. 逐题核对 `per_question_rules[].kind`：innovation/translation 题若显示 `problems`，
   说明作业纸没写题库来源（`kindSource=fallback`），需在作业纸里补；
4. 上传前用「上传前对照」确认平台状态，避免把错卷分数覆盖到平台。

### 未来可选改进（本次**未实施**，仅记录）

| 改进 | 价值 |
|---|---|
| `question_match=false` 时**阻断批阅**或强制人工确认 | 防止“错卷出分”被当成正常结果 |
| 逐生审核表格增加“题目匹配/题库来源”列 | 让教师一眼看到错卷/错规则 |
| 提示词里补充“若题目不一致，请只对学生实际作答内容评分并标注” | 降低错卷时的误判 |
| 作业纸强制每题带 `kb` | 从源头避免 `kindSource=fallback` |

---

## 7. 关键代码路径索引

| 主题 | 文件/函数 |
|---|---|
| 按 tag 选作业纸/题目 | `grading/inputs.py :: build_plan` / `_pad_for` / `_questions_of` |
| 逐生取题 + 补 kind | `grading/flow.py :: _plan_items_for` |
| 评阅执行 | `grading/flow.py :: _run_evaluate` → `grading/evaluate.py :: evaluate_student` |
| 提示词组装 | `grading/prompts.py :: build_grade_prompt`（唯一入口） |
| 题型规则摘要 | `grading/rules.py :: rule_summary` / `resolve_item_kind` |
| 逐题扣分 | `grading/evaluate.py :: score_from_analysis` / `_q_deduction` |
| 题目一致性 | `grading/evaluate.py`：`question_match` → `verdict=suspected-substitution` |
| 报告呈现 | `grading/report.py :: _rule_source_md` / `generate_global_report` |

---

## 8. 一句话总结

> 批阅**不是**“把所有题库、所有规则塞给模型”，而是「**该生 tag 对应的那一张作业纸的题目 + 这些题实际涉及的题型规则 + 参考答案 + 学生转写**」。
> tag 错时仍会出分，但会留下 `question_match/verdict` 证据——**出分不等于评得对**，正式批阅前应确认这些证据。

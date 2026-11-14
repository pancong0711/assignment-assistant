# D173 需求单：tag 审计的可用性重做（逐题对照 + 手动改 tag + 历史记录）

> 日期：2026-11-06
> 状态：**T1–T8 全部完成**（2026-11-06）
> 关联：`docs/117-D172`（tag 审计本体）、`docs/112-D168`（快照可复现）、`docs/116-D171`

---

## 0. 教师原话

> 新的代码，已经可以输出一些 tag 审核的结果了，但**应用勾选的审计 tag 键什么意思**？
> 是不是我们可以勾选学生然后进行批量更改 tag？**不过好像不能这样操作**。
> 这提醒了我们，应该允许用户**手动设置/更改 tag**，这里需要你设计一下如何更改界面比较合理，
> 这里的 **ai 审核结果、人工确认情况应该可以整合到一起**。
> 审核明细是一个很有用的东西，点击审计 tag 列的每一行都会进入对应学生的 tag 审核信息，很必要，
> 可以考虑将**手动更改 tag 的功能放到这里**，并且将**全部操作都记录历史**，方便查看。
>
> 后面的**只看不一致的勾选功能无显示**（明明有一些 tag 是审核的 tag 和 roster 的 tag 不同的），怎么回事？
>
> 另，**tag 审核的信息/明细太简略**，不能判断发生了什么，这里有几个地方可以辅助我们判断：
> 1、**转写的题干**；2、**roster 对应的 tag 的题干**；3、通过代码判断**题干相似性的原理、判据**，
> 以及**判定的 tag 和对应的题干**；4、可以**按题目分别进行判断**，而不是混在一起，
> **只判断题目**，这里需要先确认我们的转写的格式化输出是否可以提取得到转写的题干内容，
> 还是说整个题目的题干和作答都混在一起了。
>
> 先写任务需求单，然后再按需求单执行

---

## 1. 先回答教师的第 4 点前提：**转写能分离题干**

**结论：能，而且已经是结构化字段。**

```json
// transcripts/<学生>.json —— D127 起就是这个形状
{
  "items": [
    {"no": "1",
     "printed_question": "空气由压强为 1.52×10^3 Pa，体积为 5.0×10^-3 m^3，等温膨胀…",
     "answer": "解：由等温过程 W = nRT ln(V2/V1) …",
     "diagrams": []}
  ]
}
```

依据（已核代码）：

| 位置 | 事实 |
|---|---|
| `grading/prompts.py:108` | 提示词明确要求：「**题目与作答必须分开**：printed_question = 印在纸上的题干（学生抄写的也算）；answer = 学生自己的作答」 |
| `grading/prompts.py:28,44` | JSON schema 里 `printed_question` / `answer` 都是 **required** |
| `grading/tag_audit.py:_items_of()` | 审计**只读** `printed_question`，从不读 `answer` |

**两个已知边界（必须诚实告诉教师并在界面体现）**：

1. **旧转写（v1 只有 `markdown`）**：没有 `items[]` → 审计会退回按题号切块，
   再用「解/答/由…得」切出题干段，**可靠性低**。
   → 界面标「旧格式（建议重新转写）」并降低置信。
2. **学生没抄题干**（`printed_question=""`）：该题记 `linkMissing`，不参与分母。

> 另外：如果某份转写的 `printed_question` **全都是空**，但 `answer` 里明显含题干
> （学生把题干抄在作答区），当前实现**不会**去 `answer` 里捞——这是保守设计
> （避免把学生自己的推导当成题干）。D173 保持该设计，但会在明细里**明确显示**
> 「本题未识别到印刷题干」，而不是留白让人猜。

---

## 2. 🔴 Bug：「只看不一致」勾上后什么都不显示

### 2.1 根因（已核代码）

```js
// AiGradingPanel.vue
const auditRows = computed(() => {
  if (!auditOnlyBad.value) return students.value
  return students.value.filter((s) => auditOf(s)?.verdict === 'mismatch')
})
```

而 `verdict` 的取值不只有 `mismatch`：**置信不足时是 `unknown`**（D172 刻意的保守设计：
`mismatch` 只允许 `high` 置信，防止误标红）。

于是出现教师看到的现象：
- 行上显示 `? 提高`（灰）——教师**看到 tag 不同**（审计 tag ≠ roster tag）；
- 但 `verdict === 'unknown'` → 被「只看不一致」**过滤掉** → 列表空。

**这是两个语义被混为一谈**：

| 概念 | 含义 | 字段 |
|---|---|---|
| **tag 是否相同**（事实） | `auditTag === rosterTag` ? | 应新增 `tagDiffers: bool` |
| **置信度是否够**（引擎把握） | high / medium / low | `confidence` |
| **判定**（结论） | match / mismatch / unknown | `verdict` |

`unknown` = "tag 可能不同、但引擎不敢拍板"，它**属于教师需要看的那一批**。

### 2.2 修复

1. 引擎输出新增 **`tagDiffers`**（`auditTag` 与 `rosterTag` 都非空且归一后不等 → true）；
2. 「只看不一致」改按 **`tagDiffers`** 过滤（而不是 `verdict`）；
3. 界面文案改为：「只看 tag 不同的」；
4. 列头显示计数：`不一致 3 · 待确认 2 · 一致 36 · 未转写 1`（**全部可点，点即过滤**）。

### 2.3 「应用勾选的审计 tag」为什么"不能操作"

```js
function auditSelectable(s) {
  return !!a && a.verdict === 'mismatch' && a.confidence === 'high'
}
```

只有 `mismatch && high` 才出现复选框；而教师看到的多数是 `unknown`（medium/low）
→ **一个复选框都不出现** → 按钮点了提示「没有勾选可应用的行」。

按 D173 的设计，**这个按钮与勾选框都会被"整合式详情页"取代**（见 §3）——
批量操作保留，但入口更清楚。

---

## 3. 设计：把「AI 审计结果 + 人工确认」整合到一个**详情页**

### 3.1 交互模型

```
逐生审核表（列表层）
  学生 | roster tag | 🛡 审计 tag | AI 状态 | AI 分 | …
  ↑ 点击「🛡 审计 tag」单元格 → 打开该生的【tag 判定详情】
  ↑ 每行左侧复选框 = 批量选择（**任何行都可勾**，不再限于 high）
        └─ 列头「批量改 tag…」→ 弹窗：把选中学生设为 <下拉选 tag>
```

### 3.2 详情页（核心，替代现在的简陋弹窗）

```
┌─ 张三 —— tag 判定详情 ──────────────────────────────── ✕ ┐
│                                                          │
│  【结论】                                                │
│   roster tag：基础        🛡 审计 tag：提高（high）        │
│   判定：**tag 不同**（不是错误，是让学生核对）             │
│   一句话：3 道题全部对上「提高」层作业纸（得分 0.91）      │
│                                                          │
│  【怎么判的】（让教师能自己判断结论可不可信）              │
│   · 方法：字符 2/3-gram Dice + 数值常量重合（权重 0.65/0.35）│
│   · 只看题干（printed_question），不看作答                 │
│   · 逐题与每张作业纸的**每一题**做最优配对，取平均         │
│   · S = 0.65×字面 + 0.35×数值；高置信需 S≥0.75 且领先≥0.15 │
│                                                          │
│  【逐题对照】（**一题一行**，不再混在一起）                │
│  ┌ 题1 ─────────────────────────────────────────────┐   │
│  │ 学生转写的题干：空气由压强为 2.03×10^3 Pa…（可展开全文）│
│  │ 基础层 题1：空气由压强为 1.52×10^3 Pa…   相似度 62%  │
│  │ 提高层 题1：空气由压强为 2.03×10^3 Pa…   相似度 98% ✓│
│  │ 拓展层 题1：空气由压强为 3.04×10^3 Pa…   相似度 55%  │
│  └──────────────────────────────────────────────────┘   │
│  ┌ 题2 ─────────────────────────────────────────────┐   │
│  │ …（同上）                                        │   │
│  └──────────────────────────────────────────────────┘   │
│                                                          │
│  【本层判定】（按学生 roster tag 对应的那张作业纸）       │
│   基础层合计 0.62 · 提高层合计 0.98 · 拓展层合计 0.55     │
│   → 判定「提高」                                          │
│                                                          │
│  【人工确认】                                            │
│   当前 roster tag：基础                                  │
│   改 tag 为：[基础 ▾]  （下拉：本包内所有 tag）           │
│   备注（可选）：[___________________________]            │
│   [保存并应用（会记录历史）]  [取消]                      │
│                                                          │
│  【历史】（该生的所有 tag 变更记录）                      │
│   2026-11-06 14:02  基础 → 提高  来源：审计  可撤销       │
│   2026-11-05 09:31  提高 → 基础  来源：手动               │
└──────────────────────────────────────────────────────────┘
```

### 3.3 需要引擎补的字段（否则前端算不出来）

现状 `pairs` 只有 `{block, no, paperNo, score}` —— **不够**。要补：

```jsonc
"pairs": [
  {
    "block": 1, "no": "1",                 // 学生转写里的题号
    "studentStem": "空气由压强为 2.03×10^3 Pa…",   // ← 学生题干（截断 400 字）
    "best": {"padId": "pd-mid", "tag": "提高", "paperNo": "1", "score": 0.98},
    "perPaper": [                          // **每张作业纸**这一题的最好匹配
      {"padId": "pd-base", "tag": "基础", "paperNo": "1", "score": 0.62,
       "paperStem": "空气由压强为 1.52×10^3 Pa…"},
      {"padId": "pd-mid",  "tag": "提高", "paperNo": "1", "score": 0.98,
       "paperStem": "空气由压强为 2.03×10^3 Pa…"},
      {"padId": "pd-top",  "tag": "拓展", "paperNo": "1", "score": 0.55,
       "paperStem": "空气由压强为 3.04×10^3 Pa…"}
    ]
  }
],
"why": {                                   // 「判据」——给教师看的人话 + 机器值
  "method": "ngram-v1",
  "bigramWeight": 0.65, "numberWeight": 0.35,
  "minScore": 0.75, "marginMin": 0.15,
  "perPaperTotals": [
    {"padId": "pd-base", "tag": "基础", "score": 0.62, "coverage": 1.0},
    {"padId": "pd-mid",  "tag": "提高", "score": 0.98, "coverage": 1.0},
    {"padId": "pd-top",  "tag": "拓展", "score": 0.55, "coverage": 1.0}
  ]
},
"tagDiffers": true                          // §2.2：与 verdict 解耦的「事实」
```

**逐题判据也要给**：每题除了 `score`，补 **`why` 细分**：

```jsonc
"detail": {"literal": 0.97, "number": 1.0, "numbersStudent": ["2.03", "4.2", "1.35"],
           "numbersPaper": ["2.03", "4.2", "1.35"], "numbersShared": ["2.03","4.2","1.35"]}
```

教师就能看懂「这题为什么判 98%」：字面几乎一样 + 数字全对上。

---

## 4. 手动改 tag（教师明确要求）

### 4.1 能力

| 入口 | 场景 |
|---|---|
| 详情页「改 tag 为…」 | **主路径**：单人精调（看图、看逐题对照后决定） |
| 列表勾选 + 「批量改 tag…」 | 批量（如整班几人同样判错） |
| 下拉可选：**本包内所有 tag** | `packPads` 的 `target_tag` 去重 |
| 也可选 **（不清空）** | 允许清空 tag（显式操作，二次确认） |

### 4.2 全部走引擎、全部留历史

- 走 `apply_audit_tags()`（D172 已有），`reason` 扩展：`manual-detail` / `manual-batch`；
- **每个学生**的 `previousTag` 已有；D173 再加 **`tagHistory[]`**（在快照里按人累积）：

```jsonc
{"name": "张三", "tag": "提高", "previousTag": "基础",
 "tagHistory": [
   {"at": "2026-11-06 14:02", "from": "基础", "to": "提高",
    "by": "teacher", "reason": "audit-apply", "note": ""}
 ]}
```

- 撤销：仍用 `_history/` 副本（整包级）；D173 允许**按学生记录撤销**
  —— 从 `tagHistory` 取上一条 `from` 回写（同样记一条新历史，不删除旧记录）。

### 4.3 与「批阅」的关系

改 tag **不自动重批**；详情页保存后给提示「已改 tag，建议重新「转写+批阅」」+ 一个按钮。

---

## 5. 界面改动的具体清单

| # | 改动 |
|---|---|
| U1 | 列头统计：`一致 N · tag不同 N · 待确认 N · 未转写 N`，**每项可点做过滤**（替代单一「只看不一致」） |
| U2 | 「只看不一致」→ 改名为「只看 tag 不同的」，并按 **`tagDiffers`** 过滤（修 §2） |
| U3 | 每行**始终有复选框**（不再限 high），勾选后列头出现「批量改 tag…」 |
| U4 | 审计单元格：`↑提高`（tag 不同）/ `✓基础`（一致）/ `?`（无法判定）三种，短、可扫读 |
| U5 | 详情页按 §3.2 重做（逐题对照 + 判据 + 人工确认 + 历史） |
| U6 | 详情页支持 **上一位/下一位** 浏览（教师逐个核对时不用关窗再点） |

---

## 6. 需求分解

| 批次 | 项 | 交付 |
|---|---|---|
| A | `T1` 引擎：`pairs[].perPaper/studentStem`、`why`、`detail`、`tagDiffers` | `tag_audit.py` |
| A | `T2` 引擎：`tagHistory[]` + 按学生撤销 | `tag_audit.py` |
| A | `T3` 单测：`tagDiffers` 与 verdict 解耦、逐题对照字段完整、历史累积与单人撤销 | pytest |
| B | `T4` 前端：列头统计 + 过滤（U1/U2） | `AiGradingPanel.vue` |
| B | `T5` 前端：行复选框 + 批量改 tag（U3） | 同上 |
| B | `T6` 前端：详情页重做（U5/U6） | 同上 |
| B | `T7` selfcheck：断言 `tagDiffers` 过滤、复选框常态、详情含逐题/判据/历史 | selfcheck |
| C | `T8` 文档 + 版本 0.6.1 | docs |

---

## 7. 验收标准

1. 存在 `tagDiffers=true` 但 `verdict=unknown` 的学生时，勾「只看 tag 不同的」**必须显示**；
2. 任何行都能勾选；批量改 tag 后每个学生都有 `tagHistory` 记录；
3. 详情页能回答教师四问：**转写题干？**（有）、**roster 层题干？**（有）、**为什么这么判？**（方法+权重+逐题分值+数字重合）、**逐题分别判**（一题一行）；
4. 单人撤销：`tagHistory` 追加一条 `to=原 from` 的新记录，旧记录保留（**不删历史**）；
5. 旧格式转写（无 `items[]`）在详情页明确标「旧格式，建议重新转写」；
6. 四道门：pytest / build / selfcheck / 脱敏。


---

## 8. 实施记录（2026-11-06）

### 8.1 教师三个疑问的答案

| 疑问 | 答案 |
|---|---|
| 「应用勾选的审计 tag」是什么意思？能批量吗？ | 原意是"把勾选学生各自改成他自己的审计 tag"。**但原来只有 `mismatch && high` 才出复选框** → 教师一个框都看不到，所以"好像不能操作"。D173 改为**每行都有复选框**，并拆成两个动作：**采纳审计 tag**（各自改成审计结论）/ **批量改 tag**（统一改成你指定的 tag） |
| 「只看不一致」勾上后没显示 | **D172 的 bug**：过滤按 `verdict === 'mismatch'`，而置信不足时 `verdict = 'unknown'`（引擎不敢拍板但 tag 确实不同）→ 全被滤掉。D173 新增 **`tagDiffers`**（事实字段），过滤改按它 |
| 转写能分离题干吗？ | **能**。`items[].printed_question` / `items[].answer` 是独立字段（提示词强制要求分开，schema 里两者都 required）。审计**只读** `printed_question`，不读 `answer` |

### 8.2 交付清单

| 项 | 说明 |
|---|---|
| `T1` 逐题对照 + 判据 | `pairs[]` 每题一行：`studentStem` + `perPaper[]{tag,paperStem,score,detail}`；`why{method,weights,perPaperTotals}`；`tagDiffers`；`legacyFormat` |
| `T2` 每人 tag 历史 + 单人撤销 | 快照每行 `tagHistory[]`（at/from/to/by/reason/note）；`undo_student_tag()` **追加**记录不删历史 |
| `T3` 单测 +11 项 | 见 §8.4 |
| `T4` 过滤 | 列头 5 个 chip：全部 / ⚠tag 不同 / ?待确认 / ✓一致 / 未转写，**点即过滤** |
| `T5` 批量 | 常驻复选框 → 「批量改 tag 为 [下拉] 应用」+「采纳审计 tag」 |
| `T6` 详情页重做 | 结论 / 判据 / **逐题对照（一题一行）** / 人工确认 / **变更历史** + 上一位下一位 |
| `T7` selfcheck | 断言过滤按 `tagDiffers`、复选框常驻、详情含四要素 |
| `T8` 文档 + 版本 | 0.6.1 |

### 8.3 详情页现在能回答教师的四个问题

1. **转写的题干？** → 每题「转写的题干」行（`studentStem`，截断 400 字）
2. **roster 对应 tag 的题干？** → 每题表格里**每张作业纸**的题干（`paperStem`）都在
3. **判据？** → 「怎么判的」折叠区：方法名、两个权重、阈值、每张纸合计得分；
   每对还给 `字面 xx% · 数值 xx%` 拆解（悬停看共同数值）
4. **按题目分别判？** → **一题一个卡片**，不再混在一起

### 8.4 新增测试（11 项）

| 测试 | 防的是什么 |
|---|---|
| `test_tag_differs_is_independent_of_verdict` | **教师实测 bug 的直接回归**：verdict=unknown 但 tag 确实不同 |
| `test_tag_differs_false_when_same_or_missing` | 无 roster tag 时不能算「不同」 |
| `test_audit_summary_counts_tag_differs` | 汇总计数 |
| `test_pairs_are_per_question_with_both_stems` | 逐题对照含两侧题干 |
| `test_pair_detail_explains_score` | 分值是字面/数值可解释的 |
| `test_why_block_exposes_method_and_weights` | 判据字段完整 |
| `test_explicitly_only_printed_question_used` | **只判题干**：改 answer 不影响结论 |
| `test_old_format_transcript_is_flagged` | 旧格式标 `legacyFormat` |
| `test_apply_accumulates_per_student_tag_history` | 两次修改都留记录（含 note） |
| `test_undo_student_tag_restores_previous_and_keeps_history` | 撤销是**追加**记录，不删历史 |
| `test_undo_student_without_history_errors` | 无记录时给可读错误 |

### 8.5 端到端实测（真实题库 + 真实 taskpad）

```
summary: {match: 0, mismatch: 1, unknown: 0, tagDiffers: 1}
第1题 perPaper: 提高 96% / 基础 60%
学生题干: 空气由压強为 2.03×10^3 Pa…（OCR 把"强"识别成"強"，仍判对）
每卷合计: 提高 99% / 基础 59%
apply → 张三 基础→提高（reason=manual-detail, note=看题干确认）
undo-student → 提高→基础（追加记录）
```

### 8.6 顺带修的一个可用性问题

`loadAudit()` 原本要求 `packId || padId`；刷新页面后这两个为空（学生清单靠
`resolvedScope` 反查仍能显示），导致**列表有学生但审计列全空**。
现改为同样回退到 `resolvedScope`。

### 8.7 门禁

pytest **1569**（+11）· build 0 error · selfcheck **40/40** · 脱敏/bat 通过

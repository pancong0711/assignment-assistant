# D216 需求单：批阅前置「程序对齐」落地（替代大模型题目比对）

> 日期：2026-11-20
> 状态：**已完成（2026-11-20）**
> 关联：`docs/158-D215-align-before-grade-design.md`（设计）、
> `docs/156-D213`（kind 解析）、`docs/117-D172`（tag 审计匹配器）
>
> 隐私：测试只用合成数据。

---

## 0. 已定口径（教师 2026-11-20 拍板）

| # | 决定 |
|---|---|
| 1 | mismatch：**仅警告、仍出分**（不阻断、不扣分） |
| 2 | unknown：**完全沿用现有判定**（不新增档位、不调阈值） |
| 3 | 不做「一键改用建议作业纸重批」按钮；复用现有逐生/全部改 tag 入口 |

补充采纳的 4 项建议：

- 逐生审核表加「题目匹配」列 + 草稿层补 `align`
- 阈值并入 `grading-rules.json → tagAudit`
- 对齐在**转写之后、批阅之前**计算（转录存在的最早时点），并缓存到 plan
- match 时删除提示词里的比对块；mismatch / unknown 保留

> 说明：原设计写“build_plan 时计算”，但 build_plan 发生在转写之前（没有转写可对齐）。
> 实际落在 **`_run_evaluate` 的每生前置**，结果写回 plan/evaluation/drafts 供复用。

---

## 1. 需求

### R1. 对齐引擎（纯 Python，0 token）

`grading/align.py`：

- 复用 `tag_audit` 的匹配器（`_items_of` / `score_pair` / `best_assignment` / `_cfg`）；
- 逐生、逐作业纸计算：
  - `coverage`：转写题块中能匹配上该卷的比例；
  - `margin`：最佳卷与次佳卷的覆盖差；
- 输出 `verdict ∈ match | mismatch | unknown`；
- 输出 `questionMap[]`（转写题号 → 作业纸题号 / kb / 相似度）；
- **不写任何权威数据**（只读，不改 tag/快照）。

### R2. 阈值并入 tagAudit

`grading-rules.json → tagAudit` 新增（可调）：

```json
{"coverageMin": 0.6, "worksheetMarginMin": 0.15, "matchScore": 0.45}
```

- `matchScore`：单题算“匹配上”的最低相似度（默认沿用 `mediumScore`）；
- unknown 判定沿用现有 `minScore/marginMin/mediumScore`，不新增档位。

### R3. 接入选题与提示词

- `_run_evaluate()` 每生：读转写 → `align_student()` → 结果传 `evaluate_student()`；
- `build_grade_prompt(items, ..., align=...)`：
  - `match` → 用一句“【题目已由程序核对】…（覆盖率 X）”替换原 286 字符比对块；
  - `mismatch` / `unknown` → 保留比对块（供模型给出证据）；
- 算分：用 `align.questionMap[].kb` 给每题补**真实题库**（`kindSource=align`）。

### R4. 可见性贯通（修掉“看不到提示”）

| 层 | 变更 |
|---|---|
| `plan.json` | `papers[]`（展开后的题目+kb）、`students[].align` |
| `evaluations/<学生>.json` | `align` + 兼容 `question_match`/`verdict` |
| 草稿 `drafts/<classId>.json` | `ai.align`、`ai.question_match`、`ai.per_question_rules` |
| 草稿版报告 `_mode_report_md` | 对齐结论 + 评分依据（含 fallback 警告） |
| 逐生审核表 | 新增「题目匹配」列：匹配 / 疑似错卷 / 未确定 / 未对齐（旧数据） |

### R5. 旧数据兼容

- 无 `align` 字段 → 显示「未对齐（旧数据）」，不报错；
- `question_match` 继续写入（由程序生成），旧报告/全局统计不改。

---

## 2. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 转写与当前 tag 作业纸一致 | `match`；提示词不含 286 字符比对块 |
| 2 | 转写更像另一张作业纸 | `mismatch`；**仍出分**；结果含建议 tag/padId |
| 3 | 题干太少/匹配不上 | `unknown`；行为与现状一致 |
| 4 | match 时 token | 每生减少约 250 字符 |
| 5 | 对齐给出的 per-question kb | 算分 `kindSource=align`，innovation 题不被按 problems 扣 |
| 6 | 草稿版报告 | 显示对齐结论与评分依据 |
| 7 | 逐生审核表 | 新增「题目匹配」列 |
| 8 | 旧 plan/旧评阅 | 显示「未对齐（旧数据）」，不报错 |
| 9 | 回归 | 全量 pytest 通过；selfcheck 通过 |

---

## 3. 范围

允许：`grading/align.py`（新增）、`grading/tag_audit.py`、`grading/rules.py`、
`grading/inputs.py`、`grading/flow.py`、`grading/evaluate.py`、`grading/prompts.py`、
`grading/drafts.py`、`grading/report.py`、`app/src/components/AiGradingPanel.vue`、
对应 tests、本文档与 README 索引。

不得：改评分数值口径、改 tag 权威数据、增加新按钮/弹窗。


---

## 4. 实施结果

### 4.1 新增 `grading/align.py`

| 能力 | 说明 |
|---|---|
| `align_student()` | 逐题对齐 → `match / mismatch / unknown` + `coverage/margin` + `questionMap`（含每题 kb） |
| `align_all()` / `summarize()` | 批量与汇总 |
| 匹配器 | **复用** `tag_audit`（`_items_of` / `best_assignment` / `score_pair`），不新造算法 |
| 只读 | 只产出证据，不改 tag/快照 |

判定与行为（按教师拍板）：

| verdict | 行为 |
|---|---|
| `match` | 正常批阅；提示词用短句替换 286 字符比对块 |
| `mismatch` | **仅警告、仍出分**；`padId` 仍是当前 tag 的卷；给建议 tag |
| `unknown` | 沿用现有审计口径；按当前 tag 批阅 + 提示复核 |

### 4.2 阈值（并入 tagAudit，可调）

```json
{"coverageMin": 0.6, "worksheetMarginMin": 0.15, "matchScore": 0.45, "alignMinChars": 6}
```

已加入 `_NUM_RANGES` 与 `tagAudit` 字段白名单，规则卡改值可写盘生效。

### 4.3 流程接入

- `build_plan()` 现在输出 `papers[]`（`papers_from_taskpads` 展开题干 + **每题 kb**），
  并在 `pads_by_tag` 里保留原始 pad；
- `_run_evaluate()` 每生：读转写 → `align_student(..., ws=)` → 传入 `evaluate_student`；
- `evaluate_student()`：
  - 用 `questionMap[].kb` 给每题补真实题库（`_kindSource=align` → `kindSource=align`）；
  - 结果写 `align`，并生成兼容的 `question_match`（`source=align-python`）；
  - `align=mismatch` 时 `verdict=suspected-substitution`（**不扣分、不阻断**）。

### 4.4 可见性

| 层 | 结果 |
|---|---|
| `plan.json` | `papers[]` + 每生 `align`（评阅时写入 ctx；评估 JSON 为准） |
| `evaluations/<学生>.json` | `align` + `question_match`（程序来源） |
| 草稿 `ai` | 新增 `align / question_match / verdict / per_question_rules / kind_fallback_questions` |
| 草稿版报告 | 渲染「题目差异」中性提示 + 「评分依据（按题目来源）」+ fallback 警告 |
| 逐生审核表 | 新增「🧭 题目匹配」列（匹配/疑似错卷/未确定/未对齐）+ 顶部汇总 |

> 这修掉了 D215 指出的“提示生成了但 PWA 看不到”的缺口。

### 4.5 测试

`engine/tests/test_d216_align_before_grade.py`（20 项）：

- 三态判定、只读性、逐题 kb；
- 阈值可调 + 非法值回落；
- `match` 提示词替换且**不丢题目/答案**；`mismatch` 保留比对块 + 对齐提示；
- 算分 `kindSource=align`；
- 端到端（假 LLM）：match 缩短提示词、mismatch 仍出分、align 的 kb 生效；
- 草稿层与草稿版报告渲染、plan 带 papers。

全量 pytest：`1968 passed`；`selfcheck:d216` 通过；前端 build 通过。

## 5. 已知边界

- 对齐复用审计匹配器：**手写转写噪声**可能让 coverage 偏低 → 落到 `unknown`（沿用现状，不阻断）；
- `build_plan` 发生在转写之前，所以 `papers` 在 plan 里、`align` 在评阅时计算并写入 evaluation；
- 同一 tag 绑多张作业纸不在本期范围（见 D215 §12.6）。

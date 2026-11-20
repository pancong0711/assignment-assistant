# D213：innovation 题评阅过严——题库(kind)解析在提示词与算分之间不一致

> 日期：2026-11-20
> 状态：**已完成（2026-11-20）**
> 关联：`docs/78`（三层规则）、`docs/120-D177`（唯一提示词入口）、`docs/130`（按来源分型）
>
> 隐私：测试只用合成数据。

---

## 0. 现场

tag=innovation 的学生，创新题被扣得很严（按“逻辑错误每处 −5”），
与评阅规则卡里 innovation 的口径（逻辑瑕疵不扣分、只按长度/相关性）不符。

教师判断正确，并提出关键点：

> tag 为 innovation 的学生，作业纸不一定只有 innovation 题库的题；
> 其他题库的题要按各自题库的规则评阅。

## 1. 先回答：评阅时到底发了什么

`build_grade_prompt()`（D177 唯一入口）确实把四样一起发给模型：

1. **题目**：题号 + `来源: <kb>` + `评阅范式: <kind>` + 题干；
2. **参考答案/解题要点**（`solution`，标注“仅用于核对，勿向学生透露”）；
3. **评阅要求**：按本次涉及的**每个 kind** 注入「评阅范式 + 规则摘要 + 输出要求」，
   规则摘要与规则卡同源（`rules.rule_summary`）；
4. **学生转写**（含题目与作答）。

另外还有：先判题目是否对应、知识点术语、summary 的课堂资料依据等。

所以“题目+答案+要求+转写”是齐的。

## 2. 根因：kind 的解析口径两处不一致

| 位置 | 原解析链 |
|---|---|
| 提示词 `normalize_prompt_items` | `kind > kb > tag > problems` |
| 算分 `score_from_analysis` | `kind > kb > q.kind > problems`（**没有 tag**） |

当 `plan.json` 是旧版（题目只存了 `no/content/solution`，没有 `kind/kb`）时：

- 提示词用 `tag=innovation` → 注入 innovation 规则 → 模型据此把逻辑问题写成
  `errors[].guidance`（启发式提问，本意是**不扣分**）；
- 算分因为缺 `tag` 回退 → 回落 `problems` → 把那些“启发式提问”当成错误，
  **每处 −5，单题封顶 −20**。

复现（两个逻辑错误）：

```
kind=innovation      → total=100（正确：不扣）
仅 tag=innovation    → total=90 （错误：按 problems −10）
kb=innovation        → total=100
无来源（回落）        → total=90 且 kindSource=fallback
```

## 3. 修复

### R1. 唯一解析函数 `rules.resolve_item_kind(item, q=None)`

```python
kind, source = resolve_item_kind(item, q)
# 优先级：item.kind > item.kb > item.tag > q.kind(模型自报) > problems
# source ∈ item.kind / item.kb / item.tag / model / fallback
```

- 提示词 `normalize_prompt_items` 与算分 `score_from_analysis` **都改用它**；
- 算分结果 `per_question_rules[]` 增加 `kindSource`，教师可核对“这题按哪套规则评的”。

### R2. 旧 plan 补 kind/kb

`flow._plan_items_for()`：plan 题目缺 `kind/kb/tag/related` 时，
用 `plan.questionsByTag[该生tag]` 里**同题号**的题目补齐。

这样混合作业纸（innovation 题 + problems 题）也能各按自己的题库评阅，
而不是整份按作业纸 tag 判。

### R3. 兜底可见

- 算分结果新增 `kind_fallback_questions`（回落到 problems 的题号）；
- 报告「本题来源 + 适用规则」处显示：

```
- ⚠ 第1题未识别题库来源，已按「计算/推导题(problems)」规则评阅；
  如该题属于 innovation/translation 等题库，请在作业纸里补上题目来源后重批
```

避免“静默按最严规则扣分”。

## 4. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 题目只有 `tag=innovation`（旧 plan） | 按 innovation 评，逻辑错误不扣分 |
| 2 | 题目有 `kb=innovation` | 同上 |
| 3 | 混合作业纸：innovation + problems | 各按自己题库规则；per_question_rules 分别标注 |
| 4 | 完全无来源 | 回落 problems，但 `kindSource=fallback` 且报告有警告 |
| 5 | 提示词 | 同时含 innovation 与 problems 规则块，逐题标注来源/范式 |
| 6 | 旧 plan | 从 `questionsByTag` 补 kind/kb |
| 7 | 回归 | 全量 pytest 1948 passed |

## 5. 范围

允许：`engine/src/assist/grading/rules.py`、`prompts.py`、`evaluate.py`、`flow.py`、
`report.py`、对应 tests、本文档与 README 索引。
不得改评分数值口径与规则卡默认值。

## 6. 实施结果

- 新增 `resolve_item_kind()`，提示词/算分统一口径；
- 算分记录 `kindSource` 与 `kind_fallback_questions`；
- `_plan_items_for` 用 `questionsByTag` 补 `kind/kb/tag/related`；
- 报告对 fallback 题显示警告；
- 测试：`engine/tests/test_d213_kind_resolution_consistency.py`（13 项）。

## 7. 给教师的排查建议

若仍觉得某题“按错规则”：

1. 打开该生的 `evaluations/<学生>.json`，看 `per_question_rules[]`：
   - `kind` 是否为期望题库；
   - `kindSource` 是 `item.kb` 还是 `fallback`；
2. 若 `kindSource=fallback` → 作业纸里该题没有记录题库来源，请在作业纸中补上；
3. 若 `kind` 正确但仍扣分 → 看 `rules` 与 `detail`（例如长度不足、无关），
   那不是“逻辑扣分”。

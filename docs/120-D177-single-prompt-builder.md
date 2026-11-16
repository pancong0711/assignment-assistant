# D177 需求单：评阅提示词合并为**唯一实现**

> 日期：2026-11-16
> 状态：**已完成**
> 关联：`docs/119-D176`（题目类型贯通）、`docs/117-D174`（translation 放宽）

## 0. 背景

D176 排查时发现：评阅提示词有**两份**独立实现，各自演进：

| 构建器 | 调用方 | 特点 |
|---|---|---|
| `evaluate.build_user_prompt` | **生产主路径**（`evaluate_student`） | 逐题标注「评阅范式」、注入 kind 指令、知识点词表、summary 资料依据、严谨性要求 |
| `prompts.build_evaluate_prompt` | 批量接口（`llm_batch`） | 作业纸 tag 指令 + `format_questions`，**没有**逐题评阅范式、没有严谨性要求 |

后果：题型标注、先判题目、严谨性要求等口径会**各自漂移**——
D176 的「kind 丢失导致翻译题被当计算题」就部分源于这种双份实现。

教师确认：合并。

---

## 1. 设计：一个入口 + 两个兼容包装

```
prompts.build_grade_prompt(items, markdown_text, *, student, ws, tag)   ← 唯一实现
        ▲                                   ▲
        │                                   │
evaluate.build_user_prompt(...)      prompts.build_evaluate_prompt(...)
   （生产主路径，签名不变）              （批量接口，签名不变）
```

### 1.1 唯一实现的组成（顺序固定，利于 prompt caching）
1. `学生：<姓名>`（可选）
2. 作业纸级提示（可选，`tag` 有对应指令时才加；**明确声明"与题目级冲突时以题目级为准"**）
3. 每个涉及 `kind` 的「评阅范式 + 规则摘要 + 输出要求」
4. 题库知识点 / 受控词表（`ws` 可用时）
5. summary 题的课堂资料依据 / 保底口径（`ws` 可用时）
6. 【第一步：先判断题目是否对应】
7. 【作业纸题目】逐题：`第N题（来源: …；评阅范式: …；标签: …）` + 题干 + 参考答案 + 关联知识点
8. 严谨性要求（`EVIDENCE_INSTRUCTION`）
9. 【学生转写（含题目与作答）】

### 1.2 字段兼容
新增 `normalize_prompt_items()`：统一 `序号`/`no`/`index` 三种题号字段，
题型一律取 **题目级 `kind` > `kb` > `tag` > problems**。
`kinds_of_items()` 成为唯一的 kind 去重口径，`evaluate._kinds_of` 也委托给它。

---

## 2. 验收

| # | 标准 | 验证 |
|---|---|---|
| 1 | 两个入口都**委托**而非各自实现 | `test_evaluate_build_user_prompt_delegates` / `test_prompts_build_evaluate_prompt_delegates` |
| 2 | `_kinds_of` 只有一份口径 | `test_kinds_of_is_single_source` |
| 3 | 同输入 → 两条路径产出**逐字相同**的提示词（仅"学生："行不同） | `test_two_entry_points_produce_identical_prompt` |
| 4 | 关键块不丢（逐题评阅范式/参考答案/先判题目/严谨性要求/转写） | `test_unified_prompt_contains_all_critical_blocks` |
| 5 | 无题目时明确提示，不让模型猜 | `test_missing_questions_yields_explicit_notice` |
| 6 | 作业纸 tag 提示从属于题目级 | `test_worksheet_tag_hint_is_subordinate_to_question_kind` |
| 7 | 题号字段双风格兼容 | `test_normalize_prompt_items_accepts_both_field_styles` |
| 8 | 四道门 | pytest **1611** · selfcheck **44/44** |

---

## 3. 行为变化（有意为之）

- `llm_batch` 路径现在也会带「严谨性要求」与逐题「评阅范式」→ 与生产一致；
- 作业纸 `tag` 的指令不再"一家独大"，而是明确从属于题目级 kind；
- 生产主路径行为**不变**（`evaluate.build_user_prompt` 不传 tag，输出与合并前一致，
  既有 1603 条测试全绿）。

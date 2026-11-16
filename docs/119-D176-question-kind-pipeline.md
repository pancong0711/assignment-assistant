# D176 需求单：题目类型（kind）贯通 + translation 不要求示意图

> 日期：2026-11-16
> 状态：**已完成**
> 关联：`docs/117-D174`（translation 放宽）、`docs/116-D171`（批阅三键）

## 0. 教师提问

> 1. translation 题目通常不需要画示意图，检查一下提示词。
> 2. 确认一下，我们现在的批阅是**按题目类型**的是吧？就是把对应类型题目的题干和答案
>    跟随批阅提示词以及学生作答转写内容一起发给大模型，是不是？
>    （这里有一个**作业纸类型**和**题目类型**，两者有可能出现混淆，
>    某一类型作业纸里面可能包含不同类型的题目）

---

## 1. 结论一：示意图 —— 已修正

### 1.1 原来的问题
`ANALYSIS_PROMPT` 里有一段**无条件的**【示意图】指令：

> `has_diagram` 判断学生是否画了图；若画了，还需在 `errors` 中指出
> 方向/坐标轴/标注与结论不符之处（这类问题往往比算错更关键）。

它对**所有题型**生效，包括翻译题；且 `has_diagram` 是 schema 的 required 字段，
模型对翻译题也会去"找图/报缺图"。报告里还有一条无条件提示
`if not has_diagram: 提示：缺少示意图`。

### 1.2 修复
- `ANALYSIS_PROMPT` 改为**【示意图（只在题目要求画图时才判定）】**，明确：
  - 只有计算/推导、问答、总结题可能要求；
  - **翻译题、抄写题、辨析题、创新题通常不要求画图**；
  - 题目没要求 → `has_diagram` 一律 `true`（不适用），**不要**报"缺图"；
- `kind_output_hint("translation")` / `("copy")` 增加：
  `has_diagram: 一律填 true，不要因为学生没画图而报错或扣分`；
- 报告生成里的"缺少示意图"提示**只在 qa/summary/problems** 出现
  （翻译题即使模型判成 false 也不提示）。

> 算分侧本来就不扣：`rules.py` 中 translation/copy 的 `requireDiagram=False`。
> 本次修的是**提示词误导**与**报告文案**。

---

## 2. 结论二：批阅确实是"按题目类型"，但**之前链路上断了一环**（已修复）

### 2.1 设计口径（确认无误）
- **题目类型 = `kind`**（来自题库表名：problems/qa/copy/translation/summary/...）；
- **作业纸类型 = `tag` / `target_tag`**（只决定"这张作业纸给哪批学生、用哪套题"）；
- 二者**不是一回事**：一张 `tag=qa` 的作业纸里完全可以夹一道 `kind=translation` 的题。

批阅请求的组成（已确认）：
```
[题型指令 × 涉及的每种 kind]
+ [规则摘要（该 kind 怎么扣分）]
+ [每题：题号 + 评阅范式(kind) + 题干 + 参考答案/评分点 + 关联知识点]
+ [严谨性要求]
+ [学生转写（题目 + 作答）]
→ 一次发给大模型 → 只做"发现"，算分由 Python 按每题 kind 完成
```

### 2.2 发现的断点（真实缺陷）
`flow._plan_items_for()` —— **PWA 主路径**上把 plan 的题目转成评阅 items 时：

```python
# 修复前：只传了 4 个字段
{"序号": …, "content": …, "solution": …, "tag": stu.get("tag")}
```

**丢掉了每题的 `kind` / `kb` / `related`**。后果：

| # | 影响 | 实测 |
|---|---|---|
| A | `_kinds_of()` 只能拿**作业纸 tag** 兜底 → 混题型作业纸里所有题都注入"问答题"指令 | `【翻译题输出要求】` 未出现 |
| B | 算分 `kind = it.kind or it.kb or q.kind or "problems"`；模型未自报 kind（schema 不强制）时**一律按 problems** | 翻译题被按「每错 −5」扣到 **−20**（应 −5） |

> 这正是教师担心的"作业纸类型/题目类型混淆"——**已经真实发生在生产路径上**。

### 2.3 修复
1. `_plan_items_for()` 透传 `kind` / `kb` / `related`（`tag` 保留，但仅用于"先判题目是否对应"）；
2. `_kinds_of()` 注释与优先级明确：**题目级 kind 优先**，`tag` 只作最后兜底；
3. `format_questions()`（另一条 prompt 构建路径）为每题标注`【题型：…】`
   并声明"每题的题型以该题标注为准，同一份作业可能混多种题型"。

### 2.4 修复后实测（真实 `run_task` + 混合题型作业纸）
```
第1题（来源: problems；评阅范式: problems；标签: qa）：求加速度
参考答案/解题要点：a=F/m

第2题（来源: translation；评阅范式: translation；标签: qa）：把英文译成中文
参考答案/解题要点：参考译文

每题规则: [('1','problems',['errorCount']), ('2','translation',['translation'])]
总分: 95   ← 翻译题只扣 5，不再被当成计算题扣 20
```

---

## 3. 验收

| # | 标准 | 验证 |
|---|---|---|
| 1 | plan → items 保留每题 kind/kb/related | `test_plan_items_keep_per_question_kind` |
| 2 | 作业纸 tag=qa 但题目 kind=translation → 以题目为准 | `test_plan_items_keep_kind_even_when_tag_differs` |
| 3 | 混题型作业纸注入所有涉及题型的指令 | `test_prompt_injects_each_kind_instruction_for_mixed_sheet` |
| 4 | 每题在提示词中标注评阅范式（生产路径） | `test_prompt_labels_kind_on_each_question_block` |
| 5 | 模型**不报** kind 时翻译题仍按 translation 计分 | `test_translation_scored_by_translation_rule_without_model_kind` |
| 6 | 翻译/抄写题提示词明确"不要求画图、has_diagram=true" | `test_translation_hint_says_no_diagram_needed` 等 |
| 7 | 翻译题报告不再提示"缺少示意图" | `test_report_does_not_tell_translation_student_to_draw_diagram` |
| 8 | 四道门 | pytest **1603** · selfcheck **44/44** |

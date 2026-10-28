# D116 缺陷修复：AI 辅助批阅的 tags 下拉恒为空

> 日期：2026-10-28
> 状态：已实现并验证
> 关联：`docs/05-D86`（批阅草稿/两段式）、`docs/13`（D92-R4 tags 多选）、`engine/src/assist/grading/inputs.py`

## 1. 现象

用户在「AI 辅助批阅」里选好了已下载的作业纸与作业包、其它开关都没勾，
但 **tags 下拉里没有任何可选项**。

## 2. 根因

`AiGradingPanel.vue`（D92-R4）的 tag 选项来源：

```ts
const tagOptions = computed(() => {
  for (const s of students.value) {   // students ← 学习通批阅列表
    const t = (s.tag || '').trim() ...
```

而 `students` 来自 `GET /xxt/preview/students/<classId>/<workId>`，
引擎侧由 `xxt/preview.py: parse_review_list()` 解析学习通**批阅列表页 HTML**。
实测其返回字段为：

```json
{"studentId":"12345","name":"张三","score":"85","status":"已批阅","graded":true,"review_path":""}
```

**没有 `tag` 字段**；`xxt/preview.py` 与 `xxt/review.py` 全文都**没有 tag 概念**。

分层标签是本机维护的信息，有两个真实来源，都不在学习通链路上：

| 语义 | 真实来源 |
|---|---|
| 学生属于哪一层 | 浏览器 `roster` store（`<ws>/roster.xlsx` 的 `tag` 列） |
| 作业纸对应哪一层 | 作业纸的 `target_tag` |

因此 `students[].tag` 恒为空 → `tagOptions` 恒为 `[]` → 下拉必然为空。

> 附带发现：后端 `grading/inputs.students_with_tags()` 读的是 **roster.xlsx**，
> 前端却去学习通列表里找 tag —— **两侧数据源不一致**，前端这个下拉从设计上就拿不到数据。

## 3. 「不勾选 tag」到底会发生什么（用户提问）

`grading/inputs.build_task_list()`：

```python
want = {t for t in (tags or []) if t.strip()}
for s in roster:
    tag = s.get("tag") or ""
    if want and tag not in want:      # want 为空 → 不过滤
        continue
    questions = tag_pads.get(tag).questions     # 按学生 tag 找对应作业纸的题
```

| 情况 | 结果 |
|---|---|
| **不选 tag**（`want` 为空） | **批阅全部学生**（不按 tag 过滤） |
| 学生**有** tag 且该 tag 绑定了作业纸 | 正常关联题目并批阅 |
| 学生**没有** tag | `questions = []` → **批不上题**（下游 `llm_batch` 用 `stu.questions or []`，prompt 里没有题目） |
| 批阅下载里有、roster 里没有的学生 | 补进来但 `tag=""`、`questions=[]`，同样批不上题 |

也就是说：**不选 tag ≠ 什么都不批**，而是"全部学生都走一遍，但只有打了 tag 的学生才真正有题可批"。
这层语义此前 UI 完全没提示，用户无法判断。

## 4. 修复（方案 A + C，用户拍板）

### A：tags 改从本机真实来源取

```ts
tagOptions = rosterTags ∪ padTags
```

- `rosterTags`：当前学习通作业映射到的**本地 roster 班级**里学生已打的 tag
  （`classMap[courseId:classId]` → classDir → 匹配 roster 班级；未映射时退回全部班级的 tag 用于展示）；
- `padTags`：当前**作业包内各作业纸的 `target_tag`**（未选包时取单张作业纸）。

与原 `loadStudents()` 里的"默认全选"配合改为 `watch(tagOptions)`：
首次就绪时**默认全选**，用户手动清空后不再覆盖；切换作业/作业包允许重置一次。

### C：空 tag 时给可操作提示

| 情况 | 提示 |
|---|---|
| 完全没有 tag 可选 | ⚠ 未找到任何分层 tag：请先到「班级与标签」给学生打 tag（或先在设置里关联学习通班级→本地班级目录）；不选 tag = 批阅全部学生，但未打 tag 的学生不会关联到题目 |
| 有 tag 但一个没选 | 未选 tag = **批阅全部学生**；但只有打了 tag 的学生才能关联到对应作业纸的题目 |
| 已选 | 将只批阅 tag ∈ `…` 的学生 |

另加「清空」按钮。

## 5. 执行中发现的额外缺陷

| # | 问题 | 说明 |
|---|---|---|
| N1 | **TDZ 崩溃**：`watch(tagOptions, …, { immediate: true })` 放在 `curWork` / `packPads` 定义之前 | `immediate` 会**立刻求值** computed → `Cannot access 'lt' before initialization`，整个「AI 辅助批阅」页白屏。已把 watch 移到所有相关 computed 之后，并加自检哨兵锁顺序 |
| N2 | 默认全选逻辑随 `loadStudents()` 触发 | 此时 roster 可能未就绪 → 全选落空。改为随 `tagOptions` 就绪触发 |

## 6. 验证

| 项 | 结果 |
|---|---|
| 真实界面（roster 有 tag + 作业纸有 target_tag） | 下拉 = `distinguish`、`copy`，**默认全选 2 项**，提示"将只批阅 tag ∈ distinguish、copy 的学生" |
| 真实界面（都没有 tag） | 下拉空 + **可操作提示**（指引去「班级与标签」打 tag，并说明不选=批全部） |
| 页面渲染 | 修复 TDZ 后「AI 辅助批阅」正常渲染（此前白屏） |
| engine pytest | 631 passed |
| app `vue-tsc -b` / `npm run build` | 0 error |
| app `npm run selfcheck` | 全绿（新增 `selfcheck-d116-grading-tags.mjs`，共 27 项） |
| 脱敏 | 通过 |

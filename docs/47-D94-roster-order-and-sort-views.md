# D94 任务需求单：点名册顺序为准（保序 merge）+ 标签预览/总览按加权成绩排序

> 日期：2026-10-16
> 状态：**已拍板**（讨论定调），按 §5 执行。
> 关联：`docs/46-D93`（整班预览顺序问题）、`docs/04`、
> 旧代码 `_legacy/2603paperDesign/src/paperdesign/student/student.py`（`pd.merge(namelist_df, score_df, how="left")`）。

## 1. 问题与根因（讨论定调）

**现象**：整班预览学生顺序 = 分数从大到小；而「名单」「全部成绩总览」「标签预览」顺序正确（= 点名册）。

**根因**：旧代码用 `pd.merge(namelist_df, score_df, how="left")` —— **点名册是左表**，成绩 merge **不改行序**；
PWA 去 pandas 后：
- 普通成绩 merge（`computeScoresFiltered`）**原地更新** `students` → **保序 ✅**（正确等价 `merge how=left`）；
- **`family==='roster'` 源** 却用 `src.rows.map(...) → this.students = merged` **重建数组** → **顺序被成绩源行序（常按分数降序）覆盖 ❌**。

D93 里我曾用"按学号排序"绕过 → 但**空学号时失效**，且引入了多余假设。**正解 = 让 `students` 顺序始终 = 点名册顺序**。

## 2. 拍板结论

1. **点名册为准**：整班预览直接用 `roster.students` 顺序（**去掉 D93 的按学号排序**）；
2. **现有点名册为准**：后续"加成绩源/加名单"= **保序 merge**（只补数据/追加新学生到末尾，**不改已存在学生的顺序**）；
3. **导入新点名册则以新点名册为准**：走"载入名单"入口 = **替换**（用新点名册文件行序）；
4. 新增：**标签预览** 与 **加权成绩总览** 处，提供 **按加权成绩 降序/升序 排列** 按钮（仅视图排序，不改底层顺序）；
5. **整班预览按点名册全局顺序逐人输出**（不按 pack/tag 分组），便于按顺序收齐整理。

## 3. 设计

### 3.1 `addScoreSource`（roster 分支）改为保序 merge
- **首次**（`students` 为空）：用 `src.rows` 行序初始化（= 点名册顺序）；
- **已有** `students`：**以现有数组为基准**，按 学号（`numberColumn`，别名容错）→ 姓名匹配：
  - 命中 → 补齐 `number/class`（不移动位置）；
  - 未命中且"新学生"（有姓名）→ **追加到末尾**；
  - **不重建、不重排**。
- `family!=='roster'` 的成绩源：维持现状（`computeScoresFiltered` 原地更新，已保序）。

### 3.2 「载入名单」入口 = 替换
- `loadRosterFile`：`this.students = readRosterXlsx(file)`（新点名册顺序为准）——已如此，**明确语义并加提示**。

### 3.3 整班预览：按点名册全局顺序逐人输出（不按 pack/tag 分组）
- **关键变更**：整班预览**不再按 pack/tag 分段**（不再「作业纸A全体 → 作业纸B全体」），
  改为**按点名册顺序逐人**输出：遍历 `roster.students`，每人用其 tag 对应的作业纸出一段纸；
- 连续页码（D93-S5）保留，按该全局顺序递增；
- 实现：新增 `stringifyClassHtml(students, padByKey, opts)`（或 `opts.order='roster'` + 每生 padId）——
  外层遍历学生、内层渲染该生被分配的作业纸；`partitionStudentsByTag` 仍用于"某生 → 哪张纸"映射；
- 学生无匹配作业纸 → 跳过（计入「未出页」）；
- 目的：**收上来按点名册顺序整理**。

### 3.4 排序按钮（视图层）
- **全部成绩总览**（`wideRows`）：按"综合得分*"（= 加权成绩）**降序/升序**切换；默认**点名册顺序**；
- **标签预览**（`roster.students`）：同一排序按钮（按 `score` 加权成绩）；默认点名册顺序；
- 排序**仅影响显示**，不改 `roster.students`；无成绩的学生排末尾。

## 4. 涉及改动

| 模块 | 改动 |
|---|---|
| `app/src/stores/roster.ts` | `addScoreSource` roster 分支：保序 merge（基准=现有 students；新同学 append） |
| `app/src/views/RosterView.vue` | 整班预览改为**按点名册全局顺序逐人**（不按 pack 分组）；总览/标签预览加"按加权成绩 升/降序"开关 |
| `app/src/lib/sheetHtml.ts` | 新增整班顺序渲染入口（外层遍历学生、按生选作业纸）；连续页码沿用 |
| `app/tests/selfcheck-*.mjs` | 保序 merge 语义 + 视图排序 selfcheck |
| `docs/04/13/15` | 顺序契约（点名册为准）+ 排序按钮说明 |

## 5. 分期实施（进度表）

| # | 阶段 | 交付物 | 状态 |
|---|---|---|---|
| T1 | 保序 merge：`addScoreSource` roster 分支（现有名单为准；新名单替换）+ selfcheck | `stores/roster.ts` + selfcheck | ✅ |
| T2 | 整班预览**按点名册全局顺序逐人输出**（不按 pack 分组）+ 连续页码 + selfcheck | `sheetHtml.ts`（`stringifyClassHtml`） + `RosterView.vue` | ✅ |
| T3 | 总览 + 标签预览：按加权成绩 降序/升序 按钮（视图层） | `RosterView.vue` + selfcheck | ✅ |
| T4 | 文档（docs/04/13/15）+ 验证 + 去敏 push | 文档 + CI | ⏳ |

## 6. 验收

- 加多个成绩源后，`roster.students` 顺序 == 点名册导入顺序（不被成绩源行序改变）；
- **整班预览**顺序 == 点名册全局顺序逐人（不按 pack/tag 分段，不再「某作业纸全体学生」）；
- 再次导入「成绩源/名单」保持现有顺序（新同学追加末尾）；「载入名单」以新文件顺序替换；
- **总览 / 标签预览** 可按**加权成绩 升/降序**排列（不影响底层顺序），无成绩者末尾；
- engine pytest / PWA build+selfcheck / 脱敏扫描 全绿。

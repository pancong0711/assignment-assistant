# D149 需求单：把「AI 批阅成绩」作为一种成绩源（每包一列，可加权）

> 日期：2026-10-31
> 状态：**已完成**
> 关联：`docs/05-D19`（成绩源）、`docs/12`

## 0. 教师诉求

> 如果我们已经批阅好了，那么在「班级与标签」里实际上不需要再下载这次作业的成绩。
> 应该像勾选那些表格的成绩一样，勾选我们批阅好的成绩。
>
> **没批阅记 0 分，未提交的记 0 分，每次作业包作为一列成绩，
> 可以加权到标签的总成绩里。**

## 1. 现状

成绩源统一为 `{name, score, weight, source}` 行列表，`merge_scores()` 按 `weight`
加权平均 → 分级打 tag。但**所有来源都是 Excel**，没有"从批阅产物取分"。

批阅产物里其实已有分：`<class_dir>/grading/<packId>/evaluations/<学生>.json`
的 `total_score`。

## 2. 设计

### 2.1 新增成绩源类型：`grading`

```
GET /roster/grading-scores?classDir=classes/化工25&packId=<包id>
→ { ok, packId, packName, rows: [{name, score, source, weight, submitted, graded}] }
```

- **一次作业包 = 一列**（`source = "grading:<packId>"`）；
- `score = total_score`；
- **未批阅 / 未提交 → 0 分**（按教师口径）；
- `submitted` / `graded` 两个标记随行返回，供 UI 显示"这 0 分是真 0 还是没交"。

### 2.2 学生名单来源

以该作业包目录下 `pack.json` / `plan` 的 **roster 名单**为准（与批阅同口径）；
批阅产物里有、名单里没有的学生也并入（按姓名）。

### 2.3 权重

每列权重由教师设置（默认 1.0），直接进 `merge_scores()` 的加权平均——
**与现有 Excel 成绩源完全同一套聚合逻辑**，不新增算法。

### 2.4 PWA

「班级与标签」成绩源区新增按钮：**「＋ 加入 AI 批阅成绩」**

- 弹出该班级可选的作业包列表（`grading/<packId>/evaluations` 存在即可选）；
- 选中后作为一列加入成绩源表格（与 Excel 列并排、可勾选、可调权重）；
- 列名显示 `批阅:<作业包名>`；
- 该列**只读**（不能手改分数），但可以取消勾选/调权重。

## 3. 任务清单

| # | 内容 | 验收 |
|---|---|---|
| T1 | 引擎：扫描班级下所有有评阅结果的作业包 | 单测 |
| T2 | 引擎：生成 `{name, score, source, weight}` 行，未批阅/未提交记 0 | 单测 |
| T3 | serve `GET /roster/grading-scores` | 单测 |
| T4 | PWA：加入该列（只读、可勾选、可调权重） | 浏览器 |
| T5 | 加权聚合与现有 Excel 源一致 | 单测（复用 merge_scores） |
| T6 | 文档 | — |

## 4. 验收标准

1. 能列出该班级有批阅结果的作业包；
2. 加入后每包一列，值与 `total_score` 一致；
3. **未批阅/未提交的学生在该列为 0**（不是空白、不是报错）；
4. 该列参与加权平均，结果与"手填同样分数"一致；
5. 该列只读（前端不可手改），但可取消勾选/调权重；
6. pytest / build / selfcheck / 脱敏全绿。

## 5. 风险

| 风险 | 缓解 |
|---|---|
| 0 分与"没交"混淆 | 行里带 `submitted/graded` 标记，UI 可区分展示 |
| 批阅还没跑完就取分 | 只列 `evaluations/` 非空的包；UI 显示"X 人已评阅" |
| 跨班串数据 | 路径限定在 `<class_dir>/grading/` 下并做越界校验 |

## 6. 实施记录（2026-10-31 完成）

### 6.1 引擎 `roster/grading_scores.py`

- `list_grading_packs(ws, class_dir)`：列出有 `evaluations/` 的作业包
  （跳过 `_trend` 等内部目录），带 `graded` 人数与最近时间；
- `grading_scores(ws, class_dir, pack_id, students=...)`：
  - 按姓名取 `total_score`；
  - **名单里有但没批阅 → 0 分**，并带 `graded=False / submitted=False`；
  - 批阅里有、名单没传的学生也一并返回（避免丢分）；
  - 路径 `relative_to(<ws>/classes)` 越界校验。

### 6.2 serve

- `GET /roster/grading-packs?classDir=...`
- `GET /roster/grading-scores?classDir=...&packId=...&students=a,b,c`

### 6.3 PWA

- 新增成绩源类型 `family='grading'`（`SCORE_FAMILY_PRESETS` 增加一项）；
- 「班级与标签 → 成绩源」区新增按钮 **「＋加入 AI 批阅成绩」**：
  列出该班级有评阅结果的作业包 → 选中后作为一列加入；
- `roster.addGradingSource()`：写入 `scores` 映射，标记 `includeInAggregation=true`；
  重复加入同一包会提示"已在成绩源里"；
- 该列**只读**（不能手改分数），但可取消勾选、可调权重——与现有 Excel 列并排。

## 7. 验收对照

| # | 标准（§4） | 结果 | 证据 |
|---|---|---|---|
| 1 | 能列出有批阅结果的作业包 | ✅ | `test_list_packs_only_with_evaluations` |
| 2 | 每包一列，值 = `total_score` | ✅ | `test_scores_from_evaluations` |
| 3 | **未批阅/未提交 → 0 分** | ✅ | `test_ungraded_student_gets_zero` / `test_unsubmitted_is_zero_and_flagged` |
| 4 | 参与加权，与手填同分结果一致 | ✅ | `test_rows_merge_with_existing_sources` / `test_weight_participates` |
| 5 | 只读（前端不可手改） | ✅ | PWA 只写 `scores`，无编辑入口 |
| 6 | pytest / build / selfcheck / 脱敏 | ✅ | 1222 passed · 0 error · 33/33 · 通过 |

## 8. 与现有成绩源的关系

**完全同一套聚合**：`merge_scores()` 按 `weight` 加权平均，
所以"批阅成绩列"与"Excel 成绩列"可以混在一张表里一起算总成绩。

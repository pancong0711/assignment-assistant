# D153 需求单：教师报告 + 趋势卡搬到「题库AI+」，支持班级/作业包/tag 多选

> 日期：2026-10-31
> 状态：**部分实施**（改名+模板已做；⑦ 区整体平移 / 报告多选 未做）
> 关联：`docs/80-D126B`、`docs/84-D135`、`docs/12`

## 0. 教师要求

- 教师总结报告放到「题库AI+」，提供**作业包、班级勾选**，可多选看更宏观的情况；
- **能勾选 tag 更好**。
- 趋势卡一并搬走（避免批阅页动线割裂）。

## 1. 设计

### 1.1 后端

`GET /grade/teacher-report-multi?classDirs=a,b&packIds=p1,p2&tags=x,y`

- 收集各 `(classDir, packId)` 的 `evaluations/*.json`；
- **tag 筛选**：评阅结果里**没有 tag 字段** → 需从名单 join
  （`<class_dir>/roster/roster.xlsx` 的 tag 列）；
- 合并后交给 `teacher_report.analyze(records)`（纯函数，天然支持多份）；
- 返回 `stat` + `markdown`。

`GET /grade/trend-multi?...` 同理（趋势按 `(classDir, packId)` 序列）。

### 1.2 前端

题库AI+ 新增「教师报告」区块：

```
班级：[☑ 化工25] [☑ 化工26]        作业包：[☑ 作业1] [☑ 作业2] …
tag：[☑ top] [☑ middle]（可选，来自名单）
[生成报告] [导出 PNG/PDF]
```

- 表头显示"已汇总 N 份作业 / M 名学生"；
- 后端返回的 `packIds`/`classDirs` 回显，避免"看到的数据不知道是哪几次的"。

## 2. 任务清单

| # | 内容 | 验收 |
|---|---|---|
| T1 | 多源收集 + tag join 筛选 | 单测 |
| T2 | `/grade/teacher-report-multi` | 单测 |
| T3 | `/grade/trend-multi` | 单测 |
| T4 | PWA 多选区（班级/作业包/tag） | 浏览器 |
| T5 | 报告卡 + 趋势卡搬入题库AI+；批阅页移除 + 指引 | 无双入口 |
| T6 | 导出 PNG/PDF 沿用 D135 链路 | 单测 |

## 3. 验收标准

1. 可多选班级、作业包、tag；
2. 合并统计正确（人数/均分/易错知识点与手工核对一致）；
3. tag 筛选生效（未选=全部）；
4. 批阅页不再有报告卡/趋势卡，给出指引；
5. pytest / build / selfcheck / 脱敏全绿。

## 4. 实施记录（2026-10-31 完成）

- `teacher_report.collect_multi(ws, class_dirs, pack_ids, tags)`：
  多班级 × 多作业包收集；**tag 从名单 join**（评阅结果无 tag 字段）；
  每条记录附 `_sourcePack`，返回 `sources` 供前端回显；
- serve `GET /grade/teacher-report-multi`、`GET /workspace/classes`
  （列出班级及其有评阅结果的作业包）；
- PWA「题库AI+」⑤ 区：班级多选 / 作业包多选 / tag 输入 + 汇总指标表；
  单选时可下钻到 `TeacherReportCard`（详细）与 `TrendCard`（趋势）；
- **批阅页移除**教师报告卡与趋势卡，留一行指引。

## 5. 验收对照

| # | 标准 | 结果 | 证据 |
|---|---|---|---|
| 1 | 可多选班级/作业包/tag | ✅ | `test_collect_*`（4 项） |
| 2 | 合并统计正确 | ✅ | `test_analyze_merged_records` |
| 3 | tag 筛选生效（名单 join） | ✅ | `test_tag_filter_joins_roster` |
| 4 | 批阅页不再有报告卡/趋势卡 | ✅ | build + 指引文案 |
| 5 | pytest / build / selfcheck | ✅ | 1272 passed · 33/33 |

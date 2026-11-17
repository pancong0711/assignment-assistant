# D180 需求单：采用审计 tag 后，逐生审核主表 tag 未刷新

> 日期：2026-11-17
> 状态：**已完成（2026-11-17）**
> 关联：`docs/117-D172-tag-audit.md`、`docs/118-D173-tag-audit-ux.md`、
> `docs/112-D168-metrics-and-snapshot.md`（快照口径）
>
> 隐私：本需求只涉及合成测试数据，不得使用真实学生名单、转写或成绩。

---

## 0. 教师反馈

学生原 tag 为 `innovation`，tag 审计结果为 `translation`。教师在逐生审核中点击
「采纳审计 tag」/「采用审计」后，主列表中的学生 tag 仍显示 `innovation`，
看起来像没有生效。

---

## 1. 已核实的根因

采用审计并非没有写回，而是**写回口径与页面刷新读取口径不一致**：

1. 「采纳审计 tag」调用 `POST /grade/audit-tags/apply`；
2. `grading/tag_audit.py::apply_audit_tags()` 正确把教师确认的 tag 写入
   `classes/<班级>/roster-tags/<packId>.json` 快照，并更新审计记录；
3. 前端随后调用 `loadStudents()` → `/xxt/preview/students` 刷新主列表；
4. 后端 `/xxt/preview/students` 只用 `inputs.students_with_tags()` 从
   `roster/roster.xlsx` 补 tag，**没有使用请求里已经传入的 `taskId`（packId）读取快照**；
5. 因此主表继续显示 roster.xlsx 的旧 tag，而审计详情与后续批阅使用快照中的新 tag。

D172 的设计是：`roster-tags/<packId>.json` 是**该作业包批阅依据的权威快照**；
`roster/roster.xlsx` 是可变班级主名单。因此主表在已指定作业包时应优先显示快照 tag。

---

## 2. 修复目标

在 **不修改前端、不修改评分规则、不修改审计写回语义** 的前提下，让
`/xxt/preview/students` 在带 `taskId`（packId）时优先使用该作业包的
`roster-tags/<taskId>.json` 快照补 tag。

---

## 3. 实现要求

### R1. 后端优先快照

`engine/src/assist/serve.py` 的 `/xxt/preview/students`：

- 请求带 `classDir` + `taskId` 时，优先读取
  `<ws>/<classDir>/roster-tags/<taskId>.json`；
- 按学生姓名（若有学号则优先按学号，姓名兜底）取快照 tag；
- 快照不存在、损坏或某生不在快照中点名时，回落到现有
  `inputs.students_with_tags(ws, class_dir)`；
- 不修改 `roster.xlsx`，不改变审计写回链路。

### R2. 兼容无 taskId 的调用

- 只带 `classDir`、没有 `taskId` 的调用保持原行为：从 `roster.xlsx` 补 tag；
- 不传 `classDir` 的视图（如 `XxetongView.vue`）保持原行为；
- 不得引入新的必填参数。

### R3. 可测试性

优先复用 `grading/snapshots.read_tags_snapshot()`，不要在 `serve.py` 重复实现快照解析。

---

## 4. 验收标准

| # | 场景 | 期望 |
|---|---|---|
| 1 | roster 为 `innovation`，快照为 `translation`，请求带 `classDir+taskId` | 返回学生 tag=`translation` |
| 2 | 只有 `classDir`，无 `taskId` | 返回 roster 的 `innovation` |
| 3 | 带 `taskId` 但快照缺失 | 回落到 roster 的 `innovation`，不报 500 |
| 4 | 快照 JSON 损坏 | 回落到 roster，不报 500 |
| 5 | 审计写回后立即刷新 | 主列表 tag 与审计详情/后续批阅口径一致 |
| 6 | 原有 `/xxt/preview/students` 行为 | 相关既有测试不回归 |
| 7 | 全量回归 | pytest 通过；脱敏检查通过 |

---

## 5. 范围与非目标

- 只允许修改 `engine/src/assist/serve.py`；
- 新增测试文件 `engine/tests/test_d180_audit_preview_tag_source.py`；
- 不改前端、不改 `tag_audit.py`、不改快照格式、不改评分或提示词；
- 不访问真实学生数据、不发起真实网络请求、不安装依赖、不 commit/push。

---

## 6. 实施结果

- 修改：`engine/src/assist/serve.py`，新增 `_load_preview_tags()`；
- 新增测试：`engine/tests/test_d180_audit_preview_tag_source.py`（9 项）；
- `/xxt/preview/students` 在 `classDir + taskId` 同时存在时优先读取
  `roster-tags/<taskId>.json` 快照，按学号优先、姓名兜底；
- 快照缺失/损坏/学生不在快照中时回落到 `roster.xlsx`；
- 无 `taskId` 或未传 `classDir` 时保持原行为；
- 端到端测试覆盖真实路径 `apply_audit_tags()` → 快照落盘 → preview 刷新；
- 测试隔离：恢复 serve/xxt 全局 workspace 绑定，避免污染 d130/d172；
- 验收：D180 目标测试 9 passed；D180+d130+d172 组合 79 passed；
  全量 pytest 1640 passed / 2 skipped；
- 未修改前端、审计写回语义、快照格式、评分规则或提示词。

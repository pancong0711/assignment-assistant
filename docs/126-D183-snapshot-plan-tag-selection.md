# D183 修复：批阅 plan 忽略作业包快照 tag，导致审计后仍按旧 tag 选题

> 日期：2026-11-17
> 状态：**已完成**
> 关联：`docs/117-D172-tag-audit.md`、`docs/124-D181-tag-edit-and-audit-apply-path.md`、
> `docs/112-D168-metrics-and-snapshot.md`

## 0. 现象

学生 roster 原 tag=`innovation`，AI 审计建议/采用为 `translation`。按钮和手动输入
已经能写入 `roster-tags/<packId>.json`，但后续批阅仍像按 `innovation` 走；教师怀疑
“已评阅所以 tag 没有转换”。

## 1. 根因

已评阅不是直接阻断 tag 写回的原因。真正的漏洞在批阅 plan 装配：

- `grading/inputs.build_plan()` 通过 `students_with_tags()` 读学生 tag；
- `students_with_tags()` 只读 `roster/roster.xlsx`；
- D172 的审计采用/手动改 tag 只写 `roster-tags/<packId>.json` 快照（按设计不改 roster）；
- 因此 plan 仍按 `innovation` 选作业纸和题目；
- 即使随后 `flow._write_grade_snapshots()` 按快照锁定 plan 的 tag 字段，
  plan 里的 `questions/padId` 已经按旧 tag 选好了。

表现就是：审计详情和快照已变成 `translation`，但重新批阅仍使用 `innovation`
作业纸；若未勾选“强制重做”，旧评阅结果还会被跳过，看起来更像“已评阅导致没生效”。

## 2. 修复

- `students_with_tags()` 增加可选 `pack_id`：
  - 传了 `pack_id` 且快照存在时，按学号优先、姓名兜底覆盖 roster 的 tag；
  - 快照缺失/损坏时自动回落 roster，不抛错；
- `build_plan()` 使用“作业包 id（`pack.id`）或批阅作用域 id（`task_id`）”作为
  `pack_id` 读取快照；
- 不改 roster.xlsx、不改快照格式、不改评分规则。

## 3. 验收

- 无快照：plan 仍按 roster innovation 选创新题；
- 有快照：plan 按 translation 选翻译题，其他未改 tag 学生仍选原作业纸；
- 快照按学号匹配优先于姓名；
- 原 D172/D181 与批阅相关测试不回归。

# D184 需求单：审计采用 tag 应补齐快照中缺失的实际提交学生

> 日期：2026-11-17
> 状态：**已完成（2026-11-17）**
> 关联：`docs/117-D172-tag-audit.md`、`docs/118-D173-tag-audit-ux.md`、
> `docs/124-D181-tag-edit-and-audit-apply-path.md`、`docs/126-D183-snapshot-plan-tag-selection.md`
>
> 隐私：只使用合成学生/tag 数据；不得读取或上传真实 roster、图片、转写、成绩。

---

## 0. 现场

学生 roster 原 tag=`innovation`，AI 审计建议 `translation`。教师采用审计或手动输入后，
该生 tag 仍没有变化。

检查发现：

- 对应作业包的 `roster-tags/<packId>.json` 里**没有该生姓名**；
- 同班还有另一名学生也不在快照里；
- 审计阶段从当前 roster 兜底拿到了 tag，所以能给出 `translation` 建议；
- 但 `apply_audit_tags()` 只对快照已有学生行打补丁，快照没有该生时只返回
  `missing`，不写文件；
- 前端没有展示 `missing`，把它显示成“没有变化”，于是看起来像静默失败。

---

## 1. 三份名单的正确口径

1. `roster/roster.xlsx`
   - 当前班级完整名单，包含未提交学生；
   - 提供姓名、学号、当前 tag。

2. 下载作答名单（review 列表 / `students.json` + 图片）
   - **实际有效提交名单**；
   - 审计/采用 tag 的目标范围应以它为准，未提交学生不参与。

3. `roster-tags/<packId>.json`
   - 该作业包历史批阅的学生→tag **权威快照**；
   - 不要求与“未提交学生”完全一致；
   - 已有行必须保留，不能被审计名单整体替换；
   - 缺失的**实际提交学生**应在采纳/手动改 tag 时补入（UPSERT）。

---

## 2. 修复目标

### R1. 审计采用/手动改 tag 支持 UPSERT

`engine/src/assist/grading/tag_audit.py::apply_audit_tags()`：

对被点名的每个学生：

1. 快照中已有：按现有补丁式更新；
2. 快照中没有，但 roster 中能找到（学号优先、姓名兜底）：
   - 从 roster 取 `name/number/tag`；
   - 插入快照；
   - 记录 `previousTag`、`tagHistory`、`previousTag` 来源和审计应用来源；
3. 快照/roster 都没有，但变更 payload 自带 `name`（可选 `number`）：
   - 仍插入快照；
   - `previousTag` 留空；
   - 记录来源说明，确保教师显式操作可见；
4. 以上都找不到：保留在 `missing`，不得静默写成功；
5. 不得删除快照中未参与本次操作的学生行。

### R2. 前端传递有效学生身份并显示失败

`app/src/components/AiGradingPanel.vue` / `engineClient.ts`：

- `students.value` 保留下载名单中的 `studentId`；
- `applyAuditChecked()`、`applyAuditOne()`、`saveManualTag()` 在 `changes[]` 中传
  `number: studentId/number`（有则传）；
- `applyAuditChanges()` 必须区分：
  - `applied` 非空 → 成功；
  - `missing` 非空 → 明确显示“以下学生未找到，未写入”；
  - `unchanged` 非空 → 明确显示“值未变化”；
- 不能仅以 `r.ok === false` 判断失败。

### R3. 审计名单与提交名单对齐

- 运行审计时只对实际有作答/有转写学生出结论（现有行为保持）；
- 未提交学生只作为 skipped 展示，不进入采用/批量改 tag 操作；
- 不修改 roster.xlsx；
- 不改变 D183 的“批阅 plan 按快照 tag 选题”逻辑。

---

## 3. 验收标准

| # | 场景 | 期望 |
|---|---|---|
| 1 | 快照只有学生甲，roster 有甲乙；对乙采用 translation | 快照新增乙并写入 history/previousTag |
| 2 | 快照中已有甲；对甲采用 | 原逻辑更新甲，其他行不变 |
| 3 | 快照/roster 都没有，但下载名单有该生 | 以 payload 姓名补入，previousTag 为空 |
| 4 | 变更里姓名与快照不一致、number 一致 | 按 number 命中并更新 |
| 5 | 有学生 missing | 前端必须显示红色错误，不得显示“没有变化” |
| 6 | 一次修改多名学生，部分 missing | 已匹配的正常写入，missing 明确列出 |
| 7 | 未提交学生 | 审计/采纳不改变其 tag |
| 8 | 已评阅学生 | 不因已评阅阻止 tag 写入；后续强制重批按新 tag 选题 |
| 9 | 回归 | D183 plan 快照选题、D181 apply、D172 审计测试全绿 |

---

## 4. 范围与限制

- 允许修改：
  - `engine/src/assist/grading/tag_audit.py`
  - `engine/src/assist/serve.py`（仅在 API 需要透传字段时）
  - `app/src/components/AiGradingPanel.vue`
  - `app/src/lib/engineClient.ts`
  - 对应 engine/app tests
- 不改评分规则、提示词、题库、作业纸生成；
- 不改快照 JSON 格式和 D183 行为；
- 不访问真实学生数据、不联网、不安装依赖、不 commit/push。

---

## 5. 实施结果

- `apply_audit_tags()` 改为 UPSERT：快照已有更新；快照缺失但 roster 有则补入；
  roster 也没有但 changes 带姓名/学号时按 payload 补入；不删除未参与行；
- 新增行同步写 `previousTag/tagHistory/tagUpdatedAt`，audit resolution 同步更新；
- 前端下载名单保留 `studentId`，采纳/批量/详情/手动输入均在可用时携带 number；
- 前端对 `applied/missing/unchanged` 分开展示，missing 明确提示“未找到，未写入”；
- 新增 `engine/tests/test_d184_audit_tag_upsert.py` 与
  `app/tests/selfcheck-d184-audit-tag-upsert.mjs`，并接入 `npm run selfcheck`；
- 验证：D184+D181+D183+D172+D180+D130 相关测试 99 passed；
  全量 pytest 1661 passed / 2 skipped；前端 build 与 D184 selfcheck 通过；
  脱敏检查与启动脚本 lint 通过。

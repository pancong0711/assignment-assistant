# D181 需求单：AI 审计建议 tag 与手动改写 tag 均无法生效

> 日期：2026-11-17
> 状态：**已完成（2026-11-17）**
> 关联：`docs/117-D172-tag-audit.md`、`docs/118-D173-tag-audit-ux.md`、
> `docs/123-D180-audit-apply-preview-tag-source.md`
>
> 隐私：只使用合成学生/tag 数据；不得读取或上传真实 roster、转写、图片、成绩。

---

## 0. 教师反馈

学生原 tag 为 `innovation`，AI 审计建议 tag 为 `translation`。目前以下两条路径都不能
真正改变学生 tag：

1. 点击「采纳审计 tag」/「采用审计」；
2. 在逐生审核的 tag 输入框中手动改写。

需要继续审查代码，确认 AI 审计建议 tag 到正式生效 tag 的完整链路哪里断了，并修复。

---

## 1. 需要重点核对的链路

对两条操作分别追踪：

### A. 采纳审计按钮

```text
前端按钮 → applyTagAudit API → POST /grade/audit-tags/apply
→ tag_audit.apply_audit_tags()
→ 写 roster-tags/<packId>.json / tags-audit.json
→ 前端 loadStudents()/loadAudit()
→ /xxt/preview/students 返回 tag
→ 表格显示
```

### B. 手动输入框改写

```text
前端输入框保存 → 对应 API → 后端写入哪个文件/字段
→ 前端刷新 → /xxt/preview/students 返回 tag
→ 表格/详情显示
```

必须确认：

- 手动改写是写 `roster.xlsx`、`tags-audit.json`、`roster-tags/<packId>.json`，还是多处；
- 在已有 `roster-tags/<packId>.json` 快照时，D180 已让 preview 优先读快照；
  手动改写若只写 `roster.xlsx`，会被快照覆盖 → 表现为“改了没反应”；
- 采纳审计按钮是否真的把 `translation` 写入快照，UI 传的 `taskId` 是否真的是 packId；
- 前端刷新时 `taskId/packId/padId` 是否可能为空或指向错误作用域；
- 学号/姓名匹配是否因前后空格、空值、重名、转写/显示名差异而失败；
- API 返回 `ok=false` 时前端是否吞掉错误、仍显示成功。

---

## 2. 修复目标

确保在**同一个作业包作用域**内：

1. 「采纳审计」后，主表 tag、审计详情和后续批阅都立即使用新 tag；
2. 手动改写 tag 后，刷新/重进页面仍保持新 tag，且后续批阅使用新 tag；
3. 两条路径采用一致的权威来源与写入语义，不能一条写 roster、一条写快照；
4. 无快照、快照缺失/损坏时仍能合理回落到 roster；
5. 失败时前端应可见，不得静默假成功。

---

## 3. 实现与范围

- 先由 opencode 完整定位两条路径的断点，再给最小修复；
- 允许修改的文件必须与断点直接相关，优先：
  - `engine/src/assist/serve.py`
  - `engine/src/assist/grading/tag_audit.py`
  - `app/src/components/AiGradingPanel.vue`
  - `app/src/lib/engineClient.ts`
  - 对应 engine/app 测试；
- 不改评分规则、提示词、作业纸生成、题库；
- 不改快照文件格式；
- 不访问真实数据、不发起真实网络请求、不安装依赖、不 commit/push。

---

## 4. 验收标准

| # | 场景 | 期望 |
|---|---|---|
| 1 | roster 原 tag=`innovation`，审计建议=`translation`，点击采纳 | 快照与界面 tag 均为 `translation` |
| 2 | 已有快照时手动把 tag 改为 `translation` | 刷新后仍为 `translation` |
| 3 | 无快照时手动改 tag | 刷新后新 tag 生效 |
| 4 | 采纳后立即批阅 | 使用新 tag 对应作业纸 |
| 5 | 快照缺失/损坏 | 回落 roster，不 500 |
| 6 | 保存失败 | 前端显示错误，不假成功 |
| 7 | 回归 | 相关 pytest/selfcheck 通过，全量 pytest 通过 |

---

## 5. 实施结果

- 修复：
  - `engine/src/assist/grading/tag_audit.py`：`apply_audit_tags()` 在快照缺失时自动从当前 roster 创建快照，再补丁式写入；支持按学号兜底匹配。
  - `engine/src/assist/serve.py`：`/xxt/preview/students` 在 `taskId` 为空时从磁盘反查批阅目录并用它读取快照，保证刷新/重进后 tag 仍生效。
  - `app/src/components/AiGradingPanel.vue`：`applyAuditChanges()` 使用 `resolvedScope` 兜底，避免刷新后作业包下拉为空时静默 no-op；缺少作用域/班级目录时显式报错。
  - `app/src/lib/engineClient.ts`：`applyTagAudit` 的 changes 类型允许携带 `number`。
- 新增测试：
  - `engine/tests/test_d181_tag_apply_and_manual_edit.py`（9 项）：覆盖已有/无快照、采纳/手动、刷新无 taskId、失败可见性、快照损坏回落。
  - `app/tests/selfcheck-d181-tag-apply.mjs`：验证前端 apply 错误透传与 preview 作用域查询串。
- 结果：D181 目标测试 9 passed；D181+D180+D172+D130 组合 88 passed；全量 pytest 1648 passed / 1 failed（`test_d168_atopia_task.py::test_extract_reports_per_file_error`，与本次断点无关，疑为环境依赖问题）/ 2 skipped。

## 6. 交接约束

- 使用独立 worktree 与本地 opencode service；
- 权限限制：禁止外部目录、网络、子 agent、安装依赖、真实 workspace、密钥和学生数据；
- 完成后停在 worktree 等待人工 review。

# D195：只部分学生生成报告 + 表格出现重复姓名

> 日期：2026-11-18
> 状态：**已完成（2026-11-18）**
> 关联：`docs/137-D194-report-render-interrupt-resume.md`、`docs/136-D193-upload-gbk-unicode-and-report-versioning.md`
>
> 隐私：测试只用合成数据（学生甲/学生乙/学生丙）。

---

## 0. 现场

- 点了「一键生成批阅报告」，**只有部分学生**生成了报告；
- 下方表格里，**有报告的学生显示了分数，没报告的没有**；
- 教师忘记勾选班级/作业包先点了一次，之后勾选再点一次 →
  表格里**多出很多姓名，部分重复**（实际是同一个班的两次不同作用域）。

## 1. 根因（两个独立问题）

### 成因 A：报告 = 按**草稿**生成，表格 = 按**平台名单**显示

| 数据 | 来源 | 影响 |
|---|---|---|
| 表格学生行 | `preview_students()` 解析平台批阅列表 HTML | 平台有多少提交/学生就多少行 |
| 表格分数 | 草稿 `ai.score` / `human.score` | 有草稿才有分 |
| 报告 | `render_reports_from_drafts()` 遍历**草稿** | **只给有草稿的学生出报告** |

所以“没报告的没有分数”其实是**那几名学生根本没有草稿**（没跑 AI 批阅 / 没保存人工批阅），
与报告生成无关；界面此前没有任何提示，看起来像“报告生成漏人”。

### 成因 B：同一学生在草稿里有**两个键** → 重复报告 + 重复姓名

草稿键历史上可能是 `workAnswerId`，也可能是**姓名**（批阅清单未解析到 id 时的回落）。
`render_reports_from_drafts()` 按 key 遍历，于是：

- 同一学生生成**两份**报告（内容不同）；
- 两份都写 `reports/<学生>.png` → **后者覆盖前者**；
- 版本索引里同一学生两条记录；
- 前端 `draftOf()` 兜底多个键 → 表格把同一人显示多次/状态混乱。

## 2. 修复

### R1. 报告按**学生姓名**合并（不再按草稿键）

`engine/src/assist/grading/drafts.py`：

- 新增 `_draft_richness()`：人工套已使用(8) > 有批语(4) > 有分数(2) > 有转写/图片(1)；
- 生成前按学生姓名合并，**取内容更完整的那份**，并记下所有键；
- 报告回写时**同步到该学生的所有键**（否则表格按另一个键读不到报告版本）；
- 结果里同一学生只出现一次。

### R2. 生成前「范围核对」（只读）

新增 `report_scope_report()` + `POST /xxt/grade/render-from-drafts {scopeOnly:true}`：

```json
{"studentCount": 32, "draftCount": 34,
 "missingDraft": ["学生丙", "..."],      // 平台有行、无草稿 → 不会有报告
 "notInList": [...],                     // 有草稿、平台名单没有
 "duplicateKeys": {"学生甲": ["wa_1", "学生甲"]}}
```

前端在「一键生成」前自动调用并显示醒目提示：

> ⚠ 范围核对：本次可用于生成报告的草稿 32 人（草稿记录 34 条）。
> 表格里另有 3 名学生**没有本地草稿**，不会生成报告也不会有分数：学生丙…
> → 先对他们「转写+评阅」或逐生保存批阅后再生成。

### R3. 明确的「重新生成 / 清理」入口

- 「🔁 重新生成全部报告」：按当前草稿覆盖重生成（内容未变不产生新版本，D193）；
- 「🧹 清理多余报告」：删除 `reports/` 下**不在当前名单**的报告 md/html/png 及其历史目录
  （只动 `reports/`，**不动草稿/分数/批语**）；支持 `dryRun`。

## 3. 关于「勾选/未勾选」两次操作

- 草稿按 `(classDir, taskId, workId)` 分目录存放：**未选作业包 → `taskId=''` → 读不到草稿**，
  引擎会通过 `discover_draft_scopes()` 反查出磁盘上存在的目录再读（D130-FIX2）；
- 若两个作业包目录都有同一 workId 的草稿（旧包 + 新包），会出现“不同作用域各有一批草稿”；
  D195 的范围核对会把“草稿记录数”和“学生人数”同时显示出来，多键/多目录一眼可见；
- 报告只写当前 `taskId` 的 `reports/`，不会串到另一个作业包。

## 4. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 同一学生有 `wa_xxx` 与姓名两个草稿键 | 只生成 1 份报告；两个键都回写报告版本 |
| 2 | 两个键内容不同 | 取更完整（人工套优先）的那份 |
| 3 | 平台名单有、本地无草稿 | 生成前提示 `missingDraft`，并说明“不会生成报告” |
| 4 | 重复键 | 范围核对列出 `duplicateKeys` |
| 5 | 需要全部重做 | 「🔁 重新生成全部报告」 |
| 6 | reports/ 里有旧学生残留 | 「🧹 清理多余报告」只删名单外的 |
| 7 | 回归 | 全量 pytest 1790 passed；selfcheck:d188–d195 通过 |

## 5. 范围

允许：`engine/src/assist/grading/drafts.py`、`engine/src/assist/grading/report_versions.py`、
`engine/src/assist/serve.py`、`app/src/lib/engineClient.ts`、
`app/src/components/AiGradingPanel.vue`、`app/package.json`、对应 tests、本文档与 README 索引。
不得改提取/批次/批阅评分逻辑；不得读取真实学生数据（测试全为合成数据）。

## 6. 实施结果

- `drafts.py`：`_draft_richness()`、按学生合并、回写所有同名键、`report_scope_report()`；
- `report_versions.py`：`cleanup_reports(dry_run=)`；
- `serve.py`：`scopeOnly` 只读核对、`POST /xxt/grade/report-cleanup`；
- 前端：生成前范围核对提示、`🔁 重新生成全部报告`、`🧹 清理多余报告`；
- 测试：`engine/tests/test_d195_report_scope_duplicate.py`（9 项）+ `selfcheck:d195`。

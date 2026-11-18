# D187 修复：一键生成报告作用域、强制重做复选框、追加批次作业元数据

> 日期：2026-11-18
> 状态：**已完成**
> 关联：`docs/118-D175-review-comment-score-merge.md`、
> `docs/22-D71-engine-launcher-two-phase-update.md`、`docs/24-D73`

## 0. 现场问题

1. 点击「📄 一键生成批阅报告」没有生成报告；
2. 「强制重做」前出现两个方框：一个真实 checkbox + 一个静态 `☑`；
3. 「作业预览-学习通 → 追加到当前批次」是否会重复下载、覆盖已有批阅产物。

## 1. 根因

### 1.1 报告生成缺 classDir

`renderReports()` 只传 `classId/workId/taskId`，没有传真实班级目录 `curWorkDir`。
后端 `render_reports_from_drafts()` 在 `classDir=""` 时回落到：

```text
classes/<学习通数字 classId>
```

而真实草稿在：

```text
classes/<中文班级目录>/grading/<taskId>/drafts/
```

两者不一致，后端读不到草稿，报告生成失败。

同时刷新后 `packId/padId` 可能为空，原代码没有用 `resolvedScope` 兜底 taskId。

### 1.2 强制重做 UI

模板写成：

```html
<input type="checkbox" v-model="forceRedo" />
☑ 强制重做（...）
```

真实 checkbox 前又写了一个静态 `☑`，所以视觉上像两个勾选框。属于纯 UI 文案错误。

### 1.3 追加批次数据风险

「追加到当前批次」会重新只读提取所选班级/作业的平台元数据，然后合并进目标 run JSON：

- 原 run JSON 先备份到 `runs/.history/`；
- 不下载作答图片、不写 roster.xlsx、不碰 grading/evaluations/drafts/reports/roster-tags；
- 但旧合并逻辑 `classes[kid].update(nk)` 会在“只选部分作业追加”时，
  用新的 works 列表替换该班旧 works 列表 → run 元数据里未选中的旧作业可能丢失。

## 2. 修复

### 2.1 报告生成

`app/src/components/AiGradingPanel.vue::renderReports()`：

- `taskId = packId || padId || resolvedScope`；
- 请求显式携带 `classDir: curWorkDir`；
- 缺少 taskId/classDir 时给可读提示，不再打到后端后无结果。

### 2.2 强制重做

删除静态 `☑`，只保留一个真实 checkbox。

### 2.3 追加提取合并

`engine/src/assist/xxt/extract_run.py` 新增 `merge_work_records()`：

- 旧 works 中未被本次选中的作业保留；
- 同 workId 的作业用新提取结果更新；
- 新 workId 追加；
- 无 workId 的旧/新记录保守保留。

不改变作答图片、评分、批语、报告、roster tag。

## 3. 验收

- 一键生成报告携带真实 classDir；
- 强制重做只有一个 checkbox；
- 追加部分作业后旧 run 中其它 works 不丢失；
- 新增前端 selfcheck 与 engine 纯函数测试；
- 前端 build、相关 pytest、脱敏检查通过。

## 4. 验收结果

- 报告相关 + 追加合并测试：`23 passed`；
- 全量 pytest（deselect 既有 Playwright 报告渲染超时用例）：`1691 passed`；
- 前端 `selfcheck:d187`：通过；
- 前端 build：通过；
- 脱敏检查、启动脚本 lint、`git diff --check`：通过。

# D201：逐生上传报「本地无该作业的批阅草稿」

> 日期：2026-11-18
> 状态：**已完成（2026-11-18）**
> 关联：`docs/143-D200-report-image-upload-default.md`、
> `docs/120-D177-single-prompt-builder.md`（D175 同类问题）
>
> 隐私：测试只用合成数据（学生甲/学生乙）。

---

## 0. 现场

对照表显示某学生「已提交·可传」，并带报告版本：

```text
韩冰月 | 20261119-160355-e5f465 | 90 | 待批阅 | — | 已提交·可传 | 可上传
上传 ❌ 本地无该作业的批阅草稿
```

## 1. 根因：上传 CLI 没带 scope，去旧布局找草稿

`assist xxt grade-upload --from-drafts` 原实现：

```python
drafts = grade_store.read_drafts_normalized(xxt_home(), class_id, work_id)
#                                                    ↑ 没有 ws/class_dir/task_id
```

`read_drafts_normalized()` 只有在同时给出 `ws + class_dir + task_id` 时才走**新布局**
`<ws>/<classDir>/grading/<taskId>/drafts/<workId>.json`；否则只读**旧布局**
`<xxt_home>/grade-drafts/<classId>/<workId>.json`。

而草稿实际都在新布局里 → 必然读不到 → “本地无该作业的批阅草稿”。
对照表之所以正常，是因为预览端点读了 `classDir + taskId`。

这与 D175 是同一类问题（“读草稿漏传 scope”），只是这次发生在上传链路。

## 2. 修复

### R1. CLI 新增并真正使用 scope

```bash
assist xxt grade-upload --from-drafts \
  --class-dir "classes/化工25" --task-id "packA" --student 学生甲 ...
```

- 新增 `--class-dir` / `--task-id`；
- 未给时自动解析：classmap 推 `classDir`，`discover_draft_scopes()` 反查 `taskId`；
- 同时把**其它候选 taskId** 作为 `alt_task_ids` 传入（作业包/作业纸 id 漂移时兜底）；
- 仍然读不到时，返回带 `scope` 的 JSON，便于当场判断是路径问题还是没跑批阅：

```json
{"ok": false, "error": "本地无该作业的批阅草稿",
 "hint": "请确认已对该作业跑过「转写+评阅」，且 classDir/taskId 与逐生审核一致…",
 "scope": {"classDir": "classes/化工25", "taskId": "packA", "altTaskIds": []}}
```

### R2. serve 透传 scope

`POST /xxt/grade/upload` 把 `classDir` / `taskId` 转成 `--class-dir` / `--task-id`。

### R3. 前端上传请求带 scope

**逐生上传**与**批量上传**都带上：

```ts
classDir: curWorkDir.value,
taskId: packId.value || padId.value || resolvedScope.value || undefined,
```

## 3. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 草稿在新布局、上传不带 scope | 读不到（复现原 bug，测试固化） |
| 2 | 带 `ws+classDir+taskId` | 能读到草稿并组出 payload |
| 3 | 逐生上传传姓名、草稿键是 workAnswerId | `only` 过滤仍命中该生 |
| 4 | taskId 给错但 alt 有正确值 | 兜底读到 |
| 5 | 确实没跑批阅 | 返回带 `scope` 的可读错误，而非只有一句“无草稿” |
| 6 | 逐生 + 批量上传 | 都带 `classDir/taskId` |
| 7 | 回归 | 全量 pytest 1842 passed；selfcheck:d188–d201 通过 |

## 4. 范围

允许：`engine/src/assist/xxt/cli.py`、`engine/src/assist/serve.py`、
`app/src/lib/engineClient.ts`、`app/src/components/AiGradingPanel.vue`、
`app/package.json`、对应 tests、本文档与 README 索引。
不得改评分口径；不得读取真实学生数据。

## 5. 实施结果

- `cli.py`：`--class-dir` / `--task-id`、自动反查、`alt_task_ids`、无草稿时回显 `scope`；
- `serve.py`：上传端点透传两个 scope 参数；
- 前端：逐生/批量上传都带 `classDir + taskId`；
- 测试：`engine/tests/test_d201_upload_draft_scope.py`（6 项）+ `selfcheck:d201`。

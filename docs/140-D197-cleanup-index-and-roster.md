# D197：清理多余报告后版本列表仍显示 106 条（索引未按本次名单核对）

> 日期：2026-11-18
> 状态：**已完成（2026-11-18）**
> 关联：`docs/138-D195-report-scope-and-duplicate-students.md`、
> `docs/139-D196-upload-submitted-only-and-per-student.md`
>
> 隐私：测试只用合成数据（学生001… / 旧生001…）。

---

## 0. 现场

- 点「🧹 清理多余报告」有弹窗，但**不知道操作是否完成**；
- 「🕘 报告版本」仍显示 **106 条**记录；
- 本次作业包实际作答学生只有 **57 名**（逐生审核处读取到的名单）。

## 1. 根因（两个）

### A. 清理只删文件，从不清理版本索引

`report_versions.cleanup_reports()` 原实现只做两件事：

1. 删 `reports/` 下不在名单的 `md/html/png`；
2. 删 `.versions/<学生>/` 目录。

**`.versions/index.json` 完全没动**。而「报告版本」面板读的正是这个索引 →
所以文件删了、索引里 106 条记录一条不少，看起来“清理没生效”。

### B. 空名单时静默不删

旧代码 `if keep and stem not in keep:` / `if not keep: continue`：
当 `keep_students` 为空（前端还没读到学生清单）时，**什么都不删也不报错**，
教师以为清理成功。

### C. 名单确实被“固定”了

索引是**追加式**的：历次生成（不同作业包、不同批次、按 workAnswerId/姓名两个键）
都会往同一份 `index.json` 里写，且从不按“本次作业提交名单”核对 → 记录越积越多。
这与教师判断一致：**过往名单被固定下来了，没有按该次作业提交名单核对**。

## 2. 修复

### R1. 新增 `prune_index()`：索引按名单核对

```python
prune_index(reports_dir, keep_students=[...], drop_missing_files=True)
# → {before, after, count, removed:[{student, version, reason}]}
```

- 删除 `student` 不在本次名单的所有条目；
- 删除“声明的历史文件已全部不存在”的孤儿条目；
- 只改索引，不动报告文件。

### R2. `cleanup_reports()` 同步清理索引 + 拒绝空名单

- 有 `keep_students` 才允许执行；空名单直接返回
  `缺少本次名单（keep_students 为空）：请先在「逐生审核」读取学生清单后再清理`；
- 返回新增 `indexBefore / indexAfter / indexRemoved / indexRemovedItems`；
- **dry-run 不再写索引**（旧实现这里会误写盘）。

### R3. 版本查询按名单过滤 + 报告孤儿数

`POST /xxt/grade/report-versions` 支持 `students`：

```json
{"count": 57, "totalInIndex": 106, "orphanCount": 49, "keptByRoster": true, "items": [...]}
```

面板提示：
> 报告版本：57 条（索引共 106 条；其中 49 条不属于本次名单，可点「🧹 清理多余报告」）

### R4. 前端：明确“是否完成”

新流程：

1. **先 dry-run 统计**（不删任何东西）→ 弹窗列出
   `报告文件 N 个 / 版本索引 106 → 57 条`；
2. 教师确认后才真删；
3. 完成后显示**持久结果卡**：
   - 标题 `清理完成`；
   - `报告文件 N 个 · 版本索引 106 → 57 条`；
   - 逐项列出被删文件/目录及原因（最多 40 项）；
   - 自动刷新「报告版本」与生成进度；
4. 名单为空时前端直接拦截，不发请求。

## 3. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 索引 106 条、名单 57 人 | 清理后索引 **57 条**，`indexBefore=106` |
| 2 | dry-run | 不删文件、**不改索引**，只返回预告数字 |
| 3 | 名单为空 | 返回 `ok:false` 并提示先读取学生清单；一个文件都不删 |
| 4 | 历史文件已丢的孤儿条目 | `prune_index` 一并清掉 |
| 5 | 名单内学生的多版本历史 | 全部保留（不只看最新一条） |
| 6 | 清理后查看版本 | 面板显示“索引共 X 条 / 孤儿 Y 条” |
| 7 | 回归 | 全量 pytest 1809 passed；selfcheck:d188–d197 通过 |

## 4. 范围

允许：`engine/src/assist/grading/report_versions.py`、`engine/src/assist/serve.py`、
`app/src/lib/engineClient.ts`、`app/src/components/AiGradingPanel.vue`、
`app/package.json`、对应 tests、本文档与 README 索引。
不得改评分口径；不得读取真实学生数据。

## 5. 实施结果

- `report_versions.py`：`prune_index()`、`cleanup_reports()` 同步索引、空名单拒绝、
  dry-run 不写盘；
- `serve.py`：`report-versions` 支持 `students` 过滤，返回 `totalInIndex/orphanCount`；
- 前端：dry-run → 确认 → 执行 → 结果卡（含索引前后条数）→ 刷新版本/进度；
  名单为空直接拦截；
- 测试：`engine/tests/test_d197_cleanup_index_and_roster.py`（8 项）+ `selfcheck:d197`。

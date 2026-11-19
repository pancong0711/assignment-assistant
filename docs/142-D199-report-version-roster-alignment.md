# D199：报告版本必须以「逐生审核」名单为基准（57 人，而不是另一份 53 人名单）

> 日期：2026-11-18
> 状态：**已完成（2026-11-18）**
> 关联：`docs/140-D197-cleanup-index-and-roster.md`、`docs/141-D198-version-records-vs-students.md`
>
> 隐私：测试只用合成数据（学生甲/学生乙）。

---

## 0. 现场

- 逐生审核显示 **57 名学生**，作答图片也是 57 份；
- 但「报告版本」只显示 **53 人**——两处名单不一致，教师无法判断谁漏了。

教师判断正确：**报告版本应该按逐生审核的名单核对，不应是另一份名单。**

## 1. 根因（两个叠加）

### A. 草稿没有 `student` 字段 → 报告用 `workAnswerId` 当学生名

`render_reports_from_drafts()` 原逻辑：

```python
student = str(d.get("student") or key)   # key 可能是 wa_2001
```

当草稿缺 `student` 时，报告文件名与版本索引里都是 `wa_2001`，而不是“学生乙”。
按逐生审核名单（姓名）过滤时，这几个学生就被排除了 → 57 变 53。

实测复现：索引 `['学生甲', 'wa_2001']`、报告文件 `wa_2001.md`。

### B. 版本面板只列“索引里有的学生”

面板直接渲染索引记录，**没有按名单补齐“未生成报告”的人**。
即使索引完全正确，只要有学生没生成报告，人数就天然少于名单，且看不出来缺谁。

## 2. 修复

### R1. 报告按**学生姓名**命名

`drafts.student_name_map(ws, class_id, work_id, task_id, class_dir, plan=None)`：

- 来源优先级：调用方 plan → 批阅下载清单 `students.json` → `plan.json`；
- `render_reports_from_drafts()` 解析姓名：`d.get("student") or name_map.get(key) or key`；
- 回写草稿时补上 `student` 字段（历史草稿自愈，下次不再依赖映射）。

效果：报告文件 `学生乙.md`，索引 `student: "学生乙"`。

### R2. 版本面板以逐生审核名单为基准

`POST /xxt/grade/report-versions` 新增 `keyToName`（逐生审核名单的 key→姓名），返回：

```json
{"rosterCount": 57, "reportedCount": 53, "missingReport": ["学生丙", ...],
 "roster": [{"student": "学生甲", "hasReport": true, "versionCount": 2,
             "version": "ab12cd", "tag": "...", "at": "...", "kind": "ai", "score": 88},
            {"student": "学生丙", "hasReport": false, "versionCount": 0}],
 "unmatched": ["旧生甲"], "totalInIndex": 106, "historyRecords": 53}
```

- 旧索引里的 `wa_xxx` 通过 `keyToName` 归一成姓名（并保留 `studentRaw` 供排查）；
- 面板表格改为**逐生**：`已生成 / 未生成`，未生成的显示 `—`；
- 顶部提示：`逐生审核名单里有 N 名学生还没有报告：… → 点「📄 一键生成批阅报告」补生成`；
- 标题：`名单 57 人 / 已生成 53 人 / 未生成 4 人 · 版本记录 106 条`。

## 3. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 草稿缺 `student`，清单里有 `wa_2001→学生乙` | 报告命名 `学生乙`，索引记录姓名 |
| 2 | 报告生成后 | 草稿 `student` 字段被回填 |
| 3 | 名单 57 人、只有 53 人有报告 | 面板显示 `名单 57 / 已生成 53 / 未生成 4` 并列出名单 |
| 4 | 旧索引含 `wa_xxx` | 通过 key→姓名 归一后算作已生成 |
| 5 | 索引里有名单外的姓名 | 顶部提示“可点「🧹 清理多余报告」” |
| 6 | 回归 | 全量 pytest 1825 passed；selfcheck:d188–d199 通过 |

## 4. 范围

允许：`engine/src/assist/grading/drafts.py`、`engine/src/assist/serve.py`、
`app/src/lib/engineClient.ts`、`app/src/components/AiGradingPanel.vue`、
`app/package.json`、对应 tests、本文档与 README 索引。
不得改评分口径；不得读取真实学生数据。

## 5. 实施结果

- `drafts.student_name_map()` + 报告按姓名命名 + 回填 `student`；
- `report_versions_view(..., key_to_name=)`：名单基准 `roster`、`missingReport`、
  `unmatched`、`reportedCount`；
- 前端版本面板改为逐生状态表（已生成/未生成），并提示缺失学生与补齐入口；
- 测试：`engine/tests/test_d199_report_roster_alignment.py`（6 项）+ `selfcheck:d199`。

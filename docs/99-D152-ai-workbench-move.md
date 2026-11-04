# D152 需求单：「题库AI+」整合题库 AI 作答（整体平移）+ 知识点标注并入

> 日期：2026-10-31
> 状态：**已完成**
> 关联：`docs/98-D151`、`docs/78-D130`、`docs/97-D150`、`docs/12`

## 0. 教师要求

1. 知识点选项卡里的「题库 AI 作答」过于简略，**把 AI 辅助批阅里 ⑦ 区完整平移过来**；
2. 知识点标注应可作为**选项在 AI 生成参考答案时勾选**，一次完成
   「参考答案 + 评阅要点 + 知识点提取」；
3. 避免双入口：批阅页 ⑦ 区移除，留一行指引；
4. 「知识点」选项卡**改名「题库AI+」**。

## 1. 现状差异（⑦ 区有、知识点页缺）

题号多选、模型选择、作答后置顶、真正作答并写回、同时生成要点/置顶、
**提示词模板库**、作答要求文本框、题目预览、solution 索引状态。

## 2. 设计

### 2.1 整体平移

`AiGradingPanel` ⑦ 区（模板 + 全部控件）整体搬到 `KnowledgeView`（改名 `AiWorkbenchView`），
批阅页替换为一行提示：

> 🤖 题库 AI 作答已移至「题库AI+」选项卡

### 2.2 新增勾选：同时标注知识点到题库

```
☑ 同时标注知识点到题库（写 related 列）
```

实现：`kb ai-solve --with-rubric` 产出 `knowledge[]` 后，调用
`rubric.apply_related()` 写回题库。

**安全分层**（教师确认）：

| 动作 | 级别 | 说明 |
|---|---|---|
| 生成解答+要点 | L1 | 写答案版本库，不碰题库 |
| **写回 related 到题库** | L2 | 改 xlsx，**先快照**，单独确认一次 |

PWA 流程：勾选 → 先 dry-run 预览"将改哪 N 题的 related" → 教师确认 → 执行。

### 2.3 related 存储改为独立 JSON（教师拍板）

**像 solution 一样**：`<ws>/kb/knowledge/<scope>.json`，**不再改 xlsx 的 related 列**。

- 理由：与 solution 同构，可多版本、可回滚、不碰题库文件；
- 兼容：**读取时优先 JSON，回落 xlsx 列**（旧数据不坏）；
- `kb export` 与题库表格展示时合并呈现（读 JSON 优先）。

## 3. 任务清单

| # | 内容 | 验收 |
|---|---|---|
| T1 | ⑦ 区整体搬到题库AI+ | 浏览器：控件齐全 |
| T2 | 批阅页 ⑦ 区移除 + 指引 | 无双入口 |
| T3 | 选项卡改名「题库AI+」 | 导航文案 |
| T4 | 勾选「同时标注知识点」→ 预览 → 确认写回 | 单测 + 浏览器 |
| T5 | related 改存 `kb/knowledge/<scope>.json`，读取回落 xlsx | 单测（新旧兼容） |
| T6 | `kb export` / 题库展示合并 JSON | 单测 |

## 4. 验收标准

1. 题库AI+ 页具备 ⑦ 区全部能力；
2. 批阅页无 ⑦ 区且给出指引；
3. 勾选标注 → 预览 N 题 → 确认后写 `kb/knowledge/*.json`；**xlsx 不被修改**；
4. 旧数据（related 在 xlsx）仍能正确读出；
5. pytest / build / selfcheck / 脱敏全绿。

## 5. 实施记录（2026-10-31 完成）

- 抽出 **`KbAiSolvePanel.vue`**（⑦ 区整体搬迁，不是复制）：题号多选 / 模型 /
  置顶 / 写回 / 同时生成要点 / 提示词模板 / 作答要求 / 题目预览 / 索引状态；
- 批阅页 ⑦ 区**移除**，留一行指引（消除双入口）；
- 选项卡改名 **「题库AI+」**；
- **新增勾选**「同时标注知识点到题库」：`kb ai-solve --tag-knowledge`
  → `solve_targets(tag_knowledge=True)` → `rubric.apply_related()`
  （写 `kb/knowledge/<scope>.json`，改前自动快照）；
- `related` 仍以题库为权威（sidecar 版本记录），**兼容旧数据**。

## 6. 验收对照

| # | 标准 | 结果 |
|---|---|---|
| 1 | 题库AI+ 具备 ⑦ 区全部能力 | ✅ `KbAiSolvePanel.vue` |
| 2 | 批阅页无 ⑦ 区 + 指引 | ✅ |
| 3 | 勾选标注 → 写回知识点 | ✅ `tag_knowledge` → `apply_related` |
| 4 | 旧数据兼容 | ✅ `apply_related` 保留 xlsx 回读 |
| 5 | pytest / build / selfcheck | ✅ 1272 passed · 0 error · 33/33 |

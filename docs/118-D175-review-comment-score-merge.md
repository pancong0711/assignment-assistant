# D175 需求单：逐生「批阅」无变化 + 改批语改分数保存无效 → 批语/分数一体化

> 日期：2026-11-16
> 状态：**已完成**
> 关联：`docs/116-D171`（三键 + 评阅落草稿）、`docs/117-D174`（三键语义确认）

## 0. 教师反馈

> 1. 测试逐生批阅里的「批阅」键，点击后**没有任何变化**，点审核看不到批语，也没有打分，
>    请确认代码是否功能完整。
> 2. 修改 AI 批语并另存，再修改分数点保存**没有变化**。之前讨论过好像没修复成功。
>    人工部分单独列出功能区、有勾选，教师想"改一下 AI 批语另存后作为作业批语，并修改分数"，
>    好像没有实现这样想法的功能键。需要仔细设计：**人工修改与 AI 批语如何结合**。

---

## 1. 问题一：「批阅」键点了没变化 —— 三段链路各自的缺口

### 1.1 引擎侧（复现结果：**正常**）
用真实 `run_task(steps=["evaluate"], students=["张三"], force=True)` 复现：
`evaluations/张三.json` 有 `total_score=100` + `feedback_md`，
`_persist_evaluations_to_drafts` 写入 `grading/<packId>/drafts/<workId>.json` 的
`ai.{score, comment}`，`aiState()` 因此显示「已评阅」。
→ **评阅本身确实是"出批语 + 打分"**（D171-T2 已修静默跳过与静默落草稿失败）。

### 1.2 找不到批语/分数的真实原因
| # | 位置 | 缺陷 | 修复 |
|---|---|---|---|
| A | 列表「分数」列 | 只显示 `ai.score`，教师在审核里改的分**看不见** → "改了没变化" | 新增 `finalScoreOf()`：显示**生效分**（人工优先），并标注「AI 85」 |
| B | 上传（`--from-drafts`） | `read_drafts` **未归一化** + `drafts_to_payloads` 只读**顶层** `score/comment`（双套结构里根本没有）→ **上传分数/批语恒为空** | 读取改 `read_drafts_normalized`；新增 `resolve_draft_effective()` 统一解析 |
| C | 报告生成 | `_mode_report_md` 只打印 **AI 分**，`humanMode=none` 时人工改的分不体现 → 报告与上传不一致 | 人工套有分数即显示「评分 76（人工改分；AI 原分 85）」 |
| D | 报告图回写草稿 | 漏传 `ws/class_dir/task_id` → 落到**旧布局** `<xxt_home>/grade-drafts/...`，与刚读的 scoped 草稿不是同一份 → 报告预览永远"未生成" | 回写带同一 scope |
| E | 旧「作业预览」页保存人工批阅 | 写**旧单套顶层** `score/comment`，与双套 `ai/human` 叠在同一份草稿里（混合结构） | 改写 `human` 套 + `humanMode=replace` |

> 结论：**"批阅键功能不完整"是真的**——不是模型没出分数，而是**分数/批语在下游三处（列表、上传、报告）没被读出来**。

---

## 2. 问题二：改批语 + 改分数保存无效 —— 根因与重新设计

### 2.1 根因（旧交互）
```
修订版（上方）  → saveRevisionOnly()：只写 revision.text
人工批阅（下方）→ save()：humanMode === 'none' 时**不写 human**（分数被丢弃！）
报告             → 只打印 AI 分
上传             → 只读顶层 score（空）
```
加上 D170-T4 的 `justSaved` 旗标：保存后 `emit('saved')` → 父级重拉草稿 →
`watch` 有时把输入框回填成旧值 → 教师看到"分数弹回去/没变化"。
**没有一个键能表达"我改的批语 + 我改的分数，一起发出去"。**

### 2.2 设计：**一份批语 + 一个分数 = 你要发给学生的东西**
| 控件 | 行为 |
|---|---|
| ✍ **最终批语** | 默认 = AI 原文；点「✏ 在 AI 批语基础上修改」→ 编辑 →「✓ 应用到批语」 |
| 分数 | **最终分数**，默认 = AI 分；旁边写明来源（AI 分 / 已保存人工分） |
| **批语与 AI 的关系（三选一）** | **✏ 修订 AI（标红改动）**（默认，写 `revision.text`）／ **➕ 追加到 AI 之后**（`humanMode=append`，AI 原文 + 教师补充）／ **↩ 完全替代 AI**（`humanMode=replace`，纯人工） |
| 💾 **保存（批语 + 分数一起）** | **永远同时写批语与分数**；改批语写 `revision`，分数写 `human.score` |
| 👁 **预览将发出的报告** | 调 `/xxt/grade/draft/preview`（**不写盘**），显示最终 markdown —— 确认后再保存 |
| ↩ 恢复 AI 原文 / 仅存修订版 | 高级用法，保留 |

**统一口径**（三处必须一致，已用测试锁死）：
```
最终分数  = human.score（有人工分就优先） 否则 ai.score
最终批语  = replace → human.comment
            append  → ai.comment + 【教师补充批语】+ human.comment
            revise / 有修订版 → revision.text
            否则 → ai.comment
```
`report._mode_report_md`、`grade_upload.resolve_draft_effective`、
`drafts.build_draft_report`（预览）共用上述口径。

> **D175b 补充（按评审建议）**：原方案把「追加到 AI 之后」收成了一个勾选，
> 但报告侧本来就支持三种构成。现改为**三选一**按钮组，教师可显式选择
> 「修订 AI / 追加到 AI 之后 / 完全替代 AI」，不再丢功能。

### 2.3 新增接口
`POST /xxt/grade/draft/preview`（`serve.py`）：
请求体与保存相同（可带**未保存**的编辑值），返回 `{markdown, kind, revised, effective}`。
预览与保存后的批量报告都走 `build_draft_report()` → **逐字一致**（有测试）。

---

## 3. 验收

| # | 标准 | 验证 |
|---|---|---|
| 1 | 只改分数、不勾替代 → 报告与上传都是人工分 | `test_report_shows_human_score_without_replace` / `test_report_and_upload_agree` |
| 2 | 双套草稿上传不再为空 | `test_upload_payload_reads_dual_set_draft` |
| 3 | 旧单套草稿仍兼容 | `test_upload_payload_legacy_single_set_still_works` |
| 4 | 报告图回写同一 scope | `test_render_reports_from_drafts_writes_same_scope` |
| 5 | 预览 == 保存后报告 | `test_preview_matches_saved_report` |
| 6 | 保存一定写分数（不再 mode=none 丢弃） | `selfcheck-d175-review-save.mjs` |
| 6b | 三种构成（修订/追加/替代）都可选，且报告与上传一致 | 同上 + 真实 HTTP 联调 |
| 7 | 列表显示生效分并标 AI 原分 | 同上 |
| 8 | 真实 HTTP：预览/保存/读回/上传口径一致 | 手工联调（本机 8799 端口） |
| 9 | 四道门 | pytest **1591** · build 0 error · selfcheck **42/42** |

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


---

## 4. D175b 回归：改批语「看不见 / 不能继续改」（第 21 轮反馈）

### 4.1 现象
> 点「保存（批语+分数一起）」没有效果；点「继续修改」删除/修改后「应用到批语」
> 没有效果，又恢复之前的版本，似乎已修改的批语无法继续修改。

### 4.2 定位方法
真实 Chromium 挂载 `StudentReviewModal` + 抓包（不是靠读代码猜）：

```
应用后屏幕含新批语?  False     ← 但「恢复 AI 原文」按钮已出现，说明 finalComment 确实更新了
「继续修改」键存在?  False     ← 按钮文案按 savedRevision 判断
再次编辑框内容:      'AI 原文…' ← 回退旧版本
保存请求:            /xxt/grade/draft {human_mode:none, human:{score}, revision:{text:新批语}}  ← 请求本身正确
```

### 4.3 三个根因（都是前端状态绑定，不是保存链路）
| # | 根因 | 后果 |
|---|---|---|
| A | 只读区 `v-html="aiCommentHtml"`，该 computed 只读 `aiSet.comment` | 改了、存了都**看不见**新批语 |
| B | `finalCommentNow` 只取 `savedRevision \|\| aiOriginal`，漏了本地 `finalComment` | 再点「继续修改」**回退旧版本** |
| C | 「继续修改」文案只看 `savedRevision`（未保存的修改不算） | 键一直显示「在 AI 批语基础上修改」 |

### 4.4 修复
- 新增 `finalCommentHtml`（渲染**当前最终批语**），只读区改绑它；
- 新增 `commentChanged`：与 AI 原文不同即视为"已修改"，提示「已修改（尚未保存）」；
- AI 原文改为**折叠对照**（`对照 AI 原文（N 字，只读）`），不再抢占主显示；
- `finalCommentNow` 优先 `finalComment`；「继续修改」文案认 `commentChanged`；
- KaTeX 重新渲染跟随 `finalCommentHtml`。

> 踩坑记录：`watch([... computed ...])` 在创建时**立即读取**依赖，
> 因此新 computed 必须声明在 watch 之前，否则 `Cannot access … before initialization` 白屏。
> 自检里已用 `watch 必须晚于 finalCommentHtml 声明` 断言锁死。

### 4.5 验收
| 标准 | 验证 |
|---|---|
| 应用后屏幕出现新批语 | 浏览器实测 True |
| 「继续修改」存在且编辑框是新内容 | 浏览器实测 True |
| 保存 + 父级刷新后仍显示新批语 | 浏览器实测 True |
| 静态结构防回退 | `selfcheck-d175b-comment-edit.mjs` |
| 四道门 | pytest 1591 · tsc 0 · build 0 · selfcheck **43/43** |


---

## 5. D175c 回归：改了分数后「保存」点了没反应（第 22 轮反馈）

### 5.1 现象
> 提示有未保存改动，但是点击保存（批语+分数一起）没效果。
> 操作顺序：点了「恢复 AI 原文」→「继续修改」→ 改动部分内容 →「应用到批语」→
> 再修改最终分数 → 点保存无效。

### 5.2 定位（浏览器实测）
只做一件事就复现——**改分数 → 点保存**：

```
请求数: 0
页面错误: ['finalScore.value.trim is not a function']
仍显示未保存提示? True
```

### 5.3 根因
`<input type="number" v-model="finalScore">` — Vue 3 对 `type="number"` 会**自动**
把输入转成 `number`；而 `save()` / `buildPayload()` 里写的是
`finalScore.value.trim()` → 抛 `TypeError`，异常**冒泡未捕获** →
请求根本没发出、`dirty` 仍为 true → 表现为"点了没反应"。

> 为什么之前测试没发现：`fillFromDraft()` 用 `String(...)` 赋值时是字符串，
> 不碰分数输入框就一路正常；**只要教师手动改过一次分数**就必现。

### 5.4 修复
- 分数输入改为 `:value` + `onScoreInput()`，**始终保存原始字符串**；
- 新增 `rawScore()` / `parseScore()` 统一解析（空 → null，非法 → NaN）；
- `save()` 先校验分数再组装 payload；`buildPayload()` 也用 `parseScore()`；
- `save()` / `doPreview()` 都加 `catch`，把异常写进 `msg` ——
  任何错误都必须给教师**可见反馈**，不允许再"静默无反应"。

### 5.5 验收（浏览器实测）
| 场景 | 结果 |
|---|---|
| 仅改分数 → 保存 | 请求 1 条，`human.score=72`，无报错 |
| 恢复原文 → 继续修改 → 改内容 → 应用 → 改分数 → 保存 | 请求 1 条，`score=68` + `revision.text=新批语`，无报错 |
| 静态防回归 | `selfcheck-d175c-score-input.mjs` |
| 四道门 | pytest 1591 · tsc 0 · build 0 · selfcheck **44/44** |

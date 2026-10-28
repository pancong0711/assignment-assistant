# D111 任务需求单：题库题号全局唯一（自动章节前缀）+ 遗留问题收口

> 日期：2026-10-28
> 状态：**已执行**（2026-10-28）；需求单 + 实施记录
> 关联：`docs/62-D110-solution-scope-preview-parity.md`（D110 已做的存储层隔离）
> 背景：D110 用「作用域文件名」隔离了跨章同号题，但**数据层 id 仍不唯一**，
> 只是绕开症状。用户拍板：**题库 id 应全局唯一，自动加章节前缀**。

## 0. 问题是否都已从代码中发现（审查结论）

| # | 用户反馈 | 代码定位 | 结论 |
|---|---|---|---|
| 1 | 同号不同章的答案一样 | `files/solutions.py:_path()` 只用 `qid`；`kb_io.read_xlsx` 不校验唯一 | ✅ 已发现（D110 临时隔离） |
| 2 | 没点全库却刷了全库 | `grading/solve.py:list_targets(chap="", ids=[])` 遍历整库；serve/CLI 无守卫 | ✅ 已发现（D110 已加 `--all`） |
| 3 | 置顶答案预览：文字截断 | `katexRender.ts` force 重渲染 `el.textContent = original` 抹掉标签 | ✅ 已发现（D110 已改 innerHTML） |
| 4 | 连续多行虚线 | `.q-solution{border-top:1px dashed}` 对每个续段块都渲染 | ✅ 已发现（D110 已加 `q-sol-first`） |
| 5 | 未见示意图 | ①同上 textContent 抹掉 `<svg>`；②D109 `nl2br` 往 svg 塞 `<br>`；③D109 排版按行拆 svg | ✅ 已发现（D109+D110 已修） |
| 6 | **id 全局唯一** | 无任何唯一性校验；真实题库实测 `01` 在 **9 个章节**重复 | ⚠️ **本轮新增任务** |

补充审查（本轮新发现，一并纳入）：

| # | 问题 | 代码位置 | 影响 |
|---|---|---|---|
| 7 | 题库 id 撞号时**无任何提示** | `kb_io.read_xlsx` / `kbXlsx.readKbXlsx` | 教师无感知，直到答案串味才发现 |
| 8 | `translation` 题库的合成 id 与真 id 空间混用 | `task.py:TRANSLATION_ID`、`sheetHtml.ts` | 合成题 id 可能撞真 id |
| 9 | 作业纸 `items[].ids` 存的是**裸 id** | `lib/taskpad.ts:TaskpadItem.ids` | id 加前缀后，历史作业纸会**全部失配** |
| 10 | `labels` 覆盖表按裸 id 索引 | 同上 `labels?: Record<string,string>` | 同上，需迁移 |
| 11 | 批阅/报告按 qid 关联 | `grading/items.py:_clean_id`（要求唯一） | 加前缀后天然满足唯一性 |
| 12 | 跨章答案「同一份」在 UI 无警示 | `KbEditorView` 预览 | 加唯一性后可根治；迁移期给提示 |

## 1. 目标

1. **题库 id 全局唯一**：`<chap>-<原id>`（如 `chap04-01`）；导入/读取时自动补齐前缀；
2. **不破坏历史数据**：已有 xlsx 与作业纸任务包要么自动迁移，要么双读兼容；
3. **撞号可见**：导入时若发现跨章同号，明确告知"已自动加前缀"，并列出对照；
4. **答案版本库回归简单**：id 唯一后 `kb/solutions/<id>.json` 语义成立（保留 D110 作用域文件以兼容）。

## 2. 设计决策（待确认项已标注）

### D1 前缀格式：`<chap>-<id>`

- 例：chap04 的 `01` → `chap04-01`；
- 已带前缀（`chapXX-` 开头）的 id **不重复加**（幂等）；
- 字符集：`[0-9A-Za-z_\-\u4e00-\u9fff.]`，长度 ≤ 120（与 `solutions._QID_RE` 对齐）；
- 章节名含非法字符时，前缀部分做安全化（`/`→`-`），保证可直接当文件名。

**待确认**：是否需要保留"原 id"用于显示？→ 方案：`note` 或新增只读展示用派生值，**不改 xlsx 列结构**。

### D2 迁移时机：读时补齐 + 写时落盘（惰性迁移）

| 层 | 行为 |
|---|---|
| 引擎 `read_xlsx` | 读出后按 sheet 名补前缀（幂等），仅内存；`assist kb normalize` 才写回 xlsx |
| PWA `readKbXlsx` | 同上（与引擎**同一函数语义**，parity 哨兵护航） |
| `assist kb write` / PWA 写回 | 落盘时写已带前缀的 id（一次性完成迁移） |
| 作业纸任务包 | `items[].ids` 载入时按 `chap` 补前缀（若未带）；`labels` 键同步迁移 |

**理由**：不强迫教师先跑迁移命令；老文件打开即正确。

### D3 兼容读取（双读）

- 读答案版本库时，`qid` 先按新 id 找；找不到再尝试**去掉前缀**的裸 id（仅当该裸 id 唯一时才用）；
- 作业纸的 `ids` 若为裸 id，按 `item.chap` 补前缀后再匹配（见 D2）。

### D4 撞号处理

- 同一 xlsx **同一 sheet 内**重复 id → **报错**（`normalize` 输出冲突清单，不静默改名）；
- 跨 sheet 重复 → 自动加前缀后自然消失；若加前缀后仍重复（如原 id 已含别的章前缀）→ 报错并要求人工处理。

## 3. 任务分解

| # | 任务 | 文件 | 验收 |
|---|---|---|---|
| T1 | 引擎 `scope_question_id(chap, qid)` + `normalize_ids(chapters)` 纯函数 | `files/kb_io.py` | 单测：幂等、非法字符、跨章唯一 |
| T2 | `read_xlsx` 应用前缀；`read_kb` 全量唯一性检查 | `files/kb_io.py` | 单测：读入即带前缀 |
| T3 | `assist kb normalize [--dry-run] [--write]`：报告冲突 + 写回（保留样式） | `cli.py` | CLI 单测 + 快照 |
| T4 | PWA `readKbXlsx` 同语义加前缀；`kb.ts` 加唯一性检查提示 | `lib/kbXlsx.ts`、`stores/kb.ts` | parity 自检 |
| T5 | 作业纸 `items[].ids` / `labels` 迁移（载入时补 `item.chap` 前缀） | `lib/taskpad.ts`、`stores/taskpad.ts` | 自检：老任务包可打开且题目不丢 |
| T6 | 答案版本库兼容读取（新 id 优先，裸 id 唯一时回退） | `files/solutions.py` | 单测 |
| T7 | 文档：`docs/05` 决策、`docs/04` 数据契约、使用手册「题号规范」 | docs | 更新 |
| T8 | 回归：`sheet html` / 批阅 / 报告 全链路 | tests | 603+ 全绿 |

## 4. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 历史作业纸 ids 失配 | T5 载入时补前缀；`labels` 同步迁移；迁移前 `kb/.history` 快照 |
| 已存在的答案版本库文件名 | D3 双读；不删旧文件；`assist kb normalize` 可选搬迁 |
| PWA 与引擎前缀逻辑漂移 | 同一纯函数 + parity 自检（照 D105/D109 惯例） |
| 教师在 xlsx 里手写带前缀 id | 幂等（已带则不重复加） |

## 5. 实施记录

### 5.1 落地内容

| 任务 | 实现 |
|---|---|
| T1 | `files/kb_io.py`：`safe_id_part()` / `scope_question_id(chap, qid)`（幂等）/ `normalize_question_ids()` / `find_duplicate_ids()` |
| T2 | `read_xlsx()` 读出即补前缀；`read_kb()` 全量查重并 `logger.warning` 提示 |
| T3 | `assist kb normalize [--write]`：默认 dry-run 报告；`--write` 前自动 `.history` 快照，样式保留写回 |
| T4 | `lib/kb.ts`：`safeIdPart` / `scopeQuestionId` / `findDuplicateIds`（与引擎同口径）；`readKbXlsx` 读入即补前缀 |
| T5 | `paper/task.py: item_id_matches()`：`ids` 同时兼容裸题号与全局 id；`resolve_items` / `_resolved_items_ref` / `grading.flow` / `solve.list_targets` 全部改用它。PWA `expandPadItems` 同时兼容，并把 `labels` 的裸 id / 全局 id 两种键都查 |
| T6 | 版本库按全局 id 存（D110 作用域文件名自然变成 `problems__chap04__chap04-01.json`）；旧裸 id 文件仍可回落读取 |
| T7 | 本文档 + `docs/04`/`25` 数据契约补记 |
| T8 | 回归见 §6 |

### 5.2 关键约定

- **前缀格式** `<chap>-<id>`，例：`chap04-01`；`chap04` 的 `demo-04-1` → `chap04-demo-04-1`；
- **幂等**：已带本章前缀不再重复加（往返读写稳定）；
- **安全化**：`/ \ : * ? " < > |` 与控制字符 → `-`，保证可直接作文件名；
- **不静默改名**：加前缀后仍冲突（同 sheet 重复 / 已含本章前缀的等价写法）→ 报告并要求人工处理。

### 5.3 执行中**新发现并修复**的问题

| # | 问题 | 说明 |
|---|---|---|
| N1 | `find_duplicate_ids` 漏检「同一 sheet 内重复」 | 初版按章节去重（`if cname not in chaps`），同表内 `[a,a]` 检不出；改为**按出现次数**计数 |
| N2 | 多处「按 id 过滤」是各自手写 | `_resolved_items_ref`、`grading/flow`、`solve.list_targets`、`_resolved_refs` 各自 `qid in want`，加前缀后**整包失配**；统一收口到 `item_id_matches()` |
| N3 | `summarize_solutions` 不补前缀 | 传入裸 id 时取不到生效答案摘要；改为先 `scope_question_id(sheet, id)` |

### 5.4 实测

| 项 | 结果 |
|---|---|
| 本地真实题库（不入库，仅本机验证） | 12 章 88 题 → **88 个唯一 id**（原先短题号如 `01/02/03` 跨 9 章重复）；`find_duplicate_ids` 返回空 |
| engine pytest | **613 passed**（新增 `test_d111_global_question_ids.py` 10 例） |
| app `vue-tsc -b` / `npm run build` | 0 error |
| app `npm run selfcheck` | 全绿（新增 `selfcheck-d111-global-id.mjs`） |
| CLI 端到端 | `kb normalize` dry-run 报告 `chap04-01`；`--write` 后 xlsx 落盘为 `chap04-01/chap07-01` |

### 5.5 迁移建议（教师侧）

```bash
assist kb normalize            # 先看报告：哪些题号会加前缀、有无冲突
assist kb normalize --write    # 确认后写回（自动 kb/.history 快照）
```

- **历史作业纸无需手工改**：`ids` 里的裸题号会按 `item.chap` 自动归一匹配；
- **旧答案版本库**（`<裸id>.json`）仍能回落读取；要彻底对齐可对相应题重新作答或手工搬迁；
- 题库 xlsx 的 `id` 列写回后会变成全局 id，若外部脚本依赖裸 id 需同步调整。

## 6. 文档更新清单

- `docs/63`（本文）：需求单 + 实施记录
- `docs/05-decisions.md`：新增 D111 决策条目
- `docs/04-data-model-and-privacy.md`：题号全局唯一约定
- `docs/15-usage-manual.md`：题号规范与 `kb normalize` 用法
- `docs/60`/`docs/61`/`docs/62`：相关缺陷修复交叉引用

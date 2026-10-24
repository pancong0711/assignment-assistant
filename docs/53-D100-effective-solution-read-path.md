# D100 任务需求单：参考答案「生效版」读取链路收口（AI 作答 → 题库 → 作业纸）

> 日期：2026-10-24
> 状态：**T1–T8 全部完成**（实现 + 测试见本文末尾「验收」）
> 关联：`docs/42-D89-pack-and-solution-versions.md`（solution 多版本库的设计与承诺）、
> `docs/39-D86-ai-grading-tab.md`（AI 选项卡）、`docs/46-D93-...`（`expandPadItems` 合成题）、
> `docs/04`（数据模型）、`docs/05-D3`（xlsx = source of truth）

## 1. 问题来源（2026-10-24 用户反馈）

1. 用「AI 辅助批阅 → 题库 AI 作答（写回）」生成答案后，回到题库编辑器，**solution 单元格显示空**；
2. 打开 🔍 预览能看到 AI 生成内容，但**需要手动置顶**才成为生效答案；
3. 到「作业纸设计」新建作业包 → 新建作业纸 → 添加该题，勾选「显示参考答案」后，
   **预览里看不到 AI 生成的答案**。

## 2. 根因（代码定位）

| # | 事实 | 位置 |
|---|---|---|
| R1 | AI 作答写入的是 `<ws>/kb/solutions/<qid>.json` 的 `versions[]`，**不动 xlsx `solution` 列** | `engine/src/assist/grading/solve.py:78-84` → `files/solutions.py:add_version` |
| R2 | 题库编辑器 solution 单元格是**同步渲染 xlsx 行**，从不查版本库 | `app/src/views/KbEditorView.vue:85-88`、模板 `:297` |
| R3 | AI 作答默认 `pin=false`（`--pin` 才置顶），版本库只有 latest 概念 | `engine/src/assist/cli.py:399`、`grading/solve.py:81` |
| R4 | 作业纸预览题帧**只读内存 kb 的 `r.solution`**，整条 PWA 出图链无 `effective_solution` | `app/src/lib/sheetHtml.ts:756-780`（`expandPadItems`）、`:528` |
| R5 | CLI `assist sheet html` 出图同样只读 xlsx `solution` 列（D89-N3 迁移时的**漏改**） | `engine/src/assist/paper/htmlfile.py:211-236` |
| R6 | 批阅侧是对的（`effective_solution`），所以「批阅看得到、作业纸看不到」 | `grading/flow.py:57-62`、`grading/inputs.py:64` |

> 结论：不是渲染小问题，而是「写入侧只写版本库 / 读取侧只读 xlsx 列」的**链路断裂**。
> `files/solutions.py:13` 的 docstring 已承诺「供作业包/批阅实时取最新置顶版」，但作业包出图链路没接。

## 3. 设计决策

| 项 | 决定 | 理由 |
|---|---|---|
| 单一读取入口 | 一切「参考答案」读取统一走 **`effective_solution(ws, qid, fallback)`**（TS 侧同名 `pickEffectiveSolution`），xlsx 列只做 fallback | 避免再出现第二套解析；与 `docs/42-D89` §3 决策一致 |
| 不镜像写 xlsx | **不**把 AI 答案回写 `solution` 列 | `docs/42-D89` 已拍板「不覆盖」；且 `App.vue` 启动 `restoreWorkspace()` 会用 xlsx 覆盖内存，镜像必被冲掉 |
| AI 作答默认置顶的语义 | AI 作答版本**追加后自动 pin**（等价人工「置顶」），但**不删不改**已有版本；仍可 `--no-pin` 关闭 | 用户诉求「AI 生成内容应默认置顶」；「不覆盖」依旧成立（版本可回滚） |
| 已 pin 的人工版是否被抢 | **抢**（AI 版成为新生效答案）。因为 AI 作答是教师主动发起的「重新生成」，old pin 语义已过期；旧版本仍在版本库可一键 pin 回 | 与「置顶 = 生效答案」语义一致，且可逆 |
| PWA 前端读取 | 新增 **`/kb/solutions`（无 qid）批量端点**，前端拉一次进内存索引，用于题库表格和作业纸题帧 | 避免每题一次 HTTP；一次刷新即可覆盖 |
| 缓存失效 | `kb.solutionsRev` 版本号：AI 作答完成后前端 `bumpSolutions()`；`expandPadItems` 结果纳入 `liveKey` | 预览必须能感知「刚生成完」 |
| 生效标识可视化 | 题库表格单元格显示「AI v3 ★ / AI v3（未置顶）」摘要；预览弹窗置顶操作保留 | 「显示空」不再误导 |
| 离线降级 | 引擎离线 → 索引为空 → 全部回落 xlsx 列（与现状一致），不报错 | PWA 纯前端可用的既有约束 |

## 4. 任务分解

| # | 任务 | 文件 | 验收 |
|---|---|---|---|
| T1 | `effective_solution` 支持「有版本但全未 pinned」时仍按最新版生效（已实现）；新增 `effective_map(ws)` 批量 | `engine/src/assist/files/solutions.py` | pytest：批量与单题一致 |
| T2 | `/kb/solutions` 批量端点返回 `{qid: effective}` 摘要（含 text/source/version/pinned/from） | `engine/src/assist/serve.py` | pytest：端点 shape |
| T3 | AI 作答默认 pin（`solve_targets(pin=True)` 默认，CLI `--no-pin` 显式关闭） | `engine/src/assist/grading/solve.py`、`engine/src/assist/cli.py` | pytest：`test_solve_apply_default_pins` |
| T4 | CLI `assist sheet html` 题帧改走 `effective_solution` | `engine/src/assist/paper/htmlfile.py` | pytest：pin 后 HTML 出现 AI 文本 |
| T5 | TS 侧 `pickEffectiveSolution(doc, fallback)` + `expandPadItems` 注入 `solOf` | `app/src/lib/sheetHtml.ts` | selfcheck：注入解析器生效 + 离线回落 |
| T6 | kb store 增加 solution 索引（`solIndex` / `solutionsRev` / `refreshSolutions()` / `bumpSolutions()`） | `app/src/stores/kb.ts`、`app/src/lib/engineClient.ts` | selfcheck：批量端点解析 |
| T7 | 作业纸四段（预览/输出/整班/变体 zip）全部接 `kb.effectiveSolution` | `SheetPreviewSection.vue`、`SheetOutputSection.vue`、`SheetDesignView.vue`、`RosterView.vue`、`variantBatch.ts`、`SheetContentView.vue` | selfcheck + build 0 err |
| T8 | 题库编辑器：单元格显示生效摘要（AI v3 ★/未置顶）；AI 面板作答完成后 `bumpSolutions()`；面板 `kbPin` 默认勾选 | `KbEditorView.vue`、`AiGradingPanel.vue` | selfcheck + 手动 |

## 5. 回滚方案

- 前端：`expandPadItems` 的 `solOf` 为可选参数，不传即回落 xlsx 列（旧行为）。
- 引擎：`/kb/solutions` 为**新增**只读端点，无副作用；AI 默认 pin 可通过 `--no-pin` / 请求体 `pin:false` 关闭。
- 数据：AI 版本只是追加，删除走既有 `kb solution rm`。

## 6. 验收记录

见 `docs/53` 末尾追加节 + 各测试用例名（engine pytest / app selfcheck）。

---

## 7. 实施记录（2026-10-24）

### 7.1 引擎侧

| 文件 | 改动 |
|---|---|
| `engine/src/assist/files/solutions.py` | 抽出 `_effective_of(doc, fallback)` 纯函数；`effective_solution` 增 `n_versions`/`ai_versions`；新增 `effective_map(ws)`（批量）与 `solutions_digest(ws)`；`add_version` 增 `pin_if_unpinned` |
| `engine/src/assist/grading/solve.py` | `solve_targets(pin=True)` **默认置顶**；docstring 同步 |
| `engine/src/assist/cli.py` | `--pin/--no-pin`（默认 `--pin`）；帮助文本与命令说明同步 |
| `engine/src/assist/serve.py` | `/kb/ai-solve` 的 `pin` 缺省改 true（`pin:false` 才加 `--no-pin`）；`GET /kb/solutions` 改返回 `{effective, digest}`（`?raw=1` 保留旧的 `items` 形态） |
| `engine/src/assist/paper/htmlfile.py` | `expand_items_html(..., ws=...)` 改走 `effective_solution`；`build_context` 传 `ws` —— 修复 `assist sheet html` 漏读版本库 |

### 7.2 PWA 侧

| 文件 | 改动 |
|---|---|
| `app/src/lib/sheetHtml.ts` | 新增 `pickEffectiveSolution(doc, fallback)`（与引擎同语义，含扁平批量条目）、`SolutionResolver`、`xlsxOnlySolutions`；`expandPadItems(pad, bookOf, solOf?)` 注入解析器；`SheetHtmlItem` 增 `solutionFrom/solutionVersion/solutionSource` |
| `app/src/lib/engineClient.ts` | 新增 `fetchKbSolutionIndex()`（`GET /kb/solutions`） |
| `app/src/stores/kb.ts` | state `solIndex` / `solutionsRev` / `solutionsMsg`；getter `effectiveSolution` / `solutionOf`；action `refreshSolutions()` / `bumpSolutions()` |
| `app/src/components/SheetPreviewSection.vue` | `expandPadItems(..., kb.effectiveSolution)`；`sheetHtmlItems` 显式依赖 `kb.solutionsRev`（作答完成后预览自动重建） |
| `app/src/views/SheetDesignView.vue` | ④段 `currentInput()` 注入生效解析器 |
| `app/src/views/RosterView.vue` | 整班预览两处 `expandPadItems` 注入生效解析器 |
| `app/src/lib/variantBatch.ts` | `ensureDefaultSheetHtmlProvider(kbBookOf, solOf?)` 透传解析器 |
| `app/src/views/SheetContentView.vue` | batch zip 生成时注入 `kb.effectiveSolution` |
| `app/src/views/KbEditorView.vue` | solution 单元格改显示**生效答案**摘要 + 来源徽标（`AI v3 ★` / `AI v3（未置顶）` / `人工 v1 ★` / `xlsx 旧列`）；🔍 按钮标识是否有版本库；追加/置顶/删除后 `kb.bumpSolutions()`；`onMounted` 拉一次索引 |
| `app/src/components/AiGradingPanel.vue` | `kbPin` 默认 **true**（界面文案「作答后置顶（默认）」）；作答写回完成后 `kbStore.bumpSolutions()`；说明文案改为"生效版"口径 + 索引状态回显 |
| `app/src/App.vue` | 启动时 `restoreWorkspace()` 后 `bumpSolutions()` |

### 7.3 测试

| 套件 | 用例 | 结果 |
|---|---|---|
| engine pytest（新增 `tests/test_d100_effective_solution_read_path.py`） | `effective_map` 与单题一致 / 空库 / digest；`solve_targets` 默认置顶、`pin=False` 保持原答案、`pin_if_unpinned`；CLI `--no-pin`；`sheet html` 用置顶 AI 答案 / 未置顶 latest 也生效 / 无版本回落 xlsx；`GET /kb/solutions` 批量与 `?raw=1` | **12 passed** |
| engine 全量 | — | **512 passed** |
| app selfcheck（新增 `tests/selfcheck-d100-solution-readpath.mjs`，已挂进 `npm run selfcheck`） | 优先级（pinned>latest>fallback>空）/ 注入解析器 / 离线回落 / 未置顶生效 / translation 合成题 | **通过** |
| app `vue-tsc -b` + `vite build` | — | **0 error** |
| 端到端（脚本） | 题库 xlsx + 桩 LLM → `solve_targets(apply)` → 版本库 pinned → `sheet_html_from_task` → HTML 含 AI 答案且不含 xlsx 旧列 | **✅** |

### 7.4 行为变化（需知会）

1. **AI 作答默认置顶**：以前需手动勾「作答后置顶」，现在默认勾选；CLI 对应 `--pin` 默认开，`--no-pin` 恢复旧行为。
2. **题库 solution 单元格不再显示"（空）"误导**：显示生效答案摘要 + 来源徽标；xlsx 列本身仍可能是空的（设计如此，`docs/42-D89`）。
3. **"未置顶"版本也会生效**：版本库有版本但全未 pinned 时，取最新版（`from=latest`，UI 标注"未置顶"）。这是本次"忘点置顶也能在作业纸看到"的兜底，与引擎 `effective_solution` 既有语义一致。
4. 引擎离线：索引为空 → 全部回落 xlsx `solution` 列（行为与 D100 前相同，不报错）。

### 7.5 未纳入本单

- `app/src/lib/variantBatch.ts` 若**先**注册过 provider（`if (sheetHtmlProvider) return`），后注册的 `solOf` 不会生效——当前只有 `SheetContentView` 一个调用点，无实际影响；未来多调用点时需改为"重注册或参数校验"。
- PDF 通道（`assist sheet make`）当前不渲染参考答案（与 `docs/42-D89` 现状一致），本单未改动。

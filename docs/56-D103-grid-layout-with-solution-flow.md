# D103 任务需求单：恢复 MxN 网格/虚线 + 参考答案跨格续写（教师版）

> 日期：2026-10-24
> 状态：**T1–T9 全部完成**（2026-10-24/25）
> 关联：`docs/55-D102-...`（本单**回滚** D102 的"单列流式"布局）、`docs/54-D101`（公式渲染）、
> `docs/13-D43`（参考答案开关）、`docs/14 §VB`（HTML 打印主通道）、`docs/46-D93`（合成题）

## 1. 背景：D102 是一次版式回归

D102 为"答案必须完整"把 `.sheet-body` 从 MxN 等分网格改成单列 flex 流，
导致 **MxN 版式控制权丧失**（实测横版 1×2 渲染成两题上下堆叠、各占满整宽、竖虚线隐藏）。
用户明确指出：**MxN 与全部虚线是作业纸样式的重要组成部分，必须保留**。

## 2. 用户拍板的需求（2026-10-24 三轮讨论）

| # | 需求 |
|---|---|
| R1 | **MxN 版式与所有虚线（横+竖）必须保留** |
| R2 | **同格不混排**：一格内只放一道题（或其答案续段），不把下一题塞进上一题答案的剩余空间 |
| R3 | 答案写满当前格 → **续写到下一页的第 1 格**（不是同页其它列） |
| R4 | 下一页第 1 格若已有题目 → 该题**顺延**，后面题目依次顺延 |
| R5 | **题干与答案必须全部显示**（不丢内容） |
| R6 | 公式**不切割**；横向超宽允许滚动/缩小 |
| R7 | **PWA 与 CLI 的 HTML 必须一致**（同一排版模型、同一产物结构） |
| R8 | PDF 通道：**每页一题 + 答案**，超出则续页，后续题目顺延（教师辅助用，不发给学生） |
| R9 | 带参考答案的 HTML 版式**默认只提供横版 1×2 与竖版 2×1**，其他版式自动降级 |
| R10 | 页码与虚线必须正确显示 |
| R11 | 续格加标注（如「题 1（续）」），便于教师辨认 |

## 3. 关键设计决策

| 项 | 决定 | 理由 |
|---|---|---|
| 计数单位 | **格（cell）**：每页 `per_page` 个格（带答案时 = 2） | 与既有 per_page 语义对齐 |
| 排版方式 | **静态预排版**：按格子容量把内容切段，生成固定的页/格结构 | CSS 无法表达"跨格续写"（实测三种纯 CSS 方案全部失败） |
| 测量来源 | **PWA 用真实 DOM 测量**，结果写入 taskpad `layout_result` | 测量必须精确；CLI 无法测量 |
| CLI 如何一致 | CLI **直接复用** `layout_result` 生成相同 HTML | 满足 R7，无浏览器依赖 |
| 内容变更 | PWA **自动重新排版**（防抖），并更新 `layout_result` | 避免陈旧排版 |
| 无 `layout_result` | 回退 D61 网格行为（可能裁切答案） | 兼容历史作业纸 |
| 切分点 | 段落边界 / 行间公式整体（`$$..$$`、`\[..\]` 不可切） | R6 |
| 超高公式 | `transform: scale` 缩到格高，标 `data-scaled` | R6 兜底 |
| 裁剪与续写 | 每格 `overflow:hidden`；超出部分进入下一页第 1 格 | R3 |
| 虚线 | 由格边界绘制（grid 的 `border`），随格走 | R1/R10 |
| 页码 | 预排版后每页独立 `.sheet-page`，页码准确 | R10 |
| PDF | 一题一页 + 完整答案，reportlab 自动续页 | R8（独立实现，允许与 HTML 版式不同） |

## 4. `layout_result` 数据契约（taskpad JSON 新增字段）

```jsonc
"layout_result": {
  "v": 1,
  "measuredAt": "2026-10-24T...",
  "engine": { "ua": "Chrome/1228", "font": "Noto Sans SC", "basePt": 10 },
  "geometry": { "cellW": 508, "cellH": 643, "pageW": 790, "perPage": 2 },
  "pages": [
    { "page": 1, "cells": [
        { "row": 0, "col": 0, "blocks": [{ "qid": "c1", "part": 1, "from": 0, "to": 1200, "cont": false }] },
        { "row": 0, "col": 1, "blocks": [{ "qid": "c2", "part": 1, "from": 0, "to": 400,  "cont": false }] }
    ]},
    { "page": 2, "cells": [
        { "row": 0, "col": 0, "blocks": [{ "qid": "c1", "part": 2, "from": 1200, "to": 2100, "cont": true }] }
    ]}
  ]
}
```

- `blocks[].from/to`：该题内容（题号+题干+答案拼接后的字符区间）
- `cont: true` → 渲染时加「（题 N 续）」
- 内容 hash 存 `contentHash`，与当前 items 不一致时视为失效

## 5. 排版算法（PWA 端）

```
输入：items[]（题号/题干/答案）、cellW/cellH、perPage（带答案时=2）
  1. 渲染每题为可测量 DOM（宽度 = cellW 内宽）
  2. 求每题总高 h_i（含公式/图片）
  3. 逐题贪心装箱：
       cursor = (page 1, cell 1)
       对每题：
         若 h_i <= 剩余格高 → 整题放入 cursor，cursor++
         否则 → 按「段落/公式边界」切段：
                 填满当前格 → 余段进「下一页第 1 格」（R3），后续题顺延
                 若单段（如整块公式）仍超格高 → scale 缩放
         格用尽 → 翻页
  4. 输出 pages[].cells[].blocks[]
```

## 6. 任务分解

| # | 任务 | 文件 | 验收 |
|---|---|---|---|
| T1 | **回滚 D102 布局**：恢复 MxN grid + 全部虚线（`.sf-line` 显示） | `sheetHtml.ts`、`assignment.html.j2`、`taskpad.ts`、`paper/grid.py` | 横版 1×2 两列并排、竖虚线可见 |
| T2 | 新增 `layout_result` 类型与读写（taskpad schema 扩展，向后兼容） | `app/src/lib/taskpad.ts`、`engine/src/assist/paper/task.py` | 旧 JSON 无该字段仍可解析 |
| T3 | PWA 排版引擎：测量 + 贪心装箱 + 切段（段落/公式边界） | `app/src/lib/autoLayout.ts`（新增） | 自检：给定内容产出确定 pages 结构 |
| T4 | PWA 渲染：按 `layout_result` 生成页/格 HTML（含虚线、页码、续格标注） | `app/src/lib/sheetHtml.ts` | 与 CLI 产物逐字级别一致 |
| T5 | PWA 自动重排：内容/版式/答案变化 → 防抖重排 → 更新 `layout_result` | `SheetPreviewSection.vue`、`stores/taskpad.ts` | 改动后预览自动更新 |
| T6 | CLI 复用 `layout_result` 渲染（无则回退 D61 网格） | `engine/src/assist/paper/htmlfile.py`、`assignment.html.j2` | pytest：有/无 layout_result 两态 |
| T7 | 带答案时版式降级：只允许横版 1×2 / 竖版 2×1，其他自动降级并提示 | `SheetLayoutView.vue`、`autoLayout.ts` | 选 4 题/页 + 答案 → 自动变 2 且提示 |
| T8 | PDF 通道：每页一题 + 完整答案，超出自动续页 | `engine/src/assist/paper/layout.py` | pytest：单题超高 → 跨页且答案完整 |
| T9 | 自检/测试：pytest + selfcheck（含变异验证） | `engine/tests/`、`app/tests/` | 全绿 |

## 7. 已知边界

1. **PWA 与 CLI 的一致性依赖字体一致**：PWA 测量用浏览器字体；若引擎/PDF 字体不同，HTML 仍一致（同一 `layout_result`），PDF 版式独立（一题一页）。
2. **内容 hash 失效**：教师手改 JSON 未重排 → 回退旧网格并提示。
3. **单段（整块行间公式）高于格高** → 缩放，可读性下降（已在 UI 标注）。
4. D102 的**打印不横切、页脚定位**修复保留。

## 8. 回滚

- `layout_result` 为可选字段；删除即回到 D61 网格。
- T1 回滚 D102 属于恢复既有行为，无数据迁移。

---

## 9. 实施记录（待填）

## 9. 实施记录（第一批：2026-10-24）

### 9.1 已完成

| # | 内容 | 状态 |
|---|---|---|
| T1 | **回滚 D102，恢复 MxN 网格与全部虚线** | ✅ 已验证 |
| T2 | `autoLayout.ts` 排版引擎（切分 + 装箱 + 续格 + 降级 + 指纹） | ✅ 已验证 |
| T6(部分) | D102 自检转为**回归哨兵**（断言 MxN/虚线不得再被去掉） | ✅ |
| T9(部分) | 新增 `selfcheck-d103-autolayout.mjs`（8 组断言 + 变异验证） | ✅ |

### 9.2 T1 实测结果

| 项 | D102（回归） | D103 恢复后 |
|---|---|---|
| `.sheet-body` | `flex-direction: column`（单列） | **`display: grid`** |
| 横版 1×2 | 两题上下堆叠、各占满整宽 | **两列并排**（`508.344px 508.344px`，同一 top） |
| 竖虚线 | `display:none` | **可见**（1 条，`left:50%`） |
| 页高 | `auto` | **固定 296mm/209mm**（MxN 需确定格高） |

真实 PWA（vite preview + 设计页 iframe）实测：
`{'display': 'grid', 'rows': '591.875px', 'cols': '508.344px 508.344px', 'sfLines': 1, 'sfVisible': 1}`

### 9.3 排版引擎（T2）能力与实测

| 能力 | 实现 | 实测 |
|---|---|---|
| 切分点 | 段落/行边界 + 行间公式**整块不切** | ✅ `$$\begin{aligned}…$$` 含空行仍为 1 块 |
| 长段落二次切分 | >120 字符按句末标点切，再退化按字符切 | ✅ 1200 字符答案切成多段 |
| 同格不混排 | 放置前检查槽占用 + 每题结束换格（双层保护） | ✅ 变异单点破坏被兜住；双层破坏才报错 |
| 写满续写 | 续段进入**下一页第 1 格**并标 `cont` | ✅ 真实浏览器测量验证 |
| 题目顺延 | 后题不覆盖前题，内容不丢 | ✅ 断言"答案文本拼回与原文逐字一致" |
| 页号连续 | 空页过滤后重编号 | ✅ |
| 公式缩放 | 行间公式高于格高 → `scale`，并记 warning | ✅ |
| 版式降级 | 横→1×2、竖→2×1 | ✅ |
| 失效判定 | `contentHash` + `layoutMatches` | ✅ |

**真实浏览器测量验证**（Chromium + KaTeX，格 478×480px）：`q2` 超长答案切成 2 段，第 2 段标 `cont` 进入下一页第 1 格，`q3` 顺延到第 2 页。

### 9.4 验证

| 项 | 结果 |
|---|---|
| engine pytest | **512 passed** |
| app `vue-tsc -b` | **0 error** |
| app `vite build` | **0 error** |
| app `npm run selfcheck` | **全绿**（109 条断言，含新增 D103 9 组） |
| 变异验证 | 双重破坏"同格不混排" → **断言失败** |

### 9.5 剩余任务（T4–T8，下一批）

| # | 内容 | 说明 |
|---|---|---|
| T4 | 按 `layout_result` 渲染页/格 HTML（含续格标注、虚线、页码） | 前后端共用同一结构 |
| T5 | PWA 自动重排（内容变更 → 防抖测量 → 更新 `layout_result`） | 需接入 `SheetPreviewSection` |
| T6 | CLI 复用 `layout_result`（无则回退网格） | `htmlfile.py` + j2 |
| T7 | 带答案时版式自动降级 UI 提示 | `SheetLayoutView` |
| T8 | PDF 通道：每页一题 + 完整答案 + 续页 | `layout.py`（reportlab） |

T2 的引擎与数据结构已就绪，T4–T8 都是在其上接线，无未解决的技术风险。

## 10. 实施记录（第二批：T4–T8，2026-10-25）

### 10.1 变更清单

| # | 内容 | 文件 |
|---|---|---|
| T4 | 按 `layout_result` 渲染页/格 HTML：`layoutCellsForPage()`、`cellBodyHtml()`、`SheetHtmlCellView`；`pageBlockHtml` 增 `layoutCells` 分支；续格标注 `（题 N 续）`；缩放样式 | `app/src/lib/sheetHtml.ts` |
| T5 | PWA 自动重排：`cellGeometry()`（按 A4 与页眉页脚推算格尺寸）、`reflowPad()`（离屏测量 + KaTeX）、防抖 260ms + 序号丢弃过期结果 | `app/src/lib/measureLayout.ts`（新增）、`SheetPreviewSection.vue` |
| T6 | CLI 复用 `layout_result`：`_layout_cells_for_page()`、按排版页数分页、j2 `pg.has_layout` 分支 | `engine/src/assist/paper/htmlfile.py`、`assignment.html.j2` |
| T7 | 带答案版式降级提示（横 1×2 / 竖 2×1） | `app/src/views/SheetLayoutView.vue` |
| T8 | PDF 教师版：`--teacher`、`_question_with_solution_flowables()`、`_teacher_flow()`（一题一页 + 完整答案 + 自动续页 + 页码正确）、`resolve_items_with_ids()`（按**题库 id** 取生效答案） | `engine/src/assist/paper/layout.py`、`task.py`、`cli.py` |
| T9 | 新增 `test_d103_layout_result.py`（8 例） | `engine/tests/` |

### 10.2 端到端验证

| 项 | 结果 |
|---|---|
| 浏览器真实测量 → 排版 → 渲染 | 2 页 / 3 格 / **7 处续格标注** / MxN 网格保留 |
| **PWA 与 CLI 同 layout_result 一致性** | 均为 **1 页 / 2 格 / 4 处续格标注**、`display:grid` ✅ |
| PDF 教师版 | 2 题 → **2 页**、含 AI 置顶答案、页码 `第1/2页`/`第2/2页` |
| PDF 超长答案 | 2000 句 → **自动续页**，内容完整（≥1500 处） |
| PDF 非教师版 | 行为不变（2 题/页 → 1 页，不含答案） |
| `--no-solution` + layout_result | 格内不渲染答案（不泄漏） |

### 10.3 修复的 bug（实施中发现）

1. **页号空洞**（1→3）：空页过滤后未重编号 → 排序后连续编号。
2. **超长段落未切分**：只在换行处切 → 增加「句末标点二次切分 + 超长硬切」（上限 120 字符）。
3. **同格塞多个块**：初版把续段全塞进同格 → 改为「同题续段可共格；写满才进下一页第 1 格」。
4. **无 layout 时题目全丢**：`chunks` 初始化成全 `null` → 改为无 layout 时按 per_page 正常切片（回归修复，被 `selfcheck-roster-fig` 抓住）。
5. **PDF 页码错误**（`第1/1页`）：`n_pages` 仍按 per_page 算 → 教师版按题目数计。
6. **PDF 取答案用错 id**：用题号 `no` 当题库 id → 新增 `resolve_items_with_ids()` 返回 qid。
7. **`_teacher_flow` 参数名不匹配**（`figure_indent` vs `indent`）→ 兼容转换。
8. **`colors` 未导入** → 补 `from reportlab.lib import colors`。

### 10.4 最终验证

| 项 | 结果 |
|---|---|
| engine pytest | **520 passed**（新增 D103 8 例） |
| app `vue-tsc -b` / `vite build` | **0 error** |
| app `npm run selfcheck` | **全绿** |

### 10.5 使用方式

```bash
# 教师版 PDF（一题一页 + 完整答案）
assist sheet make --task <task.json> --teacher

# HTML（带答案）：PWA 自动预排版；CLI 读取 taskpad 里的 layout_result 复用同一排版
assist sheet html --task <task.json>
```

## 11. 修复记录（2026-10-25，用户反馈）

### 11.1 问题：答案续段全挤在每页左上角

用户反馈（2×2 / 2×1 横版）：答案被分段了，但**每一段都只写在每页的第 1 格（左上角）**，
其它格空着；后续题目（如第 2 题）被推到很后面的页。

**复现实测**（格高 300、每块 100）：
```
修改前：page1 [0,0] q1+q1+q1续
        page2 [0,0] q1续+q1续+q1续
        page3 [0,0] q1续+q1续+q1续
        page4 [0,0] q1续 [0,1] q2+q2     ← 第 2 题被推到第 4 页
```

**根因**：R3 实现时把「续写到下一格」误写成「续写到**下一页第 1 格**」：
```ts
slot = Math.max(slot + 1, (Math.floor(slot / perPage) + 1) * perPage)   // ← 强制跳到下一页 col=0
```
导致每页的其它格永远空着。

**修复**：改为按阅读顺序进入**下一格**（同页后续格 → 下一页第 1 格）：
```ts
slot += 1
```

**修复后实测**：
```
page1 [0,0] q1+q1+q1续  [0,1] q1续×3  [1,0] q1续×3  [1,1] q1续
page2 [0,0] q2+q2                                    ← 第 2 题顺延正确
```
真实浏览器测量（竖版 2×1）：
```
page1 [0,0] q1+q1+q1续×5  [1,0] q2+q2
```

**回归防护**：`selfcheck-d103-autolayout.mjs` 新增 4c 组断言
（第 1 页须填满 ≥3 格、续段须分散在多个 (row,col)、后续题目必须在续段之后），
并做变异验证（改回旧逻辑 → 断言立即失败："第 1 页应尽量填满多格（实际 1 格）"）。

### 11.2 关于"写满后截断到下一格"的语义澄清

用户描述的规则已完整实现：
- 答案在**当前格**写不下 → 在该格底部**截断**；
- 余下内容写入**下一格**（按阅读顺序：同行右格 → 下一行左格 → 下一页第 1 格）；
- 若仍有剩余 → 继续截断、继续往后写；
- 本题后面的题目整体**顺延**，不插队。

唯一与"截断"措辞的差异：切分点取**段落/句子/行间公式边界**（公式绝不切开，R6），
因此实际截断位置可能比格底略早（留白），但**不丢内容**。

---

## 12. D104：题库 AI 作答支持「教师额外作答要求」

### 12.1 需求

AI 辅助批阅 → 题库作答，增加文本框让教师输入作答要求（例如"请画出示意图"、
"输出为 HTML 文档"）。

### 12.2 实现

| 层 | 改动 |
|---|---|
| 引擎 `grading/solve.py` | `build_question_prompt(..., extra_requirement)`：要求追加为「教师额外作答要求（优先满足）：」段；`solve_targets(requirement=)` 透传 |
| CLI | `assist kb ai-solve --requirement "..."` |
| serve | `POST /kb/ai-solve` 的 `requirement` → `--requirement`（空白不传） |
| PWA `engineClient.ts` | `startKbAiSolve` payload 增 `requirement?` |
| PWA `AiGradingPanel.vue` | 文本框（3 行、含示例占位符）+ 说明"留空=默认风格"；随请求发送 |

### 12.3 验证

| 项 | 结果 |
|---|---|
| prompt 拼接 | 含「教师额外作答要求（优先满足）」+ 要求正文；空白不追加 |
| 真实调用链 | 要求确实进入发给 LLM 的 `user_text`（桩客户端断言） |
| CLI | `--requirement` 可解析 |
| serve | HTTP 端点确实把 `requirement` 转成 `--requirement`（两态：有值/空白） |
| engine pytest | **527 passed**（新增 D104 7 例） |
| app | `vue-tsc`/`build` 0 err、selfcheck 全绿 |

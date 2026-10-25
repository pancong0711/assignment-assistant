# D105 任务需求单：答案以 JSON 为真源 + md+html 渲染 + 弹窗内编辑修正

> 日期：2026-10-25
> 状态：**实施中**
> 关联：`docs/42-D89`（solution 多版本库）、`docs/53-D100`（生效版读取链路）、
> `docs/56-D103`（预排版/作业纸渲染）、`docs/05-D3`（xlsx 作为题库真源的历史决策）

## 1. 背景与决策

### 1.1 现状（已查证）

| 数据 | 真源 | 位置 |
|---|---|---|
| 题干 content / img_path / page / type / note | **xlsx** | `kb/<kind>.xlsx` |
| 参考答案（含多版本/置顶/时间戳） | **json** | `kb/solutions/<qid>.json` |
| xlsx `solution` 列 | 仅旧数据 fallback | `kb_io.py:17` COLUMNS 仍保留 |

D89 引入版本库后，实际已是「题干在 xlsx、答案在 json」的**分裂状态**，
但 xlsx 的 `solution` 列仍被保留（写回时原样保留、不更新），造成"表格显示空/到底谁是准"的困惑。

### 1.2 用户拍板（2026-10-25）

1. **答案以 JSON 为真源**（解除 xlsx 单元格 32767 字符限制，支持 md+html/SVG）；
2. **xlsx `solution` 列保留为「纯文本摘要」**（单向派生：json → xlsx，供教师扫读/检索）；
3. Excel 里手改 `solution` 列 → 导入时识别为「新增人工版本」并提示，**不直接覆盖 json**；
4. 修正答案的入口放在 **题库管理 → 🔍 预览弹窗**（不放在 AI 面板）；
5. 保存语义：**默认追加为新版本**（可回滚，符合 D89「不覆盖」原则），另提供"保存并置顶"；
6. 导出交付包包含 `kb/solutions/`（否则交付出去的作业纸没有答案）。

## 2. 数据模型

### 2.1 `kb/solutions/<qid>.json`（版本库，答案真源）

```jsonc
{
  "qid": "c1", "kb": "problems", "chap": "chap04",
  "versions": [
    { "id": "v1",
      "text": "解：由 $v=\\frac{dx}{dt}$ …<svg …>…</svg>",   // md+html（真源）
      "text_plain": "解：由 v=dx/dt …（纯文本摘要）",          // 派生：检索/摘要/降级
      "source": "ai", "model": "qwen-max",
      "at": "2026-10-25 10:00:00", "pinned": true }
  ]
}
```

- **新增字段 `text_plain`**（缺失时按 `stripMarkup(text)` 现算）；
- `text` 允许 Markdown + HTML 子集（见 §3 白名单）；
- 兼容：旧数据只有 `text` → `text_plain` 视为 `text`。

### 2.2 xlsx `solution` 列（摘要，单向派生）

- 写入时机：答案版本变更后，把「生效版 `text_plain`」截断到 200 字回填；
- 读取时**不作为答案真源**（仅 `effective_solution` 的最后一级 fallback，兼容从未生成过版本库的旧题库）；
- 表头注释：`solution（摘要，完整答案见 kb/solutions/<id>.json）`。

## 3. md+html 渲染（安全边界）

| 项 | 决定 |
|---|---|
| 语法 | Markdown + HTML 白名单子集 + KaTeX（`$..$` / `$$..$$` / `\(..\)` / `\[..\]`） |
| 允许标签 | `p br strong em del code pre blockquote ul ol li table thead tbody tr th td hr h1-h6 img svg g path line rect circle ellipse polygon polyline text tspan defs marker` |
| 允许属性 | `class style(viewBox/width/height/fill/stroke/...) src alt title colspan rowspan` |
| `img` 限制 | **仅允许 `src="data:image/(png|jpeg|gif|webp);base64,..."`**（禁外链） |
| `svg` 限制 | 禁 `foreignObject` / `use[href]` / `image[href]` / 任何 `on*` 事件 / `javascript:` |
| 禁止 | `script iframe object embed form input link meta base style` 标签、事件属性、外链 URL |
| 降级 | 净化后为空 → 显示 `text_plain`；渲染异常 → 显示源码（不白屏） |
| 双端一致 | PWA 用 `markdown-it` + `dompurify`；CLI 用 Python `markdown` + `bleach`（同一白名单常量，各自实现、用同一份测试样例校验） |

## 4. 交互：🔍 预览弹窗内的编辑与修正

```
┌─ 题目与答案 · c1 ─────────────────────────────┐
│ 题干（渲染）                                    │
│ ─────────────────────────────────────────── │
│ 版本：v3(AI,★) v2(人工) v1(AI)  [＋新版本]     │
│ ┌─ 预览（渲染 md+html）─────┐ ┌─ 源码 ───────┐│
│ │ 解：…  [SVG 示意图]       │ │ ## 解        ││
│ │ $$v=2t$$                  │ │ 由 $v=…$     ││
│ └───────────────────────────┘ └──────────────┘│
│ [预览] [编辑] [保存为新版本] [保存并置顶]        │
└───────────────────────────────────────────────┘
```

- 默认「预览」态；点「编辑」切到左右分栏（源码 + 实时预览）；
- 保存 = `POST /kb/solution {action:add, text, source:'human'}`（追加版本）；
- 保存并置顶 = add + pin；
- 保存后同步刷新 `text_plain` 并回填 xlsx 摘要（§2.2）。

## 5. 任务分解

| # | 任务 | 文件 |
|---|---|---|
| T1 | 版本库 schema 增 `text_plain`；`add_version` 自动派生；`effective_solution` 返回该字段 | `engine/src/assist/files/solutions.py` |
| T2 | Python 侧 md+html 安全渲染（白名单 + KaTeX 占位）；`stripMarkup()` 派生纯文本 | `engine/src/assist/paper/richdoc.py`（新增） |
| T3 | PWA 侧渲染模块（markdown-it + dompurify，同一白名单） | `app/src/lib/richdoc.ts`（新增） |
| T4 | 作业纸渲染接入：TS `sheetHtml.ts` + j2 模板改为渲染 md+html（不再 `escapeHtml` 整段） | 两处 |
| T5 | 🔍 弹窗：预览渲染 + 源码编辑 + 保存新版本/保存并置顶 | `KbEditorView.vue` |
| T6 | xlsx `solution` 列改为摘要回填（json→xlsx 单向）+ 表头注释 | `files/kb_io.py`、`stores/kb.ts` |
| T7 | Excel 手改 `solution` 检测 → 提示「新增人工版本」 | `files/kb_io.py` + 导入路径 |
| T8 | 交付包 `exportAllZip` 含 `kb/solutions/*.json` | `SheetOutputSection.vue` |
| T9 | 测试：Python 白名单/净化/派生；app 渲染白名单；端到端渲染 SVG | 两侧 |

## 6. 安全与回滚

- 白名单**双端同一份常量表**，并用同一组恶意样例（`<script>`、`onerror=`、外链 `src`、
  `javascript:`、`foreignObject`）互相校验；
- 回滚：`text` 若不含 HTML/Markdown 记号，渲染结果与旧行为等价（纯文本 + KaTeX）。

---

## 7. 实施记录（待填）

## 7. 实施记录（2026-10-25）

### 7.1 完成项

| # | 内容 | 文件 |
|---|---|---|
| T1 | 版本库增 `text_plain`（自动派生，可显式覆盖）；`effective_solution` 返回该字段 | `files/solutions.py` |
| T2 | Python md+html 安全渲染：Markdown → 白名单净化（bleach）+ SVG/data:image 限制 + 危险块连内容删除；`strip_markup()` 纯文本派生 | `paper/richdoc.py`（新增） |
| T3 | PWA md+html 渲染：`markdown-it` + `DOMPurify`（同一白名单）；**无 DOM 时（自检/SSR）保守字符串净化兜底** | `lib/richdoc.ts`（新增） |
| T4 | 作业纸渲染接入（TS + j2）：答案/题干改为渲染 md+html；图片/SVG/表格限宽样式 | `sheetHtml.ts`、`assignment.html.j2`、`htmlfile.py` |
| T5 | 🔍 弹窗：预览渲染 + **源码编辑（左右分栏实时预览）** + 保存为新版本/保存并置顶 | `KbEditorView.vue` |
| T6 | xlsx `solution` 列降级为摘要（`summarize_solutions()` 单向派生，≤200 字）+ 表头注「摘要，完整答案见 kb/solutions/<id>.json」 | `files/kb_io.py` |
| T8 | 交付包 zip 附带 `kb/solutions/*.json`；README 说明答案真源 | `SheetOutputSection.vue`、`engineClient.ts` |

### 7.2 安全边界（实测拦截）

10 类恶意样例全部拦截（双端同一组用例）：
`<script>`、`onerror=`/`onload=`、外链 `https://evil.com`、`javascript:`、
`<iframe>`、`<style>` 全局污染、`onclick`、`<foreignObject>`、`data:image` + 事件属性。
并且 **JS/CSS 正文不会泄漏为可见文本**（整段连内容删除）。

### 7.3 双端一致性

`selfcheck-d105-richdoc.mjs` 第 5 项直接解析 Python 的 `ALLOWED_TAGS` 与 TS 的
`ALLOWED_TAGS` 比对，**55 个标签完全一致**（任一缺失即失败）。

### 7.4 验证

| 项 | 结果 |
|---|---|
| engine pytest（含新增 D105 23 例） | **565 passed** |
| app `vue-tsc` / `build` | **0 error** |
| app `npm run selfcheck` | **全绿**（117 条，含 D105 5 组） |
| 端到端 | 答案含 SVG/表格/公式 → HTML 正确渲染且无 `<script>` 泄漏 |

## 8. 修复记录（2026-10-25，用户反馈）

### 8.1 三个显示问题

| # | 现象 | 根因 | 修复 |
|---|---|---|---|
| 1 | **题号后空一行**才开始题目 | 题干用 `renderRich()` 直接插在题号后，而它输出 `<p>`（块级）→ 必然换行 | 新增 `renderRichInline()` / `render_rich_inline()`：**仅当整体是单个 `<p>`** 时去包裹；多段/表格/SVG 保持块级 |
| 2 | **「参考答案：」每行重复** | 与「题 N 续」同源：按**切分段**加标签，而一格内常有多个切分段 | 按**格**判定：只在该格首个答案块前标注（TS `isFirstSol` / Python `show_sol_label` 预计算） |
| 3 | **公式显示为 LaTeX 源码** | `markdown-it` / Python `markdown` 把 `\(` `\[` 当**转义序列**吃掉 → `\(v=2t\)` 变成 `(v=2t)`，KaTeX 认不出 | 渲染前把公式片段抽成**占位符**（`D105MATHPLACEHOLDER<n>END`），Markdown 渲染后再还原；双端同实现 |

实测（Chromium）：

```
修复前 q-content: "1.  <p>一质点...</p>"          ← 题号独占一行
修复前 \(v=2t\)  →  "(v=2t)"                      ← 公式失效
修复后 q-content: "1.  一质点..."                  （lineTops 只 1 个值）
修复后 4 个公式全部渲染成 .katex，无 LaTeX 泄漏
修复后 3 个答案块 → 「参考答案：」只出现 1 次
```

### 8.2 代码审核发现的另外 4 个问题（一并修复）

| # | 问题 | 影响 | 修复 |
|---|---|---|---|
| A1 | **批阅报告正文未净化**：`grading/report.py:_md_to_html` 直接 `markdown.markdown()` | AI 输出可注入脚本到报告 PNG 渲染页；且 `\(..\)` 同样失效 | 改用 `paper.richdoc.render_rich`（净化 + 公式保护），保留旧路径兜底 |
| A2 | **批阅 prompt 用 `text`（含 SVG/base64）** | 每条 prompt 浪费大量 token，且干扰模型阅读 | `grading/inputs.py`、`grading/flow.py` 改用 `text_plain` |
| A3 | **PWA 报告 `reports.ts` 直接把 `stem`/`review`/`transcript` 插值** | md+html 显示为源码、公式不渲染 | 三处改用 `renderRich()` |
| A4 | 题干 `2*3*4` 曾被 Markdown 当斜体 | 数学内容被误改 | 公式保护顺带缓解；纯文本星号仍在（Markdown 语义）|

### 8.3 验证

| 项 | 结果 |
|---|---|
| engine pytest | **571 passed**（新增 6 例：反斜杠定界符/markdown 表格公式/行内去 `<p>`/块级保持/报告净化/prompt 用纯文本） |
| app `vue-tsc` / `build` | **0 error** |
| app `npm run selfcheck` | **全绿** |
| 真实浏览器 | 题号与题干同一行；4 个公式全部渲染；3 个答案块仅 1 个「参考答案：」；无 LaTeX 泄漏 |

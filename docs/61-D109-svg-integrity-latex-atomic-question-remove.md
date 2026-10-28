# D109 缺陷修复：示意图不显示 / LaTeX 处截断 / 作业纸单题移除

> 日期：2026-10-28
> 状态：已实现并验证
> 关联：`docs/60-D108-requirement-prompt-templates.md`（提示词模板库）、`docs/56-D103-grid-layout-with-solution-flow.md`（R6 公式不切割）；`docs/63-D111-global-question-id-taskboard.md`（题号全局唯一）

## 1. 现象（用户反馈）

1. 用内置「含示意图」方案做题库题目，答案里**看不到示意图**，只看到一句杂字
   （疑似 `/box` 一类残片）。
2. 示意图**总被堆到答案末尾**，位置不合适。
3. 作业纸里题目**只能移动顺序、不能单题删除**；只有"移除整张作业纸"。
   起因是发现某题预览不全（**在 LaTeX 语法处截断**），想删掉再加回来试试。

## 2. 根因（三条独立缺陷）

### 2.1 SVG 被 `nl2br` 注入 `<br>` → 浏览器解析成 0 个图元

`paper/richdoc.py` 用 Python-Markdown 的 `nl2br` 扩展。只要答案里是**多行**内联
`<svg>`（AI 几乎总是换行写），`<br>` 就会被插进 `<svg>` 内部：

```html
<svg viewBox="0 0 200 150" ...><br />
  <rect .../><br />
  <text ...>m</text><br />
</svg>
```

Chromium 实测（Playwright）：`svg.children.length = 0`、`rects = 0`、`innerHTML` 为空 —
**空框**，图元文本则漏到框外成为杂字。这就是"只看到一句话、图没显示"。

### 2.2 预排版把 SVG 按行拆成 5 块 → 每格只拿到残缺片段

`app/src/lib/autoLayout.ts: splitIntoPieces()` 先按行间公式切，再按 `\n{2,}` 分段、
按 `\n` 逐行切，**完全不知道 `<svg>` 是整体**：

| 块 | 内容 | 渲染结果 |
|---|---|---|
| 0 | `由受力分析可知：` | 正常 |
| 1 | `<svg viewBox=…>` | **空白框** |
| 2 | `<rect …/>` | 不可见 |
| 3 | `<text>m</text>` | 杂字 |
| 4 | `</svg>` | 杂字 |

### 2.3 无 `width/height` 的 SVG 被撑满容器

模板只有 `.q-solution svg { max-width:100%; height:auto }`，而 AI 输出通常没有
`width/height`。浏览器实测渲染成 **684×513px** 的巨型图（挤占整格、比例失真）。

### 2.4 LaTeX 处截断：`splitLongParagraph` 按 120 字符硬切，切断公式

```ts
for (let i = 0; i < piece.length; i += limit) final.push(piece.slice(i, i + limit))
```

复现（`$h = \frac{v_0^2}{2g}$` 恰好跨过 120 边界）：

```
piece 0: …的表达式为 $h =
piece 1:  \frac{v_0^2}{2g}$
```

前一段是**未闭合的 `$`** → KaTeX 拒绝渲染、按源码显示；后一段内容从预览里"消失"。
这正是用户说的"在 latex 语法处截断，后面内容没有显示"。
（`docs/56 §R6` 早已规定"公式不切割"，此硬切是违约实现。）

## 3. 修复

### 3.1 `paper/richdoc.py`（引擎渲染）

- `_protect_html_blocks` / `_restore_html_blocks`：把**跨行**的
  `<svg>`/`<table>`/`<pre>`/`<blockquote>` 先整体抽成占位（与既有公式占位同一手法），
  Markdown 之后再还原，`nl2br` 再也插不进 `<br>`；
  还原时把「整段就是一个占位的 `<p>`」替换为块本身——块级元素不能待在 `<p>` 里
  （浏览器会自动闭合 `<p>`，图元会跑到框外）。
- `_normalize_svg_size`：无 `width/height` 时按 `viewBox` 比例补
  `width="60.0mm" height="45.0mm"`（高 ≤45mm、宽 ≤80mm，等比），不再撑满容器。
  不用 `style`——bleach 白名单不含 style，只靠模板 CSS 兜底。

### 3.2 `app/src/lib/autoLayout.ts`（PWA 预排版，CLI 复用同一份）

- 新增 `HTML_BLOCK_RE` + `splitKeepingHtmlBlocks()`：`<svg>/<table>/<pre>` **整体成块**，
  绝不按行拆；`splitIntoPieces()` 改为先保块再切段落。
- 新增 `INLINE_MATH_RE` / `atomizeMath()` / `isMathAtom()`：`$$..$$`、`\[..\]`、
  `\(..\)`、**`$..$`** 全部视为不可切原子；句子打包与"极端长句字符切"都**跳过公式**，
  公式宁可超出 120 字符上限也不切开。
- 重新生成 `engine/src/assist/paper/layout_bundle.mjs`（`node engine/tools/build-layout-bundle.mjs`），
  保证 PWA 与 CLI 跑同一份算法。

### 3.3 `app/src/lib/richdoc.ts`（PWA 渲染，与引擎对齐）

- 新增 `normalizeSvgSize()`，口径与引擎 `_normalize_svg_size` 一致。

### 3.4 提示词：明确"就近摆放"

- 内置「含示意图」模板（`files/prompts.py`）：新增**位置**条目——
  "紧跟受力分析/过程分析/几何关系那一段之后，**不要**统一堆到答案末尾"；
  并要求单行 `width/height`、另起一段、前后留空行。
- `grading/prompts.py: SVG_REDRAW_INSTRUCTION`（手绘图重绘）同步加"就近插入 + 另起一段"。

### 3.5 作业纸单题移除

- `stores/taskpad.ts`：新增 `removeId(itemIdx, idIdx)`（只摘单个题号，不动其它题）。
- `views/SheetContentView.vue`：题号旁在 ↑/↓ 之后新增 **`✕` 移除**按钮
  （`title` 说明"不删题库原题"）；同时清掉该题号的编号覆盖 `labels[id]`，避免重新加入时串号；
  移除后该组为空则一并删除分组（并先 confirm）。
- `<details>` 标题由「题号顺序（…）」改为「**题目明细：排序 / 编号 / 单题移除（…）**」，
  提高可发现性（此前功能藏在折叠区里，用户以为只能整张移除）。
- 移除/重加会改变 `pad.current` → `SheetPreviewSection` 的 deep watch 触发 `scheduleReflow()`，
  **自动重排**，正是用户"删掉再加回来试试"的诉求。

## 4. 验证

| 项 | 结果 |
|---|---|
| engine pytest | **594 passed**（D105 用例 34，新增 SVG 完整性/尺寸/提示词 5 例） |
| app `vue-tsc -b` / `npm run build` | **0 error** |
| app `npm run selfcheck` | **全绿**（新增 `selfcheck-d109-layout-atoms.mjs`） |
| Playwright 真实浏览器 | 修复前 `svg.children=0`、684×513px；修复后 `children=3`、227×170px，公式 `.katex-error=0` |
| CLI 端到端 `sheet html` | 多行 SVG 无 `<br>`、图元齐全、带尺寸；`$s=\frac{1}{2}at^2$` 与 `4.0 m` 完整保留；未闭合 `$` 片段数 0 |
| `splitIntoPieces` 压测 | 长无标点段落 / 超长公式 / 多定界符 / 表格 / 转义 `\$` 全部通过，`$` 均成对 |

## 5. 遗留讨论

- **示意图位置**：目前用提示词引导"就近摆放"。若要更强约束，可后续在排版层
  识别答案中的 `<svg>` 块并强制"图随其所在段落"（当前已因 SVG 整体成块而天然如此）。
- 若某题预览仍异常，现在可以直接用 `✕` 单题移除 + 重新「加入作业纸」来触发重排定位。

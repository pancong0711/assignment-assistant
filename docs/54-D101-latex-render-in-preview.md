# D101 任务需求单：参考答案 LaTeX 在题库编辑器 / 作业纸预览未渲染

> 日期：2026-10-24
> 状态：**T1–T5 完成**
> 关联：`docs/53-D100-...`（参考答案生效版读取链路）、`docs/13-D43-3/6`（KaTeX 同源自托管）、
> `docs/42-D89`（solution 多版本库）

## 1. 现象（用户反馈）

参考答案里的 LaTeX 在预览中**没被渲染**，两处都中招：
1. 题库编辑器（solution 单元格 / 🔍 预览弹窗）；
2. 作业纸设计（勾选「显示参考答案」后的模板预览）。

## 2. 实测复现（Playwright + 真实生成的 HTML，离线环境）

用 `stringifySheetHtml({katex:'relative'})` 生成预览页，Chromium 加载后统计 `.katex` 节点：

| 答案源码 | `.katex` 节点 | 结论 |
|---|---|---|
| `$v=2t$` | 1 | ✅ 正常 |
| `$$\int_0^1 x\,dx$$` | 1 | ✅ 正常 |
| `\[a=\frac{dv}{dt}\]` | **0** | ❌ **定界符未配置**（原样显示源码） |
| `\(E=mc^2\)` | **0** | ❌ **定界符未配置** |
| `\begin{aligned}…\end{aligned}`（裸块） | **0** | ⚠ LaTeX 惯例需包在定界符内（KaTeX 自身行为，非本 bug） |

补测：给 auto-render 加上 `\[..\]`、`\(..\)` 后，上述两类**立刻渲染成功**（各 1 个 `.katex`）。
另确认资源侧无问题：`./katex/` 下 css/js/auto-render/woff2 全部 200，页面加载 20 个字体，无失败请求。

## 3. 根因

| # | 根因 | 位置 |
|---|---|---|
| R1 | auto-render 只配置了 `$$..$$` 与 `$..$`，**缺 `\[..\]` / `\(..\)`**。AI 作答（`solve.py` 的 system prompt 要求"行内 `$...$`、行间 `$$...$$`"）虽以 `$` 为主，但人工/其他模型产出的 `\[..\]`、`\(..\)` 一律不渲染 | `app/src/lib/sheetHtml.ts:katexScript()`、`engine/templates/assignment.html.j2`（两处逐字同构，须同改） |
| R2 | **题库编辑器完全没有 KaTeX 链路**：solution 单元格是纯文本截断，🔍 弹窗用 `{{ solShown.text }}` 纯文本插值，从未调用 `renderMathInElement` | `app/src/views/KbEditorView.vue:390` |
| R3 | 作业纸预览的渲染脚本只在页面 `load` / `DOMContentLoaded` 时执行一次；PWA 预览是 **`srcdoc` 实时重建 iframe**（防抖 180ms），若重建时机晚于首次 load，需依赖脚本自身轮询（现有轮询只等 `renderMathInElement` 就绪，**已就绪时不会再触发**） | `sheetHtml.ts:katexScript()` |

## 4. 设计决策

| 项 | 决定 |
|---|---|
| 定界符集合 | `$$..$$`（display）、`\[..\]`（display）、`$..$`、`\(..\)`；顺序必须 **长定界符优先**（`$$` 在 `$` 前）否则 `$$x$$` 会被拆成两个行内 |
| 裸 `\begin{env}` | **不自动包裹**。这是 LaTeX 惯例（环境必须处于数学模式）；AI prompt 已要求 `$` 定界。若后续需要，单开需求 |
| 题库编辑器渲染 | 引入 `renderMathInElement`（同源 `./katex/`），对弹窗答案区做后置渲染；单元格仍纯文本（避免每行渲染开销与排版抖动） |
| 渲染时机 | 抽 `renderMathIn(el, opts)` 公共函数 + `ensureKatex()` 资源懒加载（幂等缓存），Vue 侧 `watch` + `nextTick` 驱动；HTML 侧脚本额外在 `load` 后补一次 `renderAll()` |
| 引擎模板 | 与 TS 侧**逐字同构**（D1 超集铁律），parity 哨兵同步加断言 |
| 失败降级 | `throwOnError:false`，KaTeX 不可用时保留源码，绝不抛错 |

## 5. 任务分解

| # | 任务 | 文件 |
|---|---|---|
| T1 | 补齐 4 个定界符（TS 侧 + j2 模板），长定界符优先 | `sheetHtml.ts`、`assignment.html.j2` |
| T2 | 抽公共 `renderMathIn` / `ensureKatex`（同源懒加载、幂等、`displayMode` 支持） | `app/src/lib/katexRender.ts`（新增） |
| T3 | 题库编辑器：🔍 弹窗答案区渲染公式（切换版本时重渲染）；题干同步渲染 | `KbEditorView.vue` |
| T4 | 作业纸预览：`load` 后补渲染 + 幂等（防重复渲染破坏 DOM） | `sheetHtml.ts` |
| T5 | 测试：引擎 parity 哨兵断言新定界符；app selfcheck 断言生成的 HTML 含 4 个定界符且渲染脚本幂等 | `test_sheet_html.py`、`selfcheck-d101-latex-render.mjs`（新增） |

## 6. 回滚

- 定界符为纯增量配置，回滚即恢复旧行为（`\[..\]` 重新显示为源码）。
- 题库编辑器渲染为独立组件调用，异常时 catch 后保持纯文本。

---

## 7. 实施记录（2026-10-24）

### 7.1 转义层数（本次最关键的坑）

浏览器侧 `renderMathInElement` 的 `delimiters` 必须是 **`'\\['`（HTML 源里 2 个反斜杠）**，
JS 解析后才是字符串 `\[`（长度 2）。
实测矩阵（Chromium，`eval` 后取 `left.length` / 反斜杠数）：

| HTML 源反斜杠数 | JS 值 | 结果 |
|---|---|---|
| 1 | `[` | ❌ 定界符失效 → **公式原样显示源码（本 bug）** |
| **2** | **`\[`** | ✅ 正确 |
| 4 | `\\[`（字面量反斜杠） | ❌ 同样不渲染 |

而两侧源码层数**不同**，极易改错：

- `app/src/lib/sheetHtml.ts`：定界符在**模板字符串**里 → 源码写 **4 个**反斜杠（求值后 2 个写入 HTML）；
- `engine/templates/assignment.html.j2`：Jinja 原样输出 → 源码写 **2 个**。

> 首版实现误写成「TS 4 个 / j2 4 个」，导致产物分别是 2 个和 4 个 —— 只有 TS 对。
> 已由 `selfcheck-d101-latex-render.mjs` 断言 2（含变异验证）与 pytest parity 哨兵双重锁定。

### 7.2 变更清单

| 文件 | 改动 |
|---|---|
| `app/src/lib/sheetHtml.ts` | `katexScript()`：补 `\[..\]`/`\(..\)`（长定界符在前）；`data-katex-done` 幂等；`load` 后补渲染 |
| `engine/templates/assignment.html.j2` | 同步上述脚本（parity，与 TS 逐字同构） |
| `app/src/lib/katexRender.ts`（新增） | `ensureKatex()` 同源懒加载 + `renderMathIn(el, force)` 幂等渲染 + `KATEX_DELIMITERS` 单一事实源 |
| `app/src/views/KbEditorView.vue` | 🔍 弹窗题干/答案区接入 `renderMathIn`；`watch([solOpen, solPick, versions])` 切换版本即重渲染 |
| `app/tests/selfcheck-d101-latex-render.mjs`（新增） | 4 项断言：定界符集合与顺序 / 转义层数 / 幂等标记 / 与 katexRender 同口径 |
| `engine/tests/test_sheet_html.py` | parity 哨兵增加定界符与幂等标记断言（区分两侧源码层数） |
| `app/package.json` | selfcheck 家族追加 D101 |

### 7.3 验收

| 项 | 结果 |
|---|---|
| engine pytest 全量 | **512 passed** |
| app `vue-tsc -b` / `vite build` | **0 error** |
| app `npm run selfcheck` | **全绿**（含 D101 4 项） |
| 变异验证（故意少一层反斜杠） | app selfcheck 与 pytest parity **均失败** → 断言有效 |
| 浏览器端到端（真实 HTML + Chromium，离线） | `$..$` / `$$..$$` / `\[..\]` / `\(..\)` **全部渲染**；`data-katex-done=1`；无 pageerror |
| 题库编辑器（真实 PWA 构建 + vite preview） | KaTeX 同源资源加载成功；注入含 LaTeX 答案后 **3 个 `.katex` 正常生成** |

### 7.4 已知边界（非 bug）

- **裸 `\begin{aligned}…\end{aligned}`（无定界符包裹）不渲染**：这是 LaTeX 惯例（环境必须处于数学模式），
  KaTeX 自身行为。AI prompt 已要求用 `$…$` / `$$…$$`；需要时用 `$$\begin{aligned}…\end{aligned}$$`。
- 题库表格**单元格**仍显示纯文本摘要（不渲染公式，避免每行排版抖动）；公式在 🔍 弹窗内完整渲染。

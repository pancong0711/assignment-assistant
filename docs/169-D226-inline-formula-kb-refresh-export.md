# D226：题号仍换行（松散列表/公式）+ 整班导出命名收口 + 题库 AI+ 目录实时刷新

> 日期：2026-11-25
> 状态：**已完成（2026-11-25）**
> 关联：`docs/165-D222`（软换行题号换行）、`docs/168-D225`（列表/div/引用 + 导出命名）、
> `docs/170-D227`（个性化作业纸规划）
>
> 隐私：无学生数据。

---

## 0. 本轮核查结论

D225 已修复常规列表 `<ul><li>…`、`<div>`、`<blockquote>` 与题号同排的路径，
但教师复测仍看到：

1. 部分第 1 题的 `$$…$$` 题干，题号后仍另起一行；
2. translation 题导入后，第 2 题仍可能另起一行；
3. `class_sheet_json`/整班 HTML 下载的命名仍有仅日期路径；
4. 「题库AI+ → 题库 AI 作答」的题目预览不会随题库内容更新，需要手动刷新页面。

本轮把四件事分开定位并修复。

---

## 1. 题号换行：D225 漏掉的三类 HTML

`renderRichInline()` 旧实现只处理几种固定开头，以下现场会漏：

| 输入形态 | Markdown/HTML 产物 | 旧结果 |
|---|---|---|
| 松散列表 | `<li><p>Sentence one.</p></li>` | 首项仍是 `<p>` → 题号独占一行 |
| 带属性段落 | `<p class="translation">…</p>` | 旧正则只匹配 `<p>`（无属性）→ 未去包裹 |
| div 包首段 | `<div class="q"><p>第一段</p>…</div>` | 旧逻辑看到内部有块级元素就放弃 → 题号独占一行 |
| 行间公式开头 | `<p>$$E=mc^2$$</p>` | HTML 层可去包裹，但 KaTeX 把 `$$…$$` 渲染成 `display:block` 的 `.katex-display`，且带上边距 → 视觉上题号仍被挤到上一行 |

### 修复

1. **行内化改为递归处理首块**（PWA `richdoc.ts` 与引擎 `richdoc.py` 同口径）：
   - `<p>`（含 class）→ 去包裹；
   - `<div>` → 递归行内化内部首块；
   - `<blockquote>` / 标题 → 递归行内化；
   - `<ul>/<ol>` → 每个 `<li>` 先递归行内化，再用 `<br>` 连接；
   - 表格 / SVG / 代码块保持块级。
2. **错开题号与正文的排版层**：
   - 模板由「题号文本 + 正文」改为 `.q-no` + `.q-content-body` 两个 flex 子项；
   - 即使正文首块确实是行间公式、表格或 SVG，题号也始终在左侧，不会单独占一行；
   - `.q-content-body > :first-child { margin-top:0 }`；
   - 额外清零 KaTeX auto-render 首块 `.katex-display` 的上边距。
3. PWA `sheetHtml.ts` 与引擎 `engine/templates/assignment.html.j2` 同步，保持 CLI/PWA 同构。

### 仍需注意

- 行间公式在语义上仍是 `display:block`；现在做到的是**题号与公式块顶部同排**，不是把公式强行改成行内公式。
- 表格/SVG 同理：题号在左侧，内容按块级语义排。

---

## 2. 整班导出命名：HTML 与 sidecar JSON 统一配对

D225 只改了 sidecar 和回退路径；下载成功路径仍残留
`class-sheet-preview-<YYYY-MM-DD>.html`，同一天多班仍可能覆盖。

本轮统一为：

```text
classExportBase(prefix) = <prefix>-<班级名>-<YYYYMMDD-HHMMSS>
```

- 整班 HTML：`class-sheet-preview-<班级>-<YYYYMMDD-HHMMSS>.html`
- 打印 sidecar：`class-sheet-<班级>-<YYYYMMDD-HHMMSS>.json`
- 下载 sidecar：与 HTML 同名换 `.json`
- 成功/回退两条下载路径共用同一个 `htmlName`，避免时间戳跨秒导致 HTML/JSON 对不上。

---

## 3. 题库 AI+ 的题目预览不跟随题库更新

### 根因

- `KbAiSolvePanel` 只在挂载时拉取一次 `/kb/catalog`；
- `GET /kb/catalog` 没有 `Cache-Control`，浏览器存在返回旧目录的可能；
- 多窗口/引擎侧写回题库后，已打开的 AI+ 页面没有刷新入口。

### 修复

- `fetchKbCatalog()` 改为：
  - URL 附加 `?_=<Date.now()>`；
  - `cache: 'no-store'`。
- AI+ 题库 AI 作答面板新增：
  - 「🔄 刷新题目」按钮；
  - 监听 `window focus`、`document visibilitychange` 自动刷新；
  - 监听 `kbStore.savedAt`，同页题库写回后自动刷新；
  - 刷新时尽量保留当前 kind/chap/题号选择；
  - 浏览器题库存在未写回修改时显示黄色提醒（AI 作答读的是引擎侧 xlsx，避免“预览与真实输入不一致”）。

---

## 4. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 松散列表 translation | 题号 + 第一项同排 |
| 2 | `<p class="…">` / 嵌套 div | 题号 + 首段同排 |
| 3 | `$$…$$` 作为首块 | 题号与公式块顶部同排，无题号独占行 |
| 4 | 软换行 / 多段 | 首段同排，后续段落仍换行 |
| 5 | 表格 / SVG | 题号在左，内容保持块级 |
| 6 | 连续导出两个班 | HTML 与 JSON 文件名均带班级名 + 到秒时间戳 |
| 7 | 写回题库后切回 AI+ | 题号下拉与题目预览立即更新；也可手动刷新 |
| 8 | 回归 | engine pytest / app selfcheck / build 通过 |

### 自动化

- 引擎：`test_d105_richdoc.py` **44 passed**；`test_sheet_html.py` **9 passed**；
- PWA：`app/tests/selfcheck-d226-inline-and-kb-refresh.mjs`；
- Chromium 真浏览器：`app/tests/run-d226-sheet-inline-browser.sh`
  - 真实渲染 KaTeX 后测量 `.q-no` 与正文顶部；
  - 覆盖公式首块、松散列表、软换行三类现场；
- 前端 build/selfcheck 通过。

# D112 缺陷修复：题库编辑器答案/题干预览不渲染（示意图不显示、公式显示源码）

> 日期：2026-10-28
> 状态：已实现并验证
> 关联：`docs/62-D110`（答案作用域）、`docs/63-D111`（题号全局唯一）、`docs/61-D109`（示意图/LaTeX）

## 1. 现象（用户反馈）

题库里某题答案源码含内联 `<svg>` 示意图与大量 `\(...\)` / `\[...\]` 公式，
**预览时看不到图，公式显示成源码**：

```
设 \(x\) 轴沿细棒向右……        ← 原样显示 \( \)
<svg viewBox="0 0 200 150">     ← 原样显示标签，没有画出图
  <line x1="15" y1="105" …/>
</svg>
```

## 2. 排查过程（先排除渲染引擎）

逐个验证，**都正常**，说明问题不在渲染能力而在「哪条 UI 分支被使用」：

| 验证对象 | 结果 |
|---|---|
| `richdoc.render_rich()`（引擎） | ✅ 6 个行间公式、`\boxed` 保留、SVG 1 个、19 个图元 |
| `richdoc.renderRich()`（PWA） | ✅ 同上 |
| 真实浏览器 + KaTeX | ✅ `katexErr=0`、23 个公式、SVG 227×170px 正常绘制 |
| `assist sheet html` 整份作业纸 | ✅ SVG 正常、`max-width:100%` 生效 |
| 答案版本库写入/回读 | ✅ `text` 原样保存（1598 字，含 `<svg>`） |
| KaTeX `renderMathInElement` 对含 SVG 的容器 | ✅ 不破坏图元 |
| `renderMathIn(el, force)` 用 innerHTML 还原 | ✅ 反复渲染结构稳定 |

## 3. 根因

`app/src/views/KbEditorView.vue` 的预览弹窗有**三个分支**，只有一个走了 `renderRich`：

| 分支 | 条件 | 原实现 | 结果 |
|---|---|---|---|
| 版本库答案 | `solShown` 存在 | `v-html="renderRich(solShown.text)"` | ✅ 正常 |
| **xlsx 旧列答案** | `solFallback` 存在 | `{{ solFallback }}`（**纯文本插值**） | ❌ **原样输出源码** |
| 题干 | 总是 | `{{ solContent }}`（**纯文本插值**） | ❌ 公式显示源码 |

**触发条件**：引擎离线，或该题**还没有版本库**（只存在于 xlsx `solution` 列）。
这时走 `solFallback` 分支，`<svg>` 被 Vue 当文本转义输出 → 看不到图；
`\(...\)` 也不会被 KaTeX 处理 → 显示成源码。**与用户现象完全一致。**

> 注：`solFallback` 注释写的是"旧列"，但 D105 之后 xlsx 列只是**纯文本摘要**；
> 老题库（D105 之前）的 solution 列里保存的仍是完整 md+html，因此这条分支必须渲染。

## 4. 修复

`KbEditorView.vue`：

- `solFallback` 分支：`{{ solFallback }}` → `v-html="renderRich(solFallback)"`；
- `solContent`（题干）分支：同样改走 `renderRich`（题干也可能含公式/图）；
- 保留原有 `solShown` / 编辑态实时预览的 `renderRich` 行为不变。

## 5. 验证

| 项 | 结果 |
|---|---|
| PWA 真实界面（Playwright，引擎离线 + 无版本库） | 修复前答案区是纯文本 `<span>`；修复后为 `<div>`，**SVG 正常绘制、23 个公式全部渲染** |
| app `vue-tsc -b` | 0 error |
| app `npm run selfcheck` | 全绿（新增 `selfcheck-d112-kb-solution-render.mjs`，24 项） |
| engine pytest | 613 passed |

## 6. 经验

同一份内容在 UI 里有多个渲染分支时，**必须逐个确认是否都走 `renderRich`**。
本次是"引擎离线/无版本库"这条**低频分支**漏了处理，而正常联网路径一直正常，
所以此前 D105/D109/D110 的回归用例都没覆盖到。
新增的自检用**静态断言**锁定三个分支，防止将来又退回纯文本插值。

---

## 7. 追加修复：公式里的 `<` 导致答案被截断（同日）

### 7.1 现象

题干含 `$R_1<R_2$` 这类**公式内部带 `<`** 的内容时，预览在 `$R_1` 之后就断了：

```
两个带有等量异号电荷的无限长同轴圆柱面,半径分别为$R_1$和$R_2$($R_1   ← 到此为止
```

### 7.2 根因

`richdoc._protect_math()` 先把公式抽成占位、Markdown 解析后再 `_restore_math()` 还原。
还原时**直接把公式原文插回 HTML**，于是 `$R_1<R_2$` 里的裸 `<` 被
bleach / DOMPurify 当成**标签开头**，把 `<R_2$),单位长度上的电荷为…` 整段当标签丢弃
→ 答案从 `$R_1` 后全部消失。

验证（`_sanitize('<p>$R_1$和$R_2$($R_1<R_2$)</p>')`）：

```
<p>$R_1$和$R_2$($R_1</p>     ← 后续被吞
```

PWA 侧 `restoreMath()` 是同一实现，同样截断。

### 7.3 修复

还原公式时先做 **HTML 转义**（`& < >`；`quote=False`，保留引号）：

```python
return _html.escape(math[idx], quote=False)
```

KaTeX 从文本节点读取时浏览器会自动 unescape，**公式计算不受影响**；
而 `<` 变成 `&lt;` 后不再被净化器误判为标签。

### 7.4 验证

| 项 | 结果 |
|---|---|
| 引擎 `render_rich` | 全文保留，`$R_1&lt;R_2$`、`$R_1&lt;r&lt;R_2$`、`$\\lambda$` 齐全 |
| PWA `renderRich` | 同上（与引擎同口径） |
| 真实浏览器 + KaTeX | **6 个公式全部渲染、`katexErr=0`**、结尾"并画出示意图"完整 |
| engine pytest | **617 passed**（新增 4 例：行内/行间 `<`、`&`、后续 SVG） |
| app selfcheck | 全绿（新增 `selfcheck-d112-math-escape.mjs`，25 项） |

### 7.5 教训

"占位符抽取—还原"这类做法，**还原时必须按目标上下文重新转义**。
此前 D105 引入该机制时只考虑了 `\\(` `\\[` 被 Markdown 吃掉的问题，
没有考虑公式内容本身含 HTML 元字符（`<` `&`）的情况。

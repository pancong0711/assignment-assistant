# D129：逐生审核公式预览 + 报告预览 KaTeX + 名单固定高度滚动

> 日期：2026-10-30
> 状态：**已执行完成**
> 关联：`docs/54-D101`（PWA 内联 KaTeX 渲染）、`docs/56-D103`、`docs/76-D127`

## 1. 现象

1. 逐生审核里 AI 转写出现了，但**公式显示 `$...$` 源码**，没有渲染；
2. 要求顺带检查「批阅预览」与「人工报告预览」是否也缺公式渲染；
3. 逐生审核名单希望**固定高度 + 滚轮滚动**（参照「班级与标签」名单表）。

## 2. 根因

**`renderRich()` 只做 Markdown→HTML + 白名单净化，本身不含 KaTeX。**

D127 里我把它当作"富文本渲染"直接用 `v-html` 输出，漏了第二步：

```js
// ❌ 只转换，不渲染公式 → 看到 $...$
el.innerHTML = renderRich(text)

// ✅ 转换 + 对容器跑 KaTeX（题库编辑器 D101 的正确做法）
el.innerHTML = renderRich(text)
await renderMathIn(el, true)
```

| 位置 | 原状态 | 说明 |
|---|---|---|
| 逐生审核 · AI 转写 | ❌ 无 KaTeX | 本次主问题 |
| 逐生审核 · AI 批语 | ❌ 无 KaTeX | 同一处遗漏 |
| 报告 HTML（`lib/reports.ts`） | ❌ 无 KaTeX | 题干/转录/评语都含 LaTeX，导出的报告公式也是源码 |
| 题库编辑器 / 作业纸预览 / 整班 HTML | ✅ 已有 | D101 已修，本次不受影响 |

> 注：`GradingView` 的「作业纸式报告预览」当前仍是 **demo 数据占位**（真数据未接入），
> 本次把它的 HTML 生成器补上了 KaTeX，真数据接入后即可直接显示公式。

## 3. 修复

| # | 改动 | 文件 |
|---|---|---|
| T1 | 转写区/批语区加 `ref`，内容或当前学生变化时 `renderMathIn(el, true)`（先清除 `data-katex-done` 再重渲染） | `StudentReviewModal.vue` |
| T2 | 报告 HTML 引入同源自托管 KaTeX（css + katex.min.js + auto-render）+ 自动渲染脚本（长定界符在前、幂等、失败降级源码） | `lib/reports.ts` |
| T3 | 逐生审核名单改为 `max-height:420px + overflow:auto` + 粘性表头（与「班级与标签」宽表同口径） | `AiGradingPanel.vue` |

## 4. 验收

| 项 | 结果 |
|---|---|
| 真实浏览器：转写正文渲染后 `.katex` 节点 ≥2、无残留 `$` 源码 | ✅ **4 处公式（含行间）** |
| `selfcheck-d129-katex-preview`（静态断言：引入/ref/幂等标记/报告带 KaTeX/名单滚动） | ✅ |
| `run-d129-katex-browser.sh`（真实 Chromium + 真实 KaTeX） | ✅ |
| engine pytest | 749 passed |
| app build | 0 error |
| app selfcheck | 全绿 |

## 5. 经验

**`v-html` + 公式 = 必须补第二步。** 以后任何"插入富文本"的地方都应按同一 checklist：

1. `renderRich()` 产生 HTML；
2. 插入 DOM 后 `renderMathIn(el, true)`；
3. 内容变化时先 `removeAttribute('data-katex-done')`，否则幂等标记会阻止重渲染；
4. 若有 iframe/srcdoc，还需在 HTML 里自带 KaTeX 资源 + 自动渲染脚本。

自检已把这条规则固化为断言（`selfcheck-d129`），并有真实浏览器兜底。

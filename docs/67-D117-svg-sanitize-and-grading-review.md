# D117 缺陷修复：SVG 在 PWA 里空白（DOMPurify 全局 URI 正则）+ 逐生审核空白 + 作业纸设计排版

> 日期：2026-10-28
> 状态：已实现并验证
> 关联：`docs/65-D113`（参考答案预览）、`docs/66-D116`（批阅 tags）、`docs/62-D110`

## 1. SVG 空白：真正的根因（前几轮为什么没修好）

### 1.1 根因

`app/src/lib/richdoc.ts` 的 DOMPurify 配置里：

```ts
ALLOWED_URI_REGEXP: /^data:image\/...(base64)...$/i,
```

**它是全局生效的**：DOMPurify 会对**所有属性值**跑这个正则，而不只是 `src`/`href`。
于是 `viewBox="0 0 200 150"`、`width="60mm"`、`cx="100"`、`r="35"`、`stroke="black"`
全都不匹配 `data:image/...` → **被当成非法 URI 全部剥掉**：

```html
<!-- sanitize 前 -->
<svg viewBox="0 0 200 150" width="60.0mm" height="45.0mm">
  <circle cx="100" cy="75" r="35" stroke="black" fill="none"/>
</svg>

<!-- 浏览器里实际输出 -->
<svg xmlns="http://www.w3.org/2000/svg"><circle></circle></svg>
```

SVG 变成**没有任何几何信息的空壳** → 页面上就是「一片空白」。
任何公式/题图都正常（它们是文本/`src`），所以症状看起来"只有图不行"。

**引擎侧（bleach）不受影响**：`protocols=["data"]` 只检查 URI 类属性，
所以 `assist` 产出的 HTML 一直是对的 —— 这也解释了「CLI 正常、PWA 坏」。

### 1.2 为什么前几轮一直没修掉（反省）

| 轮次 | 做法 | 为什么没发现 |
|---|---|---|
| D109 | 修 `nl2br` 往 `<svg>` 塞 `<br>` | 真问题，但不是这个 |
| D110 | 修 `force` 重渲染用 `textContent` 抹掉标签 | 真问题，但不是这个 |
| D112 | 修公式 `<` 截断 | 真问题，但不是这个 |
| D113 | 修测量探针 `textContent` | 真问题（影响排版），但不是这个 |
| D115 | 补题图 `imgPath` | 真问题，但不是这个 |

**共同的方法错误**：每轮都在 **Node/引擎侧** 断言 `renderRich()` / `render_rich()` 的**字符串输出**。
而 `richdoc.ts` 在无 DOM 时会走 `sanitizeWithoutDom()` 兜底，**那段会剥属性的 DOMPurify 配置根本不会执行**。
所以每次结论都是"渲染正常"，问题被一次次漏过。

**正确做法**（本轮）：在**真实浏览器 + 真实 DOMPurify** 下断言 DOM 的
`getAttribute('viewBox')` / 渲染宽度。二分实验直接定位到唯一元凶：

| 配置 | 结果 |
|---|---|
| 只 `ALLOWED_TAGS` + `ALLOWED_ATTR` | ✔ 属性完整 |
| `+ALLOW_DATA_ATTR:false` | ✔ |
| **`+ALLOWED_URI_REGEXP`** | **✘ 属性全丢** |
| `+FORBID_TAGS` / `+FORBID_ATTR` / `+USE_PROFILES` | ✔ |

### 1.3 修复

删掉全局 `ALLOWED_URI_REGEXP`，改用 hook **只校验 `src`**：

```ts
DOMPurify.addHook('uponSanitizeAttribute', (_n, data) => {
  if (String(data.attrName || '').toLowerCase() === 'src') {
    if (!DATA_IMG_RE.test(String(data.attrValue || '').trim())) data.keepAttr = false
  }
})
try { return DOMPurify.sanitize(parsed, {...}) } finally { DOMPurify.removeAllHooks() }
```

实测：`viewBox/width/height/cx/r/stroke/fill` 全部保留，`<img src="data:image/...">` 仍放行，
外链 `src` 仍被拦截。

### 1.4 验证（用户那条"带 SVG 的 AI 参考答案"）

| 界面 | 结果 |
|---|---|
| 题库编辑器 🔍 答案预览 | `viewBox="0 0 200 150"`、`width=60mm`、**227×170px**、2 圆 + 7 文字 + 2 线 |
| 作业纸设计 › 参考答案预览 | 同上（227×170、2 圆、7 文字）、7 个公式、0 错误 |
| 引擎/CLI | 本来就正常（bleach protocols） |

## 2. 逐生审核区空白（功能并非占位，是没加载数据）

### 2.1 确认：功能是完整的

弹窗实测可用：`← 上一位 / 下一位 →`、旋转、上下布局、AI 批语（只读基线）、
「另存修订版」、人工批阅（4 种模式）。**不是占位。**

### 2.2 根因

`students` 只在 `loadStudents()` 里填充，而它原只有三个触发点：
作业下拉的 `@change`、批阅完成回调、上传后。

问题：**`loadWorks()` 是代码自动赋值 `workKey.value`，不会触发 `@change`**；
`onMounted` 也没有调用 `loadStudents()`。
→ 进页面（以及自动选中作业后）学生清单**永远为空** → 表格不渲染（`v-if="students.length"`）
→ 只显示一句"（未选作业或该作业无学生清单）"，**没有任何「审核」按钮**。

用户"点了开始 AI 批阅没变化"也是这个原因之一：批阅完成后虽调了 `loadStudents()`，
但若 `workKey` 有值、接口正常，本应能刷新；而先前因学生清单从未加载，
"逐生审核"区在批阅前后看起来都一样空。

### 2.3 修复

- 新增 `watch(workKey)`：选中即加载学生+草稿（覆盖代码自动赋值）；
- `onMounted` 里补 `if (workKey) void loadStudents()`；
- 空态改为**可诊断**：区分「未选作业 / 正在读取 / 该作业无学生清单」，
  并给「重新读取」按钮；
- 新增 `studentsLoading` 状态。

### 2.4 验证

| 项 | 结果 |
|---|---|
| 修复前（真实浏览器 + mock 引擎） | `reviewButtons: 0`，提示"无学生清单" |
| 修复后 | `reviewButtons: 2`；点击「审核」弹窗正常打开（标题"逐生审核：张三（第 1 / 2 位）"） |
| 批阅完成 | 提示"✅ AI 批阅完成（结果已写入本地批阅草稿，可在下方逐生审核）"且表格就绪 |

## 3. 作业纸设计排版：改整行单列（R4 补齐）

用户反馈：各栏多列并排，高度不一致导致大量空白。

原 D113-R4 只改了 `SheetPreviewSection` 一处，遗漏：

| 文件 | 原布局 | 改为 |
|---|---|---|
| `SheetLayoutView.vue` | `display:flex` + `flex:0 0 380px` 两栏并排 | `flex-direction:column; align-items:stretch` + `width:100%` |
| `SheetContentView.vue` | 同上（400px / 500px） | 同上 |

实测：`form / items / preview-block / answer-preview-block / output-block`
全部单列、占满整行（1240px）。

> 按用户要求，`PlaygroundPanel`（属「AI 辅助批阅」侧）**未改动**。

## 4. 新增自检（关键：能在浏览器里抓到这类 bug）

| 自检 | 作用 |
|---|---|
| `tests/selfcheck-d117-svg-sanitize.mjs` | 静态哨兵：禁止 `ALLOWED_URI_REGEXP`、要求 hook 只校验 src、白名单含几何属性、引擎用 protocols |
| `tests/run-d117-browser.sh` | **真实浏览器 + 真实 DOMPurify**：断言 `viewBox/width/height/cx/r` 保留、渲染宽度 > 0、`data:image` 放行 |

> 已验证自检确实能抓到原 bug：临时把 `ALLOWED_URI_REGEXP` 加回去，
> `run-d117-browser.sh` 立即失败；还原后通过。

## 5. 全量验证

| 项 | 结果 |
|---|---|
| engine pytest | 631 passed |
| app `vue-tsc -b` / `npm run build` | 0 error |
| app `npm run selfcheck` | **29 项全绿**（含新增 d117 两项） |
| 脱敏 / bat lint | 通过 |

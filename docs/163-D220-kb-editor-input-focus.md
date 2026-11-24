# D220 修复：题库编辑器里 id 栏每输一个字就失焦

> 日期：2026-11-23
> 状态：**已完成（2026-11-23）**
> 关联：`docs/162-D219`（本轮批次）
>
> 隐私：无学生数据。

---

## 0. 现场

题库编辑器点「＋新增一行（题）」后，在 **id** 栏输入时：

> 每次只能输入一个字，然后要重新点击该格，再输入一个字。

教师同时提出期望：**一次输入多字不中断；点「写回」才保存。**

## 1. 根因

表格行的 `v-for` key 把**正在编辑的字段**拼了进去：

```html
<tr v-for="(r, idx) in visibleRows" :key="r.id + idx">
```

Vue 的 key 变化 = 该行被视为**新节点** → 销毁并重建整行 DOM（含 input）。
于是每敲一个字符：

```
r.id 变化 → key 变化 → <tr> 重建 → input 失焦
```

其它列（content/related…）也一样会受影响，只是 id 最明显。

## 2. 修复

### R1. 行 key 改用「行对象身份」，与可编辑值无关

新增 `app/src/lib/stableRowKey.ts`：

```ts
export function createRowKeyer() {
  const keys = new WeakMap<object, string>()
  let seq = 0
  return function rowKey(r: any, idx = 0): string {
    if (!r || typeof r !== 'object') return `i${idx}`
    let k = keys.get(r)
    if (!k) { k = `rk${++seq}`; keys.set(r, k) }
    return k
  }
}
```

模板改为：

```html
<tr v-for="(r, idx) in visibleRows" :key="rowKey(r, idx)">
```

行为：

| 场景 | key |
|---|---|
| 同一行对象，编辑 id/content… | **不变** → 不重建 → 不失焦 |
| 新增一行（新对象） | 新 key（正确渲染新行） |
| 重新载入 xlsx（全新对象） | 新 key（正确重建） |

### R2. 保存分层（符合教师预期）

| 层 | 时机 | 作用 |
|---|---|---|
| 内存 | 每次输入（`v-model`） | 连续输入不中断 |
| 浏览器草稿 | 单元格**失焦**（`@change`）→ `persistDebounced()` | 误关页面不丢；防抖避免大题库卡顿 |
| **xlsx 文件** | 点 **「写回 …xlsx」** | 真正落盘；也可「导出副本」另存 |

> `persist()` 仍是同步全量写 localStorage，用于结构变更（增/删行）；
> 文本编辑统一走 `persistDebounced()`（400ms）。

## 3. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 在 id 栏连续输入 `NEW-123` | 一次输完，不失焦 |
| 2 | content/related 等列 | 同样不失焦 |
| 3 | 新增一行 | 新行正常出现、可编辑 |
| 4 | 失焦后刷新页面 | 草稿仍在（localStorage） |
| 5 | 点「写回」 | 才写入 xlsx 文件 |
| 6 | 回归 | 前端 build + selfcheck 通过 |

## 4. 测试

`app/tests/selfcheck-d220-kb-editor-input-focus.mjs`：

- 静态：模板不再用 `r.id + idx` 作 key；改用 `rowKey(r, idx)`；引用 `stableRowKey` 模块；
- **行为**：同一行对象改 `id` 后 key 必须不变；新对象必须换 key；非对象有回退 key；
- 保存分层：编辑用 `persistDebounced()`，仍保留「写回」。

已接入 `npm run selfcheck`。

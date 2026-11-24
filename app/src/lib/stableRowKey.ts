/** D220：表格行的**稳定 key**（与行内可编辑字段无关）。
 *
 * 背景：题库编辑器原来用 `r.id + idx` 当 `v-for` 的 key。教师在 id 栏每输入一个
 * 字符，`r.id` 变化 → key 变化 → Vue 销毁并重建整行 DOM → 输入框失焦，
 * 只能“输入一个字、重新点一次格子”。
 *
 * 用 `WeakMap` 绑定**行对象身份**：编辑字段不换 key；重新载入/新增行产生新对象
 * 才会换 key（此时确实需要重建）。
 */
export function createRowKeyer() {
  const keys = new WeakMap<object, string>()
  let seq = 0
  return function rowKey(r: any, idx = 0): string {
    if (!r || typeof r !== 'object') return `i${idx}`
    let k = keys.get(r)
    if (!k) {
      k = `rk${++seq}`
      keys.set(r, k)
    }
    return k
  }
}

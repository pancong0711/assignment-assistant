// D170-T2：重载题库不再卡死（只替换当前 kind + 防抖持久化）。
//
// 教师现象：点「从引擎重载题库」后页面卡住；知识点其实已写回，只是看不到。
// 根因：整体替换所有题库 + 同步写 localStorage，大题库阻塞主线程。
import assert from 'node:assert/strict'
import { createPinia, setActivePinia } from 'pinia'
import { useKbStore } from './d170-kb.bundle.mjs'

// 最小 localStorage shim（node 环境）
const store = new Map()
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
  clear: () => store.clear(),
}
globalThis.window = globalThis

setActivePinia(createPinia())
const kb = useKbStore()

/* 构造一个"大"题库响应：qa 300 行，problems 50 行 */
const mkRows = (n, prefix) => Array.from({ length: n }, (_, i) => ({
  id: `${prefix}-${i}`, content: `题 ${i}`, related: `知识点${i}`,
  solution: '', img_path: '', page: '', type: '', note: '',
}))
const raw = {
  problems: { chap01: mkRows(50, 'p') },
  qa: { chap01: mkRows(300, 'q') },
}

// 1) 只重载当前 kind：其它 kind 保持不变
const beforeProblems = kb.books['problems']
const t0 = Date.now()
const n = kb.adoptEngineKb(raw, { onlyKind: 'qa' })
const elapsed = Date.now() - t0
assert.equal(n, 300, '只应统计 qa 的 300 行')
assert.equal(kb.books['qa'].chapters[0].rows.length, 300)
assert.equal(kb.books['qa'].chapters[0].rows[0].related, '知识点0', 'related 必须带回')
assert.ok(elapsed < 500, `只换单个 kind 应很快（实际 ${elapsed}ms）`)
// problems 未被触碰（同一个对象引用）
assert.equal(kb.books['problems'], beforeProblems, '未指定的 kind 不应被替换')

// 2) related 里的知识点确实写进了 store（教师"看不到"的另一半：前端数据要正确）
assert.ok(kb.books['qa'].chapters[0].rows.every((r) => r.related.startsWith('知识点')))

// 3) 全量替换仍可用（旧行为保留）
const n2 = kb.adoptEngineKb(raw)
assert.equal(n2, 350, '全量时应统计 50+300')

// 4) persistDebounced 不阻塞（同步返回）
const t1 = Date.now()
kb.persistDebounced(10)
assert.ok(Date.now() - t1 < 100, 'persistDebounced 必须立即返回（不阻塞）')

await new Promise((r) => setTimeout(r, 50))
assert.ok(store.get('assignment-assistant.kb.v1'), '防抖后应最终写入 localStorage')

console.log('OK d170-kb-reload：只换当前 kind · 未指定 kind 不动 · related 带回 · 防抖持久化')

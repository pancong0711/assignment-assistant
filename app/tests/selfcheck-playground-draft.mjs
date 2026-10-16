/** D91-M4 自检：Playground 输入草稿自动保存/恢复（镜像组件中的 draft 逻辑）。 */
import assert from 'node:assert'

const KEY = 'assignment-assistant.playground.draft.v1'
const stub = new Map()
const localStorage = {
  getItem: (k) => (stub.has(k) ? stub.get(k) : null),
  setItem: (k, v) => stub.set(k, String(v)),
  removeItem: (k) => stub.delete(k),
}

function saveDraft(d) { try { localStorage.setItem(KEY, JSON.stringify(d)) } catch {} }
function loadDraft() {
  try { const d = JSON.parse(localStorage.getItem(KEY) ?? 'null'); return (d && typeof d === 'object') ? d : null }
  catch { return null }
}

const draft = {
  provider: 'aliyun', model: 'qwen-max', customModel: false, temperature: 0.3,
  folder: '默认', batchMode: false, question: '什么是熵？$S=k\\ln W$',
  batchText: '', attachments: [{ name: 'a.pdf', path: '/x/a.pdf', kind: 'pdf' }],
}
saveDraft(draft)
const back = loadDraft()
assert.equal(back.provider, 'aliyun')
assert.equal(back.model, 'qwen-max')
assert.equal(back.question, '什么是熵？$S=k\\ln W$')
assert.equal(back.attachments[0].name, 'a.pdf')
console.log('1) 草稿保存/恢复（含 LaTeX 文本与附件）… ok')

// 清空
localStorage.removeItem(KEY)
assert.equal(loadDraft(), null)
console.log('2) 清空草稿… ok')

// 损坏 JSON 容错
localStorage.setItem(KEY, '{{{bad')
assert.equal(loadDraft(), null)
console.log('3) 损坏草稿容错（返回 null，不抛错）… ok')

console.log('\nD91-M4 Playground 草稿自检通过 ✔')

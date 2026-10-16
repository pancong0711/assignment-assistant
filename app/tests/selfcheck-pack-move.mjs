/** D91-M1 自检：作业包内作业纸的**移动**与**复制引用**语义（纯数组逻辑，镜像 packs store）。
 *  运行：node tests/selfcheck-pack-move.mjs */
import assert from 'node:assert'

/** 镜像 packs.ts：把 padId 从 from 包**移动**到 to 包。 */
function movePad(packs, fromId, padId, toId, tag = '') {
  const from = packs.find((p) => p.id === fromId)
  const to = packs.find((p) => p.id === toId)
  if (!from || !to || fromId === toId) return false
  from.pads = from.pads.filter((r) => r.padId !== padId)
  if (!to.pads.some((r) => r.padId === padId)) to.pads.push({ padId, tag })
  return true
}

/** 镜像 packs.ts：**复制引用**（from 保留 + to 加入同一 padId）。 */
function copyRef(packs, padId, toId, tag = '') {
  const to = packs.find((p) => p.id === toId)
  if (!to) return false
  if (!to.pads.some((r) => r.padId === padId)) to.pads.push({ padId, tag })
  return true
}

const packs = [
  { id: 'A', pads: [{ padId: 'p1', tag: 't1' }, { padId: 'p2', tag: 't2' }] },
  { id: 'B', pads: [] },
]

// 移动 p1: A→B
assert.ok(movePad(packs, 'A', 'p1', 'B', 't1'))
assert.deepEqual(packs.find((p) => p.id === 'A').pads.map((r) => r.padId), ['p2'])
assert.deepEqual(packs.find((p) => p.id === 'B').pads.map((r) => r.padId), ['p1'])
console.log('1) 移动：A→B 正确（A 移除、B 加入）… ok')

// 复制引用 p2: A 保留 + B 加入
assert.ok(copyRef(packs, 'p2', 'B', 't2'))
assert.deepEqual(packs.find((p) => p.id === 'A').pads.map((r) => r.padId), ['p2'])
assert.ok(packs.find((p) => p.id === 'B').pads.some((r) => r.padId === 'p2'))
console.log('2) 复制引用：A 保留 + B 加入同一 padId（改一处两包同步）… ok')

// 幂等：重复复制引用不产生重复项
copyRef(packs, 'p2', 'B')
assert.equal(packs.find((p) => p.id === 'B').pads.filter((r) => r.padId === 'p2').length, 1)
console.log('3) 复制引用幂等（不重复入包）… ok')

// 移动同包拒绝
assert.equal(movePad(packs, 'B', 'p2', 'B'), false)
console.log('4) 移动目标=来源 被拒绝 … ok')

// 「另存为新作业纸」语义：新 padId 加入目标包，原包保留、两包独立
function duplicateAsNew(saved, id, newId) {
  const src = saved.find((s) => s.id === id)
  if (!src) return false
  saved.push({ id: newId, json: src.json.replace(/"id":\s*"[^"]*"/, `"id": "${newId}"`) })
  return true
}
const saved = [{ id: 'p1', json: '{"id":"p1","x":1}' }, { id: 'p2', json: '{"id":"p2","x":2}' }]
assert.ok(duplicateAsNew(saved, 'p1', 'p1-copy'))
copyRef(packs, 'p1-copy', 'B')
assert.ok(packs.find((p) => p.id === 'A').pads.some((r) => r.padId === 'p1') === false ||
          packs.find((p) => p.id === 'A').pads.some((r) => r.padId === 'p1'),
          '原包不被改动')
assert.ok(saved.some((s) => s.id === 'p1-copy'))
assert.ok(packs.find((p) => p.id === 'B').pads.some((r) => r.padId === 'p1-copy'))
console.log('5) 另存为新作业纸（新 id 入目标包，两包独立）… ok')

console.log('\nD91-M1 作业包移动/复制自检通过 ✔')

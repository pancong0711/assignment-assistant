/** D97 自检：逐目标班「已发布」判定 + 默认时间(now+5min/+5days)。 */
import assert from 'node:assert'

// 逐班已发布（镜像 publishedPickedClasses/workPublished/publishWork 跳过逻辑）
function publishedPicked(work, picked) {
  const set = new Set(work.publishedClasses || [])
  return picked.filter((c) => set.has(c.classId)).map((c) => c.classId)
}
function workPublished(work, picked) {
  if (!picked.length) return false
  const pub = new Set(publishedPicked(work, picked))
  return picked.every((c) => pub.has(c.classId))
}
const picked = [{ classId: 'A' }, { classId: 'B' }]

// 1) 只有旧届班(不在勾选)发过 → 不误报
assert.equal(workPublished({ publishedClasses: ['OLD'] }, picked), false, '旧届班发过不应误报')
console.log('1) 仅其他(未勾选)班发过 → 不误报 … ok')

// 2) 都未发
assert.deepEqual(publishedPicked({ publishedClasses: [] }, picked), [])
assert.equal(workPublished({ publishedClasses: [] }, picked), false)
console.log('2) 勾选班都未发 … ok')

// 3) 部分已发：A 发过 → 只发布 B（跳过 A）
const w = { publishedClasses: ['A'] }
const pub = new Set(publishedPicked(w, picked))
const unpub = picked.filter((c) => !pub.has(c.classId)).map((c) => c.classId)
assert.deepEqual(unpub, ['B'], '跳过已发 A，仅发 B')
assert.equal(workPublished(w, picked), false, '未全发 → 允许')
console.log('3) 部分已发 → 只发未发班（跳过已发）… ok')

// 4) 全部已发 → 禁止
assert.equal(workPublished({ publishedClasses: ['A', 'B'] }, picked), true)
console.log('4) 全部已发 → 禁止 … ok')

// 5) 默认时间 now+5min / now+5days
const now = Date.now()
const start = now + 5 * 60_000
const end = now + 5 * 24 * 3600_000
assert.ok(start > now && start - now === 5 * 60_000, 'start=now+5min')
assert.ok(end - now === 5 * 24 * 3600_000, 'end=now+5days')
console.log('5) 默认时间 now+5min / +5days … ok')

console.log('\nD97 逐班已发布 + 默认时间自检通过 ✔')

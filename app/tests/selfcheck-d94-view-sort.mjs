/** D94-T3 自检：按加权成绩 升/降序（视图层；默认点名册；无成绩末尾；稳定）。 */
import assert from 'node:assert'

function sortedIdx(arr, scores, sort) {
  const idx = arr.map((_, i) => i)
  if (sort === 'roster') return idx
  const scoreOf = (i) => (scores[`${arr[i].name}\u0000${arr[i].number}`] ?? null)
  return idx.slice().sort((a, b) => {
    const sa = scoreOf(a), sb = scoreOf(b)
    const ha = typeof sa === 'number', hb = typeof sb === 'number'
    if (ha && hb) { const d = sa - sb; return sort === 'desc' ? -d : d }
    if (ha !== hb) return ha ? -1 : 1
    return a - b
  })
}
const stu = [
  { name: 'A', number: '01' }, { name: 'B', number: '02' },
  { name: 'C', number: '03' }, { name: 'D', number: '04' },
]
const scores = { 'A\u000001': 70, 'B\u000002': 95, 'C\u000003': 80 }  // D 无成绩
const names = (sort) => sortedIdx(stu, scores, sort).map((i) => stu[i].name)
assert.deepEqual(names('roster'), ['A', 'B', 'C', 'D'], '默认点名册顺序')
assert.deepEqual(names('desc'), ['B', 'C', 'A', 'D'], '降序（D 无成绩末尾）')
assert.deepEqual(names('asc'), ['A', 'C', 'B', 'D'], '升序（D 无成绩末尾）')
console.log('1) 视图排序 点名册/降序/升序（无成绩末尾）… ok')

console.log('\nD94-T3 视图排序自检通过 ✔')

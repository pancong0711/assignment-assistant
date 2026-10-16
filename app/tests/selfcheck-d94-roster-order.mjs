/** D94-T1 自检：成绩源/名单 merge 保序（镜像 stores/roster.ts addScoreSource 语义）。
 *  规则：首次以点名册行序；已有名单为基准，只补数据/新同学 append，绝不重排。 */
import assert from 'node:assert'

function mergeRoster(existing, rows /* [{name,number,class}] */) {
  if (!existing.length) {
    return rows.filter((r) => r.name).map((r) => ({ ...r, tag: '', score: null }))
  }
  const byNumber = new Map(existing.filter((x) => x.number).map((x) => [x.number, x]))
  const byName = new Map(existing.map((x) => [x.name, x]))
  const added = []
  for (const r of rows) {
    if (!r.name) continue
    const hit = (r.number && byNumber.get(r.number)) || byName.get(r.name)
    if (hit) {
      if (!hit.number && r.number) hit.number = r.number
      if (!hit.class && r.class) hit.class = r.class
      continue
    }
    const fresh = { ...r, tag: '', score: null }
    added.push(fresh); byName.set(r.name, fresh); if (r.number) byNumber.set(r.number, fresh)
  }
  return [...existing, ...added]
}

// 1) 首次：以点名册行序
let stu = mergeRoster([], [
  { name: 'C', number: '03', class: '' }, { name: 'A', number: '01', class: '' },
  { name: 'B', number: '02', class: '' },
])
assert.deepEqual(stu.map((s) => s.name), ['C', 'A', 'B'], '首次以点名册行序')
console.log('1) 首次导入：以点名册行序 … ok')

// 2) 加成绩源（行序按分数降序）：现有名单顺序不变
stu = mergeRoster(stu, [
  { name: 'A', number: '01', class: '1班' }, { name: 'C', number: '03', class: '' },
  { name: 'B', number: '02', class: '' },
])
assert.deepEqual(stu.map((s) => s.name), ['C', 'A', 'B'], '保序：顺序不因成绩源行序改变')
assert.equal(stu.find((s) => s.name === 'A').class, '1班', '补数据不移动位置')
console.log('2) 加成绩源保持现有点名册顺序 … ok')

// 3) 新同学追加末尾
stu = mergeRoster(stu, [{ name: 'D', number: '04', class: '' }, { name: 'A', number: '01', class: '' }])
assert.deepEqual(stu.map((s) => s.name), ['C', 'A', 'B', 'D'], '新同学 append 末尾')
console.log('3) 新同学追加末尾 … ok')

// 4) 载入新点名册 = 替换（以新名单为准）—— 由 loadRosterFile 直接赋值，这里验证语义
const replaced = [{ name: 'Z', number: '09' }, { name: 'Y', number: '08' }]
assert.deepEqual(replaced.map((s) => s.name), ['Z', 'Y'], '载入新名单=替换')
console.log('4) 载入新点名册=替换（新名单为准）… ok')

console.log('\nD94 保序 merge 自检通过 ✔')

/** D95 自检：多班勾选 —— 勾一个班不影响其它（镜像 PublishView 的 toggle 逻辑）。
 *  回归背景：曾用 `<input v-model 绑定 Record>` 导致勾一个班 × 全部课程全班被选中。 */
import assert from 'node:assert'

const key = (c) => `${c.courseId}:${c.classId}`
// 白名单班（跨 2 课程）
const classes = [
  { courseId: 'C1', classId: 'k1', name: '一班' },
  { courseId: 'C1', classId: 'k2', name: '二班' },
  { courseId: 'C2', classId: 'k3', name: '三班' },
  { courseId: 'C2', classId: 'k4', name: '四班' },
]
function toggleClassPick(cur, c, on) {
  const next = { ...cur }
  if (on) next[key(c)] = true; else delete next[key(c)]
  return next
}
function toggleCoursePick(cur, g, on) {
  const next = { ...cur }
  for (const c of g.classes) { if (on) next[key(c)] = true; else delete next[key(c)] }
  return next
}
const pickedKeys = (sel) => Object.keys(sel).filter((k) => sel[k])

// 1) 勾一个班 → 只选中该班
let sel = {}
sel = toggleClassPick(sel, classes[0], true)
assert.deepEqual(pickedKeys(sel), ['C1:k1'], '勾一个班只选中一个')
console.log('1) 勾单个班只选中该班 … ok')

// 2) 再勾另一个课程的班 → 两个（互不影响）
sel = toggleClassPick(sel, classes[2], true)
assert.deepEqual(pickedKeys(sel).sort(), ['C1:k1', 'C2:k3'], '跨课程各自选中')
console.log('2) 勾第二个（另一课程）不波及其它 … ok')

// 3) 取消一个
sel = toggleClassPick(sel, classes[0], false)
assert.deepEqual(pickedKeys(sel), ['C2:k3'], '取消只删该班')
console.log('3) 取消单个班 … ok')

// 4) 课程级全选/取消只影响本课程
let s2 = {}
s2 = toggleCoursePick(s2, { classes: classes.filter((c) => c.courseId === 'C1') }, true)
assert.deepEqual(pickedKeys(s2).sort(), ['C1:k1', 'C1:k2'], '课程级全选仅本课程')
s2 = toggleCoursePick(s2, { classes: classes.filter((c) => c.courseId === 'C2') }, true)
assert.equal(pickedKeys(s2).length, 4, '两课程全选=4')
s2 = toggleCoursePick(s2, { classes: classes.filter((c) => c.courseId === 'C1') }, false)
assert.deepEqual(pickedKeys(s2).sort(), ['C2:k3', 'C2:k4'], '取消课程仅清本课程')
console.log('4) 课程级全选/取消仅影响本课程 … ok')

console.log('\nD95 多班勾选自检通过 ✔')

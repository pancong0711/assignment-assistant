/** D96 自检：作业来源课程 → 基准班（(courseId,cpi)）+ 发布限同课程守卫。 */
import assert from 'node:assert'
const key = (c) => `${c.courseId}:${c.classId}`

// 勾选班（跨 2 课程）
const picks = [
  { courseId: 'C1', courseName: '课1', classId: 'k1', cpi: '11' },
  { courseId: 'C1', courseName: '课1', classId: 'k2', cpi: '11' },
  { courseId: 'C2', courseName: '课2', classId: 'k3', cpi: '22' },
]
function pickedCourses(picks) {
  const seen = {}
  for (const c of picks) seen[c.courseId] = seen[c.courseId] || { courseId: c.courseId, courseName: c.courseName }
  return Object.values(seen)
}
function baseClass(picks, sourceCourseId) {
  const cid = sourceCourseId || picks[0]?.courseId || ''
  return picks.find((c) => c.courseId === cid)
}
function crossCourse(picks) { return new Set(picks.map((c) => c.courseId)).size > 1 }

// 1) 来源课程列表 = 勾选班涉及的课程（去重）
assert.deepEqual(pickedCourses(picks).map((c) => c.courseId), ['C1', 'C2'], '来源课程去重')
console.log('1) 来源课程列表（去重）… ok')

// 2) 选 C2 → 基准班 = k3（cpi 22）；选 C1 → k1（cpi 11）
assert.equal(baseClass(picks, 'C2').classId, 'k3')
assert.equal(baseClass(picks, 'C2').cpi, '22')
assert.equal(baseClass(picks, 'C1').classId, 'k1')
assert.equal(baseClass(picks, 'C1').cpi, '11')
console.log('2) 基准班随来源课程切换（决定作业库 cpi）… ok')

// 3) 未选来源 → 默认第一个勾选班的课程
assert.equal(baseClass(picks, '').courseId, 'C1')
console.log('3) 未选来源课程 → 默认第一个勾选班课程 … ok')

// 4) 跨课程守卫
assert.equal(crossCourse(picks), true)
assert.equal(crossCourse(picks.filter((c) => c.courseId === 'C1')), false)
console.log('4) 跨课程识别（发布限同课程）… ok')

console.log('\nD96 作业来源课程自检通过 ✔')

/** D184 前端自检：审计采用 tag 的 UPSERT / missing 可见性 / studentId 透传。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const panel = fs.readFileSync(join(appRoot, 'src/components/AiGradingPanel.vue'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []

// 1) 下载名单的 studentId 必须保留
if (!/studentId:\s*String\(s\.studentId \|\| ''\)/.test(panel)) {
  errors.push('students.value 未保留下载名单 studentId')
}
// 2) apply 时至少有一条路径把 number 传给后端
if (!/number:\s*String\(s\.studentId \|\| ''\)/.test(panel)) {
  errors.push('applyAuditChecked 未传 number/studentId')
}
// 3) 详情“采纳审计”需要通过名单补齐 studentId
if (!/const stu = students\.value\.find/.test(panel)) {
  errors.push('applyAuditOne 未从下载名单补齐 studentId')
}
// 4) missing 必须显式显示，不能伪装成没有变化
if (!/const missing = r\.missing \|\| \[\]/.test(panel)) {
  errors.push('applyAuditChanges 未读取 missing')
}
if (!/以下学生未找到，未写入/.test(panel)) {
  errors.push('applyAuditChanges 未显示 missing 错误')
}
// 5) selfcheck 必须接入 npm run selfcheck
if (!String(pkg.scripts?.selfcheck || '').includes('selfcheck:d184')) {
  errors.push('selfcheck 链未接入 selfcheck:d184')
}

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ students 保留 studentId')
console.log('✓ apply 路径透传 number/studentId')
console.log('✓ 详情采纳从下载名单补齐 studentId')
console.log('✓ missing 显式错误提示')
console.log('✓ D184 selfcheck 已接入 npm run selfcheck')
console.log('D184 前端自检通过')

/** D187：一键生成报告作用域 + 强制重做复选框 UI 静态自检。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const panel = fs.readFileSync(join(__dirname, '..', 'src/components/AiGradingPanel.vue'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(__dirname, '..', 'package.json'), 'utf8'))
const errors = []

if (!/classDir:\s*curWorkDir\.value/.test(panel)) {
  errors.push('renderReports 未传 classDir=curWorkDir')
}
if (!/taskId\s*=\s*packId\.value \|\| padId\.value \|\| resolvedScope\.value/.test(panel)) {
  errors.push('renderReports 未使用 resolvedScope 兜底 taskId')
}
if (/<input type="checkbox" v-model="forceRedo" \/>\s*☑/.test(panel)) {
  errors.push('强制重做仍保留静态 ☑，UI 会显示两个勾选框')
}
if (!/强制重做（覆盖已有结果，会重新花额度）/.test(panel)) {
  errors.push('强制重做文案缺失')
}
if (!String(pkg.scripts?.selfcheck || '').includes('selfcheck:d187')) {
  errors.push('selfcheck 链未接入 selfcheck:d187')
}
if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 一键生成报告携带 classDir')
console.log('✓ 一键生成报告使用 resolvedScope 兜底 taskId')
console.log('✓ 强制重做只保留一个真实 checkbox')
console.log('✓ D187 selfcheck 已接入 npm run selfcheck')

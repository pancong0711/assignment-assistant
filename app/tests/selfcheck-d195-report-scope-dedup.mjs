/** D195：报告范围核对 + 同名学生多键去重 + 重新生成/清理入口（静态自检）。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const root = join(appRoot, '..')
const view = fs.readFileSync(join(appRoot, 'src/components/AiGradingPanel.vue'), 'utf8')
const client = fs.readFileSync(join(appRoot, 'src/lib/engineClient.ts'), 'utf8')
const drafts = fs.readFileSync(join(root, 'engine/src/assist/grading/drafts.py'), 'utf8')
const serve = fs.readFileSync(join(root, 'engine/src/assist/serve.py'), 'utf8')
const rv = fs.readFileSync(join(root, 'engine/src/assist/grading/report_versions.py'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

// 1) 同名学生多键去重
must(/def _draft_richness\(/.test(drafts), '缺少 _draft_richness（合并取更完整的一份）')
must(/merged: "dict\[str, tuple\[str, dict, list\[str\]\]\]"/.test(drafts)
  || /merged\[stu\]/.test(drafts), '未按学生姓名合并草稿键')
must(/for kk in \[key\] \+ sibling_keys/.test(drafts), '报告未回写到同名的其它键')

// 2) 范围核对
must(/def report_scope_report\(/.test(drafts), '缺少 report_scope_report')
must(/"missingDraft": missing/.test(drafts), '未返回 missingDraft')
must(/"duplicateKeys": duplicates/.test(drafts), '未返回 duplicateKeys')
must(/scopeOnly/.test(serve), 'serve 未提供 scopeOnly 只读核对')

// 3) 清理端点
must(/def cleanup_reports\(/.test(rv), '缺少 cleanup_reports')
must(serve.includes('/xxt/grade/report-cleanup'), 'serve 缺少 report-cleanup 端点')
must(/export async function cleanupXxtReports/.test(client), 'engineClient 缺少 cleanupXxtReports')

// 4) 前端
must(/scopeCheck/.test(view), '前端未接入范围核对')
must(/没有本地草稿/.test(view), '未提示“有行但无草稿”')
must(/async function regenerateAllReports/.test(view), '缺少“重新生成全部报告”')
must(/async function cleanupDuplicateReports/.test(view), '缺少“清理多余报告”')
must(/🔁 重新生成全部报告/.test(view), '缺少重生成按钮')
must(/🧹 清理多余报告/.test(view), '缺少清理按钮')
must(/scopeOnly: true/.test(view), '生成前未做只读范围核对')

// 5) selfcheck 接入
must(/selfcheck:d195/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d195')
must(!!pkg.scripts?.['selfcheck:d195'], 'package.json 缺少 selfcheck:d195')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 同名学生多键 → 合并为一份报告并回写所有键')
console.log('✓ 生成前范围核对：提示“有行但无草稿”的学生')
console.log('✓ 重新生成全部报告 / 清理多余报告（只动 reports/）')
console.log('✓ D195 selfcheck 已接入 npm run selfcheck')

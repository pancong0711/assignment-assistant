/** D194：一键生成报告的中断 / 续做（静态自检）。 */
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
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

// 后端：可中断 / 可续做 / 单人失败隔离
must(/def read_report_progress\(/.test(drafts), '缺少 read_report_progress')
must(/_write_progress\(out_root, progress\)/.test(drafts), '未在生成过程中落盘进度')
must(/resume: bool = False/.test(drafts), 'render 未支持 resume')
must(/only: "list\[str\] \| None" = None/.test(drafts), 'render 未支持 only')
must(/"partial": bool\(failed\)/.test(drafts), '结果未标记 partial')
must(/'skipped'/.test(drafts) || /"skipped"/.test(drafts), '结果未返回 skipped')
must(/_RENDER_RUNNING/.test(serve), 'serve 未做同作业单实例')
must(/progressOnly/.test(serve), 'serve 未提供只读进度')

// 前端
must(/export async function fetchReportProgress/.test(client), 'engineClient 缺少 fetchReportProgress')
must(/resume\?: boolean/.test(client) && /only\?: string\[\]/.test(client),
  'renderReportsFromDrafts 未支持 resume/only')
must(/async function resumeReports/.test(view), '缺少续做入口')
must(/async function retryFailedReports/.test(view), '缺少只补失败入口')
must(/续做报告/.test(view), '缺少续做按钮文案')
must(/只补失败/.test(view), '缺少只补失败按钮文案')
must(/报告生成进度/.test(view), '缺少进度展示')
must(/r\?\.busy/.test(view), '前端未处理 409 busy')
must(/r\?\.partial/.test(view), '前端未处理 partial 结果')
must(/refreshReportProgress/.test(view), '前端未刷新进度')

// 幂等口径：续做不重复产生版本由后端保证，前端文案需说明
must(/不产生新版本/.test(view), '未向教师说明幂等版本语义')

must(/selfcheck:d194/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d194')
must(!!pkg.scripts?.['selfcheck:d194'], 'package.json 缺少 selfcheck:d194')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 后端：逐生隔离失败 + 进度落盘 + resume/only')
console.log('✓ 同一作业单实例（重复点击不会并发渲染）')
console.log('✓ 前端：续做 / 只补失败 / 进度展示 / 409 处理')
console.log('✓ D194 selfcheck 已接入 npm run selfcheck')

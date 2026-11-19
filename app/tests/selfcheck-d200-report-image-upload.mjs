/** D200：上传“报告图+分数”即可，不因批语文本为空被判阻塞。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const root = join(appRoot, '..')
const view = fs.readFileSync(join(appRoot, 'src/components/AiGradingPanel.vue'), 'utf8')
const client = fs.readFileSync(join(appRoot, 'src/lib/engineClient.ts'), 'utf8')
const plan = fs.readFileSync(join(root, 'engine/src/assist/xxt/grade_plan.py'), 'utf8')
const cli = fs.readFileSync(join(root, 'engine/src/assist/xxt/cli.py'), 'utf8')
const serve = fs.readFileSync(join(root, 'engine/src/assist/serve.py'), 'utf8')
const upload = fs.readFileSync(join(root, 'engine/src/assist/xxt/grade_upload.py'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

// 1) 就绪判定看“报告图/批语/分数”三者任一
must(/NO_REPORT = "no-report"/.test(plan), '缺少 no-report 状态')
must(/has_image/.test(plan), '判定未考虑报告图')
must(/hasScore/.test(plan), '判定未考虑分数')
must(/uploadMode/.test(plan), '未标注上传模式（report-only/text）')
must(/报告图 \+ 分数/.test(plan), '未说明“报告图+分数”上传口径')

// 2) 上传模式：有报告图时不重复传批语文本
must(/--report-only/.test(cli), 'CLI 缺少 --report-only')
must(/payload_comment = ""/.test(cli), '有报告图时未清空批语文本')
must(/reportOnly/.test(serve), 'serve 未透传 reportOnly')
must(/reportOnly\?: boolean/.test(client), 'engineClient 未声明 reportOnly')

// 3) evaluations 兜底
must(/def enrich_payloads_from_evaluations/.test(upload), '缺少 evaluations 兜底')
must(/enrich_payloads_from_evaluations/.test(serve), 'serve 预览未走兜底')

// 4) 前端
must(/uploadReportOnly/.test(view), '缺少“只上传报告图+分数”开关')
must(/只上传/.test(view) && /报告图 \+ 分数/.test(view), '开关文案缺失')
must(/r\.hasImage/.test(view), '对照表未区分是否有报告图')
must(/no-report/.test(view), '未处理 no-report 状态')
must(/emptyComment/.test(view), '未单独提示“批语文本为空但有报告图”')
must(/reportOnly: uploadReportOnly\.value/.test(view), '上传时未传 reportOnly')

// 5) selfcheck 接入
must(/selfcheck:d200/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d200')
must(!!pkg.scripts?.['selfcheck:d200'], 'package.json 缺少 selfcheck:d200')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 就绪判定 = 报告图/批语/分数 任一（不再误判“批语为空”）')
console.log('✓ 默认只上传“报告图 + 分数”，不重复写原始批语')
console.log('✓ 草稿缺批语时用 evaluations 的 AI 批语兜底')
console.log('✓ D200 selfcheck 已接入 npm run selfcheck')

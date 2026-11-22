/** D217：疑似错卷照常批阅 + 上传前默认拦截。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const root = join(appRoot, '..')
const view = fs.readFileSync(join(appRoot, 'src/components/AiGradingPanel.vue'), 'utf8')
const client = fs.readFileSync(join(appRoot, 'src/lib/engineClient.ts'), 'utf8')
const plan = fs.readFileSync(join(root, 'engine/src/assist/xxt/grade_plan.py'), 'utf8')
const upload = fs.readFileSync(join(root, 'engine/src/assist/xxt/grade_upload.py'), 'utf8')
const cli = fs.readFileSync(join(root, 'engine/src/assist/xxt/cli.py'), 'utf8')
const serve = fs.readFileSync(join(root, 'engine/src/assist/serve.py'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

// 后端
must(/ALIGN_MISMATCH = "align-mismatch"/.test(plan), '缺少 align-mismatch 状态')
must(/alignMismatch/.test(plan), 'readiness 未返回 alignMismatch')
must(/"align": \(\(d\.get\("ai"\) or \{\}\)\.get\("align"\) or \{\}\)/.test(upload),
  'payload 未携带 align')
must(/"--allow-mismatch"/.test(cli), 'CLI 缺少 --allow-mismatch')
must(/skippedMismatch/.test(cli), 'CLI 未记录被跳过的疑似错卷')
must(/payload\.get\("allowMismatch"\)/.test(serve), 'serve 未透传 allowMismatch')

// 前端
must(/uploadIncludeMismatch/.test(view), '缺少“包含疑似错卷”勾选项')
must(/疑似错卷·暂不上传/.test(view), '缺少疑似错卷徽标')
must(/包含疑似错卷/.test(view), '缺少勾选文案')
must(/allowMismatch/.test(client) && /allowMismatch\?: boolean/.test(client),
  'engineClient 未声明 allowMismatch')
must(/改 tag 后点「转写\+批阅」重批/.test(view), '逐生审核缺少处置指引')
must(/if \(r\.readyState === 'align-mismatch'\) return uploadIncludeMismatch\.value/.test(view),
  '批量上传未默认排除疑似错卷')
must(/仍要上传这一名学生吗/.test(view), '逐生上传未二次确认')

must(/selfcheck:d217/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d217')
must(!!pkg.scripts?.['selfcheck:d217'], 'package.json 缺少 selfcheck:d217')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ readiness 新增 align-mismatch（默认不上传）')
console.log('✓ 引擎默认跳过疑似错卷，--allow-mismatch 才传')
console.log('✓ 对照表徽标/汇总/勾选项 + 逐生上传二次确认')
console.log('✓ 逐生审核行内“改 tag 后重批”指引')
console.log('✓ D217 selfcheck 已接入 npm run selfcheck')

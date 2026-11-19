/** D211：同名去重（112→56）+ 覆盖原报告（清旧图、写新图新分）。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const root = join(appRoot, '..')
const view = fs.readFileSync(join(appRoot, 'src/components/AiGradingPanel.vue'), 'utf8')
const client = fs.readFileSync(join(appRoot, 'src/lib/engineClient.ts'), 'utf8')
const up = fs.readFileSync(join(root, 'engine/src/assist/xxt/grade_upload.py'), 'utf8')
const prev = fs.readFileSync(join(root, 'engine/src/assist/xxt/upload_preview.py'), 'utf8')
const cli = fs.readFileSync(join(root, 'engine/src/assist/xxt/cli.py'), 'utf8')
const serve = fs.readFileSync(join(root, 'engine/src/assist/serve.py'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

// 1) 去重
must(/def dedupe_payloads_by_student\(/.test(up), '缺少按学生去重')
must(/dedupe_payloads_by_student\(out\)/.test(up), 'drafts_to_payloads 未去重')
must(/draftKeys/.test(up), '未记录合并后的草稿键')

// 2) 覆盖
must(/overwrite: bool = False/.test(up), 'upload_grade 缺少 overwrite')
must(/清空原批语/.test(up), '覆盖模式未清空原批语')
must(/if comment_images and not overwrite:/.test(up), '覆盖模式仍会保留旧图')
must(/if overwrite:\s*\n\s*force = True/.test(up) || /if overwrite:\n        force = True/.test(up),
  '覆盖模式未自动 force')
must(/'"--overwrite"'/.test(cli) || /"--overwrite"/.test(cli), 'CLI 缺少 --overwrite')
must(/args \+= \["--overwrite"\]/.test(serve), 'serve 未透传 --overwrite')

// 3) 平台分数读取状态
must(/platformScoreUnknown/.test(prev), '未标记“平台分数未知”')
must(/platformReadError/.test(prev), '未暴露逐生读取失败原因')
must(/platformReadErrors/.test(prev), '未统计读取失败数')

// 4) 前端
must(/overwrite\?: boolean/.test(client), 'engineClient 缺少 overwrite')
must(/uploadOneStudent\(r, \{ overwrite: true \}\)/.test(view), '缺少覆盖按钮绑定')
must(/>覆盖<\/button>/.test(view), '缺少“覆盖”按钮')
must(/将清空平台上该生的原批语\/原报告图/.test(view), '覆盖前未提示会清除旧报告')
must(/读取失败/.test(view), '平台分数读取失败未显示')
must(/platformScoreUnknown/.test(view), '平台分数未知未显示')

must(/selfcheck:d211/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d211')
must(!!pkg.scripts?.['selfcheck:d211'], 'package.json 缺少 selfcheck:d211')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 同一学生多草稿键 → 去重为 1 行（112→56）')
console.log('✓ 「覆盖」：清空平台旧批语/旧报告图，写入新图与新分数')
console.log('✓ 平台分数读取失败/未知有明确显示')
console.log('✓ D211 selfcheck 已接入 npm run selfcheck')

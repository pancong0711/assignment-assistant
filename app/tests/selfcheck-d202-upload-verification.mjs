/** D202：上传成功必须经“提交后核验”，不能只看点了按钮。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const root = join(appRoot, '..')
const view = fs.readFileSync(join(appRoot, 'src/components/AiGradingPanel.vue'), 'utf8')
const upload = fs.readFileSync(join(root, 'engine/src/assist/xxt/grade_upload.py'), 'utf8')
const marking = fs.readFileSync(join(root, 'engine/src/assist/xxt/marking.py'), 'utf8')
const extractor = fs.readFileSync(join(root, 'engine/src/assist/xxt/extractor.py'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

// 1) 提交后核验
must(/def verify_submission\(/.test(upload), '缺少 verify_submission')
must(/verify_submission\(page, str\(course_id\)/.test(upload), '提交后未调用核验')
must(/result\["ok"\] = bool\(clicked and ver\.get\("ok"\)\)/.test(upload),
  'ok 未与核验结果绑定')
must(/提交后平台状态仍为/.test(upload), '未给出“状态未变”的明确错误')
must(/提交后平台分数为/.test(upload), '未给出“分数不一致”的明确错误')

// 2) 提交前分数写入校验
must(/分数未成功写入页面/.test(upload), '未做提交前分数校验')
must(/score-not-filled/.test(upload), '缺少 score-not-filled 状态')

// 3) 分数填写更可靠 + 列表回读分数
must(/inp\.blur\(\)/.test(marking), '填分未触发 blur')
must(/score: sc/.test(extractor) || /"score": sc/.test(extractor), '列表未回读分数')
must(/"score": str\(r\.get\("score"\) or ""\)\.strip\(\)/.test(upload),
  '_students_from_mark_list 未保留 score')

// 4) 前端文案
must(/已上传（已核验平台状态）/.test(view), '前端未区分“已核验”')

must(/selfcheck:d202/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d202')
must(!!pkg.scripts?.['selfcheck:d202'], 'package.json 缺少 selfcheck:d202')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 提交后重新读取批阅列表核验（状态 + 分数）')
console.log('✓ 分数未写入页面时中止提交，不误报成功')
console.log('✓ 填分触发 blur/回车，列表回读分数')
console.log('✓ D202 selfcheck 已接入 npm run selfcheck')

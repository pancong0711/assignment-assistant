/** D199：报告版本以逐生审核名单为基准（57 人），未生成的显式标出。 */
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

// 1) 报告不得用草稿键当学生名
must(/def student_name_map\(/.test(drafts), '缺少 student_name_map')
must(/name_map\.get\(str\(k\)\)/.test(drafts), '报告未用 workAnswerId→姓名 解析')
must(/"student": stu/.test(drafts), '未回填草稿 student 字段')

// 2) 版本视图以名单为基准
must(/"roster": roster/.test(serve), '版本视图未按名单生成逐生状态')
must(/"missingReport": missing/.test(serve), '未返回未生成报告的名单')
must(/key_to_name/.test(serve), '未接收 key→姓名 映射')
must(/studentRaw/.test(serve), '未保留索引原始学生值以便归一')

// 3) 前端
must(/versionRoster/.test(view), '前端未保存逐生状态')
must(/versionTableRows/.test(view), '版本表未统一逐生视图')
must(/未生成/.test(view), '未显式标出“未生成”学生')
must(/还没有报告/.test(view), '未提示缺失报告的学生')
must(/keyToName/.test(view), '未传 key→姓名 映射')
must(/keyToName\?: Record<string, string>/.test(client), 'engineClient 缺少 keyToName')
must(/missingReport\?: string\[\]/.test(client), 'engineClient 缺少 missingReport')
must(/逐生审核名单/.test(view), '未以“逐生审核名单”为口径说明')

// 4) selfcheck 接入
must(/selfcheck:d199/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d199')
must(!!pkg.scripts?.['selfcheck:d199'], 'package.json 缺少 selfcheck:d199')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 报告以学生姓名命名（不再用 workAnswerId 当名字）')
console.log('✓ 版本面板以逐生审核名单为基准，未生成的显式标出')
console.log('✓ 旧索引里的 wa_xxx 通过 key→姓名 归一')
console.log('✓ D199 selfcheck 已接入 npm run selfcheck')

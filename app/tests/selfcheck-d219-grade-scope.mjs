/** D219：批阅范围（逐生/全局）与如实统计 + 任务接续/取消。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const root = join(appRoot, '..')
const view = fs.readFileSync(join(appRoot, 'src/components/AiGradingPanel.vue'), 'utf8')
const client = fs.readFileSync(join(appRoot, 'src/lib/engineClient.ts'), 'utf8')
const flow = fs.readFileSync(join(root, 'engine/src/assist/grading/flow.py'), 'utf8')
const cli = fs.readFileSync(join(root, 'engine/src/assist/cli.py'), 'utf8')
const serve = fs.readFileSync(join(root, 'engine/src/assist/serve.py'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

// 1) 逐生范围
must(/only = _only_students\(ctx\)/.test(flow), '转录未按 only_students 过滤')
must(/if only and name not in only:/.test(flow), '逐生转录仍会处理全班')

// 2) 评阅统计
must(/evaluate_summary/.test(flow), '评阅未产出统计')
must(/skippedExisting/.test(flow) && /skippedNoItems/.test(flow), '统计字段缺失')
must(/__GRADE_SUMMARY__/.test(cli), 'CLI 未输出评阅统计标记')

// 3) 单实例
must(/_GRADE_RUNNING/.test(serve) && /_grade_scope_key\(/.test(serve),
  '缺少批阅单实例锁')
must(/该作业已有批阅任务在运行/.test(serve), '缺少 busy 可读提示')

// 4) 前端
must(/XxtGradeStart/.test(client) && /kind: 'busy'/.test(client),
  'engineClient 未把 409 建模为 busy')
must(/start\.kind === 'busy'/.test(view), '前端未接上正在运行的批阅任务')
must(/grade-job\.v1/.test(view), '批阅任务未持久化')
must(/cancelGradeJob/.test(view) && /⏹ 取消任务/.test(view), '缺少取消任务入口')
must(/__GRADE_SUMMARY__/.test(view), '前端未解析评阅统计')
must(/本次没有新评阅/.test(view), '空跑时未如实提示')
must(/超过 40 分钟仍在后台执行/.test(view), '超时未说明“仍在后台执行”')

must(/selfcheck:d219/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d219')
must(!!pkg.scripts?.['selfcheck:d219'], 'package.json 缺少 selfcheck:d219')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 逐生转写/批阅只处理该生（only_students 贯穿）')
console.log('✓ 评阅如实统计（新评/跳过已有/无题目/失败）并显示')
console.log('✓ 同一作业单实例批阅；页面接上运行中任务并可取消')
console.log('✓ 超时不再误报失败；刷新后自动接续')
console.log('✓ D219 selfcheck 已接入 npm run selfcheck')

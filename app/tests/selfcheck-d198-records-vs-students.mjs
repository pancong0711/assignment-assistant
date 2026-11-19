/** D198：版本“记录数”≠“学生数”；清理无内容时要解释原因，并提供压缩历史。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const root = join(appRoot, '..')
const view = fs.readFileSync(join(appRoot, 'src/components/AiGradingPanel.vue'), 'utf8')
const client = fs.readFileSync(join(appRoot, 'src/lib/engineClient.ts'), 'utf8')
const rv = fs.readFileSync(join(root, 'engine/src/assist/grading/report_versions.py'), 'utf8')
const serve = fs.readFileSync(join(root, 'engine/src/assist/serve.py'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

// 1) 后端：记录数 vs 学生数
must(/def index_stats\(/.test(rv), '缺少 index_stats')
must(/totalRecords/.test(rv) && /studentCount/.test(rv), 'index_stats 未区分记录数/学生数')
must(/historyRecords/.test(rv), '未统计历史版本条数')
must(/历史版本/.test(rv), '未解释“历史版本”')
must(/压缩版本历史/.test(rv), '未引导使用压缩历史')

// 2) 压缩
must(/def compact_index\(/.test(rv), '缺少 compact_index')
must(/keep_latest/.test(rv), 'compact 未支持 keep_latest')
must(/delete_history_files/.test(rv), 'compact 未区分是否删历史文件')
must(/report-compact/.test(serve), 'serve 缺少 report-compact 端点')

// 3) 版本查询返回构成
must(/studentCount/.test(serve) && /historyRecords/.test(serve), '版本查询未返回构成统计')

// 4) 前端
must(/export async function compactXxtReportVersions/.test(client), 'engineClient 缺少压缩接口')
must(/async function compactReportVersions/.test(view), '缺少压缩历史前端逻辑')
must(/🗜 压缩版本历史/.test(view), '缺少压缩按钮')
must(/逐生审核名单/.test(view) && /版本记录共/.test(view),
  '版本面板未显示“名单人数/记录数”')
must(/历史版本，不是多余学生|不是多余学生/.test(view), '未解释记录≠学生')
must(/每生只保留最新 1 版/.test(view), '压缩确认未说明策略')
must(/只压缩索引，不删文件/.test(view), '压缩确认未说明“不删历史文件”')

// 5) selfcheck 接入
must(/selfcheck:d198/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d198')
must(!!pkg.scripts?.['selfcheck:d198'], 'package.json 缺少 selfcheck:d198')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 版本面板区分“学生数”与“记录数”')
console.log('✓ 清理无内容时解释原因（历史版本≠多余学生）')
console.log('✓ 新增「🗜 压缩版本历史」（每生保留最新 1 版，历史文件保留）')
console.log('✓ D198 selfcheck 已接入 npm run selfcheck')

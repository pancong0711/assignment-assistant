/** D204：提交前先判页面/会话；提交按钮兜底；逐生「演练」安全验证。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const root = join(appRoot, '..')
const view = fs.readFileSync(join(appRoot, 'src/components/AiGradingPanel.vue'), 'utf8')
const marking = fs.readFileSync(join(root, 'engine/src/assist/xxt/marking.py'), 'utf8')
const upload = fs.readFileSync(join(root, 'engine/src/assist/xxt/grade_upload.py'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

// 1) 页面状态诊断
must(/def page_state\(/.test(marking), '缺少 page_state 页面诊断')
must(/hasCommentBox/.test(marking) && /hasScoreInput/.test(marking), '未检测关键控件')
must(/loginRedirect/.test(marking), '未检测登录页跳转')
must(/session-expired/.test(marking), '未返回 session-expired 状态')
must(/重新扫码登录/.test(marking), '未提示重新扫码')

// 2) 提交按钮兜底
must(/no-submit-candidate/.test(marking), '缺少提交按钮兜底策略')
must(/confirmPiyueWork/.test(marking), '兜底未覆盖 confirmPiyueWork')
must(/no-markAction\(1\)/.test(marking), '仍保留主路径 markAction(1)')

// 3) 上传链路：打开批阅页先判页面，提交遇会话过期直接收尾
must(/result\["pageState"\]/.test(upload), '打开批阅页后未记录页面状态')
must(/not-mark-page/.test(upload), '未识别“不是批阅页”')
must(/session-expired/.test(upload), '上传链路未处理会话过期')

// 4) 前端演练
must(/async function uploadOneStudent\(row[\s\S]{0,160}opts\?: \{ dryRun\?: boolean/.test(view),
  '逐生上传未支持演练参数')
must(/send: !dryRun/.test(view), '演练未使用 send=false')
must(/演练通过（已填入并读回，未提交）/.test(view), '缺少演练成功文案')
must(/>演练<\/button>/.test(view), '缺少“演练”按钮')
must(/D204/.test(view), '前端未标注 D204 语义')

must(/selfcheck:d204/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d204')
must(!!pkg.scripts?.['selfcheck:d204'], 'package.json 缺少 selfcheck:d204')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 提交前诊断页面（登录页/无批语框 → 会话过期提示）')
console.log('✓ 提交按钮多策略兜底（markAction/confirmPiyueWork/文案）')
console.log('✓ 逐生「演练」：只填入并读回，不提交')
console.log('✓ D204 selfcheck 已接入 npm run selfcheck')

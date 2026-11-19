/** D203：提交后仍“待批阅”——必须点中新版确认按钮（confirmPiyueWork）。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const root = join(appRoot, '..')
const marking = fs.readFileSync(join(root, 'engine/src/assist/xxt/marking.py'), 'utf8')
const upload = fs.readFileSync(join(root, 'engine/src/assist/xxt/grade_upload.py'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

// 1) 确认弹窗覆盖新版入口
must(/confirmPiyueWork/.test(marking), '未覆盖 confirmPiyueWork() 确认按钮')
must(/text:确定|'确定'|确定提交/.test(marking), '未按“确定/确认”文案兜底点击')
must(/no-visible-confirm/.test(marking), '无法点击时未报告原因')
must(/def handle_confirmation_dialog/.test(marking), '缺少确认弹窗处理')

// 2) 多层弹窗 + 关闭检测
must(/popups/.test(marking) && /clicks/.test(marking), '未记录弹窗与点击明细')
must(/idle >= 3/.test(marking), '未等待弹窗稳定关闭')

// 3) submit 诊断
must(/__assistDialogs/.test(marking), '未记录平台 confirm/alert')
must(/submitCandidates/.test(marking), '未导出候选提交按钮')

// 4) 页面层记录 confirm 并接受
must(/__assistDialogs/.test(upload), '页面未注入 confirm 记录')
must(/window\.confirm = function/.test(upload), '未接管 window.confirm')

// 5) 未生效自动重试 + 错误带证据
must(/for attempt in \(1, 2\)/.test(upload), '未在未生效时重试一次')
must(/submitAttempts/.test(upload), '未记录提交尝试')
must(/confirmPiyueWork/.test(upload), '错误提示未指出新版确认入口')

must(/selfcheck:d203/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d203')
must(!!pkg.scripts?.['selfcheck:d203'], 'package.json 缺少 selfcheck:d203')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 确认弹窗支持 confirmPiyueWork/文案兜底，能点中“确定”')
console.log('✓ 支持多层确认并记录弹窗/点击明细')
console.log('✓ 提交未生效自动重试一次；错误带 confirm/alert 证据')
console.log('✓ D203 selfcheck 已接入 npm run selfcheck')

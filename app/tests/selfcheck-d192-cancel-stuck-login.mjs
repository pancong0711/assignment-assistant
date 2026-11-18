/** D192：扫码任务卡住时可取消并重新出码；无需退出学习通账号。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const root = join(appRoot, '..')
const view = fs.readFileSync(join(appRoot, 'src/views/XxetongView.vue'), 'utf8')
const client = fs.readFileSync(join(appRoot, 'src/lib/engineClient.ts'), 'utf8')
const servePy = fs.readFileSync(join(root, 'engine/src/assist/serve.py'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

// 1) 引擎：可取消旧任务 + replace 重新出码
must(/def cancel_job\(/.test(servePy), '引擎缺少 cancel_job')
must(/def cancel_xxt_login_job\(/.test(servePy), '引擎缺少 cancel_xxt_login_job')
must(/_JOBS\[job_id\]\["proc"\] = proc/.test(servePy), '任务未登记子进程句柄')
must(/proc\.terminate\(\)/.test(servePy) && /proc\.kill\(\)/.test(servePy),
  '取消未实现 terminate → kill 兜底')
must(servePy.includes('/cancel", u.path)'), '缺少 /jobs/<id>/cancel 端点')
must(/replace"\]/.test(servePy) || /get\("replace"/.test(servePy), '登录启动未识别 replace=1')
must(/cancel_xxt_login_job\(reason="replace"\)/.test(servePy), 'replace 未先取消旧登录任务')
must(/_XXT_LOGIN_MAX_AGE/.test(servePy) && /"stale"/.test(servePy), '缺少任务超时(stale)判定')

// 2) 引擎：无任务在跑时不采信遗留状态/二维码
must(/job_running: "bool \| None" = None/.test(servePy), '_xxt_login_state 未接收 job_running')
must(/if job_running is False:/.test(servePy), '未处理“本进程无登录任务”分支')
must(/st\["jobRunning"\] = job_running/.test(servePy), '/xxt/login/state 未回显 jobRunning')
must(/st\["job"\] = \{/.test(servePy), '/xxt/login/state 未回显任务摘要')

// 3) 前端：强制重新出码 + 卡住提示 + 刷新接上
must(/export async function cancelXxtJob/.test(client), 'engineClient 缺少 cancelXxtJob')
must(/replace\?: boolean/.test(client), 'startXxtLogin 未支持 replace')
must(/async function forceReissueQr/.test(view), '缺少强制重新出码')
must(/⚡ 强制重新出码/.test(view), '缺少强制重新出码按钮')
must(/不需要退出学习通账号/.test(view), '未说明无需退出账号')
must(/await startScan\(\{ replace: true \}\)/.test(view), '强制重新出码未使用 replace')
must(/qrBlocked/.test(view), '缺少 qrBlocked 状态')
must(/stalled/.test(view) && /45000/.test(view), '缺少“长时间无二维码”判定')
must(/st\.job\.job_id/.test(view), '刷新后未接上正在跑的任务')

// 4) selfcheck 接入
must(/selfcheck:d192/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d192')
must(!!pkg.scripts?.['selfcheck:d192'], 'package.json 缺少 selfcheck:d192')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 引擎可取消卡住的扫码任务（terminate→kill）')
console.log('✓ /xxt/login/start?replace=1 先取消旧任务再出新码')
console.log('✓ 无任务在跑时不采信遗留状态/二维码')
console.log('✓ 前端「⚡ 强制重新出码」且无需退出账号')
console.log('✓ 长时间无二维码给出卡住提示与出口')
console.log('✓ D192 selfcheck 已接入 npm run selfcheck')

/** D191：409「已有扫码任务」要接管而不是报死；遗留状态/旧红字不得冒充当前扫码。 */
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

// 1) 409 = 接管正在运行的任务
must(/export type XxtLoginStart/.test(client), 'engineClient 缺少 XxtLoginStart 联合类型')
must(/kind: 'busy'/.test(client), 'startXxtLogin 未把 409 建模为 busy')
must(/res\.status === 409 && o\.stage === 'busy'/.test(client), '未识别 409 busy')
must(/started\.kind === 'busy'/.test(view), 'XxetongView 未处理 busy（接管）')
must(/已接上正在进行的扫码任务/.test(view), '缺少“已接上正在进行的任务”提示')
must(!/⚠ \$\{msg\}/.test(view), '409 仍被当作错误告警显示')
must(/qrStartedAt = Date\.now\(\) - started\.ageSec \* 1000/.test(view),
  '接管任务后未按其已运行时长设置二维码等待起点')

// 2) 上一轮遗留状态/二维码不再冒充“等待扫码”
must(/readonly_since/.test(servePy), '引擎缺 readonly_since 只读过滤')
must(/def _xxt_login_state\(home: "Path \| None" = None,/.test(servePy)
  && /readonly_since: float = 0\.0/.test(servePy),
  '_xxt_login_state 未支持 readonly_since')
must(/if not qr_exists or qr\.stat\(\)\.st_mtime < float\(readonly_since\) - 1\.0/.test(servePy),
  '只读查询未过滤陈旧二维码')
must(/!_xxt_task_started_at\(_xxt_login_job_running\(\) or ""\)/.test(servePy) === false,
  '不太可能')
must(servePy.includes('t0 = float((running_info or {}).get("started_at") or 0.0)')
  && servePy.includes('t0 = _STARTED_EPOCH or time.time()')
  && servePy.includes('readonly_since = t0'),
  '只读查询未以“运行中任务起点/进程启动时间”为基准')
must(/job_running=job_running/.test(servePy), '只读查询未显式传 job_running（D192）')
must(/!loginJobId && !qrFiled/.test(view), '前端未处理“无任务且二维码非本轮”')
must(/没有正在等待的扫码任务/.test(view), '缺少“没有正在等待的扫码任务”提示')
must(/qrStale/.test(view) && /二维码已失效/.test(view), '缺少二维码失效态展示')

// 3) 引擎重启后任务消失 → 停止轮询
must(/res\.status === 404/.test(client) && /status: 'missing'/.test(client),
  'fetchXxtLoginJob 未把 404 映射为 missing')
must(/job\.status === 'missing'/.test(view), '前端未处理 job missing')
must(/上一次扫码任务已结束/.test(view), '缺少 job missing 的可读提示')

// 4) 登录成功后旧的“被跳登录页”红字要消失
must(/loginCompletedTs/.test(client) && /login_completed_ts/.test(client),
  'engineClient 未接入 loginCompletedTs')
must(/def _xxt_login_completed_after/.test(servePy), '引擎缺少 _xxt_login_completed_after')
must(/view\["loginCompletedTs"\]/.test(servePy), '/xxt/status 未透传 loginCompletedTs')
must(/staleRedirect/.test(view) && /loginOkTs > 0 && redirectTs <= loginOkTs/.test(view),
  '前端未按登录成功时间隐藏旧跳转提示')

// 5) 刷新页面后可接上正在跑的任务
must(/view\["loginJob"\]/.test(servePy), '/xxt/status 未透传 loginJob')
must(/loginJob\?: \{ job_id\?: string/.test(client), 'XxtSessionStatus 未声明 loginJob')

// 6) 409 不再要求重启引擎
must(!/关闭引擎窗口后重启，再点「重新扫码登录」/.test(servePy),
  '409 hint 仍要求重启引擎')

// 7) selfcheck 接入
must(/selfcheck:d191/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d191')
must(!!pkg.scripts?.['selfcheck:d191'], 'package.json 缺少 selfcheck:d191')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 409 已有扫码任务 → 页面接管并继续显示其二维码')
console.log('✓ 上一轮遗留 logged_in/旧二维码不再冒充等待扫码')
console.log('✓ 引擎重启后任务消失 → 停止轮询并提示重新出码')
console.log('✓ 登录成功后旧的“被跳登录页”红字自动消失')
console.log('✓ 刷新页面可接上正在运行的扫码任务')
console.log('✓ D191 selfcheck 已接入 npm run selfcheck')

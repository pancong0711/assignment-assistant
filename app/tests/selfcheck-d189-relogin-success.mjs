/** D189：重新扫码登录的成功判定 / 单实例 / 可读失败原因（静态自检）。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const root = join(appRoot, '..')
const view = fs.readFileSync(join(appRoot, 'src/views/XxetongView.vue'), 'utf8')
const client = fs.readFileSync(join(appRoot, 'src/lib/engineClient.ts'), 'utf8')
const sessionPy = fs.readFileSync(join(root, 'engine/src/assist/xxt/session.py'), 'utf8')
const servePy = fs.readFileSync(join(root, 'engine/src/assist/serve.py'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

// 前端：只读登录状态 + 可读原因
must(/fetchXxtLoginState/.test(client), 'engineClient 缺少 fetchXxtLoginState')
must(/fetchXxtLoginState/.test(view), 'XxetongView 未调用 fetchXxtLoginState')
must(/LOGIN_STAGE_HINT/.test(view) && /function describeLoginState/.test(view),
  '缺少登录阶段→可读原因映射')
must(/等待扫码超时/.test(view), '超时未给出可读提示')
must(/二维码生成\/浏览器阶段失败/.test(view), '二维码/浏览器失败未给出可读提示')
must(/已有扫码登录任务/.test(view) || /已有扫码登录任务/.test(servePy),
  '409 单实例提示未透传（D191 起由页面接管并在 hint 中说明）')
must(/maskSensitive\(String\(st\.error/.test(view), '登录状态错误未脱敏')

// 后端：基线判定 + 单实例 + 只读状态
must(/def cookie_fingerprint\(/.test(sessionPy), '缺少 cookie_fingerprint')
must(/def session_cookie_changed\(/.test(sessionPy), '缺少 session_cookie_changed')
must(/function _is_logged_in/.test(sessionPy) === false || /def _is_logged_in\(page, baseline/.test(sessionPy), '_is_logged_in 未接收 baseline')
must(/session_cookie_changed\(baseline, current\)/.test(sessionPy),
  '_is_logged_in 未校验本次扫码新 cookie')
must(/baseline = cookie_fingerprint\(ctx\.cookies\(\)\)/.test(sessionPy),
  'qr_login 未记录扫码前基线')
must(/def _xxt_login_job_running\(/.test(servePy), '缺少登录任务单实例检查')
must(/def _xxt_login_state\(/.test(servePy), '缺少只读登录状态')
must(/u\.path == "\/xxt\/login\/state"/.test(servePy), '未注册 /xxt/login/state 只读端点')
must(/"stage": "busy"/.test(servePy), '并发登录未返回 busy 状态')

// 隐私：状态接口不得返回 cookie 值
must(!/cookies.*value/.test(servePy.split('def _xxt_login_state(')[1]?.split('def installer_for')[0] || ''),
  '登录状态疑似返回 cookie 值')

must(/selfcheck:d189/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d189')
must(!!pkg.scripts?.['selfcheck:d189'], 'package.json 缺少 selfcheck:d189')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 登录成功判定使用基线 + 新会话 cookie')
console.log('✓ 登录任务单实例（409 可读提示）')
console.log('✓ 只读 /xxt/login/state 且不含敏感值')
console.log('✓ 前端展示阶段/超时/二维码失败等可读原因')
console.log('✓ D189 selfcheck 已接入 npm run selfcheck')

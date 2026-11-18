/** D188：学习通主动重新扫码 + 会话失效红字 + 提取失败详情静态自检。
 *
 * 只做源码静态断言，不启动浏览器、不读取任何真实会话/学生数据。
 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const root = join(__dirname, '..', '..')
const view = fs.readFileSync(join(__dirname, '..', 'src/views/XxetongView.vue'), 'utf8')
const client = fs.readFileSync(join(__dirname, '..', 'src/lib/engineClient.ts'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(__dirname, '..', 'package.json'), 'utf8'))
const sessionPy = fs.readFileSync(join(root, 'engine/src/assist/xxt/session.py'), 'utf8')
const servePy = fs.readFileSync(join(root, 'engine/src/assist/serve.py'), 'utf8')
const errors = []

function must(cond, msg) {
  if (!cond) errors.push(msg)
}

// R1：任何 verdict 都可用的「重新扫码登录」按钮
const reloginMatch = view.match(/<button[^>]*@click="relogin"[^>]*>[\s\S]*?<\/button>/)
const reloginTag = reloginMatch?.[0] || ''
must(!!reloginMatch && /🔁 重新扫码登录/.test(reloginTag), '缺少「🔁 重新扫码登录」按钮')
must(!!reloginTag, '重新扫码按钮未绑定 relogin')
must(!!reloginTag && !/:disabled/.test(reloginTag), '重新扫码按钮不得被 verdict 禁用')
const reloginBody = view.match(/async function relogin\(\) \{([\s\S]*?)\n\}/)?.[1] || ''
must(/confirm\(/.test(reloginBody), 'relogin 缺少确认提示')
must(/旧会话可能立即失效/.test(reloginBody), 'relogin 未提示旧会话可能立即失效')
must(/loginJobId = ''/.test(reloginBody), 'relogin 未清掉旧 job 状态')
must(/qrcode\.value = ''/.test(reloginBody), 'relogin 未清掉旧二维码')
must(/startScan\(/.test(reloginBody), 'relogin 未重新发起 startXxtLogin 流程')
must(/loginStartedAlive = verdict\.value === 'alive'/.test(view),
  'active 会话重新扫码时未记录 baseline，轮询会误判成功')
must(/job\.status === 'done' && \(job\.returncode \?\? 0\) === 0/.test(view),
  '重新扫码未通过登录任务完成态收尾')

// R2：会话失效红色提示（不得回显 cookie/token）
must(/会话已失效，请点「🔁 重新扫码登录」/.test(view), '缺少会话失效红色提示')
must(/color:#b91c1c; font-weight:600; background:#fef2f2/.test(view),
  '会话失效提示不是醒目红色样式')
must(/function maskSensitive\(/.test(view), '缺少敏感值脱敏函数')
must(/const safeReasons = computed\(\(\) => statusReasons\.value\.map\(maskSensitive\)/.test(view),
  '失效原因未经脱敏就显示')
must(/safeStepUrl\(s\.url\)/.test(view), 'steps URL 未经脱敏就显示')
must(/const reasonsHitLogin = computed/.test(view), '未按 reasons 命中登录/会话')
must(/r\.login_redirect === true/.test(view), '未处理 /xxt/status 的 loginRedirect')
must(/r\.login_redirect_ts/.test(view), '未处理 loginRedirectTs（重新登录后旧记录仍红）')
must(/reloginAt/.test(view), '缺少重新登录时间基准，无法忽略旧跳转记录')

// R3：提取失败详情（输出、steps、failures、登录页跳转、折叠）
must(/提取失败详情/.test(view), '缺少可折叠的提取失败详情')
must(/<details>\s*<summary[^>]*>\s*提取失败详情/.test(view), '提取失败详情不可折叠')
must(/最后任务输出/.test(view), '缺少最后若干行任务输出')
must(/run steps：/.test(view), '缺少 run steps 展示')
must(/s\.action/.test(view) && /s\.detail/.test(view) && /s\.title/.test(view)
  && /s\.url/.test(view) && /s\.ts/.test(view), 'steps 未展示 action/detail/title/url/ts')
must(/<b>failures：<\/b>/.test(view), '缺少 failures 展示')
must(/f\.scope/.test(view) && /f\.ref/.test(view) && /f\.kind/.test(view)
  && /f\.detail/.test(view) && /f\.hint/.test(view), 'failures 未展示 scope/ref/kind/detail/hint')
must(/检测到学习通登录页跳转 → 会话已失效，请点「🔁 重新扫码登录」/.test(view),
  '缺少登录页跳转明确提示')
must(/function stepUrlIsLogin\([\s\S]*?passport\|login/.test(view),
  '未按 steps.url 的 passport/login 判定登录页跳转')

// R3/R4：0 课程/0 班级 不得显示“提取完成”
must(/\(latest\.classes \?\? 0\) === 0/.test(view), '未检测 run 的 0 班级')
must(/提取失败：0 课程 \/ 0 班级/.test(view), '0 课程/0 班级未显示失败态')
must(/setExtractDetail\(reason, lines/.test(view), '失败/0 结果未构建失败详情')
must(/extractJobError\(lines\.join\('\\n'\)\)/.test(view), '失败原因仍只取最后一行')

// engine：只读登录页判定与 status 最小字段
must(/def is_login_redirect_url\(/.test(sessionPy), 'engine 缺少登录页 URL 纯函数')
must(/def steps_have_login_redirect\(/.test(sessionPy), 'engine 缺少 steps 登录页纯函数')
must(/def _xxt_login_redirect\(/.test(servePy), 'serve 缺少 loginRedirect 只读判断')
must(/"loginRedirect": True/.test(servePy) && /"loginRedirectTs"/.test(servePy),
  'serve 未返回 loginRedirect/loginRedirectTs')
must(/loginRedirect\?: boolean/.test(client) && /login_redirect\?: boolean/.test(client),
  'engineClient 未声明 loginRedirect 只读字段')

// 隐私：不直接读页面 cookie
must(!/document\.cookie/.test(view), '前端不得读取 document.cookie')

// 自检接入 npm run selfcheck
must(/selfcheck:d188/.test(String(pkg.scripts?.['selfcheck'] || '')),
  'selfcheck 链未接入 selfcheck:d188')
must(!!pkg.scripts?.['selfcheck:d188'], 'package.json 缺少 selfcheck:d188')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 重新扫码登录按钮任何 verdict 可用，并清旧 QR/job')
console.log('✓ 会话失效红色提示 + 敏感值脱敏')
console.log('✓ 提取失败详情含输出/steps/failures/登录页跳转，可折叠')
console.log('✓ 0 课程/0 班级显示失败态，不显示“提取完成”')
console.log('✓ loginRedirect 只读字段已接入前端')
console.log('✓ D188 selfcheck 已接入 npm run selfcheck')

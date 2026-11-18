/** D190：扫码流程中必须先显示二维码，头像只在登录成功后出现（静态自检）。 */
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

// 1) 扫码流程中头像位让给二维码
must(/const loginFlowActive = computed\(\(\) => qrLoading\.value \|\| qrcode\.value !== ''\)/.test(view),
  '缺少 loginFlowActive（扫码进行中不允许回头像态）')
const tpl = view.split('<template>')[1] || ''
must(/v-if="qrcode"/.test(tpl), '缺少二维码 img')
must(/verdict==='alive' && avatar && !loginFlowActive/.test(tpl),
  '头像未加 !loginFlowActive 守卫：生成二维码时会显示旧头像')
must(/verdict==='alive' && !loginFlowActive/.test(tpl), '🎓 已登录占位未加守卫')
must(/v-else-if="loginFlowActive"/.test(tpl), '扫码中缺少“二维码生成中”占位')
must(tpl.indexOf('v-if="qrcode"') < tpl.indexOf("verdict==='alive' && avatar"),
  '模板顺序错误：二维码必须在头像之前')

// 2) 发起扫码立刻清旧头像
const startBody = view.split('async function startScan() {')[1]?.split('async function relogin()')[0] || ''
must(/avatar\.value = null/.test(startBody), 'startScan 未清掉旧头像')
const reloginBody = view.split('async function relogin() {')[1]?.split('async function startQrPolling')[0] || ''
must(/avatar\.value = null/.test(reloginBody), 'relogin 未清掉旧头像')

// 3) 头像只在登录成功收尾时刷新
must(/function refreshAvatarAfterLogin/.test(view), '缺少登录后头像刷新函数')
must(/avatar\.value = null\n  void refreshAvatarAfterLogin\(\)/.test(view),
  'finishLoginSuccess 未先清旧头像再异步刷新')
must(/r\.verdict === 'alive' && r\.avatar_dataurl/.test(view), '头像刷新未校验 alive')
must(/if \(r\.verdict !== 'alive'\) avatar\.value = null/.test(view),
  'dead/unknown 时未清掉头像')

// 4) QR 就绪判定：状态 + 图片双确认
must(/fetchXxtLoginState\(engUrl\.value, tok\.value, loginJobId\)/.test(view),
  '二维码就绪未查询当前登录任务状态')
must(/qrExists !== false/.test(view) && /waiting_scan\|logged_in/.test(view),
  '二维码就绪未校验 qrExists/stage')
must(/let imgOk = false/.test(view) && /if \(imgOk\) \{/.test(view),
  '图片可解码后未以图片为准放行显示')

// 5) 扫码任务进行中 /xxt/status 不得覆盖阶段提示
must(/if \(!qrReady && !qrLoading\)/.test(view), '扫码中状态提示会被“已登录”覆盖')

// 6) 任务失败不得被旧 logged_in 状态包装成成功
must(/const detailText = \/waiting_scan\|timeout\|failed\/\.test\(stage\) \? detail : ''/.test(view),
  '失败分支未过滤上一轮 logged_in 状态')
must(/扫码登录失败\$\{why \? `（\$\{why\}）` : ''\}：\$\{detailText \|\| line\}/.test(view),
  '失败文案未使用过滤后的 detailText')

// 7) 引擎：登录开始清头像缓存 + 状态按任务起点过滤
must(/_XXT_AVATAR = None/.test(servePy), '登录开始未清理头像缓存')
must(/def _xxt_task_started_at/.test(servePy), '缺 _xxt_task_started_at')
must(/"started_at": time\.time\(\)/.test(servePy), '_start_stream_job 未记录 started_at')
must(/since: float = 0\.0/.test(servePy) && /if since and mtime < float\(since\) - 1\.0/.test(servePy),
  'login state 未按任务起点过滤旧状态')
must(/job_id=\$\{encodeURIComponent\(jobId\)\}/.test(client), 'engineClient 未传 job_id')

// 8) 按钮不再因 alive 禁用
must(/<button class="btn primary" :disabled="qrLoading" @click="startScan">/.test(view),
  '扫码按钮仍被 verdict=alive 禁用')

// 9) selfcheck 接入
must(/selfcheck:d190/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d190')
must(!!pkg.scripts?.['selfcheck:d190'], 'package.json 缺少 selfcheck:d190')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 扫码流程中头像位让给二维码（无旧头像残留）')
console.log('✓ 登录成功收尾后才异步刷新头像')
console.log('✓ QR 就绪 = 状态 waiting_scan + 图片可解码')
console.log('✓ 任务失败不会被上一轮 logged_in 状态包装成成功')
console.log('✓ 引擎登录开始清头像缓存且状态按任务起点过滤')
console.log('✓ D190 selfcheck 已接入 npm run selfcheck')

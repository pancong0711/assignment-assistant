/** D201：上传必须带 classDir/taskId，否则读不到新布局草稿。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const root = join(appRoot, '..')
const view = fs.readFileSync(join(appRoot, 'src/components/AiGradingPanel.vue'), 'utf8')
const client = fs.readFileSync(join(appRoot, 'src/lib/engineClient.ts'), 'utf8')
const cli = fs.readFileSync(join(root, 'engine/src/assist/xxt/cli.py'), 'utf8')
const serve = fs.readFileSync(join(root, 'engine/src/assist/serve.py'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

// CLI：scope 选项 + 真正用于读草稿
must(/"--class-dir"/.test(cli), 'CLI 缺少 --class-dir')
must(/"--task-id"/.test(cli), 'CLI 缺少 --task-id')
must(/class_dir=cd_use, task_id=tid_use, alt_task_ids=alt_tids/.test(cli),
  '读草稿未带 scope/alt_task_ids')
must(/discover_draft_scopes/.test(cli), '未自动反查 taskId')
must(/"scope": \{"classDir": cd_use/.test(cli), '无草稿时未回显作用域')

// serve：透传 scope
must(/args \+= \["--class-dir", cdir_up\]/.test(serve), 'serve 未透传 --class-dir')
must(/args \+= \["--task-id", tid_up\]/.test(serve), 'serve 未透传 --task-id')

// 前端：逐生 + 批量都带 scope
must(/classDir\?: string/.test(client) && /taskId\?: string/.test(client),
  'engineClient 未声明 classDir/taskId')
const perStudent = view.split('async function uploadOneStudent')[1]?.split('async function ')[0] || ''
must(/classDir: curWorkDir\.value/.test(perStudent), '逐生上传未带 classDir')
must(/taskId: packId\.value \|\| padId\.value \|\| resolvedScope\.value/.test(perStudent),
  '逐生上传未带 taskId')
const batch = view.split('async function uploadAll')[1]?.split('async function ')[0] || ''
must(/classDir: curWorkDir\.value/.test(batch), '批量上传未带 classDir')

must(/selfcheck:d201/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d201')
must(!!pkg.scripts?.['selfcheck:d201'], 'package.json 缺少 selfcheck:d201')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 上传 CLI 支持并使用了 --class-dir/--task-id')
console.log('✓ serve 透传 scope；无草稿时回显作用域便于排查')
console.log('✓ 前端逐生/批量上传都带 classDir+taskId')
console.log('✓ D201 selfcheck 已接入 npm run selfcheck')

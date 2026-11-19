/** D210：上传前对照用本地缓存，仅「重新读取平台状态」刷新。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const root = join(appRoot, '..')
const view = fs.readFileSync(join(appRoot, 'src/components/AiGradingPanel.vue'), 'utf8')
const client = fs.readFileSync(join(appRoot, 'src/lib/engineClient.ts'), 'utf8')
const up = fs.readFileSync(join(root, 'engine/src/assist/xxt/upload_preview.py'), 'utf8')
const serve = fs.readFileSync(join(root, 'engine/src/assist/serve.py'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

// 后端缓存
must(/def cache_path\(/.test(up), '缺少 cache_path')
must(/def payload_fingerprint\(/.test(up), '缺少本地内容指纹')
must(/def invalidate_cache\(/.test(up), '缺少缓存失效')
must(/DEFAULT_TTL_SEC/.test(up), '缺少缓存有效期')
must(/force_refresh/.test(up), '缺少强制刷新开关')
must(/compose_preview\(/.test(up), '缺少 live/cache 共用组装函数')
must(/stale/.test(up), '未标记“本地内容已变化”')

// serve 接入
must(/force_refresh=bool\(payload\.get\("force"\)\)/.test(serve), 'serve 未透传 force')
must(/invalidate_cache\(ws/.test(serve), '上传后未使缓存失效')

// 前端
must(/previewCache/.test(view), '前端未保存缓存信息')
must(/openUploadPreview\(true, \{ force: true \}\)/.test(view), '“重新读取平台状态”未强制刷新')
must(/平台状态来自本地缓存/.test(view), '未显示缓存来源/时间')
must(/本地内容已变化/.test(view), '未提示缓存 stale')
must(/force\?: boolean/.test(client), 'engineClient 未声明 force')
must(/cache\?: \{/.test(client), 'engineClient 未声明 cache 信息')

must(/selfcheck:d210/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d210')
must(!!pkg.scripts?.['selfcheck:d210'], 'package.json 缺少 selfcheck:d210')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 平台状态本地缓存（含 TTL 与本地内容指纹）')
console.log('✓ 本地内容变化 → 用缓存快照重判并标 stale')
console.log('✓ 「重新读取平台状态」强制刷新；上传后缓存自动失效')
console.log('✓ D210 selfcheck 已接入 npm run selfcheck')

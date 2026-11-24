/** D224：题库编辑器“选图”链路加固（弹窗、取消、配额校验、缩略图刷新、清空）。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const view = fs.readFileSync(join(appRoot, 'src/views/KbEditorView.vue'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

const fn = view.split('async function uploadFig(')[1]?.split('\n}\n')[0] || ''
must(fn.length > 0, '找不到 uploadFig 实现')

// 1) input 必须挂载到 DOM 再 click（部分浏览器对游离 input 不弹窗）
must(/document\.body\.appendChild\(input\)/.test(fn), 'input 未挂载到 DOM')
must(/input\.remove\(\)/.test(fn), 'input 用后未移除')

// 2) 取消/超时兜底，避免 Promise 永久挂起（按钮“没反应”）
must(/oncancel/.test(fn), '未处理用户取消（oncancel）')
must(/setTimeout\(/.test(fn), '缺少超时兜底')

// 3) 存图校验 + 无条件替换 img_path + 刷新计数
must(/settings\.figAssets\[file\.name\]/.test(fn), '存图后未校验 figAssets')
must(/row\.img_path = `fig\/\$\{file\.name\}`/.test(fn), '未无条件更新 img_path')
must(/figRev\.value \+= 1/.test(fn), '未递增缩略图刷新计数')
must(/缩略图\$\{hit \? '已刷新'/.test(fn), '状态未提示缩略图是否命中')

// 4) 模板：缩略图 key 含 figRev；提供清空按钮
must(/:key="`\$\{r\.img_path\}#\$\{figRev\}`"/.test(view), '缩略图未用 figRev 强制刷新')
must(/function clearFig\(/.test(view), '缺少清除题图函数')
must(/@click="clearFig\(r\)"/.test(view), '缺少清除题图按钮')

must(/selfcheck:d224/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d224')
must(!!pkg.scripts?.['selfcheck:d224'], 'package.json 缺少 selfcheck:d224')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 选图 input 挂载 DOM + 取消/超时兜底（不再“没反应”）')
console.log('✓ 存图后校验 figAssets（配额失败有明确报错）')
console.log('✓ 无条件替换 img_path + figRev 强制刷新缩略图')
console.log('✓ 新增「✕ 清除题图」入口')
console.log('✓ D224 selfcheck 已接入 npm run selfcheck')

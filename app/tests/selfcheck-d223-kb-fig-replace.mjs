/** D223：题库编辑器选图可替换（img_path 必须更新）+ fig 写回不再 kb/kb。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const view = fs.readFileSync(join(appRoot, 'src/views/KbEditorView.vue'), 'utf8')
const settings = fs.readFileSync(join(appRoot, 'src/stores/settings.ts'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

const L = await import('../src/lib/kbLayout.ts')

// 1) 行为：kb 前缀判定（写 xlsx 与写 fig 共用）
must(L.resolveKbDirPrefix('kb', ['problems.xlsx']) === '', 'kb 目录应无前缀')
must(L.resolveKbDirPrefix('2609assignment', ['kb', 'classes']) === 'kb',
  'workspace 根应有 kb 前缀')

// 2) 源码契约：选中图片必须**始终**替换 img_path
const fn = view.split('async function uploadFig(')[1]?.split('\n}')[0] || ''
must(fn.length > 0, '找不到 uploadFig 实现')
must(!/if \(!row\.img_path\) row\.img_path =/.test(fn),
  'uploadFig 仍只在 img_path 为空时赋值（换图无效）')
must(/row\.img_path = `fig\/\$\{file\.name\}`/.test(fn),
  'uploadFig 未无条件更新 img_path')
must(/resolveKbDirPrefix\(/.test(fn), 'fig 写回未使用 kb 前缀自动识别')
must(/`\$\{prefix \? prefix \+ '\/' : ''\}fig\/\$\{file\.name\}`/.test(fn),
  'fig 写回路径未按前缀拼装（连 kb 目录会写成 kb/kb/fig）')

// 3) 覆盖同一文件名时也要刷新（persistFigAsset 应覆盖）
must(/persistFigAsset\(name: string, dataUrl: string\) \{\s*\n\s*this\.figAssets\[name\] = dataUrl/.test(settings),
  'persistFigAsset 未覆盖同名图片')

must(/selfcheck:d223/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d223')
must(!!pkg.scripts?.['selfcheck:d223'], 'package.json 缺少 selfcheck:d223')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 选图后 img_path 无条件更新（可更换图片）')
console.log('✓ 同名图片覆盖会刷新预览（persistFigAsset 覆盖）')
console.log('✓ fig 写回按 kb 前缀自动识别（不再 kb/kb/fig）')
console.log('✓ D223 selfcheck 已接入 npm run selfcheck')

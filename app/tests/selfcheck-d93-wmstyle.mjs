/** D93-S3 自检：水印 style_ref 解析（内联 items > style_ref > 默认样式 > 内置三槽）。
 *  通过 stringifySheetHtml 产出的 HTML 间接验证 resolveWmItems 行为。 */
import assert from 'node:assert'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const tmp = mkdtempSync(join(tmpdir(), 'selfcheck-d93wm-'))
const bundle = join(tmp, 's.mjs')
const tpBundle = join(tmp, 't.mjs')
execFileSync(join(appDir, 'node_modules', '.bin', 'esbuild'), [
  resolve(appDir, 'src/lib/sheetHtml.ts'), '--bundle', '--format=esm',
  `--outfile=${bundle}`, '--external:jszip'], { stdio: 'inherit' })
execFileSync(join(appDir, 'node_modules', '.bin', 'esbuild'), [
  resolve(appDir, 'src/lib/taskpad.ts'), '--bundle', '--format=esm', `--outfile=${tpBundle}`], { stdio: 'inherit' })
process.on('exit', () => rmSync(tmp, { recursive: true, force: true }))
const { stringifySheetHtml } = await import(pathToFileURL(bundle).href)
const { emptyTaskpad } = await import(pathToFileURL(tpBundle).href)

function padWith(wm) {
  const p = emptyTaskpad()
  p.layout.orientation = 'portrait'; p.layout.per_page = 1
  p.watermark = wm
  return p
}
const stu = [{ name: '张三', number: '1', class: '', tag: '' }]
const styles = [
  { name: '期末版', items: [{ image: 'watermark/logo-final.png', pos: 'rb', ratio: 0.3, alpha: 0.5 }] },
  { name: '_default', default: true, items: [{ image: 'watermark/logo-default.png', pos: 'lb', ratio: 0.2, alpha: 0.4 }] },
]

// 1) style_ref 命中 → 该样式的图出现在 HTML
let html = stringifySheetHtml({ pad: padWith({ enabled: true, style_ref: '期末版', items: [] }), items: [], students: stu },
  { wmAssets: {}, wmStyles: styles, katex: 'cdn' })
assert.ok(html.includes('logo-final.png'), 'style_ref 应解析出 style 的图（此前不解析 → 预览不变）')
console.log('1) style_ref 命中样式 → 预览含该样式图 … ok')

// 2) 无 style_ref → 默认样式
html = stringifySheetHtml({ pad: padWith({ enabled: true, items: [] }), items: [], students: stu },
  { wmAssets: {}, wmStyles: styles, katex: 'cdn' })
assert.ok(html.includes('logo-default.png'), '无 style_ref 应用默认样式')
console.log('2) 无引用 → 默认样式生效 … ok')

// 3) 内联 items 优先于 style_ref
html = stringifySheetHtml({ pad: padWith({ enabled: true, style_ref: '期末版', items: [{ image: 'watermark/inline.png', pos: 'rt', ratio: 0.2, alpha: 0.5 }] }), items: [], students: stu },
  { wmAssets: {}, wmStyles: styles, katex: 'cdn' })
assert.ok(html.includes('inline.png') && !html.includes('logo-final.png'), '内联 items 优先')
console.log('3) 内联 items 优先于 style_ref … ok')

// 4) 样式库为空 + 无 items → 默认三槽占位标签
html = stringifySheetHtml({ pad: padWith({ enabled: true, items: [] }), items: [], students: stu },
  { wmAssets: {}, wmStyles: [], katex: 'cdn' })
assert.ok(html.includes('university') || html.includes('logo-university'), '回落内置三槽')
console.log('4) 无样式 → 内置三槽 … ok')

console.log('\nD93-S3 水印 style_ref 解析自检通过 ✔')

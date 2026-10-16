/** D93-S5 自检：整班预览连续页码 + KaTeX 就绪等待脚本存在。 */
import assert from 'node:assert'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const tmp = mkdtempSync(join(tmpdir(), 'selfcheck-d93cp-'))
const bundle = join(tmp, 's.mjs'); const tp = join(tmp, 't.mjs')
execFileSync(join(appDir, 'node_modules', '.bin', 'esbuild'),
  [resolve(appDir, 'src/lib/sheetHtml.ts'), '--bundle', '--format=esm', `--outfile=${bundle}`, '--external:jszip'], { stdio: 'inherit' })
execFileSync(join(appDir, 'node_modules', '.bin', 'esbuild'),
  [resolve(appDir, 'src/lib/taskpad.ts'), '--bundle', '--format=esm', `--outfile=${tp}`], { stdio: 'inherit' })
process.on('exit', () => rmSync(tmp, { recursive: true, force: true }))
const { stringifySheetHtml } = await import(pathToFileURL(bundle).href)
const { emptyTaskpad } = await import(pathToFileURL(tp).href)

function mkPad(id, perPage) {
  const p = emptyTaskpad(); p.id = id; p.layout.orientation = 'portrait'; p.layout.per_page = perPage
  p.items = []
  return p
}
const stu = [{ name: 'A', number: '1', class: '', tag: 't' }, { name: 'B', number: '2', class: '', tag: 't' }]
// 两页块/生（per_page=1, 无 items → 1 chunk；用两个 pad 各 1 生制造总块数）
const inputs = [
  { pad: mkPad('p1', 1), items: [], students: [stu[0]] },
  { pad: mkPad('p2', 1), items: [], students: [stu[1]] },
]
const htmlC = stringifySheetHtml(inputs, { katex: 'cdn', continuousPage: true, includePageText: true })
// 连续：第 1 页、第 2 页
assert.ok(htmlC.includes('第 1 页') && htmlC.includes('第 2 页'), '连续页码应出现 第1页 & 第2页')
assert.ok(htmlC.includes('/2页'), '页脚总页数应为 2（整班连续）')
console.log('1) continuousPage=true → 跨学生连续页码（第1/第2页，总2）… ok')

const htmlS = stringifySheetHtml(inputs, { katex: 'cdn', continuousPage: false, includePageText: true })
// 非连续：两份都从第 1 页起
const count1 = (htmlS.match(/第 1 页/g) || []).length
assert.ok(count1 >= 2, '非连续：每生从第 1 页起（出现 ≥2 次）')
console.log('2) continuousPage=false → 每生从第 1 页起 … ok')

// KaTeX 就绪等待脚本（轮询 renderMathInElement）
assert.ok(htmlC.includes('waitReady') && htmlC.includes('renderMathInElement'), '应含 KaTeX 就绪等待脚本')
console.log('3) KaTeX 就绪等待脚本存在 … ok')

console.log('\nD93-S5 整班预览（连续页码 + KaTeX 就绪）自检通过 ✔')

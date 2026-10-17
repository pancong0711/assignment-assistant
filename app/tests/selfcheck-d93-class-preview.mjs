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

/* ---------- D93-fix：整班学生按学号升序（教务处名单顺序） ---------- */
{
  // 镜像 buildClassInputs 的排序（含空学号排末尾 + 稳定）
  function sortByNumber(students) {
    return [...students].map((st, i) => ({ st, i })).sort((A, B) => {
      const na = String(A.st.number || '').trim(), nb = String(B.st.number || '').trim()
      const ha = na !== '', hb = nb !== ''
      if (ha && hb) { const c = na.localeCompare(nb, undefined, { numeric: true }); return c !== 0 ? c : A.i - B.i }
      if (ha !== hb) return ha ? -1 : 1
      return A.i - B.i
    }).map(({ st }) => st)
  }
  // 输入：分数降序（模拟成绩源顺序）
  const input = [
    { name: 'D', number: '2026004' }, { name: 'B', number: '2026002' },
    { name: 'A', number: '2026001' }, { name: 'C', number: '2026003' },
    { name: 'X', number: '' },
  ]
  const got = sortByNumber(input).map((s) => s.name)
  assert.deepEqual(got, ['A', 'B', 'C', 'D', 'X'], `按学号升序（空号末尾），实得 ${got}`)
  // 数值感知：2 < 10
  const g2 = sortByNumber([{ name: 'y', number: '10' }, { name: 'x', number: '2' }]).map((s) => s.name)
  assert.deepEqual(g2, ['x', 'y'], '学号数值感知排序')
  console.log('4) 整班按学号升序（空号末尾、数值感知）… ok')
}
console.log('\nD93-fix 整班顺序自检通过 ✔')

/* ---------- D94-T2：stringifyClassHtml 按点名册顺序逐人（不按 pack 分组） ---------- */
{
  const { stringifyClassHtml } = await import(pathToFileURL(bundle).href)
  function mkPad(id) { const p = emptyTaskpad(); p.id = id; p.layout.orientation = 'portrait'; p.layout.per_page = 1; p.items = []; return p }
  const padA = mkPad('padA'), padB = mkPad('padB')   // 两个 tag 两张纸
  const map = { qa: padA, copy: padB }
  // 点名册顺序：A(qa), B(copy), C(qa), D(copy) —— 交错 tag
  const students = [
    { name: 'A', number: '1', tag: 'qa' }, { name: 'B', number: '2', tag: 'copy' },
    { name: 'C', number: '3', tag: 'qa' }, { name: 'D', number: '4', tag: 'copy' },
  ]
  const resolve = (stu) => map[stu.tag] ? { pad: map[stu.tag], items: [] } : null
  const { html } = stringifyClassHtml(students, resolve, { katex: 'cdn' })
  const order = [...html.matchAll(/data-student="([^"]+)"/g)].map((m) => m[1])
  assert.deepEqual(order, ['A', 'B', 'C', 'D'], `应按点名册逐人交错输出，实得 ${order}`)
  console.log('5) 整班按点名册逐人输出（不按 pack 分组）… ok')
}
console.log('\nD94-T2 整班点名册顺序自检通过 ✔')

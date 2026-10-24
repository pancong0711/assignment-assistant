/** D101 自检：参考答案 LaTeX 渲染（定界符 + 幂等）。
 *  1) 生成的 HTML 含 4 个定界符，且长定界符在前（顺序决定 $$ 不被 $ 拆开）；
 *  2) HTML 里的 JS 字面量层数正确（浏览器 eval 后 '\\[' 必须等于"反斜杠+方括号"）；
 *  3) 渲染幂等标记 data-katex-done 存在；
 *  4) katexRender.ts 的 KATEX_DELIMITERS 与打印模板同口径（单一事实源）。
 *  运行：node tests/selfcheck-d101-latex-render.mjs */
import assert from 'node:assert'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const tmp = mkdtempSync(join(tmpdir(), 'selfcheck-d101-'))
const shBundle = join(tmp, 'sheetHtml.bundle.mjs')
const tpBundle = join(tmp, 'taskpad.bundle.mjs')
const krBundle = join(tmp, 'katexRender.bundle.mjs')
execFileSync(join(appDir, 'node_modules', '.bin', 'esbuild'),
  [resolve(appDir, 'src/lib/sheetHtml.ts'), '--bundle', '--format=esm', `--outfile=${shBundle}`, '--external:jszip'], { stdio: 'inherit' })
execFileSync(join(appDir, 'node_modules', '.bin', 'esbuild'),
  [resolve(appDir, 'src/lib/taskpad.ts'), '--bundle', '--format=esm', `--outfile=${tpBundle}`], { stdio: 'inherit' })
execFileSync(join(appDir, 'node_modules', '.bin', 'esbuild'),
  [resolve(appDir, 'src/lib/katexRender.ts'), '--bundle', '--format=esm', `--outfile=${krBundle}`], { stdio: 'inherit' })
process.on('exit', () => rmSync(tmp, { recursive: true, force: true }))

const { stringifySheetHtml } = await import(pathToFileURL(shBundle).href)
const { emptyTaskpad } = await import(pathToFileURL(tpBundle).href)
const { KATEX_DELIMITERS } = await import(pathToFileURL(krBundle).href)

const pad = emptyTaskpad(); pad.id = 'd101'; pad.layout.per_page = 1
const items = [{ id: 'c1', no: '1.', content: '求 $v$', solution: '解 $v=2t$' }]
const html = stringifySheetHtml([{ pad, items }],
  { katex: 'relative', includeSolution: true, students: [{ name: 'A', number: '1', class: 'c' }] })

/* ---------- 1) 四个定界符 + 顺序 ---------- */
const backslash = String.fromCharCode(92)
const expected = [
  { left: '$$', right: '$$', display: true },
  { left: backslash + '[', right: backslash + ']', display: true },
  { left: '$', right: '$', display: false },
  { left: backslash + '(', right: backslash + ')', display: false },
]
{
  // 从 HTML 里取出 delimiters 数组源码，交给 Function 求值（= 浏览器真实语义）
  const start = html.indexOf('delimiters:')
  const arrStart = html.indexOf('[', start)
  let depth = 0, end = -1
  for (let i = arrStart; i < html.length; i++) {
    if (html[i] === '[') depth++
    else if (html[i] === ']') { depth--; if (depth === 0) { end = i; break } }
  }
  assert.ok(end > arrStart, 'HTML 里应能找到 delimiters 数组')
  const expr = html.slice(arrStart, end + 1)
  const parsed = new Function(`return ${expr}`)()
  assert.deepEqual(parsed, expected,
    `打印模板定界符必须为 4 个且顺序固定（长定界符在前）；实际 ${JSON.stringify(parsed)}`)
  console.log('1) 打印 HTML 含 4 个定界符（$$ \\[ $ \\(，长定界符在前）… ok')
}

/* ---------- 2) 转义层数：确保浏览器拿到的就是"反斜杠+方括号" ---------- */
{
  // HTML 源里必须是「2 个反斜杠 + [」：浏览器 JS 解析后得到 \[（反斜杠+方括号，长度 2）。
  // 1 个 → JS 值变成 "["（未被识别，公式原样显示源码，D101 的原始 bug）；
  // 3+ 个 → JS 值变成字面量 \\[（多一层，同样不渲染）。
  let count = 0
  const idx = html.indexOf("left: '" + backslash)
  assert.ok(idx >= 0, 'HTML 应含 left: \\[ 形式的定界符')
  for (let i = idx + "left: '".length; html[i] === backslash; i++) count++
  assert.equal(count, 2,
    `HTML 源里应有 2 个反斜杠（实际 ${count}）：1 个会被 JS 吞成 "["，3+ 个会变成字面量`)
  console.log('2) 转义层数正确（HTML 源 2 个反斜杠 → 浏览器 JS 值 "\\\\["）… ok')
}

/* ---------- 3) 幂等标记 ---------- */
assert.ok(html.includes('data-katex-done'), '渲染脚本必须有幂等标记（避免重复渲染破坏 DOM）')
console.log('3) 渲染幂等标记 data-katex-done 存在 … ok')

/* ---------- 4) katexRender 与模板同口径（单一事实源） ---------- */
{
  assert.deepEqual([...KATEX_DELIMITERS], expected, 'katexRender.ts 定界符必须与打印模板一致')
  console.log('4) katexRender.ts 与打印模板定界符同口径 … ok')
}

console.log('\nD101 LaTeX 渲染自检通过 ✔')

/** D109 自检：预排版切分不得破坏 <svg> 与 LaTeX 公式。
 *
 *  背景 bug：
 *  1) splitIntoPieces 把多行 <svg> 按行拆成 5 块 → 每格只拿到残缺片段
 *     （`<svg…>` 单独成块 = 空白框，`<rect/>` 单独成块 = 不可见，`</svg>` = 杂字）；
 *  2) splitLongParagraph 按 120 字符硬切，会把 `$h = \frac{v_0^2}{2g}$` 撕成
 *     两半，前一段是未闭合的 `$` → KaTeX 不渲染，后续内容从预览里消失。
 *
 *  运行：node tests/selfcheck-d109-layout-atoms.mjs */
import assert from 'node:assert'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const tmp = mkdtempSync(join(tmpdir(), 'selfcheck-d109-'))
const bundle = join(tmp, 'autoLayout.bundle.mjs')
execFileSync(join(appDir, 'node_modules', '.bin', 'esbuild'), [
  resolve(appDir, 'src/lib/autoLayout.ts'), '--bundle', '--format=esm',
  `--outfile=${bundle}`, '--log-level=error',
], { stdio: 'inherit' })
process.on('exit', () => rmSync(tmp, { recursive: true, force: true }))

const { splitIntoPieces } = await import(pathToFileURL(bundle).href)

/** 未转义 `$` 必须成对（奇数 = 有公式被切断）。 */
function assertBalanced(label, pieces) {
  for (const p of pieces) {
    const n = (p.match(/(?<!\\)\$/g) || []).length
    assert.equal(n % 2, 0, `${label}：出现未闭合 $（片段=${JSON.stringify(p)}）`)
  }
}

/* 1) 多行 SVG 必须整体成块 */
{
  const sol = '由受力分析可知：\n\n'
    + '<svg viewBox="0 0 200 150" xmlns="http://www.w3.org/2000/svg">\n'
    + '  <rect x="10" y="10" width="80" height="40" stroke="black" fill="none"/>\n'
    + '  <text x="30" y="35">m</text>\n</svg>\n\n因此 $a = F/m$。'
  const pieces = splitIntoPieces(sol)
  const svgPieces = pieces.filter((p) => p.includes('<svg'))
  assert.equal(svgPieces.length, 1, 'SVG 应只出现在一个块里')
  assert.ok(/<svg[\s\S]*<\/svg>/.test(svgPieces[0]), 'SVG 起止标签必须在同一块')
  assert.ok(svgPieces[0].includes('<rect') && svgPieces[0].includes('<text'), '图元不能被丢到别的块')
  for (const p of pieces) {
    assert.ok(!p.includes('</svg>') || p.includes('<svg'), '</svg> 不能落单')
  }
  assertBalanced('svg 混合', pieces)
}

/* 2) 长段落里的 $..$ 不得被切断（原始 bug 复现用例） */
{
  const para = '由机械能守恒定律可知系统在运动过程中只有重力做功因此机械能保持不变取地面为零势能参考面'
    + '则物体在最高点的动能为零全部转化为重力势能于是有等式 $$\\frac{1}{2}mv_0^2 = mgh$$ '
    + '由此可解得最大高度 h 的表达式为 $h = \\frac{v_0^2}{2g}$'
  const pieces = splitIntoPieces(para)
  assertBalanced('长段落', pieces)
  const joined = pieces.join('')
  assert.ok(joined.includes('$h = \\frac{v_0^2}{2g}$'), '公式应完整保留在某一块中')
  assert.ok(joined.includes('$$\\frac{1}{2}mv_0^2 = mgh$$'))
}

/* 3) 超长单公式：宁可超限也不切断 */
{
  const pieces = splitIntoPieces('前言$' + 'q'.repeat(300) + '$结尾')
  assertBalanced('超长公式', pieces)
  assert.ok(pieces.join('').includes('$' + 'q'.repeat(300) + '$'))
}

/* 4) 多种定界符 */
{
  const pieces = splitIntoPieces('于是 \\(a=b\\) 并且 \\[c=d\\] 结束，' + 'x'.repeat(200) + ' $e=f$')
  for (const p of pieces) {
    assert.equal((p.match(/\\\(/g) || []).length, (p.match(/\\\)/g) || []).length, '\\( 应成对')
    assert.equal((p.match(/\\\[/g) || []).length, (p.match(/\\\]/g) || []).length, '\\[ 应成对')
  }
}

/* 5) 表格/代码块同样整体保留 */
{
  const md = '数据：\n\n<table>\n<tr><td>1</td><td>2</td></tr>\n</table>\n\n完。'
  const pieces = splitIntoPieces(md)
  const t = pieces.filter((p) => p.includes('<table'))
  assert.equal(t.length, 1)
  assert.ok(t[0].includes('</table>'))
}

/* 6) 空白输入 */
assert.deepEqual(splitIntoPieces(''), [])
assert.deepEqual(splitIntoPieces('   '), [])

console.log('OK d109-layout-atoms：SVG/表格整体成块 · 公式不被切断 · 定界符成对 · 超长公式保完整')

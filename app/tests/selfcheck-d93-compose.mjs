/** D93-S2 自检：合成题（summary/copy/translation）与引擎同算法。
 *  - seedIndex 与引擎 compose.seed_index 结果一致（parity 向量）；
 *  - copyContent 模板一致；
 *  - expandPadItems 的 summary/copy/translation 行为（用桩 bookOf）。
 *  运行：node tests/selfcheck-d93-compose.mjs */
import assert from 'node:assert'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const tmp = mkdtempSync(join(tmpdir(), 'selfcheck-d93-'))
const bundle = join(tmp, 'sheetHtml.bundle.mjs')
const tpBundle = join(tmp, 'taskpad.bundle.mjs')
execFileSync(join(appDir, 'node_modules', '.bin', 'esbuild'), [
  resolve(appDir, 'src/lib/sheetHtml.ts'), '--bundle', '--format=esm',
  `--outfile=${bundle}`, '--external:jszip',
], { stdio: 'inherit' })
execFileSync(join(appDir, 'node_modules', '.bin', 'esbuild'), [
  resolve(appDir, 'src/lib/taskpad.ts'), '--bundle', '--format=esm',
  `--outfile=${tpBundle}`,
], { stdio: 'inherit' })
process.on('exit', () => rmSync(tmp, { recursive: true, force: true }))

const { expandPadItems } = await import(pathToFileURL(bundle).href)
const { seedIndex, copyContent, SUMMARY_CONTENT } = await import(pathToFileURL(tpBundle).href)

// 1) seedIndex 范围 + 确定性
for (const s of [0, 1, 12345, 2 ** 31 - 1]) {
  for (const n of [1, 3, 7]) {
    const v = seedIndex(s, n)
    assert.ok(v >= 0 && v < n, `seedIndex(${s},${n})=${v} 越界`)
  }
}
assert.equal(seedIndex(123, 5), seedIndex(123, 5))
console.log('1) seedIndex 范围/确定性 … ok')

// 1b) 跨语言 parity：与引擎 paper/compose.seed_index 的实测向量逐一对齐
const PARITY = {
  0: [0, 0, 0, 4, 5], 1: [0, 0, 0, 4, 0], 123: [0, 0, 1, 4, 6],
  12345: [0, 1, 1, 2, 6], 2147483647: [0, 2, 3, 6, 8],
}
const NS = [1, 3, 5, 7, 10]
for (const [s, expect] of Object.entries(PARITY)) {
  const got = NS.map((n) => seedIndex(Number(s), n))
  assert.deepEqual(got, expect, `seedIndex parity 不符 seed=${s}: ${got} vs ${expect}`)
}
console.log('1b) seedIndex 与引擎跨语言 parity … ok')

// 2) copyContent 模板
assert.equal(copyContent('42', 'X', 'k1'), '请抄写：42页 X，并画出示意图。（k1）')
console.log('2) copyContent 模板 … ok')

// 3) expandPadItems：summary / copy-page / translation
const bookOf = (kind) => {
  if (kind === 'problems') return { chapters: [{ name: 'chap10', rows: [{ id: 'c1', content: '计算题1', solution: '', img_path: '', page: '' }] }] }
  if (kind === 'copy') return { chapters: [{ name: 'chap10', rows: [
    { id: 'k1', content: '抄写A', solution: '', img_path: '', page: '42' },
    { id: 'k2', content: '抄写B', solution: '', img_path: '', page: '' }] }] }
  if (kind === 'translation') return { chapters: [{ name: 'translation', rows: [
    { id: 'translation', content: '翻译0', solution: '', img_path: '', page: '' },
    { id: 'translation', content: '翻译1', solution: '', img_path: '', page: '' },
    { id: 'translation', content: '翻译2', solution: '', img_path: '', page: '' }] }] }
  return undefined
}

const padSummary = { id: 'p1', random_seed: 1, layout: { orientation: 'portrait', per_page: 1, numbering: 'auto' },
  items: [{ kb: 'problems', chap: 'chap10', ids: ['c1'], tag: 'summary' }] }
const outS = expandPadItems(padSummary, bookOf)
assert.ok(outS.some((x) => x.content === SUMMARY_CONTENT), 'summary 应追加总结题')
assert.equal(outS.filter((x) => x.id === 'summary').length, 1)
console.log('3) summary 自动追加 … ok')

const padCopy = { id: 'p2', layout: { orientation: 'portrait', per_page: 1, numbering: 'auto' },
  items: [{ kb: 'copy', chap: 'chap10', ids: ['k1', 'k2'], tag: 'copy' }] }
const outC = expandPadItems(padCopy, bookOf)
assert.ok(outC.find((x) => x.id === 'k1').content.startsWith('请抄写：42页'))
assert.equal(outC.find((x) => x.id === 'k2').content, '抄写B')
console.log('4) copy 有 page 改写 … ok')

const padTr = { id: 'p3', random_seed: 123, layout: { orientation: 'portrait', per_page: 1, numbering: 'auto' },
  items: [{ kb: 'problems', chap: 'chap10', ids: ['c1'], tag: 'translation' }] }
const a = expandPadItems(padTr, bookOf).find((x) => x.id === 'translation').content
const b = expandPadItems(padTr, bookOf).find((x) => x.id === 'translation').content
assert.equal(a, b, '同 seed 同题')
console.log('5) translation 确定随机（同 seed 同题）… ok')

// 6) 切 tag 不残留（qa 不含 summary/translation）
const padQa = { id: 'p4', random_seed: 1, layout: { orientation: 'portrait', per_page: 1, numbering: 'auto' },
  items: [{ kb: 'problems', chap: 'chap10', ids: ['c1'], tag: 'qa' }] }
const outQ = expandPadItems(padQa, bookOf)
assert.ok(!outQ.some((x) => x.id === 'summary' || x.id === 'translation'), '切 tag 后不残留合成题')
console.log('6) 切 tag 合成题不残留 … ok')

console.log('\nD93-S2 合成题（PWA 同源）自检通过 ✔')

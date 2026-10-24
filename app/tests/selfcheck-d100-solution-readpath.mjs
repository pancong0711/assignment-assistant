/** D100 自检：参考答案「生效版」读取链路（PWA 侧）。
 *  1) pickEffectiveSolution 优先级与引擎 effective_solution 一致（pinned > latest > fallback > 空）；
 *  2) expandPadItems 注入解析器后题帧 solution 取生效版，并带 solutionFrom/Version/Source；
 *  3) 不传解析器 → 回落 xlsx 列（旧行为，引擎离线也一致）；
 *  4) 未置顶（latest）也生效（AI 作答后忘点置顶仍可见）；
 *  5) 批量索引条目（带 id 而非 version）也能正确取版本号。
 *  运行：node tests/selfcheck-d100-solution-readpath.mjs */
import assert from 'node:assert'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const tmp = mkdtempSync(join(tmpdir(), 'selfcheck-d100-'))
const bundle = join(tmp, 'sheetHtml.bundle.mjs')
execFileSync(join(appDir, 'node_modules', '.bin', 'esbuild'), [
  resolve(appDir, 'src/lib/sheetHtml.ts'), '--bundle', '--format=esm',
  `--outfile=${bundle}`, '--external:jszip',
], { stdio: 'inherit' })
process.on('exit', () => rmSync(tmp, { recursive: true, force: true }))

const { pickEffectiveSolution, expandPadItems, xlsxOnlySolutions } =
  await import(pathToFileURL(bundle).href)

/* ---------- 1) 优先级 ---------- */
{
  const doc = { versions: [
    { id: 'v1', text: '旧 AI', source: 'ai', pinned: false },
    { id: 'v2', text: '人工定稿', source: 'human', pinned: true },
    { id: 'v3', text: '新 AI', source: 'ai', pinned: false },
  ] }
  const e = pickEffectiveSolution(doc, 'xlsx 旧列')
  assert.equal(e.text, '人工定稿', 'pinned 优先于最新版')
  assert.equal(e.from, 'pinned')
  assert.equal(e.version, 'v2')
  assert.equal(e.source, 'human')

  const latest = pickEffectiveSolution({ versions: [{ id: 'v1', text: 'A' }, { id: 'v2', text: 'B' }] }, 'x')
  assert.equal(latest.text, 'B')
  assert.equal(latest.from, 'latest', '无 pinned → 最新版生效（不得回落 xlsx）')
  assert.equal(latest.pinned, false)

  assert.equal(pickEffectiveSolution(null, 'xlsx 旧列').from, 'fallback')
  assert.equal(pickEffectiveSolution(null, 'xlsx 旧列').text, 'xlsx 旧列')
  assert.equal(pickEffectiveSolution(null, '   ').from, 'xlsx')
  assert.equal(pickEffectiveSolution({ versions: [{ id: 'v1', text: '  ' }] }, 'fb').from, 'fallback',
    '空正文版本应被忽略')
  // 批量索引条目（field=id、无 versions）
  const idx = pickEffectiveSolution({ id: 'v7', text: 'AI 正文', source: 'ai', from: 'pinned', pinned: true }, '')
  assert.equal(idx.version, 'v7')
  console.log('1) pickEffectiveSolution 优先级（pinned > latest > fallback > 空）… ok')
}

/* ---------- 2)~4) expandPadItems 注入解析器 ---------- */
const bookOf = (kind) => {
  if (kind === 'problems') return { chapters: [{ name: 'chap04', rows: [
    { id: 'c1', content: '题一', solution: 'xlsx 旧答案', img_path: '', page: '' },
    { id: 'c2', content: '题二', solution: '', img_path: '', page: '' },
  ] }] }
  return undefined
}
const pad = { id: 'p1', layout: { orientation: 'portrait', per_page: 2, numbering: 'auto' },
  items: [{ kb: 'problems', chap: 'chap04', ids: ['c1', 'c2'], tag: 't' }] }

{
  // 模拟 kb store 索引：c1 = AI 置顶版，c2 = 无版本
  const index = { c1: { id: 'v3', text: 'AI 置顶答案', source: 'ai', from: 'pinned', pinned: true } }
  const solOf = (qid, fallback) => {
    const hit = index[qid]
    if (hit && String(hit.text || '').trim()) return { ...hit, version: hit.id }
    return pickEffectiveSolution(null, fallback)
  }
  const out = expandPadItems(pad, bookOf, solOf)
  const c1 = out.find((x) => x.id === 'c1')
  const c2 = out.find((x) => x.id === 'c2')
  assert.equal(c1.solution, 'AI 置顶答案', 'AI 生效答案必须进入题帧')
  assert.equal(c1.solutionFrom, 'pinned')
  assert.equal(c1.solutionVersion, 'v3')
  assert.equal(c1.solutionSource, 'ai')
  assert.equal(c2.solution, '', '无版本无 xlsx → 空')
  console.log('2) expandPadItems 注入生效解析器（AI 置顶版进入题帧）… ok')

  // 4) latest（未置顶）也生效
  const index2 = { c1: { id: 'v4', text: 'AI 未置顶', source: 'ai', from: 'latest', pinned: false } }
  const out2 = expandPadItems(pad, bookOf, (q, fb) => index2[q] ?? pickEffectiveSolution(null, fb))
  const c1b = out2.find((x) => x.id === 'c1')
  assert.equal(c1b.solution, 'AI 未置顶', '未置顶的最新版也要生效')
  assert.equal(c1b.solutionFrom, 'latest')
  console.log('4) 未置顶（latest）同样生效（AI 忘点置顶也可见）… ok')
}

/* ---------- 3) 不传解析器 → 旧行为（xlsx 列） ---------- */
{
  const out = expandPadItems(pad, bookOf)
  assert.equal(out.find((x) => x.id === 'c1').solution, 'xlsx 旧答案')
  const explicit = expandPadItems(pad, bookOf, xlsxOnlySolutions)
  assert.deepEqual(explicit.map((x) => x.solutionFrom), ['fallback', 'xlsx'])
  console.log('3) 缺省/显式 xlsxOnlySolutions 回落 xlsx 列（引擎离线同旧行为）… ok')
}

/* ---------- 5) translation 合成题同样走解析器 ---------- */
{
  const bookOfT = (kind) => {
    if (kind === 'translation') return { chapters: [{ name: 'translation', rows: [
      { id: 'T1', content: '翻译题', solution: '', img_path: '', page: '' },
    ] }] }
    return undefined
  }
  const padT = { id: 'p2', random_seed: 1, target_tag: 'translation', layout: { orientation: 'portrait', per_page: 1 },
    items: [] }
  const out = expandPadItems(padT, bookOfT, (q, fb) =>
    q === 'T1' ? { text: '译文生效版', from: 'pinned', version: 'v1', source: 'ai' } : pickEffectiveSolution(null, fb))
  const tr = out.find((x) => x.tag === 'translation')
  assert.equal(tr.solution, '译文生效版')
  assert.equal(tr.solutionFrom, 'pinned')
  console.log('5) translation 合成题同样走生效解析器 … ok')
}

console.log('\nD100 参考答案生效版读取链路自检通过 ✔')

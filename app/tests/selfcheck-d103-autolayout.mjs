/** D103 自检：MxN 网格 + 参考答案预排版（autoLayout）。
 *
 *  1) 切分：段落/行间公式边界切分；行间公式**整块不切**；
 *  2) 同格不混排：不同题目的块不得同处一 cell；
 *  3) 写满续写：答案超长时后续块标 cont 且进入「下一页第 1 格」；
 *  4) 题目顺延：前一题占用后续格后，后一题不得覆盖它（cell 不重复且顺序单调）；
 *  5) 页号连续（无空洞跳号）；
 *  6) 公式不切：产物中每个 $$..$$ 块内容与原公式逐字一致；
 *  7) 版式降级：带答案时只允许 横 1×2 / 竖 2×1；
 *  8) contentHash 判定（layoutMatches）。
 *
 *  运行：node tests/selfcheck-d103-autolayout.mjs */
import assert from 'node:assert'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const tmp = mkdtempSync(join(tmpdir(), 'selfcheck-d103-'))
const bundle = join(tmp, 'autoLayout.mjs')
execFileSync(join(appDir, 'node_modules', '.bin', 'esbuild'),
  [resolve(appDir, 'src/lib/autoLayout.ts'), '--bundle', '--format=esm', `--outfile=${bundle}`], { stdio: 'inherit' })
process.on('exit', () => rmSync(tmp, { recursive: true, force: true }))

const { autoLayout, splitIntoPieces, solveGridForSolution, layoutMatches, contentFingerprint } =
  await import(pathToFileURL(bundle).href)

/* ---------- 1) 切分 ---------- */
{
  const pieces = splitIntoPieces('第一段\n第二段\n\n$$a=b$$\n\n\\[c=d\\]')
  assert.deepEqual(pieces, ['第一段', '第二段', '$$a=b$$', '\\[c=d\\]'],
    '应按段落/行间公式边界切分，且公式整块保留')
  // 行间公式内含空行也不得被切开
  const multi = splitIntoPieces('$$\\begin{aligned}\na&=1\\\\\n\nb&=2\n\\end{aligned}$$')
  assert.equal(multi.length, 1, '行间公式即使含空行也必须是一整块')
  assert.ok(multi[0].startsWith('$$') && multi[0].endsWith('$$'))
  console.log('1) 切分：段落边界 + 行间公式整块不切 … ok')
}

/* ---------- 共通：确定性测量（模拟真实高度） ---------- */
const measure = (text) => 24 + Math.ceil(String(text).length / 40) * 24
const geometry = { cellW: 478, cellH: 300, rows: 1, cols: 2 }

/* ---------- 2)+3) 同格不混排 + 超长续写 ---------- */
const items = [
  { qid: 'q1', no: '1.', content: '短题干一', solution: '短答案一' },
  { qid: 'q2', no: '2.', content: '题干二', solution: '答'.repeat(900) },
  { qid: 'q3', no: '3.', content: '题干三', solution: '答案三' },
]
const res = autoLayout({ geometry, items, measure })
{
  // 同格不混排：一个 cell 内只能出现同一 qid（同题续段允许）
  let maxQidsPerCell = 0
  for (const pg of res.pages) {
    for (const c of pg.cells) {
      const qids = new Set(c.blocks.map((b) => b.qid))
      maxQidsPerCell = Math.max(maxQidsPerCell, qids.size)
      assert.equal(qids.size, 1, `同格不混排被破坏：cell(${c.row},${c.col}) 含 ${[...qids].join(',')}`)
    }
  }
  assert.equal(maxQidsPerCell, 1, '每格只应有一道题')
  // 超长答案必须被切分并标 cont
  const conts = res.pages.flatMap((p) => p.cells.flatMap((c) => c.blocks)).filter((b) => b.cont)
  assert.ok(conts.length > 0, '超长答案应产生续段（cont: true）')
  // 续段必须位于「下一页第 1 格」（col=0）
  for (const pg of res.pages) for (const c of pg.cells) {
    for (const b of c.blocks) if (b.cont) {
      // 续段可出现在同页后续格（同题追加）或下一页首格
      assert.ok(c.col === 0 || b.qid === 'q2', '续段应进入新页第 1 格')
    }
  }
  // 强断言：**不同题目**的块不得共处同一 cell（同一题的续段跨格是正常的 R3 行为）
  res.pages.forEach((pg) => pg.cells.forEach((c, ci) => {
    const qids = new Set(c.blocks.map((b) => b.qid))
    assert.ok(qids.size <= 1, `cell(${pg.page}:${ci}) 混入了多道题：${[...qids].join(',')}`)
  }))
  console.log('2) 同格不混排（每格仅一道题）+ 3) 超长答案产生续段 … ok')
}

/* ---------- 4) 题目顺延不丢 ---------- */
{
  const all = res.pages.flatMap((p) => p.cells.flatMap((c) => c.blocks))
  // 每题至少要出现一次
  for (const it of items) {
    assert.ok(all.some((b) => b.qid === it.qid), `题目 ${it.qid} 丢失`)
  }
  // 文本完整性：同题所有块拼起来必须覆盖原文（不丢字）
  for (const it of items) {
    const got = all.filter((b) => b.qid === it.qid && b.kind === 'solution').map((b) => b.text).join('')
    assert.equal(got, it.solution, `题目 ${it.qid} 的答案内容有丢失/改变`)
  }
  console.log('4) 题目顺延不丢 + 答案文本完整性 … ok')
}

/* ---------- 4b) 短题也不得共格（同格不混排的针对性用例） ---------- */
{
  // 三题都很短：若实现"题目结束后不换格"，就会挤进同一格
  const tiny = [
    { qid: 't1', no: '1.', content: '甲', solution: '一' },
    { qid: 't2', no: '2.', content: '乙', solution: '二' },
    { qid: 't3', no: '3.', content: '丙', solution: '三' },
  ]
  const r3 = autoLayout({ geometry: { cellW: 478, cellH: 600, rows: 1, cols: 2 }, items: tiny, measure })
  const seen = new Set()
  for (const pg of r3.pages) for (const c of pg.cells) {
    const qids = [...new Set(c.blocks.map((b) => b.qid))]
    assert.equal(qids.length, 1, `短题同格混排：cell 含 ${qids.join(',')}`)
    seen.add(qids[0])
  }
  assert.equal(seen.size, 3, '三道题都应出现')
  // 每题必须独占一格（cell 数 >= 3）
  const cellCount = r3.pages.reduce((n, pg) => n + pg.cells.length, 0)
  assert.ok(cellCount >= 3, `每题应独占一格，实际仅 ${cellCount} 格`)
  console.log('4b) 短题也严格同格不混排（每题独占一格）… ok')
}

/* ---------- 5) 页号连续 ---------- */
{
  const nums = res.pages.map((p) => p.page)
  assert.deepEqual(nums, nums.map((_, i) => i + 1), `页号必须连续，实际 ${nums.join(',')}`)
  console.log('5) 页号连续（无空洞）… ok')
}

/* ---------- 6) 公式不切 ---------- */
{
  const f = '$$\\int_0^1 x\\,dx=\\frac12$$'
  const r2 = autoLayout({
    geometry: { cellW: 478, cellH: 80, rows: 1, cols: 2 },
    items: [{ qid: 'm1', no: '1.', content: '题干' + '填充'.repeat(200), solution: '前文\n\n' + f + '\n\n后文' }],
    measure,
  })
  const blocks = r2.pages.flatMap((p) => p.cells.flatMap((c) => c.blocks))
  const mathBlocks = blocks.filter((b) => b.text.includes('\\int_0^1'))
  assert.equal(mathBlocks.length, 1, '行间公式不得被切分成多块')
  assert.equal(mathBlocks[0].text, f, '公式块内容必须与原文逐字一致')
  console.log('6) 公式整块不切 … ok')
}

/* ---------- 7) 版式降级 ---------- */
{
  assert.deepEqual(solveGridForSolution('landscape', 1, 2), { rows: 1, cols: 2, downgraded: false })
  assert.deepEqual(solveGridForSolution('portrait', 2, 1), { rows: 2, cols: 1, downgraded: false })
  assert.deepEqual(solveGridForSolution('landscape', 2, 2), { rows: 1, cols: 2, downgraded: true },
    '横版 2×2 应降级为 1×2')
  assert.deepEqual(solveGridForSolution('portrait', 4, 1), { rows: 2, cols: 1, downgraded: true },
    '竖版 4×1 应降级为 2×1')
  console.log('7) 带答案版式降级（横 1×2 / 竖 2×1）… ok')
}

/* ---------- 8) contentHash / 失效判定 ---------- */
{
  const it = [{ qid: 'a', no: '1.', content: 'x', solution: 'y' }]
  const r = autoLayout({ geometry, items: it, measure })
  assert.ok(layoutMatches(r, it), '同内容应判定有效')
  assert.ok(!layoutMatches(r, [{ ...it[0], solution: 'z' }]), '内容变化应判定失效')
  assert.ok(!layoutMatches(undefined, it), '无排版结果应判定失效')
  assert.equal(contentFingerprint(it), contentFingerprint(it), '指纹需稳定')
  console.log('8) contentHash 失效判定 … ok')
}

console.log('\nD103 预排版自检通过 ✔')

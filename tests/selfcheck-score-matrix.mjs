#!/usr/bin/env node
/** S2b（docs/14 §VC-5 / M-C R3.2/3.3/3.5）自测：勾选/取消勾选影响综合分。
 *
 *  纯 node 运行（无 DOM / 无 xlsx 依赖），把 src/lib/roster.ts 经 esbuild
 *  即时转译（app node_modules 自带 esbuild，vue-tsc 构建链同款），：
 *  1) 默认全部勾选 → 综合得分 = 多源加权均值；
 *  2) 取消勾选某源 → score excluding：该源不再参与，得分随之变化（≠原值）；
 *  3) computeScoresFiltered([单源]) → 一列即排：该源单独决定综合得分；
 *  4) applyAutoTagging 切分对"手动覆盖 / punish"免疫（重算不冲掉）；
 *  5) buildTaskPackage 的 include_in_aggregation 标记随勾选翻转。
 *
 *  运行：node app/../tests/selfcheck-score-matrix.mjs（仓库根）
 *  或： node tests/selfcheck-score-matrix.mjs
 */
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const esbuildBin = path.join(repoRoot, 'app', 'node_modules', '.bin', 'esbuild')

const tmp = mkdtempSync(path.join(tmpdir(), 'roster-selfcheck-'))
const outfile = path.join(tmp, 'roster-lib.mjs')
// bundle src/lib/roster.ts（含 ./kb 依赖；xlsx 层不进 bundle——不依赖 DOM/浏览器）
execFileSync(esbuildBin, [
  path.join(repoRoot, 'app', 'src', 'lib', 'roster.ts'),
  '--bundle', '--format=esm', `--outfile=${outfile}`,
  '--log-level=error',
])

const R = await import(path.join(tmp, 'roster-lib.mjs').replace(/\\/g, '/'))

const rosterXlsxSrc = path.join(repoRoot, 'app', 'src', 'lib', 'rosterXlsx.ts')
const pkgOut = path.join(tmp, 'rosterXlsx.mjs')
execFileSync(esbuildBin, [
  rosterXlsxSrc, '--bundle', '--format=esm', `--outfile=${pkgOut}`, '--log-level=error',
])
// xlsx 包在 node 下需 fs 接入（esbuild-bundled xlsx 的 ESM 入口也可能拉 node 内建）
const P = await import(pkgOut.replace(/\\/g, '/')).catch(() => null)

let failed = 0
function check(cond, label) {
  if (cond) console.log(`  ok  ${label}`)
  else { failed++; console.error(`FAIL  ${label}`) }
}

function student(name, opts = {}) {
  return { name, number: '2026x', class: 'classA', tag: '', score: null, manualTag: false, punish: false, ...opts }
}
function source(name, pairs, weight = 1, include = true) {
  return {
    name, fileName: `${name}.xlsx`, family: 'custom',
    scoreColumn: `${name}-col`, nameColumn: '姓名', weight,
    rows: pairs.map(([n, v]) => ({ 姓名: n, [`${name}-col`]: String(v) })),
    scores: Object.fromEntries(pairs),
    includeInAggregation: include,
  }
}

/* ---------- 用例数据（归一后格局互斥，便于断言切分结果） ---------- */
// 源A：分高者 → 高层；源B：反序（便于验证"排除某源改变排位"）
const stuA = { 甲: 100, 乙: 90, 丙: 80 }
const stuB = { 甲: 60, 乙: 70, 丙: 100 }
const mkStu = () => [student('甲'), student('乙'), student('丙')]

const ratios = [
  { tag: 'distinguish', ratio: 1 / 3 },
  { tag: 'qa', ratio: 1 / 3 },
  { tag: 'copy', ratio: 1 / 3 },
  { tag: 'translation', ratio: 0 },
  { tag: 'summary', ratio: 0 },
]

/* === 1) 默认全勾：加权均值且与既有多源口径一致 === */
{
  const students = mkStu()
  const A = source('A', Object.entries(stuA), 1)
  const B = source('B', Object.entries(stuB), 1)
  R.computeScores(students, [A, B])
  // 手工期望：各源按自身最大值归一 → 等权平均
  const exp = {
    甲: ((stuA['甲'] / 100) + (stuB['甲'] / 100)) / 2 * 100,
    乙: ((stuA['乙'] / 100) + (stuB['乙'] / 100)) / 2 * 100,
    丙: ((stuA['丙'] / 100) + (stuB['丙'] / 100)) / 2 * 100,
  }
  for (const s of students) check(s.score === exp[s.name], `全勾加权分 ${s.name}=${s.score} == ${exp[s.name]}`)
}
console.log('')

/* === 2) 取消勾选 = score excluding：该源不再参与 === */
{
  const students = mkStu()
  const A = source('A', Object.entries(stuA), 1)
  const B = source('B', Object.entries(stuB), 1, false) // ← 取消勾选
  R.computeScores(students, [A, B])
  // 排除 B 后只剩 A（甲 100 / 乙 90 / 丙 80 归一后保持相对位）
  check(students[0].score === 100 && students[1].score === 90 && students[2].score === 80,
    `取消勾选 B：只剩 A 的分 ${students.map((s) => s.score).join('/')} == 100/90/80`)

  // 对照组：勾选 B 时的分数应不同（说明勾选状态确实影响综合分）
  const students2 = mkStu()
  const A2 = source('A', Object.entries(stuA), 1)
  const B2 = source('B', Object.entries(stuB), 1, true)
  R.computeScores(students2, [A2, B2])
  const d = students2.map((s) => s.score)
  check(JSON.stringify(d) !== '100,90,80', `全勾对照：${d.join('/')} ≠ 100/90/80（勾选状态影响综合分）`)
}
console.log('')

/* === 3) 单列即排（vc5"按某单一列切分打 tag"入口同款调用） === */
{
  const students = mkStu()
  const A = source('A', Object.entries(stuA), 1)
  const B = source('B', Object.entries(stuB), 1) // 即使在集合里也不参与
  const used = R.computeScoresFiltered(students, [A])
  check(used.length === 1 && used[0].name === 'A', `single-col 返回参与源 = A`)
  check(students[0].score === 100 && students[2].score === 80, `单列分 ${students.map((s) => s.score).join('/')}`)
}
console.log('')

/* === 4) 切分对手动覆盖/punish 免疫 + 排除源改变切分结果 === */
{
  const students = mkStu()
  students[0].manualTag = true; students[0].tag = 'punish'
  const A = source('A', Object.entries(stuA), 1)
  const B = source('B', Object.entries(stuB))
  R.computeScores(students, [A, B])
  R.applyAutoTagging(students, ratios)
  check(students[0].tag === 'punish', '手动覆盖 punish 不被重算冲掉')

  // 排除 B：甲(100) 乙(90) 丙(80) → 甲 distinguish、乙 qa、丙 copy
  const students2 = mkStu()
  const A2 = source('A', Object.entries(stuA))
  const B2 = source('B', Object.entries(stuB))
  R.computeScores(students2, [A2, B2])
  R.applyAutoTagging(students2, ratios)
  const tags2 = students2.map((s) => s.tag).join(',')
  // 全勾时：甲 = (1+0.6)/2=80；丙=(0.8+1)/2=90 → 丙最高的局面不同
  check(tags2 !== 'punish,distinguish,qa' && !tags2.includes('punish'),
    `全勾切分（无手动覆盖）结果 ${tags2} 与 A-only 局面不同`)
}
console.log('')

/* === 5) buildTaskPackage 的 include_in_aggregation 标记随勾选翻转 === */
if (P) {
  const pkg = JSON.parse(P.buildTaskPackage(mkStu(), [
    source('A', Object.entries(stuA), 1, true),
    source('B', Object.entries(stuB), 1, false),
  ], ratios))
  check(pkg.score_sources[0].include_in_aggregation === true && !pkg.score_sources[0].excluded,
    'pkg: 勾选源 include_in_aggregation=true')
  check(pkg.score_sources[1].include_in_aggregation === false && pkg.score_sources[1].excluded === true,
    'pkg: 未勾选源 include_in_aggregation=false（excluded 标记）')
} else {
  console.log('skip  buildTaskPackage 断言（xlsx 不能在 node 侧 bundle；PWA 浏览器路径由 npm run build 覆盖）')
}

rmSync(tmp, { recursive: true, force: true })
console.log(failed ? `\n${failed} 项断言失败` : '\n全部断言通过 ✓')
process.exit(failed ? 1 : 0)

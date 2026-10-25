/** D102 自检（**已由 D103 取代**）：D102 的「单列流式」是版式回归，
 *  D103 恢复了 MxN 网格与虚线。本文件保留为**回归哨兵**，断言 D102 的
 *  "去网格"改动不得回潮 —— 即：MxN 网格与虚线必须存在。
 *
 *  1) .sheet-body 不再等分行高（grid-template-rows 必须缺席 —— 否则超长答案被裁）；
 *  2) 题框高度随内容：overflow 不得为 hidden、必须 flex:none、break-inside:avoid；
 *  3) 「虚线跟随题目」：.sf-line 绝对定位虚线默认隐藏，改由题框 border-bottom 绘制；
 *  4) 页高自适应：.sheet-page 用 min-height 而非固定 height；
 *  5) 打印规则：页脚绝对定位贴页底（否则跨页时跑到下一页顶部）。
 *
 *  运行：node tests/selfcheck-d102-flow-layout.mjs */
import assert from 'node:assert'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const tmp = mkdtempSync(join(tmpdir(), 'selfcheck-d102-'))
const shBundle = join(tmp, 'sheetHtml.bundle.mjs')
const tpBundle = join(tmp, 'taskpad.bundle.mjs')
// 顺便充当「模板字符串语法哨兵」：CSS 里误写反引号会让 esbuild 失败（vue-tsc 查不出）
execFileSync(join(appDir, 'node_modules', '.bin', 'esbuild'),
  [resolve(appDir, 'src/lib/sheetHtml.ts'), '--bundle', '--format=esm', `--outfile=${shBundle}`, '--external:jszip'], { stdio: 'inherit' })
execFileSync(join(appDir, 'node_modules', '.bin', 'esbuild'),
  [resolve(appDir, 'src/lib/taskpad.ts'), '--bundle', '--format=esm', `--outfile=${tpBundle}`], { stdio: 'inherit' })
process.on('exit', () => rmSync(tmp, { recursive: true, force: true }))

const { stringifySheetHtml } = await import(pathToFileURL(shBundle).href)
const { emptyTaskpad, gridBodyStyle } = await import(pathToFileURL(tpBundle).href)

/* ---------- 0) gridBodyStyle 不再等分行高 ---------- */
{
  // D103：必须是 MxN 等分网格（版式控制权），不得退回单列流式
  const st = gridBodyStyle(4, 1, 'row')
  assert.ok(st.includes('display:grid'), 'D103：必须输出 CSS Grid（MxN 版式）')
  assert.ok(st.includes('grid-template-rows:repeat(4, minmax(0, 1fr))'), 'D103：必须等分行高')
  assert.ok(st.includes('grid-template-columns:repeat(1, minmax(0, 1fr))'))
  assert.ok(!st.includes('flex-direction:column'), 'D103：不得退回单列流式（D102 回归）')
  assert.notEqual(gridBodyStyle(1, 2, 'col'), gridBodyStyle(2, 1, 'row'), 'D103：行列必须影响排版')
  console.log('0) gridBodyStyle 为 MxN 网格（D102 回归哨兵）… ok')
}

const pad = emptyTaskpad(); pad.id = 'd102'; pad.layout.per_page = 4
const longSol = '解：'.repeat(1) + '这是一段很长的参考答案，用于验证超长内容不会被裁切。'.repeat(40)
const items = Array.from({ length: 4 }, (_, i) => ({
  id: `q${i + 1}`, no: `${i + 1}.`, content: `第 ${i + 1} 题题干`, solution: longSol,
}))
const html = stringifySheetHtml([{ pad, items }],
  { katex: 'relative', includeSolution: true, students: [{ name: 'A', number: '1', class: 'c' }] })

/* ---------- 1) 无等分行高 ---------- */
{
  assert.ok(html.includes('grid-template-rows:repeat('), 'D103：产物必须含 MxN 等分行高')
  assert.ok(/\.sheet-body \{[^}]*display:\s*grid/.test(html), 'D103：.sheet-body 应为 grid')
  console.log('1) 产物为 MxN 网格 … ok')
}

/* ---------- 2) 题框不裁切 ---------- */
{
  // 精确取「主规则」：行首 `.sheet-frame {`（排除 .sheet-body.divided 等组合选择器）
  const m = html.match(/^\.sheet-frame \{([^}]*)\}/m)
  assert.ok(m, '应能找到 .sheet-frame 主规则')
  const rule = m[1]
  // D103：格内允许裁剪（超长答案由预排版切段续写，不靠 overflow 撑开）
  assert.ok(/overflow:\s*hidden/.test(rule), 'D103：格内裁剪（续写由预排版负责）')
  assert.ok(/break-inside:\s*avoid/.test(rule), 'D102：题目之间不得被分页合并')
  assert.ok(/page-break-inside:\s*avoid/.test(rule), 'D102：需同时写旧属性兼容')
  console.log('2) 格内裁剪 overflow:hidden + break-inside:avoid … ok')
}

/* ---------- 3) 虚线跟随题目 ---------- */
{
  // D103：虚线必须可见，且由 .sf-line 按网格百分比绘制（横+竖）
  assert.ok(!/\.sf-line \{ display: none/.test(html), 'D103：虚线必须可见')
  assert.ok(/\.sf-line\.v \{/.test(html) && /\.sf-line\.h \{/.test(html), 'D103：横竖虚线样式都要保留')
  console.log('3) 虚线可见（横+竖，按网格绘制）… ok')
}

/* ---------- 4) 页高自适应 ---------- */
{
  const m = html.match(/^\.sheet-page \{([^}]*)\}/m)
  assert.ok(m, '应能找到 .sheet-page 主规则')
  const rule = m[1]
  // D103：恢复固定页高（MxN 需要确定格高；溢出由预排版处理）
  assert.ok(/height:\s*296mm/.test(rule), 'D103：页高固定 296mm')
  assert.ok(/overflow:\s*hidden/.test(rule), 'D103：页容器裁剪（内容由预排版保证放得下）')
  console.log('4) 固定页高 296mm（MxN）… ok')
}

/* ---------- 5) 打印规则 ---------- */
{
  const printBlock = html.slice(html.indexOf('@media print'))
  assert.ok(/\.sheet-footer \{[^}]*position:\s*absolute[^}]*bottom:/.test(printBlock),
    'D102-P1：打印时页脚须绝对定位贴页底（否则跨页跑到下一页顶部）')
  assert.ok(/\.sheet-page \{[^}]*page-break-after:\s*always/.test(printBlock),
    'D103：打印态每页强制换页')
  console.log('5) 打印态每页强制换页 + 页脚贴页底 … ok')
}

console.log('\nD102→D103 版式回归哨兵通过 ✔（MxN 网格 + 虚线必须保留）')

/** D102 自检：参考答案溢出 → 流式排布（答案必须完整）。
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
  const st = gridBodyStyle(4, 1, 'row')
  assert.ok(!st.includes('grid-template-rows'), 'D102：不得输出 grid-template-rows（等分行高会裁切答案）')
  assert.ok(!st.includes('grid-template-columns'), 'D102：不得输出 grid-template-columns')
  assert.ok(st.includes('flex-direction:column'), 'D102：应改为纵向流式')
  assert.ok(st.includes('overflow:visible'), 'D102：容器必须允许内容撑开')
  assert.equal(gridBodyStyle(1, 2, 'col'), st, 'D102：rows/cols 不再影响排版结果')
  console.log('0) gridBodyStyle 改流式（无等分行高）… ok')
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
  assert.ok(!html.includes('grid-template-rows:repeat('), 'D102：产物不得含等分行高')
  // CSS 是多行书写（属性间有空格），用宽松匹配
  assert.ok(/\.sheet-body \{[^}]*display:\s*flex[^}]*flex-direction:\s*column/.test(html),
    'D102：.sheet-body 应为 flex 列')
  console.log('1) 产物无等分行高、改 flex 列 … ok')
}

/* ---------- 2) 题框不裁切 ---------- */
{
  // 精确取「主规则」：行首 `.sheet-frame {`（排除 .sheet-body.divided 等组合选择器）
  const m = html.match(/^\.sheet-frame \{([^}]*)\}/m)
  assert.ok(m, '应能找到 .sheet-frame 主规则')
  const rule = m[1]
  assert.ok(/overflow:\s*visible/.test(rule), 'D102：.sheet-frame 必须 overflow:visible（不得 hidden 裁掉答案）')
  assert.ok(/flex:\s*none/.test(rule), 'D102：题框不得参与 flex 收缩')
  assert.ok(/break-inside:\s*avoid/.test(rule), 'D102：题目之间不得被分页合并')
  assert.ok(/page-break-inside:\s*avoid/.test(rule), 'D102：需同时写旧属性兼容')
  console.log('2) 题框 overflow:visible / flex:none / break-inside:avoid … ok')
}

/* ---------- 3) 虚线跟随题目 ---------- */
{
  assert.ok(/\.sf-line \{ display: none/.test(html), 'D102：绝对定位虚线必须隐藏（题高不等会错位）')
  assert.ok(/\.sheet-body\.divided \.sheet-frame \{ border-bottom: 1px dashed/.test(html),
    'D102：分隔线应由题框底边绘制（跟随题目）')
  console.log('3) 虚线跟随题目（废弃百分比绝对定位）… ok')
}

/* ---------- 4) 页高自适应 ---------- */
{
  const m = html.match(/^\.sheet-page \{([^}]*)\}/m)
  assert.ok(m, '应能找到 .sheet-page 主规则')
  const rule = m[1]
  assert.ok(/min-height:\s*296mm/.test(rule), 'D102：页高应有 min-height 保底')
  assert.ok(/height:\s*auto/.test(rule), 'D102：页高必须 auto（否则超出内容被裁）')
  assert.ok(/overflow:\s*visible/.test(rule), 'D102：页容器不得 hidden')
  // 注意：不能直接匹配 "height: 296mm"，否则会与 "min-height: 296mm" 冲突 —— 用词边界精确判断
  assert.ok(!/(?:^|[;{\s])height:\s*296mm/.test(rule), 'D102：不得再锁死 height:296mm')
  console.log('4) 页高自适应（min-height + height:auto）… ok')
}

/* ---------- 5) 打印规则 ---------- */
{
  const printBlock = html.slice(html.indexOf('@media print'))
  assert.ok(/\.sheet-footer \{[^}]*position:\s*absolute[^}]*bottom:/.test(printBlock),
    'D102-P1：打印时页脚须绝对定位贴页底（否则跨页跑到下一页顶部）')
  assert.ok(/\.sheet-page \{[^}]*min-height:\s*0[^}]*height:\s*auto/.test(printBlock),
    'D102：打印态不得锁页高（应为 min-height:0 + height:auto）')
  console.log('5) 打印态页脚定位 + 页高自适应 … ok')
}

console.log('\nD102 流式排布自检通过 ✔')

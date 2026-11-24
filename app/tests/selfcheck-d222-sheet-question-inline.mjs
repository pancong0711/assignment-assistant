/** D222：作业纸预览中「题号 + 题干」必须同排（含软换行/多段题干）。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const sheetHtml = fs.readFileSync(join(appRoot, 'src/lib/sheetHtml.ts'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

const { renderRichInline } = await import('../src/lib/richdoc.ts')

// 1) 单行题干：题号与题干同排（不能以块级 <p> 开头）
const single = renderRichInline('求加速度并说明理由')
must(!single.trim().startsWith('<p>'), `单行题干仍以 <p> 开头：${single.slice(0, 60)}`)

// 2) 含软换行（现场 Q2）：必须仍是行内，保留 <br> 但不外包 <p>
const br = renderRichInline('求加速度\n并说明理由')
must(!br.trim().startsWith('<p>'),
  `含软换行的题干仍以 <p> 开头（题号会独占一行）：${br.slice(0, 80)}`)
must(br.includes('<br>'), '软换行信息丢失（应保留 <br>）')

// 3) 多段：首段行内化，其余段落保留块级
const multi = renderRichInline('求加速度\n\n并说明理由')
must(!multi.trim().startsWith('<p>'), '多段题干的**首段**未行内化（题号会独占一行）')
must(/<\/p>/.test(multi) || /<p>/.test(multi), '多段题干的后续段落应保留块级')

// 4) 表格/SVG 等首块即块级的，保持原样（不能强行行内化）
const table = renderRichInline('|a|b|\n|-|-|\n|1|2|')
must(table.trim().startsWith('<table'), '表格题干应保持块级渲染')

// 5) 源码契约：块级判定不得包含 br
const richdoc = fs.readFileSync(join(appRoot, 'src/lib/richdoc.ts'), 'utf8')
const blockRe = richdoc.match(/const BLOCK_TAG_RE = \/(.+?)\/i/)
must(!!blockRe, '缺少 BLOCK_TAG_RE')
must(blockRe && !/(^|\|)br(\||\)|\/)/.test(blockRe[1]), 'BLOCK_TAG_RE 仍把 <br> 当块级')
must(/renderRichInline/.test(sheetHtml), '作业纸渲染未使用 renderRichInline')

must(/selfcheck:d222/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d222')
must(!!pkg.scripts?.['selfcheck:d222'], 'package.json 缺少 selfcheck:d222')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 单行题干：题号与题干同排')
console.log('✓ 含软换行题干：仍同排（保留 <br>）——修复现场 Q2')
console.log('✓ 多段题干：首段同排，后续段落换行')
console.log('✓ 表格/SVG 等保持块级')
console.log('✓ D222 selfcheck 已接入 npm run selfcheck')

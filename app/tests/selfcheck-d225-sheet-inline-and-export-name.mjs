/** D225：题干首块为列表/div/引用时也同排；班级导出文件名带班级名+时间戳。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const roster = fs.readFileSync(join(appRoot, 'src/views/RosterView.vue'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

const { renderRichInline } = await import('../src/lib/richdoc.ts')
const blocky = (s) => /^<(p|div|table|ul|ol|blockquote|pre)/.test(s.trim())

// 1) 题干行内化：列表 / div / 引用 / 软换行 / 多段
must(!blocky(renderRichInline('- 第一句\n- 第二句')), '无序列表题干仍块级（题号会独占一行）')
must(!blocky(renderRichInline('1. 第一句\n2. 第二句')), '有序列表题干仍块级')
must(!blocky(renderRichInline('<div>题干内容</div>')), 'div 包裹的题干仍块级')
must(!blocky(renderRichInline('> 引用内容\n\n正文')), '引用块题干仍块级')
must(!blocky(renderRichInline('求加速度\n并说明理由')), '软换行题干仍块级')
must(!blocky(renderRichInline('求加速度\n\n并说明理由')), '多段题干首段未行内化')
must(renderRichInline('- 第一句\n- 第二句').includes('<br>'), '列表项未用 <br> 连接')

// 2) 表格/SVG 保持块级
must(blocky(renderRichInline('|a|b|\n|-|-|\n|1|2|')), '表格题干应保持块级')

// 3) 导出文件名：班级名 + 完整时间戳
must(/function exportStamp\(\)/.test(roster), '缺少 exportStamp()')
must(/function exportClassLabel\(\)/.test(roster), '缺少 exportClassLabel()')
// D226：统一经 classExportBase(prefix) 生成「前缀-班级-时间戳」基名。
must(/function classExportBase\(prefix: string\)/.test(roster), '缺少 classExportBase()')
must(/exportClassLabel\(\)\}-\$\{exportStamp\(\)\}/.test(roster),
  '导出基名未带班级名+时间戳')
must(/classExportBase\('class-sheet-preview'\)/.test(roster),
  '整班 HTML 下载名未带班级名+时间戳')
must(/downloadData\(html, htmlName, 'text\/html'\)/.test(roster),
  '下载成功路径未复用带班级名+时间戳的 htmlName')
must(/emitClassSidecar\('download', htmlName\)/.test(roster),
  'sidecar 未与 HTML 使用同一基名')
must(!/class-sheet[^\n]{0,160}toISOString\(\)\.slice\(0, 10\)/.test(roster), '仍存在仅日期的作业纸导出文件名')
// 时间戳必须到秒（8 位日期 + 6 位时间）
must(/padStart\(2, '0'\)[\s\S]{0,200}p\(d\.getSeconds\(\)\)/.test(roster),
  '时间戳未包含时分秒')

must(/selfcheck:d225/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d225')
must(!!pkg.scripts?.['selfcheck:d225'], 'package.json 缺少 selfcheck:d225')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 列表/div/引用/软换行/多段题干均与题号同排（首行）')
console.log('✓ 表格/SVG 等保持块级')
console.log('✓ 班级导出文件名 = class-sheet-<班级>-<YYYYMMDD-HHMMSS>')
console.log('✓ D225 selfcheck 已接入 npm run selfcheck')

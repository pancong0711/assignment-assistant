/** D226：题号行内化补全 + 整班导出命名收口 + 题库 AI+ 目录实时刷新。 */
import fs from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { dirname, join, resolve } from 'node:path'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const repo = resolve(appRoot, '..')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

/* ---------- 1) renderRichInline：D225 漏掉的现场 ---------- */
const tmp = mkdtempSync(join(tmpdir(), 'selfcheck-d226-'))
const bundle = join(tmp, 'richdoc.bundle.mjs')
execFileSync(join(appRoot, 'node_modules', '.bin', 'esbuild'),
  [join(appRoot, 'src/lib/richdoc.ts'), '--bundle', '--format=esm', `--outfile=${bundle}`],
  { stdio: 'inherit' })
process.on('exit', () => rmSync(tmp, { recursive: true, force: true }))
const { renderRichInline } = await import(pathToFileURL(bundle).href)

const blocky = (s) => /^<(p|div|table|ul|ol|blockquote|pre|h[1-6])\b/i.test(s.trim())
const cases = [
  ['translation 松散列表', '- Sentence one.\n\n- Sentence two.', ['Sentence one.', 'Sentence two.']],
  ['带 class 的段落', '<p class="translation">Sentence one.<br>Sentence two.</p>', ['Sentence one.', 'Sentence two.']],
  ['嵌套 div 首段', '<div class="q"><p>第一段</p><p>第二段</p></div>', ['第一段', '第二段']],
  ['行间公式开头', '$$E=mc^2$$\n\n求能量。', ['E=mc^2', '求能量']],
  ['列表内 p 包裹', '- <p>第一句</p>\n- <p>第二句</p>', ['第一句', '第二句']],
]
for (const [name, src, needles] of cases) {
  const out = renderRichInline(src)
  must(!blocky(out), `${name}仍以块级元素开头，题号会另起一行：${out.slice(0, 80)}`)
  for (const n of needles) must(out.includes(n), `${name}内容丢失：${n}`)
}
must(/<br>/.test(renderRichInline('- Sentence one.\n\n- Sentence two.')),
  '松散列表项未用 <br> 合并为可续排的第一行')

/* ---------- 2) 作业纸模板：q-no / q-content-body 契约（PWA + 引擎） ---------- */
const sheetHtml = fs.readFileSync(join(appRoot, 'src/lib/sheetHtml.ts'), 'utf8')
const template = fs.readFileSync(join(repo, 'engine/templates/assignment.html.j2'), 'utf8')
for (const [name, src] of [['PWA', sheetHtml], ['引擎模板', template]]) {
  must(src.includes('class="q-no"'), `${name} 缺少独立题号 .q-no`)
  must(src.includes('class="q-content-body"'), `${name} 缺少正文容器 .q-content-body`)
  must(/\.q-content\s*\{[^}]*display:\s*flex/.test(src), `${name} .q-content 未使用 flex 排版`)
  must(/\.q-content-body\s*>\s*:first-child\s*\{\s*margin-top:\s*0/.test(src),
    `${name} 未消除正文首块的上边距（题号会悬空）`)
}

/* ---------- 3) 导出命名：所有整班 HTML/JSON 都带班级名与到秒时间戳 ---------- */
const roster = fs.readFileSync(join(appRoot, 'src/views/RosterView.vue'), 'utf8')
must(/function exportStamp\(\)/.test(roster), '缺少 exportStamp()')
must(/function classExportBase\(prefix: string\)/.test(roster), '缺少 classExportBase()')
must(/exportClassLabel\(\)\}-\$\{exportStamp\(\)\}/.test(roster), '导出基名未带班级名+时间戳')
must(/classExportBase\('class-sheet-preview'\)/.test(roster), '整班 HTML 未使用统一导出基名')
must(/downloadData\(html, htmlName, 'text\/html'\)/.test(roster), '下载成功路径未复用 htmlName')
must(/emitClassSidecar\('download', htmlName\)/.test(roster), 'sidecar JSON 未与 HTML 配对')
must(/const name = sidecarFileName\(htmlName \|\| `\$\{classExportBase\('class-sheet'\)\}\.html`\)/.test(roster),
  '打印 sidecar 未使用「班级-时间戳」基名')
must(!/class-sheet[^\n]{0,160}toISOString\(\)\.slice\(0, 10\)/.test(roster),
  '仍存在仅日期（无班级名）的作业纸导出文件名')

/* ---------- 4) 题库 AI+ 目录刷新：禁缓存 + 手动/聚焦刷新 ---------- */
const client = fs.readFileSync(join(appRoot, 'src/lib/engineClient.ts'), 'utf8')
const panel = fs.readFileSync(join(appRoot, 'src/components/KbAiSolvePanel.vue'), 'utf8')
must(/fetchKbCatalog[\s\S]{0,600}cache:\s*'no-store'/.test(client),
  'fetchKbCatalog 未设置 no-store（浏览器可能返回旧题库）')
must(/fetchKbCatalog[\s\S]{0,600}\/kb\/catalog\?_=\$\{Date\.now\(\)\}/.test(client),
  'fetchKbCatalog 未加时间戳绕缓存')
must(panel.includes('🔄 刷新题目'), 'AI+ 面板缺少「刷新题目」按钮')
must(panel.includes("window.addEventListener('focus'"), 'AI+ 面板未在窗口聚焦时刷新目录')
must(panel.includes("document.addEventListener('visibilitychange'"), 'AI+ 面板未在页面可见时刷新目录')
must(/watch\(\(\) => kbStore\.savedAt/.test(panel), 'AI+ 面板未跟随题库写回时间刷新')

must(/selfcheck:d226/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d226')
must(!!pkg.scripts?.['selfcheck:d226'], 'package.json 缺少 selfcheck:d226')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 松散列表/带 class 段落/嵌套 div/行间公式开头均与题号同排')
console.log('✓ PWA 与引擎模板均使用 q-no + q-content-body（首块无上边距）')
console.log('✓ 整班 HTML/JSON 统一命名 = 前缀-班级-YYYYMMDD-HHMMSS')
console.log('✓ 题库 AI+ 目录禁缓存 + 手动/窗口聚焦/写回后自动刷新')
console.log('✓ D226 selfcheck 已接入 npm run selfcheck')

/** D226 浏览器夹具：生成含「公式开头 / 松散列表 / 软换行」题干的真实作业纸 HTML。 */
import { readFileSync, writeFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'

const [shBundle, tpBundle, outFile] = process.argv.slice(2)
const { stringifySheetHtml } = await import(pathToFileURL(shBundle).href)
const { emptyTaskpad } = await import(pathToFileURL(tpBundle).href)
const publicDir = new URL('../public/katex/', import.meta.url)
const katexRaw = {
  css: readFileSync(new URL('katex.min.css', publicDir), 'utf8'),
  katexJs: readFileSync(new URL('katex.min.js', publicDir), 'utf8'),
  autoRenderJs: readFileSync(new URL('contrib/auto-render.min.js', publicDir), 'utf8'),
}
const pad = emptyTaskpad()
pad.id = 'd226-browser'
pad.layout.per_page = 3
const items = [
  { id: 'q1', no: '1.', content: '$$E=mc^2$$\n\n求能量。' },
  { id: 'q2', no: '2.', content: '- Sentence one.\n\n- Sentence two.' },
  { id: 'q3', no: '3.', content: '请翻译以下内容：\nThe quick brown fox.\n并说明理由。' },
]
const html = stringifySheetHtml([{ pad, items }], {
  katex: 'raw', katexRaw, includeSolution: false,
  students: [{ name: '测试学生', number: '1', class: '测试班' }],
})
writeFileSync(outFile, html, 'utf8')

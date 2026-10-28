/** D113 自检：参考答案独立预览（竖版单列 · 一题一页）+ 测量探针修复 + 公式语义。
 *
 *  覆盖：
 *  1) R5 测量探针必须用 renderRich+innerHTML（旧 textContent → 探针内 svg=0、高度少算）；
 *  2) R6 行间公式独立成段、行内公式保持行内（与引擎同口径）；
 *  3) R2/R3 参考答案 HTML：一题一卡、新题 break-before:page、超高题 break-inside:auto；
 *  4) R7 公式语义：行内/行间两类都在输出中保留各自定界符。
 *
 *  运行：node tests/selfcheck-d113-answer-preview.mjs */
import assert from 'node:assert'
import { execFileSync } from 'node:child_process'
import { rmSync, readFileSync } from 'node:fs'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
// bundle 放 app/tests 下：markdown-it/dompurify 需按 node 模块解析
const bundle = join(appDir, 'tests', '.answerHtml.d113.bundle.mjs')
process.on('exit', () => { try { rmSync(bundle, { force: true }) } catch { /* noop */ } })
execFileSync(join(appDir, 'node_modules', '.bin', 'esbuild'), [
  resolve(appDir, 'src/lib/answerHtml.ts'), '--bundle', '--format=esm',
  `--outfile=${bundle}`, '--log-level=error',
], { stdio: 'inherit' })

/* ---- 1) R5：探针必须 renderRich + innerHTML ---- */
{
  const src = readFileSync(resolve(appDir, 'src/lib/measureLayout.ts'), 'utf-8')
  const code = src.replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n').filter((l) => !/^\s*\/\//.test(l)).join('\n')
  assert.ok(/probe\.innerHTML = renderRich\(/.test(code),
    'R5：探针必须用 innerHTML = renderRich(text)')
  assert.ok(!/probe\.textContent\s*=\s*text\b/.test(code),
    'R5：禁止用 textContent 注入（会把 <svg> 当纯文本 → 图不占高度）')
  assert.ok(/import \{ renderRich \} from '\.\/richdoc'/.test(src), 'R5：需 import renderRich')
  assert.ok(/svg \{ max-width:100%; height:auto/.test(src), 'R5：探针需对齐 svg 限宽')
}

/* ---- 2)/3)/4) 参考答案 HTML ---- */
const { buildAnswerHtml, ANSWER_CSS } = await import(pathToFileURL(bundle).href)

const items = [
  { id: 'chap04-c1', no: '1.', content: '题干一 $a=1$', solution: '解：\n\\[\nE=mc^2\n\\]\n行内 $b=2$。' },
  { id: 'chap04-c2', no: '2.', content: '题干二', solution: '简答 $c=3$。' },
]
const html = buildAnswerHtml([{ title: '作业纸：p1', items }], { docTitle: '参考答案 · 测试' })

assert.equal((html.match(/class="answer-card"/g) || []).length, 2, '每题一卡片')
assert.ok(html.includes('data-qid="chap04-c1"') && html.includes('data-qid="chap04-c2"'))
assert.ok(html.includes('作业纸：p1'), 'D1/D2：分节标题应输出')
assert.ok(html.includes('参考答案 · 测试'), '文档标题应输出')

/* 一题一页 + 超高题允许内部跨页 */
assert.ok(/\.answer-card \+ \.answer-card \{ break-before: page/.test(ANSWER_CSS),
  'R3：新题应另起一页')
assert.ok(/\.answer-card \{[^}]*break-inside: auto/.test(ANSWER_CSS),
  'R3：超高题必须允许题内跨页（否则首页只剩标题）')
assert.ok(/katex-display[^}]*break-inside: avoid/.test(ANSWER_CSS),
  'R3：行间公式不应被拆开')

/* R6/R7：行间公式独立成段（不与正文同 <p>），行内公式保持原样 */
assert.ok(!/<p>[^<]*<br\s*\/?>\\\[/.test(html), 'R6：行间公式不应与正文同段')
assert.ok(html.includes('$a=1$') && html.includes('$b=2$') && html.includes('$c=3$'),
  'R7：行内公式定界符必须保留')
assert.ok(html.includes('\\[') && html.includes('\\]'), 'R7：行间公式定界符必须保留')

/* 两种开关 */
const noQ = buildAnswerHtml([{ items }], { includeContent: false })
assert.ok(!noQ.includes('class="answer-q"'), 'includeContent=false 不应输出题干')
const noNo = buildAnswerHtml([{ items }], { includeNo: false })
assert.ok(!noNo.includes('class="answer-no"'), 'includeNo=false 不应输出题号')
// 连排模式：必须覆盖掉"新题另起一页"规则
const noBreak = buildAnswerHtml([{ items }], { onePagePerQuestion: false })
assert.ok(noBreak !== html, '连排模式输出应与默认不同')
assert.ok(/\.answer-card \+ \.answer-card \{ break-before: auto/.test(noBreak),
  'onePagePerQuestion=false 应关闭强制分页')
assert.ok(!/\.answer-card \+ \.answer-card \{ break-before: auto/.test(html),
  '默认模式不得关闭强制分页')

/* 与引擎模板同构哨兵：两边都必须有相同的关键 CSS 规则 */
{
  const py = readFileSync(resolve(appDir, '..', 'engine/templates/_answer_css.css'), 'utf-8')
  for (const rule of ['.answer-card + .answer-card { break-before: page',
                      'break-inside: auto',
                      '.answer-sol svg { max-width: 100%']) {
    assert.ok(ANSWER_CSS.includes(rule), `PWA CSS 缺少规则：${rule}`)
    assert.ok(py.includes(rule), `引擎 CSS 缺少规则：${rule}`)
  }
}

console.log('OK d113-answer-preview：探针 innerHTML · 行间独立成段 · 行内保持行内 · '
  + '一题一卡/一题一页 · 超高题可跨页 · PWA 与引擎 CSS 同构')

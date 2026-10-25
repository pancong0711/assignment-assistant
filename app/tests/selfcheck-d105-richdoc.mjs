/** D105 自检：md+html 安全渲染（PWA 侧）+ 与 Python 白名单一致 + 纯文本派生。
 *  运行：node tests/selfcheck-d105-richdoc.mjs */
import assert from 'node:assert'
import { readFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repo = resolve(appDir, '..')
const tmp = mkdtempSync(join(tmpdir(), 'selfcheck-d105-'))
const bundle = join(tmp, 'richdoc.bundle.mjs')
execFileSync(join(appDir, 'node_modules', '.bin', 'esbuild'),
  [resolve(appDir, 'src/lib/richdoc.ts'), '--bundle', '--format=esm', `--outfile=${bundle}`], { stdio: 'inherit' })
process.on('exit', () => rmSync(tmp, { recursive: true, force: true }))
const { renderRich, stripMarkup, ALLOWED_TAGS } = await import(pathToFileURL(bundle).href)

/* 1) Markdown / 表格 / 公式源码 */
{
  const h = renderRich('**粗** 与 `代码`\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n$v=2t$')
  assert.ok(h.includes('<strong>粗</strong>'), 'Markdown 粗体')
  assert.ok(h.includes('<table>'), '表格')
  assert.ok(h.includes('$v=2t$'), '公式源码保留')
  console.log('1) Markdown/表格/公式源码 … ok')
}

/* 2) 内联 SVG + data:image */
{
  const svg = '<svg viewBox="0 0 100 50"><circle cx="10" cy="10" r="5" fill="none" stroke="black"/></svg>'
  const h = renderRich(svg)
  assert.ok(h.includes('<svg') && h.includes('<circle'), 'SVG 保留')
  const png = 'data:image/png;base64,iVBORw0KGgo='
  assert.ok(renderRich(`<img src="${png}">`).includes('data:image/png'), 'data:image 允许')
  console.log('2) 内联 SVG / data:image … ok')
}

/* 3) 安全：恶意样例全部拦截 */
{
  const MAL = [
    '<script>alert(1)</script>正常',
    '<img src=x onerror=alert(1)>',
    '<img src="https://evil.com/a.png">',
    '<img src="javascript:alert(1)">',
    '<a href="javascript:alert(1)">点击</a>',
    '<iframe src="//evil"></iframe>',
    '<style>body{display:none}</style>输出',
    '<div onclick="alert(1)">点击</div>',
    '<svg><foreignObject><body><script>x</script></body></foreignObject></svg>',
    '<img src="data:image/png;base64,AAAA" onload="alert(1)">',
  ]
  const needles = ['<script', 'onerror', 'onload', 'javascript:', '<iframe',
                   'foreignobject', '<style', 'onclick', 'evil.com']
  for (const bad of MAL) {
    const out = renderRich(bad).toLowerCase()
    for (const n of needles) assert.ok(!out.includes(n), `泄漏 ${n}：${out}（输入 ${bad}）`)
  }
  assert.ok(!renderRich('<script>alert(1)</script>正常').includes('alert(1)'), 'JS 正文不得泄漏')
  assert.ok(!renderRich('<style>a{display:none}</style>输出').includes('display:none'), 'CSS 正文不得泄漏')
  console.log('3) 恶意样例全部拦截（含 JS/CSS 正文不泄漏）… ok')
}

/* 4) 纯文本派生 */
{
  const p = stripMarkup('## 解\n由 $v=2t$ 得\n\n<svg><circle r="1"/></svg>\n\n**结论**：20 m/s')
  assert.ok(!p.includes('#') && !p.includes('**'), 'Markdown 记号应去除')
  assert.ok(p.includes('[图]'), '图应占位')
  assert.ok(p.includes('$v=2t$') && p.includes('20 m/s'), '正文与公式源码保留')
  assert.ok(stripMarkup('字'.repeat(500), 50).length <= 51, 'limit 生效')
  console.log('4) 纯文本派生（检索/摘要用）… ok')
}

/* 5) 双端白名单一致（与 Python ALLOWED_TAGS 比对） */
{
  const py = readFileSync(resolve(repo, 'engine/src/assist/paper/richdoc.py'), 'utf-8')
  const m = py.match(/ALLOWED_TAGS = \{([\s\S]*?)\}/)
  assert.ok(m, '应能读到 Python ALLOWED_TAGS')
  const pyTags = new Set([...m[1].matchAll(/"([a-z0-9]+)"/g)].map((x) => x[1]))
  const jsTags = new Set(ALLOWED_TAGS)
  const onlyPy = [...pyTags].filter((t) => !jsTags.has(t))
  const onlyJs = [...jsTags].filter((t) => !pyTags.has(t))
  assert.deepEqual(onlyPy, [], `Python 有而 JS 缺：${onlyPy.join(',')}`)
  assert.deepEqual(onlyJs, [], `JS 有而 Python 缺：${onlyJs.join(',')}`)
  console.log(`5) 双端白名单一致（${jsTags.size} 个标签）… ok`)
}

console.log('\nD105 md+html 渲染自检通过 ✔')

/** D110 自检：答案作用域键 + KaTeX 重渲染不破坏 HTML。
 *
 *  1) solutionScopeKey 必须与引擎 solutions.scope_id 同口径（kb__chap__qid），
 *     否则跨章同号题会读到同一份答案；
 *  2) katexRender 的 force 重渲染必须用 innerHTML 还原（旧实现用 textContent，
 *     会抹掉 <svg>/表格 → "未见示意图"、"文字截断"）。
 *
 *  运行：node tests/selfcheck-d110-solution-scope.mjs */
import assert from 'node:assert'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const tmp = mkdtempSync(join(tmpdir(), 'selfcheck-d110-'))
process.on('exit', () => rmSync(tmp, { recursive: true, force: true }))

const bundle = join(tmp, 'engineClient.bundle.mjs')
execFileSync(join(appDir, 'node_modules', '.bin', 'esbuild'), [
  resolve(appDir, 'src/lib/engineClient.ts'), '--bundle', '--format=esm',
  `--outfile=${bundle}`, '--log-level=error', '--external:vue', '--external:pinia',
], { stdio: 'inherit' })
const { solutionScopeKey } = await import(pathToFileURL(bundle).href)

/* 1) 作用域键格式（与 Python scope_id 一致） */
assert.equal(solutionScopeKey('c1', 'problems', 'chap04'), 'problems__chap04__c1')
assert.equal(solutionScopeKey('c1', 'problems', ''), 'problems__c1')
assert.equal(solutionScopeKey('c1', '', ''), 'c1')
assert.notEqual(
  solutionScopeKey('c1', 'problems', 'chap04'),
  solutionScopeKey('c1', 'problems', 'chap05'),
  '跨章同号必须得到不同键',
)
// 与引擎同口径：分隔符归一
assert.equal(solutionScopeKey('c1', 'pro/blems', 'chap04'), 'pro-blems__chap04__c1')

/* 2) katexRender 源码哨兵：force 还原必须用 innerHTML，不能是 textContent */
{
  const src = readFileSync(resolve(appDir, 'src/lib/katexRender.ts'), 'utf-8')
  // 只看真正的代码行（去掉注释），避免被注释里提到的旧写法误导
  const code = src.split('\n')
    .filter((ln) => !/^\s*(\/\/|\*|\/\*)/.test(ln))
    .join('\n')
  assert.ok(/el\.innerHTML = original/.test(code), 'force 重渲染必须用 innerHTML 还原')
  assert.ok(!/el\.textContent\s*=/.test(code), '禁止用 textContent 还原（会丢 svg/表格）')
  assert.ok(/KATEX_SRC_ATTR, src/.test(code) && /const src = el\.innerHTML/.test(code),
    '快照必须保存 innerHTML')
}

/* 3) 引擎 Python 侧同口径（静态校验 scope_id 实现存在且格式一致） */
{
  const py = readFileSync(resolve(appDir, '..', 'engine/src/assist/files/solutions.py'), 'utf-8')
  assert.ok(/f"\{k\}\{_SCOPE_SEP\}\{c\}\{_SCOPE_SEP\}\{q\}"/.test(py), 'Python scope_id 应为 kb__chap__qid')
}

console.log('OK d110-solution-scope：作用域键前后端同口径 · 跨章同号不撞键 · KaTeX 用 innerHTML 还原')

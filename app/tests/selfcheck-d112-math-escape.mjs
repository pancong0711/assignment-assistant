/** D112 自检：公式里的 `<` / `&` 必须转义，否则答案会被截断。
 *
 *  背景 bug：`$R_1<R_2$` 抽出占位后，还原时把裸 `<` 插回 HTML，
 *  DOMPurify/bleach 把 `<R_2$),单位长度…` 当标签开头丢弃
 *  → 答案在 `$R_1` 之后整段消失（用户报"题目被截断"）。
 *
 *  运行：node tests/selfcheck-d112-math-escape.mjs */
import assert from 'node:assert'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const tmp = mkdtempSync(join(tmpdir(), 'selfcheck-d112e-'))
const bundle = join(tmp, 'richdoc.bundle.mjs')
execFileSync(join(appDir, 'node_modules', '.bin', 'esbuild'), [
  resolve(appDir, 'src/lib/richdoc.ts'), '--bundle', '--format=esm',
  `--outfile=${bundle}`, '--log-level=error',
], { stdio: 'inherit' })
process.on('exit', () => rmSync(tmp, { recursive: true, force: true }))

const { renderRich } = await import(pathToFileURL(bundle).href)

/* 1) 行内公式里的 < 不得截断后续内容 */
{
  const src = '两个带有等量异号电荷的无限长同轴圆柱面,半径分别为$R_1$和$R_2$($R_1<R_2$),'
    + '单位长度上的电荷为$\\lambda$。求离轴线为$r$($R_1<r<R_2$)处的电场强度，并画出示意图。'
  const out = renderRich(src)
  assert.ok(out.includes('并画出示意图'), `答案被截断：${out}`)
  assert.ok(out.includes('处的电场强度'), `中间内容丢失：${out}`)
  assert.ok(out.includes('$R_1&lt;R_2$'), `< 必须转义：${out}`)
  assert.ok(out.includes('$R_1&lt;r&lt;R_2$'), `< 必须转义：${out}`)
  assert.ok(!/<(?![a-zA-Z/!])/.test(out), `存在裸 < ：${out}`)
}

/* 2) 行间公式同理 */
{
  const out = renderRich('条件为\n\\[\nR_1<r<R_2\n\\]\n这就是结论。')
  assert.ok(out.includes('这就是结论'), `行间公式后内容丢失：${out}`)
  assert.ok(out.includes('R_1&lt;r&lt;R_2'))
}

/* 3) & 也要转义（否则被当实体开头） */
{
  const out = renderRich('条件 $a&b$ 结束')
  assert.ok(out.includes('结束'), `& 导致截断：${out}`)
  assert.ok(out.includes('a&amp;b'))
}

/* 4) 公式里的 < 不影响后续 SVG */
{
  const out = renderRich('半径 $R_1<R_2$ 如图：\n\n'
    + '<svg viewBox="0 0 10 10"><line x1="0" y1="0" x2="5" y2="5"/></svg>\n\n完毕。')
  assert.ok(out.includes('<svg') && out.includes('<line'), 'SVG 应保留')
  assert.ok(out.includes('完毕'), 'SVG 后内容应保留')
}

console.log('OK d112-math-escape：公式 < / & 均转义 · 不再截断 · 后续 SVG 保留 · 与引擎同口径')

/** D117 自检：DOMPurify 不得剥掉 SVG 几何属性（否则图是一片空白）。
 *
 *  回归的 bug：
 *    richdoc.ts 里 `ALLOWED_URI_REGEXP: /^data:image\/...$/` 是**全局**生效的，
 *    DOMPurify 会对**所有属性值**跑它，而不是只查 src/href。
 *    于是 viewBox / width / height / cx / cy / r / stroke / fill 全部被当非法 URI 剥掉：
 *        <svg viewBox="0 0 200 150" width="60mm"><circle cx="100" r="35"/></svg>
 *      → <svg xmlns="..."><circle></circle></svg>   ← 浏览器里就是空白
 *    引擎侧（bleach protocols 只查 URI 类属性）不受影响，所以 CLI 一直是对的。
 *
 *  ⚠ 这个 bug 在 Node 里**测不出来**：richdoc 无 DOM 时走 sanitizeWithoutDom 兜底，
 *    根本不执行那段配置。所以本自检是「静态哨兵 + 浏览器行为断言」两部分，
 *    浏览器部分见 tests/selfcheck-d117-svg-browser.mjs。
 *
 *  运行：node tests/selfcheck-d117-svg-sanitize.mjs */
import assert from 'node:assert'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const src = readFileSync(resolve(appDir, 'src/lib/richdoc.ts'), 'utf-8')
const code = src.replace(/\/\*[\s\S]*?\*\//g, '')
  .split('\n').filter((l) => !/^\s*\/\//.test(l)).join('\n')

/* 1) 禁止全局 ALLOWED_URI_REGEXP（只允许出现在注释里） */
assert.ok(!/ALLOWED_URI_REGEXP\s*:/.test(code),
  'richdoc.ts 不得设置 ALLOWED_URI_REGEXP（全局生效会剥掉 svg 几何属性）')

/* 2) 必须用 hook 只校验 src */
assert.ok(/addHook\('uponSanitizeAttribute'/.test(code), '应用 uponSanitizeAttribute 校验 src')
assert.ok(/data\.attrName[\s\S]{0,40}===\s*'src'/.test(code), 'hook 应只针对 src')
assert.ok(/removeAllHooks\(\)/.test(code), 'sanitize 后应清理 hook（避免累积）')

/* 3) 白名单必须包含关键 SVG 几何属性 */
for (const a of ['viewBox', 'width', 'height', 'cx', 'cy', 'r', 'stroke', 'fill', 'points', 'd']) {
  assert.ok(new RegExp(`'${a}'`).test(src), `ALLOWED_ATTRS 缺少 ${a}`)
}

/* 4) 引擎侧 bleach 用 protocols 而非全局正则（确认两端不会同时犯这个错） */
{
  const py = readFileSync(resolve(appDir, '..', 'engine/src/assist/paper/richdoc.py'), 'utf-8')
  assert.ok(/protocols=\["data"\]/.test(py), '引擎侧应使用 protocols=["data"]')
  assert.ok(!/ALLOWED_URI_REGEXP/.test(py), '引擎侧不应有全局 URI 正则')
}

console.log('OK d117-svg-sanitize：未使用 ALLOWED_URI_REGEXP · hook 只校验 src · '
  + 'SVG 几何属性在白名单 · 引擎用 protocols')

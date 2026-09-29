#!/usr/bin/env node
/** copy-katex.mjs — D44（docs/05）：KaTeX 归属 = npm 依赖 + 构建期拷贝。
 *  仓库不再 vendor 资产（app/public/katex 已 gitignore；包内容只留 package-lock 元数据）。
 *  npm ci 拉取 katex@0.16.4 → 本脚本把所需最小集拷入 app/public/katex（vite 随 dist 发布）：
 *  katex.min.css + katex.min.js + contrib/auto-render.min.js + fonts/*.woff2（与 D43 之前
 *  手工 vendor 的 600KB 子集完全同口径）。版本锁 0.16.4，与 engine/templates/
 *  assignment.html.j2 的 CDN 口径对齐（升级必须两处同步，parity 哨兵 test_sheet_html.py 护航）。 */
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const katexPkg = require('katex/package.json')
// katex 的 package.json exports 只暴露 js/css 入口；dist 目录按 node_modules 布局直接定位
const dist = join(dirname(require.resolve('katex/package.json')), 'dist')
const dest = join(dirname(fileURLToPath(import.meta.url)), '..', 'public', 'katex')

if (!existsSync(dist)) {
  console.error('[copy-katex] node_modules/katex 缺失：先 npm ci（scripts: predev/prebuild 均已挂）')
  process.exit(1)
}
rmSync(dest, { recursive: true, force: true })
mkdirSync(dest, { recursive: true })
for (const f of ['katex.min.css', 'katex.min.js']) cpSync(join(dist, f), join(dest, f))
// contrib 只取 auto-render（与 D43 前手工 vendor 子集同口径）；字体只取 woff2（约 600KB）
mkdirSync(join(dest, 'contrib'), { recursive: true })
cpSync(join(dist, 'contrib', 'auto-render.min.js'), join(dest, 'contrib', 'auto-render.min.js'))
mkdirSync(join(dest, 'fonts'), { recursive: true })
for (const f of readdirSync(join(dist, 'fonts'))) {
  if (f.endsWith('.woff2')) cpSync(join(dist, 'fonts', f), join(dest, 'fonts', f))
}
console.log(`[copy-katex] katex ${katexPkg.version} → ${dest}（css/js/auto-render/woff2 ×${readdirSync(join(dest, 'fonts')).length}）`)

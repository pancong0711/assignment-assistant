#!/usr/bin/env node
/** D107：把前端「测量 + 排版」打包成可被 headless 页导入的 ES module。
 *
 *  产物：engine/src/assist/paper/layout_bundle.mjs
 *  由 `assist sheet layout` 通过 Playwright 页面 import 后调用，保证
 *  **PWA 与 CLI 跑同一份算法**（避免 Python 重写导致漂移）。
 */
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const { build } = require(process.env.ESBUILD_PATH || '../../app/node_modules/esbuild')
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { mkdirSync, writeFileSync, rmSync } from 'node:fs'

const here = dirname(fileURLToPath(import.meta.url))
const appDir = resolve(here, '..', '..', 'app')
const outFile = resolve(here, '..', 'src', 'assist', 'paper', 'layout_bundle.mjs')
mkdirSync(dirname(outFile), { recursive: true })

const entry = join(here, '.layout-entry.mjs')
writeFileSync(entry, `
export { autoLayout, solveGridForSolution, contentFingerprint, layoutMatches } from '${join(appDir, 'src/lib/autoLayout.ts').replace(/\\/g, '/')}'
export { cellGeometry } from '${join(appDir, 'src/lib/measureLayout.ts').replace(/\\/g, '/')}'
`, 'utf-8')

try {
  await build({
    entryPoints: [entry],
    bundle: true,
    format: 'esm',
    outfile: outFile,
    platform: 'browser',
    target: ['chrome100'],
    external: ['jszip'],
    logLevel: 'warning',
  })
  console.log(`[build-layout-bundle] → ${outFile}`)
} finally {
  rmSync(entry, { force: true })
}

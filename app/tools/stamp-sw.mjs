#!/usr/bin/env node
/** stamp-sw.mjs — D89-N7：把构建产物 dist/sw.js 的 __APP_VERSION__ 替换为本次构建 id。
 *
 *  设计：**源文件 public/sw.js 永远保留占位符 __APP_VERSION__**（git diff 干净）；
 *  本脚本在 build 之后只改 dist/sw.js（vite 已把 public/ 原样拷进 dist）。
 *  构建 id 优先 GITHUB_SHA（CI）→ BUILD_ID → 本地时间戳。
 *  作用：每次构建产生不同缓存名 → SW activate 删除旧缓存 → 升级不滞留旧包。
 *  幂等：dist/sw.js 是构建产物，每次 build 都被 public/sw.js 覆盖回占位符版本，再 stamp。
 */
import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const swPath = join(root, 'dist', 'sw.js')
const PLACEHOLDER = '__APP_VERSION__'

if (!existsSync(swPath)) { console.error('[stamp-sw] dist/sw.js 缺失：请先 npm run build'); process.exit(1) }

const buildId = (process.env.GITHUB_SHA || process.env.BUILD_ID ||
  new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14))
let src = readFileSync(swPath, 'utf-8')
if (!src.includes(PLACEHOLDER)) {
  console.error('[stamp-sw] dist/sw.js 未含占位符 __APP_VERSION__（源 public/sw.js 应保留占位符）')
  process.exit(1)
}
writeFileSync(swPath, src.replaceAll(PLACEHOLDER, buildId), 'utf-8')
console.log(`[stamp-sw] dist/sw.js CACHE → assignment-assistant-${buildId}`)

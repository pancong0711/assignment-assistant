#!/usr/bin/env node
/** stamp-sw.mjs — D89-N7：把构建产物 sw.js 的 __APP_VERSION__ 替换为本次构建 id。
 *
 *  设计：**源文件 public/sw.js 永远保留占位符 __APP_VERSION__**（git diff 干净）；
 *  本脚本在 build 之后只改**产物目录**里的 sw.js（vite 已把 public/ 原样拷进去）。
 *  构建 id 优先 GITHUB_SHA（CI）→ BUILD_ID → 本地时间戳（带毫秒，同一秒内多次构建不重名）。
 *  作用：每次构建产生不同缓存名 → SW activate 删除旧缓存 → 升级不滞留旧包。
 *
 *  产物目录：`--outDir=xxx` / `--outDir xxx` 参数 > 环境变量 STAMP_SW_DIST > 缺省 `dist`。
 *
 *  幂等（D99 修复）：
 *  - 已 stamp 过（无占位符、但已有生成的 cache 名）→ **跳过并返回 0**，不再报错；
 *  - 原实现第二次 build（CI 的 `npm run build -- --outDir dist-test`）也去 stamp 已加戳的
 *    dist/sw.js，直接 exit 1，导致 app-tests 从 D89 起长期红。
 */
import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { dirname, join, isAbsolute } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const PLACEHOLDER = '__APP_VERSION__'
const STAMPED_RE = /assignment-assistant-(?!__APP_VERSION__)[^\s'"]+/

function outDirFromArgv(argv) {
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a.startsWith('--outDir=')) return a.slice('--outDir='.length)
    if (a === '--outDir' && argv[i + 1]) return argv[i + 1]
  }
  return process.env.STAMP_SW_DIST || 'dist'
}

const outDir = outDirFromArgv(process.argv.slice(2))
const swPath = isAbsolute(outDir) ? join(outDir, 'sw.js') : join(root, outDir, 'sw.js')

if (!existsSync(swPath)) {
  console.error(`[stamp-sw] ${outDir}/sw.js 缺失：请先 build 到该目录`)
  process.exit(1)
}

const buildId = process.env.GITHUB_SHA || process.env.BUILD_ID ||
  new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 17)

const src = readFileSync(swPath, 'utf-8')
if (!src.includes(PLACEHOLDER)) {
  const m = src.match(STAMPED_RE)
  if (m) {
    console.log(`[stamp-sw] ${outDir}/sw.js 已 stamp（${m[0]}），跳过`)
    process.exit(0)
  }
  console.error(`[stamp-sw] ${outDir}/sw.js 既无占位符也无已 stamp 的缓存名：源 public/sw.js 应保留 ${PLACEHOLDER}`)
  process.exit(1)
}
writeFileSync(swPath, src.replaceAll(PLACEHOLDER, buildId), 'utf-8')
console.log(`[stamp-sw] ${outDir}/sw.js CACHE → assignment-assistant-${buildId}`)

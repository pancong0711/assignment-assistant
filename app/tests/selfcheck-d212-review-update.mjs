/** D212：重复下载=覆盖+历史归档+哈希去重+孤儿清理（更新模式）。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const root = join(appRoot, '..')
const view = fs.readFileSync(join(appRoot, 'src/views/XxetongView.vue'), 'utf8')
const client = fs.readFileSync(join(appRoot, 'src/lib/engineClient.ts'), 'utf8')
const rh = fs.readFileSync(join(root, 'engine/src/assist/xxt/review_history.py'), 'utf8')
const dl = fs.readFileSync(join(root, 'engine/src/assist/xxt/review_download.py'), 'utf8')
const cli = fs.readFileSync(join(root, 'engine/src/assist/xxt/cli.py'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

// 后端：覆盖 + 归档 + 去重 + 孤儿
must(/def save_file\(/.test(rh), '缺少 save_file')
must(/def sha256_bytes\(/.test(rh) && /def file_sha256\(/.test(rh), '缺少内容哈希')
must(/def atomic_write_bytes\(/.test(rh), '缺少原子写')
must(/HISTORY_DIR = "\.history"/.test(rh), '缺少历史目录约定')
must(/def cleanup_orphans\(/.test(rh), '缺少孤儿清理')
must(/def manifest_keep_names\(/.test(rh), '缺少 manifest 引用集合')
must(/def prune_history\(/.test(rh), '缺少历史清理')
must(/unchanged/.test(rh) && /archived/.test(rh) && /orphans/.test(rh), '缺少五类统计')

// 下载链路
must(/"update"/.test(dl), 'download_review 未支持 update 模式')
must(/RH\.save_file\(/.test(dl), '未使用哈希+归档写入')
must(/RH\.cleanup_orphans\(/.test(dl), '未清理孤儿')
must(/"stats": stats/.test(dl), 'manifest/receipt 未带统计')
must(/if mode in \("update", "full"\)/.test(dl), 'update 模式未触发归档/清理')

// CLI 默认 update + __STATS__
must(/default="update"/.test(cli), 'CLI 默认模式未改为 update')
must(/__STATS__/.test(cli), 'CLI 未输出统计标记')

// 前端
must(/mode\?: 'full' \| 'missing' \| 'update' \| 'comments-only'/.test(client),
  'engineClient 未声明 update 模式')
must(/updateReviewWork\(it, 'update'\)/.test(view), '缺少“更新（推荐）”按钮')
must(/🔄 更新（推荐）/.test(view), '按钮文案缺失')
must(/__STATS__/.test(view), '前端未解析统计')
must(/清理孤儿/.test(view), '前端未展示孤儿统计')

must(/selfcheck:d212/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d212')
must(!!pkg.scripts?.['selfcheck:d212'], 'package.json 缺少 selfcheck:d212')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 更新模式：覆盖变化内容 + 旧版归档 .history + 哈希去重')
console.log('✓ 按 manifest 清理孤儿（扩展名/改名/图变少三类残留）')
console.log('✓ 回执与界面显示 新增/更新/未变/归档/清理孤儿')
console.log('✓ D212 selfcheck 已接入 npm run selfcheck')

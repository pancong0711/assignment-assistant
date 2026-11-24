/** D220：题库编辑器输入不中断（行 key 不得依赖可编辑字段）+ 防抖落草稿。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const view = fs.readFileSync(join(appRoot, 'src/views/KbEditorView.vue'), 'utf8')
const store = fs.readFileSync(join(appRoot, 'src/stores/kb.ts'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

// 1) 行 key 必须稳定（与 id 等可编辑值无关）
must(!/:key="r\.id \+ idx"/.test(view), '行 key 仍依赖 r.id（输入 id 会重建行 → 失焦）')
must(/:key="rowKey\(r, idx\)"/.test(view), '未使用稳定行 key')
must(/import \{ createRowKeyer \} from '\.\.\/lib\/stableRowKey'/.test(view),
  '未引用 stableRowKey 模块')

// 1b) 行为验证：同一行对象改 id 后 key 必须不变；新对象必须换 key
const { createRowKeyer } = await import('../src/lib/stableRowKey.ts')
const key = createRowKeyer()
const row = { id: 'N', content: '' }
const k1 = key(row)
row.id = 'NEW-1'          // 模拟连续输入
row.content = 'x'
const k2 = key(row)
must(k1 === k2, `同行改 id 后 key 变化（${k1} → ${k2}）→ 会导致输入框失焦`)
const other = { id: 'NEW-1' }
must(key(other) !== k1, '新行对象应分配新 key')
must(key(null) === 'i0' && key(undefined, 7) === 'i7', '非对象行应有回退 key')

// 2) 输入只更新内存；失焦写草稿用防抖；写回才落 xlsx
must(/@change="kb\.touch\(\); kb\.persistDebounced\(\)"/.test(view),
  '编辑落草稿未使用防抖')
must(/persistDebounced\(/.test(store), 'store 缺少 persistDebounced')
must(/写回/.test(view), '缺少「写回」按钮文案')

// 3) selfcheck 接入
must(/selfcheck:d220/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d220')
must(!!pkg.scripts?.['selfcheck:d220'], 'package.json 缺少 selfcheck:d220')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 行 key 与输入值无关（连续输入不重建、不失焦）')
console.log('✓ 失焦只写浏览器草稿（防抖），「写回」才写 xlsx')
console.log('✓ D220 selfcheck 已接入 npm run selfcheck')

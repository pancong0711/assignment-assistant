/**
 * D162：作业纸 `random_seed` 必须在 parse/serialize 往返中**保留**。
 * 此前 parseTaskpad 重建对象时丢掉了它 → 保存后载入又变回默认 → 翻译题回到同一道。
 */
import { makeRandomSeed, parseTaskpad, serializeTaskpad, emptyTaskpad } from './taskpad.bundle.mjs'

let bad = 0
function ok(name, cond, detail = '') {
  if (cond) console.log(`✓ ${name}`)
  else { console.error(`✘ ${name}${detail ? '：' + detail : ''}`); bad = 1 }
}

const pad = emptyTaskpad()
ok('新建作业纸自带种子', typeof pad.random_seed === 'number' && pad.random_seed > 0,
   String(pad.random_seed))

const restored = parseTaskpad(JSON.parse(serializeTaskpad(pad)))
ok('序列化往返保留种子', restored.random_seed === pad.random_seed,
   `${restored.random_seed} vs ${pad.random_seed}`)

const a = emptyTaskpad(); const b = emptyTaskpad()
ok('两次新建种子不同（不会永远同一道翻译题）', a.random_seed !== b.random_seed,
   `${a.random_seed} / ${b.random_seed}`)

// 无种子旧数据 → 不报错
const legacy = parseTaskpad({ id: 'old', items: [] })
ok('旧数据（无种子）可解析', legacy.random_seed === undefined)

if (!bad) console.log('OK d162-taskpad-seed：种子在往返中保留 · 两次新建不同 · 旧数据兼容')
process.exit(bad)

/**
 * D162：从清单删除作业纸后，**作业包内的引用也要清掉**，否则
 * 作业包名后的「N 张」计数不会减少（教师反馈）。
 */
// Node 环境没有 localStorage：补一个内存 stub（store 内部会用它持久化）
const _mem = new Map()
globalThis.localStorage = {
  getItem: (k) => (_mem.has(k) ? _mem.get(k) : null),
  setItem: (k, v) => { _mem.set(k, String(v)) },
  removeItem: (k) => { _mem.delete(k) },
}
const { makeStores } = await import('./d162-stores.bundle.mjs')

let bad = 0
function ok(name, cond, detail = '') {
  if (cond) console.log(`✓ ${name}`)
  else { console.error(`✘ ${name}${detail ? '：' + detail : ''}`); bad = 1 }
}

const { pads, packs } = makeStores()

// 造一个包 + 两张作业纸
packs.packs = [{ id: 'packA', name: '包A', pads: [{ padId: 'p1', tag: 'a' }, { padId: 'p2', tag: 'b' }] }]
pads.saved = [{ id: 'p1', json: '{"id":"p1"}' }, { id: 'p2', json: '{"id":"p2"}' }]

ok('初始 2 张', (packs.packs[0].pads || []).length === 2,
   String((packs.packs[0].pads || []).length))

const affected = pads.removeFromLibrary('p1')
ok('删除后包内引用被清掉', (packs.packs[0].pads || []).length === 1,
   String((packs.packs[0].pads || []).length))
ok('返回受影响的作业包', affected.includes('packA'), JSON.stringify(affected))
ok('清单里也删掉了', !pads.saved.some((x) => x.id === 'p1'))

if (!bad) console.log('OK d162-pack-count：删除作业纸后包内引用同步清理（计数会减少）')
process.exit(bad)

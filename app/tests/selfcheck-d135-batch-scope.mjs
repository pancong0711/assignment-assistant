/**
 * D135：整班 batch zip 的作业纸范围 —— **优先当前作业包**。
 *
 * 此前 `downloadBatchZip` 直接用 `pad.savedJsons()`（全库），会把别的作业包的
 * 作业纸打进本次交付包。本测试锁定"与整班预览同口径"：
 *   有当前包 → 只用包内作业纸；没有包 → 回落全库（并明确标注范围）。
 */
import { makeStore } from './packs.bundle.mjs'

const packs = makeStore()

function ok(name, cond, detail = '') {
  if (!cond) { console.error(`✘ ${name}${detail ? '：' + detail : ''}`); process.exitCode = 1 }
  else console.log(`✓ ${name}`)
}

// 全库已保存作业纸：2 份属于 packA，1 份属于 packB
const saved = [
  { id: 'p1', json: JSON.stringify({ id: 'p1', target_tag: 'A', items: [] }) },
  { id: 'p2', json: JSON.stringify({ id: 'p2', target_tag: 'B', items: [] }) },
  { id: 'p3', json: JSON.stringify({ id: 'p3', target_tag: 'C', items: [] }) },
]
packs.packs = [
  { id: 'packA', name: '包A', pads: [{ padId: 'p1', tag: 'A' }, { padId: 'p2', tag: 'B' }] },
  { id: 'packB', name: '包B', pads: [{ padId: 'p3', tag: 'C' }] },
]

// 选中 packA
packs.select('packA')
const inPack = packs.packPadJsons(saved)
ok('当前包内只取本包作业纸', inPack.pads.length === 2, `got ${inPack.pads.length}`)
ok('不包含别的包的作业纸', !inPack.pads.some((x) => x.id === 'p3'))
ok('返回 packId 便于提示', inPack.packId === 'packA')

// 未选包（currentId 空）→ 应为空，调用方据此回落全库
packs.select('')
const none = packs.packPadJsons(saved)
ok('未选包时返回空（由调用方回落全库）', none.pads.length === 0)

// dangling：包内引用了不存在的作业纸
packs.packs = [{ id: 'packX', name: 'X', pads: [{ padId: 'ghost', tag: 'G' }] }]
packs.select('packX')
const dang = packs.packPadJsons(saved)
ok('检测包内悬空引用', dang.dangling.includes('ghost'), JSON.stringify(dang.dangling))

if (!process.exitCode) {
  console.log('OK d135-batch-scope：整班 batch zip 优先取当前作业包 · 未选包回落全库 · 悬空引用可提示')
}

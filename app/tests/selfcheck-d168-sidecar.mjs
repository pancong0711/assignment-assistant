// D168-T13：整班输出 sidecar（打印 PDF 后的追溯元数据）。
//
// 教师场景：「预览整班作业纸之后打印 PDF 保存，信息会丢失」——
// 这份 JSON 记录「哪个包、哪些作业纸、发给谁、谁什么 tag、用了哪些开关」。
import assert from 'node:assert/strict'
import { buildSheetSidecar, sidecarFileName } from './sheetSidecar.bundle.mjs'

const students = [
  { name: '张三', number: '2023001', tag: 'top' },
  { name: '李四', number: '2023002', tag: 'middle' },
  { name: '王五', number: '2023003', tag: 'unknown_tag' },
  { name: '赵六', number: '2023004', tag: '' },
]
const pads = [
  { padId: 'pad-top', tag: 'top' },
  { padId: 'pad-mid', tag: 'middle' },
]

const sc = buildSheetSidecar({
  packId: 'hw1', packName: '第一次作业',
  purpose: 'print', pads, students,
  options: { includeAnswers: false, includeWatermark: true, includePageText: true },
  now: new Date('2026-11-05T10:00:00Z'),
})

// 1) 基本元数据
assert.equal(sc.version, 1)
assert.equal(sc.kind, 'class-sheet-output')
assert.equal(sc.packId, 'hw1')
assert.equal(sc.packName, '第一次作业')
assert.equal(sc.purpose, 'print')
assert.equal(sc.generatedAt, '2026-11-05T10:00:00.000Z')

// 2) 学生 ↔ 作业纸绑定（按 tag 推出）
const byName = Object.fromEntries(sc.students.map((s) => [s.name, s]))
assert.equal(byName['张三'].padId, 'pad-top')
assert.equal(byName['李四'].padId, 'pad-mid')
assert.equal(byName['王五'].padId, undefined, '未绑定的 tag 不应有 padId')
assert.equal(byName['赵六'].padId, undefined)

// 3) 未绑定 tag 要**显式**列出（事后能看出"这些人当时没作业纸"）
assert.deepEqual(sc.unboundTags, ['unknown_tag'])

// 4) 开关原样记录（可复现同一版式）
assert.deepEqual(sc.options, { includeAnswers: false, includeWatermark: true, includePageText: true })

// 5) 计数
assert.deepEqual(sc.counts, { students: 4, pads: 2 })

// 6) 下载用途
const dl = buildSheetSidecar({
  packId: 'hw1', purpose: 'download', pads, students,
  options: { includeAnswers: true, includeWatermark: false, includePageText: false },
})
assert.equal(dl.purpose, 'download')
assert.equal(dl.options.includeAnswers, true)

// 7) 无作业包时也应产出（packId 为空串，不崩）
const noPack = buildSheetSidecar({
  purpose: 'print', pads: [], students: [students[0]],
  options: { includeAnswers: false, includeWatermark: true, includePageText: true },
})
assert.equal(noPack.packId, '')
assert.equal(noPack.students.length, 1)
assert.deepEqual(noPack.unboundTags, ['top'], '无作业纸时所有 tag 都算未绑定')

// 8) 文件名与 HTML 配对
assert.equal(sidecarFileName('class-sheet-2026-11-05.html'), 'class-sheet-2026-11-05.json')
assert.equal(sidecarFileName('a.HTML'), 'a.json')

// 9) 显式 padByStudent 优先于 tag 推断
const manual = buildSheetSidecar({
  purpose: 'print', pads, students: [students[0]],
  padByStudent: { 张三: 'pad-custom' },
  options: { includeAnswers: false, includeWatermark: true, includePageText: true },
})
assert.equal(manual.students[0].padId, 'pad-custom')

console.log('OK d168-sidecar：整班输出追溯 JSON（包/作业纸/学生tag/开关/未绑定）全部通过')

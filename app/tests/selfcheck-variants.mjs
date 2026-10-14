/** app 自检（docs/05-D23 / 12-B3.5 变体编排纯逻辑）：esbuild 打包
 *  src/lib/taskpad.ts 与 src/lib/variantBatch.ts → node 运行，断言：
 *  1) taskpad target_tag 序列化/解析 schema（空值不写字段，engine 兼容）；
 *  2) padInferredTag 与 engine paper/batch.py pad_tag 同口径
 *     （target_tag 优先 / items 唯一 tag / 无 tag='default' / 混合=null）；
 *  3) 缺包告警 missingBoundTags + 绑定冲突 resolveBindTag 匹配逻辑。
 *  运行：在 app/ 下执行  node tests/selfcheck-variants.mjs */
import { execFileSync } from 'node:child_process'
import assert from 'node:assert'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { pathToFileURL } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const tmp = mkdtempSync(join(tmpdir(), 'selfcheck-variants-'))
process.on('exit', () => rmSync(tmp, { recursive: true, force: true }))
for (const [src, out] of [
  ['src/lib/taskpad.ts', 'taskpad.bundle.mjs'],
  ['src/lib/variantBatch.ts', 'variant.branch.mjs'],
]) {
  execFileSync(join(appDir, 'node_modules', '.bin', 'esbuild'), [
    resolve(appDir, src), '--bundle', '--format=esm', `--outfile=${join(tmp, out)}`,
  ], { stdio: 'inherit' })
}
const tp = await import(pathToFileURL(join(tmp, 'taskpad.bundle.mjs')).href)
const { parseTaskpad, serializeTaskpad, padInferredTag, missingBoundTags, resolveBindTag } = tp

const item = (tag) => ({ kb: 'problems', chap: 'chap10', ids: ['10-1'], tag })

/* ---------- 1) target_tag 序列化/解析 schema ---------- */
{
  const pad = parseTaskpad({
    id: '2026S1-classA-chap10-1', class_dir: 'classes/x', layout: {},
    items: [item('copy')], target_tag: 'distinguish',
  })
  assert.equal(pad.target_tag, 'distinguish')
  const out = JSON.parse(serializeTaskpad(pad))
  assert.equal(out.target_tag, 'distinguish')
  console.log('1a) target_tag 显式绑定：写入 top-level 字段 … ok')
}
{
  // 空值不写字段：与缺字段任务包字节级兼容（engine CLI 三种输入一致）
  const base = { id: 't1', layout: {}, items: [item('copy')] }
  for (const t of [undefined, '', null]) {
    const pad2 = parseTaskpad(base)
    pad2.target_tag = (t === null ? undefined : t)
    const out = JSON.parse(serializeTaskpad(pad2))
    assert.equal('target_tag' in out, false, `target_tag=${t} 不应写字段`)
  }
  assert.equal(parseTaskpad(base).target_tag, undefined)
  console.log('1b) target_tag 空/缺失：不写字段，解析为 undefined … ok')
}
{
  // 清空绑定（''）→ 原字段从导出 JSON 消失（stores/taskpad.setSavedTargetTag 依赖此行为）
  const pad = parseTaskpad({ id: 't2', layout: {}, items: [], target_tag: 'qa' })
  pad.target_tag = undefined
  assert.equal('target_tag' in JSON.parse(serializeTaskpad(pad)), false)
  console.log('1c) 解绑后序列化不残留 target_tag … ok')
}

/* ---------- 2) pad_tag 推断（与 engine batch.py 同口径） ---------- */
{
  assert.equal(padInferredTag([item('copy'), item('copy')], 'distinguish'), 'distinguish') // target_tag 优先
  assert.equal(padInferredTag([item('copy')], undefined), 'copy')                          // items 唯一 tag
  assert.equal(padInferredTag([], undefined), 'default')                                   // 无 tag
  assert.equal(padInferredTag([item('copy'), item('qa')], undefined), null)                // 混合 → 需显式
  assert.equal(padInferredTag([item('copy'), item('qa')], ''), null)                       // 空串=未绑定
  console.log('2) padInferredTag：target_tag 优先 / 唯一 tag / 无 tag=default / 混合=null … ok')
}

/* ---------- 3) 缺包告警 + 绑定匹配 ---------- */
// 参考 engine：学生 tag 'distinguish' 无对应包 → 告警；干净包 → 'default'
{
  const counts = { copy: 12, distinguish: 3, unknown2: 2 }
  const binds = [
    { id: 'p-copy', binding: '', items: [item('copy')] },               // 推断 copy
    { id: 'p-explicit', binding: 'distinguish', items: [] },            // 显式 distinguish
  ]
  assert.deepEqual(missingBoundTags(counts, binds), ['unknown2'])
  assert.equal(missingBoundTags({}, binds).length, 0)
  // 混合 tag 且未绑定 → 该包不覆盖任何 tag，名单 tag 全部告警
  const mixedBinds = [{ id: 'p-mixed', binding: '', items: [item('copy'), item('qa')] }, binds[1]]
  assert.deepEqual(missingBoundTags(counts, mixedBinds), ['copy', 'unknown2'])
  // resolveBindTag：显式 > items 推断 > null
  assert.equal(resolveBindTag({ id: 'x', binding: 'qa', items: [item('copy')] }), 'qa')
  assert.equal(resolveBindTag({ id: 'x', binding: '', items: [item('copy')] }), 'copy')
  assert.equal(resolveBindTag({ id: 'x', binding: '', items: [item('copy'), item('qa')] }), null)
  console.log('3) 缺包告警/绑定冲突匹配逻辑 … ok')
}

/* ---------- 4) README 命令文案（variantBatch 纯字符串部分） ---------- */
{
  const vb = await import(pathToFileURL(join(tmp, 'variant.branch.mjs')).href)
  const p = vb.batchPaths('classA')
  assert.equal(p.classDir, 'classes/classA')
  assert.equal(p.roster, 'classes/classA/roster/roster.xlsx')
  assert.equal(p.task('t1'), 'tasks/t1.taskpad.json')
  const cmd = vb.batchCommand(p.roster, ['tasks/t1.taskpad.json', 'tasks/t2.taskpad.json'], p.classDir, ['qa'])
  for (const sub of [
    'assist sheet batch \\', '--roster classes/classA/roster/roster.xlsx',
    '--pads tasks/t1.taskpad.json', '--pads tasks/t2.taskpad.json',
    '--class-dir classes/classA', '--default',
  ]) assert.ok(cmd.includes(sub), `命令缺少片段: ${sub}`)
  console.log('4) batch 命令/README 文案生成 … ok')
}

/* ---------- 5) D82-C：figure(numbering/labels) 往返 + makeTaskpadId 语义 ---------- */
{
  const pad = parseTaskpad({
    id: '202610-chap04-321', class_dir: 'classes/x',
    layout: { numbering: 'id', figure: { scale: 1.2, pos: 'rt', max_w_mm: 40, max_h_mm: 35 } },
    items: [{ kb: 'problems', chap: 'chap04', ids: ['demo-04-1', 'demo-04-2'], tag: 'copy',
              labels: { 'demo-04-2': '(二)' } }],
  })
  assert.equal(pad.layout.numbering, 'id')
  assert.equal(pad.layout.figure.max_w_mm, 40)
  assert.equal(pad.layout.figure.max_h_mm, 35)
  assert.equal(pad.layout.figure.scale, 1.2)
  assert.equal(pad.layout.figure.pos, 'rt')
  assert.deepEqual(pad.items[0].labels, { 'demo-04-2': '(二)' })
  // 往返：重新解析序列化结果仍保留
  const round = parseTaskpad(JSON.parse(serializeTaskpad(pad)))
  assert.equal(round.layout.numbering, 'id')
  assert.equal(round.layout.figure.max_w_mm, 40)
  assert.deepEqual(round.items[0].labels, { 'demo-04-2': '(二)' })
  console.log('5a) D82-C figure/numbering/labels 往返 … ok')

  // 缺省：auto/无 labels/无 figure 不写冗余字段
  const bare = parseTaskpad({ id: '202610-q-100', layout: {}, items: [] })
  assert.equal(bare.layout.numbering, undefined)
  assert.equal(bare.layout.figure, undefined)
  const bareOut = JSON.parse(serializeTaskpad(bare))
  assert.equal(bareOut.layout.numbering, undefined)
  assert.equal(bareOut.layout.figure, undefined)
  console.log('5b) D82-C 缺省不写冗余字段 … ok')

  // makeTaskpadId：年月+章节+3位随机；章节归一
  const id = tp.makeTaskpadId('202610', 'chap04')
  assert.match(id, /^202610-chap04-\d{3}$/, `id=${id}`)
  const id2 = tp.makeTaskpadId('202610', '')
  assert.match(id2, /^202610-q-\d{3}$/, `id=${id2}`)
  const id3 = tp.makeTaskpadId('202610', 'kb/chap07/')
  assert.match(id3, /^202610-chap07-\d{3}$/, `id=${id3}`)
  // 无参 → 当前年月
  assert.match(tp.makeTaskpadId(), /^\d{6}-q-\d{3}$/)
  // 章节推断
  assert.equal(tp.chapLabelOfItems([{ chap: 'plants/04-xxx' }, { chap: 'chap09' }]), '04-xxx')
  assert.equal(tp.chapLabelOfItems([]), '')
  console.log('5c) makeTaskpadId 年月+章节+随机3位 … ok')
}

console.log('selfcheck-variants: 全部通过')

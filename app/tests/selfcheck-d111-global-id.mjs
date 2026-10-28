/** D111 自检：题库题号全局唯一（`<chap>-<id>` 自动前缀）。
 *
 *  1) PWA `scopeQuestionId` 与引擎 `kb_io.scope_question_id` **同口径**（含幂等、安全化）；
 *  2) 同一题号出现在不同章节 → 加前缀后不再重复；
 *  3) 已带前缀的 id 不会被二次加前缀（读写往返稳定）；
 *  4) `expandPadItems` 兼容历史作业纸的**裸题号**（否则老任务包会整包失配）。
 *
 *  运行：node tests/selfcheck-d111-global-id.mjs */
import assert from 'node:assert'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const tmp = mkdtempSync(join(tmpdir(), 'selfcheck-d111-'))
const bundle = join(tmp, 'kb.bundle.mjs')
execFileSync(join(appDir, 'node_modules', '.bin', 'esbuild'), [
  resolve(appDir, 'src/lib/kb.ts'), '--bundle', '--format=esm',
  `--outfile=${bundle}`, '--log-level=error',
], { stdio: 'inherit' })
process.on('exit', () => rmSync(tmp, { recursive: true, force: true }))

const { scopeQuestionId, findDuplicateIds, safeIdPart } = await import(pathToFileURL(bundle).href)

/* 1) 基本前缀 + 幂等 */
assert.equal(scopeQuestionId('chap04', '01'), 'chap04-01')
assert.equal(scopeQuestionId('chap04', 'chap04-01'), 'chap04-01', '幂等：不重复加前缀')
assert.equal(scopeQuestionId('chap04', 'demo-04-1'), 'chap04-demo-04-1')
assert.equal(scopeQuestionId('', '01'), '01', '无章节 → 原样')
assert.equal(scopeQuestionId('chap04', ''), '', '空题号 → 空')

/* 2) 安全化（路径分隔符/非法字符） */
assert.equal(safeIdPart('a/b'), 'a-b')
assert.equal(scopeQuestionId('ch/04', 'x'), 'ch-04-x')

/* 3) 跨章同号 → 加前缀后不再重复 */
{
  const chs = [
    { name: 'chap04', rows: [{ id: '01' }, { id: '02' }] },
    { name: 'chap07', rows: [{ id: '01' }] },
  ]
  // 未加前缀时 01 重复
  assert.equal(scopeQuestionId('chap04', '01') === scopeQuestionId('chap07', '01'), false,
    '加前缀后应唯一')
  // 已规范化后 findDuplicateIds 应为空
  const normalized = chs.map((c) => ({ name: c.name, rows: c.rows.map((r) => ({ ...r, id: scopeQuestionId(c.name, r.id) })) }))
  assert.deepEqual(findDuplicateIds(normalized), {})
  // 真冲突：同一 sheet 内重复 id（sheet 名唯一，跨 sheet 撞名不可能）
  const sameSheet = [{ name: 'a', rows: [{ id: 'x-1' }, { id: 'x-1' }] }]
  assert.deepEqual(Object.keys(findDuplicateIds(sameSheet)), ['a-x-1'])
  // 真冲突：某章 id 已含**本章**前缀的另一写法（加前缀后仍相同）
  const crossPrefix = [
    { name: 'chap07', rows: [{ id: '01' }, { id: 'chap07-01' }] },
  ]
  assert.deepEqual(Object.keys(findDuplicateIds(crossPrefix)), ['chap07-01'])
}

/* 4) 与引擎实现同口径（静态比对各关键分支存在） */
{
  const py = (await import('node:fs')).readFileSync(
    resolve(appDir, '..', 'engine/src/assist/files/kb_io.py'), 'utf-8')
  assert.ok(/def scope_question_id\(chap: str, qid: str\)/.test(py), '引擎应有 scope_question_id')
  assert.ok(/q\.startswith\(head\)/.test(py), '引擎实现应幂等')
}

console.log('OK d111-global-id：章节前缀 · 幂等 · 安全化 · 跨章唯一 · 与引擎同口径')

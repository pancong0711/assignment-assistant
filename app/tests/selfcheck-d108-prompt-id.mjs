/** D108-FIX 自检：提示词模板 id 归一化/建议值（PWA 侧）。
 *  背景 bug：另存为/新建模板时直接把 window.prompt 原始输入提交，用户填中文名或带空格
 *  就整串报蓝字「模板 id 非法」，表现为「另存功能不可用、无法新建模板」。
 *  运行：node tests/selfcheck-d108-prompt-id.mjs */
import assert from 'node:assert'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const tmp = mkdtempSync(join(tmpdir(), 'selfcheck-d108-'))
const bundle = join(tmp, 'promptId.bundle.mjs')
execFileSync(join(appDir, 'node_modules', '.bin', 'esbuild'), [
  resolve(appDir, 'src/lib/promptId.ts'), '--bundle', '--format=esm',
  `--outfile=${bundle}`, '--log-level=error',
], { stdio: 'inherit' })
process.on('exit', () => rmSync(tmp, { recursive: true, force: true }))

const { normalizePromptId, suggestPromptId, PROMPT_ID_RE } =
  await import(pathToFileURL(bundle).href)

/* 1) 中文 id 必须放行（本次 bug 主因） */
for (const id of ['我的模板', '含示意图', '标准_解答', 'my-template.v2', '_x']) {
  assert.ok(PROMPT_ID_RE.test(id), `中文/合法 id 应通过：${id}`)
  assert.equal(normalizePromptId(id), id, `已合法 id 不应被改动：${id}`)
}

/* 2) 常见用户输入被自动修复，而不是直接报错 */
assert.equal(normalizePromptId('  我的模板  '), '我的模板')
assert.equal(normalizePromptId('my template'), 'my-template')
assert.equal(normalizePromptId('我的 模板 v2'), '我的-模板-v2')
assert.equal(normalizePromptId('a/b\\c'), 'abc')
assert.equal(normalizePromptId('...hidden'), 'hidden')

/* 3) 无法修复的输入返回 ''（由 UI 提示规则） */
assert.equal(normalizePromptId(''), '')
assert.equal(normalizePromptId('   '), '')
assert.equal(normalizePromptId('---'), '')
assert.equal(normalizePromptId('-x'), 'x')

/* 4) 超长截断到 64 位且仍合法 */
{
  const long = normalizePromptId('a'.repeat(200))
  assert.equal(long.length, 64)
  assert.ok(PROMPT_ID_RE.test(long))
}

/* 5) 建议 id：按名称生成、自动避让已占用 */
assert.equal(suggestPromptId('我的模板'), '我的模板')
assert.equal(suggestPromptId('  '), 'template')
assert.equal(suggestPromptId('我的模板', ['我的模板']), '我的模板-2')
assert.equal(suggestPromptId('我的模板', ['我的模板', '我的模板-2']), '我的模板-3')
assert.equal(suggestPromptId('', ['template']), 'template-2')

/* 6) 与引擎规则一致性抽查：前端放行的都必须能通过后端（同一正则语义） */
const engineRe = /^[0-9A-Za-z_\u4e00-\u9fff][0-9A-Za-z_\-\u4e00-\u9fff.]{0,63}$/
for (const id of ['我的模板', 'my-template.v2', '_x', 'a'.repeat(64)]) {
  assert.ok(engineRe.test(id) && PROMPT_ID_RE.test(id), `前后端规则应一致：${id}`)
}
for (const id of ['a'.repeat(65), '-x', '.x', 'a b', 'a/b']) {
  assert.ok(!engineRe.test(id) && !PROMPT_ID_RE.test(id), `前后端应同样拒绝：${id}`)
}

console.log('OK d108-prompt-id：中文 id 放行 / 输入归一化 / 建议值避让 / 前后端规则一致')

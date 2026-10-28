/** D112 自检：题库编辑器「答案预览」必须渲染 md+html，不能原样输出源码。
 *
 *  背景 bug：`KbEditorView.vue` 里 xlsx 旧列答案用的是 `{{ solFallback }}`（纯文本插值），
 *  题干用 `{{ solContent }}`。于是当引擎离线 / 该题还没有版本库时：
 *  - 内联 <svg> 示意图不显示（只露出一堆标签文本）
 *  - \(...\) / \[...\] 公式显示成源码
 *  修复：两处都改走 renderRich()（与作业纸 q-solution 同口径）。
 *
 *  运行：node tests/selfcheck-d112-kb-solution-render.mjs */
import assert from 'node:assert'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const src = readFileSync(resolve(appDir, 'src/views/KbEditorView.vue'), 'utf-8')

/** 去注释（含多行 HTML 注释块），避免被解释性注释里的旧写法误导。 */
const code = src
  .replace(/<!--[\s\S]*?-->/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .split('\n').filter((l) => !/^\s*\/\//.test(l)).join('\n')

/* 1) 旧列答案（solFallback）必须走 renderRich，而不是 {{ solFallback }} 纯插值 */
assert.ok(!/\{\{\s*solFallback\s*\}\}/.test(code),
  'solFallback 不得用 {{ }} 纯文本插值（会原样输出 <svg>/公式源码）')
assert.ok(/v-html="renderRich\(solFallback\)"/.test(code),
  'solFallback 必须用 v-html="renderRich(solFallback)" 渲染')

/* 2) 题干（solContent）同理 */
assert.ok(!/\{\{\s*solContent\s*\}\}/.test(code),
  'solContent 不得用 {{ }} 纯文本插值')
assert.ok(/v-html="renderRich\(solContent\)"/.test(code),
  'solContent 必须用 renderRich 渲染')

/* 3) 版本库分支仍保留 renderRich */
assert.ok(/v-html="renderRich\(solShown\.text\)/.test(code),
  '版本库答案分支应继续用 renderRich')

/* 4) 编辑态实时预览仍走 renderRich */
assert.ok(/el\.innerHTML = renderRich\(solDraft\.value\)/.test(code),
  '编辑态预览应继续用 renderRich')

console.log('OK d112-kb-solution-render：旧列答案/题干均按 md+html 渲染（示意图与公式不再显示源码）')

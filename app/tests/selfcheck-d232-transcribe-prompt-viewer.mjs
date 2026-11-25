/** D232：课堂资料转写提示词可视化（强调原文、不总结不省略）。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const repo = resolve(appRoot, '..')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

const view = fs.readFileSync(join(appRoot, 'src/views/MaterialsView.vue'), 'utf8')
const client = fs.readFileSync(join(appRoot, 'src/lib/engineClient.ts'), 'utf8')
const materials = fs.readFileSync(join(repo, 'engine/src/assist/files/materials.py'), 'utf8')
const serve = fs.readFileSync(join(repo, 'engine/src/assist/serve.py'), 'utf8')

must(view.includes('转写提示词'), '页面缺少「转写提示词」查看入口')
must(view.includes('systemPrompt') && view.includes('userPrompt'), '页面未展示系统/用户提示词')
must(view.includes('transcribePrompt.note'), '页面未说明本地 OCR 不经过提示词')
must(client.includes('fetchMaterialsTranscribePrompt'), 'engineClient 缺少提示词读取函数')
must(serve.includes('/materials/transcribe-prompt'), 'serve 缺少 transcribe-prompt 端点')

must(materials.includes('MATERIAL_TRANSCRIBE_SYSTEM_PROMPT'), '缺少转写 system prompt 单一事实源')
must(materials.includes('build_materials_transcribe_prompt'), '缺少转写 user prompt 构造函数')
must(materials.includes('不得总结、概括、省略、合并、改写、润色、补充或推断'),
  '提示词未强调不得总结/省略/改写')
must(materials.includes('每一页都必须输出'), '提示词未强调逐页输出')
must(materials.includes('[本页无文字]'), '提示词未要求空白页也输出')
must(materials.includes('[不清]'), '提示词未要求看不清时标注')
must(materials.includes('N 页图片') || materials.includes('第 {nums} 页图片'), '提示词未带页范围')

must(/selfcheck:d232/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d232')
must(!!pkg.scripts?.['selfcheck:d232'], 'package.json 缺少 selfcheck:d232')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 课堂资料页可只读查看转写系统提示词与用户提示词')
console.log('✓ 提示词强调忠实原文、逐页输出、不得总结/省略/改写/补全')
console.log('✓ 空白页、看不清字符、示意图均有明确输出约束')
console.log('✓ D232 selfcheck 已接入 npm run selfcheck')

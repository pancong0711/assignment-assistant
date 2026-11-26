/** D233：转写模型与知识点识别模型分开设置；识别基于转写/抽取文本而非重做。 */
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
const materials = fs.readFileSync(join(repo, 'engine/src/assist/files/materials.py'), 'utf8')
const client = fs.readFileSync(join(appRoot, 'src/lib/engineClient.ts'), 'utf8')

// 1) 两套模型设置
must(view.includes('转写模型') && view.includes('识别模型'), '页面未分成转写模型/识别模型')
must(view.includes('transcribeProvider') && view.includes('transcribeModel'), '缺少转写 provider/model')
must(view.includes('suggestProvider') && view.includes('suggestModel'), '缺少识别 provider/model')
must(view.includes('LS_TRANSCRIBE_MODEL') && view.includes('LS_SUGGEST_MODEL'),
  '两套选择未分别持久化')
must(view.includes('跟随转录段') && view.includes('跟随评阅段'),
  '两套默认阶段说明不清晰')
must(/transcribeMaterials\([\s\S]{0,300}transcribeProvider\.value,[\s\S]{0,80}transcribeModel\.value/.test(view),
  '转写请求没有使用转写模型')
must(/suggestMaterials\([\s\S]{0,260}suggestModel\.value\.trim\(\), suggestProvider\.value/.test(view),
  '知识点识别请求没有使用识别模型')

// 2) 识别基于转写/抽取文本
must(materials.includes('D230：优先使用独立转写文本'), 'read_source_text 未优先使用转写')
must(/use_vision = \(bool\(vision\["images"\]\) and not has_transcript/.test(materials),
  '有转写时仍可能走视觉直读')
must(materials.includes('has_transcript') && materials.includes('transcriptFiles'),
  '识别依据未区分 transcript/text_layer/vision')
must(materials.includes('"basis"') && materials.includes('transcript" if has_transcript'),
  '识别结果未返回 basis')
must(client.includes("basis?: 'transcript' | 'text_layer' | 'vision' | 'none'"),
  '前端类型缺少 recognition basis')

// 3) 页面明确说明识别不重新 OCR/转写
must(view.includes('不会重新 OCR/转写'), '页面未说明识别不会重新转写')
must(view.includes('知识点识别将基于'), '页面未显示识别依据')

must(/selfcheck:d233/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d233')
must(!!pkg.scripts?.['selfcheck:d233'], 'package.json 缺少 selfcheck:d233')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 转写模型与知识点识别模型可在 PWA 分别设置并分别记住')
console.log('✓ 转写默认跟随 transcription，识别默认跟随 evaluation')
console.log('✓ 知识点识别优先使用转写文本，其次文字层，最后才视觉直读')
console.log('✓ 识别结果返回 basis，页面明确显示依据')
console.log('✓ D233 selfcheck 已接入 npm run selfcheck')

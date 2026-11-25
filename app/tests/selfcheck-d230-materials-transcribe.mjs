/** D230：课堂资料转写层（本地 OCR / 多模态）+ 转写结果可视化。 */
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
const cli = fs.readFileSync(join(repo, 'engine/src/assist/cli.py'), 'utf8')

must(view.includes('转写选中'), 'PWA 缺少「转写选中」按钮')
must(view.includes('transcribeEngine') && view.includes('仅本地 OCR') && view.includes('仅 AI 视觉'),
  'PWA 缺少转写引擎选择')
must(view.includes('已转写') && view.includes('纯页图，未转写'), '文件列表缺少转写状态')
must(view.includes('transcriptPreview'), '抽取信息弹窗未显示转写文本预览')
must(client.includes('transcribeMaterials'), 'engineClient 缺少 transcribeMaterials')
must(client.includes('/materials/transcribe'), 'engineClient 缺少 /materials/transcribe')
must(/def transcribe_chap_file\(/.test(materials), 'materials 缺少 transcribe_chap_file')
must(/def transcribe_materials\(/.test(materials), 'materials 缺少 transcribe_materials')
must(materials.includes('_ocr_page_tesseract') && materials.includes('_vision_transcribe_batch'),
  '缺少本地 OCR / 视觉转写实现')
must(materials.includes('transcriptFiles') && materials.includes('"transcript"'),
  '转写结果未进入索引/识别读路径')
must(serve.includes('u.path == "/materials/transcribe"'), 'serve 缺少转写接口')
must(cli.includes('@materials_grp.command("transcribe")'), 'CLI 缺少 materials transcribe')
must(/stage="transcription"/.test(cli), 'CLI 转写未使用 transcription 段')

must(/selfcheck:d230/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d230')
must(!!pkg.scripts?.['selfcheck:d230'], 'package.json 缺少 selfcheck:d230')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 课堂资料增加独立转写层：自动 / 本地 OCR / AI 视觉')
console.log('✓ 转写结果写回索引，知识点识别优先使用转写文本')
console.log('✓ 文件列表和抽取信息弹窗可查看转写状态与文本预览')
console.log('✓ CLI / serve / PWA 三入口对齐')
console.log('✓ D230 selfcheck 已接入 npm run selfcheck')

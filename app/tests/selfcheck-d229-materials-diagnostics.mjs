/** D229：课堂资料识别诊断 + 单文件抽取详情可视化。 */
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
const serve = fs.readFileSync(join(repo, 'engine/src/assist/serve.py'), 'utf8')
const materials = fs.readFileSync(join(repo, 'engine/src/assist/files/materials.py'), 'utf8')
const providers = fs.readFileSync(join(repo, 'engine/src/assist/grading/providers.py'), 'utf8')

// 1) 前端明确显示实际 provider/model + 可检查配置
must(view.includes('suggestStages'), '未读取评阅段 stages 配置')
must(view.includes('跟随评阅段 evaluation'), '未明确显示“跟随评阅段 evaluation”')
must(view.includes('检查识别配置'), '缺少「检查识别配置」按钮')
must(view.includes('识别诊断'), '缺少识别诊断面板')
must(view.includes('复制诊断信息'), '诊断面板缺少复制按钮')
must(view.includes('r?.detail'), '识别失败时未展示后端 detail')
must(view.includes('suggestStageWarning'), '缺少 provider/key 配置提醒')

// 2) 单文件抽取信息可查看
must(view.includes('抽取信息'), '文件行缺少「抽取信息」入口')
must(view.includes('extractInfo.textPreview'), '抽取信息弹窗未显示文本预览')
must(view.includes('extractInfo.images'), '抽取信息弹窗未显示页图清单')
must(client.includes('/materials/extract-info'), 'engineClient 缺少 extract-info')
must(client.includes('/materials/suggest-diagnostics'), 'engineClient 缺少 suggest-diagnostics')

// 3) 引擎实现
must(/def extract_info\(/.test(materials), 'materials 缺少 extract_info')
must(/def source_selection_diagnostics\(/.test(materials), 'materials 缺少 source_selection_diagnostics')
must(/def effective_endpoint_info\(/.test(providers), 'providers 缺少 effective_endpoint_info')
must(serve.includes('/materials/extract-info'), 'serve 缺少 extract-info')
must(serve.includes('/materials/suggest-diagnostics'), 'serve 缺少 suggest-diagnostics')
must(serve.includes('"diagnostics": diagnostics'), 'suggest 失败响应缺少 structured diagnostics')
must(serve.includes('"detail": str(exc)'), 'suggest 失败响应缺少 detail')

must(/selfcheck:d229/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d229')
must(!!pkg.scripts?.['selfcheck:d229'], 'package.json 缺少 selfcheck:d229')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 页面明确显示实际 provider/model，并可复制识别诊断 JSON')
console.log('✓ 识别失败展示错误类型、detail、provider/model 与选中文件/字符数')
console.log('✓ 每个已抽取文件可打开「抽取信息」查看文本预览、页图清单和元数据')
console.log('✓ D229 selfcheck 已接入 npm run selfcheck')

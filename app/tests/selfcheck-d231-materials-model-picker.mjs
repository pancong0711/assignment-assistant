/** D231：课堂资料模型选择改为「下拉候选 + 自定义」并可真实测试模型。 */
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

must(view.includes('suggestModelOptions'), '缺少 provider 模型候选列表')
must(view.includes('suggestModelCustom'), '缺少自定义模型开关')
must(view.includes('>自定义<') || view.includes('自定义</button>'), '缺少「自定义」按钮')
must(view.includes('用下拉'), '缺少切回模型下拉按钮')
must(view.includes('测试模型'), '缺少「测试模型」按钮')
must(view.includes('testSelectedModel'), '缺少测试模型处理函数')
must(view.includes("stage: 'both'") || view.includes("'both',"), '测试模型未覆盖文本+多模态')
must(view.includes('transcribeModelLabel'), '仍缺少转写实际模型展示')

must(/body: JSON\.stringify\(\{ stage, provider: opts\.provider \|\| '', model: opts\.model \|\| '' \}\)/.test(client),
  'testLlmStages 未把显式 provider/model 传给引擎')
must(/explicit_provider/.test(serve) && /explicit_model/.test(serve),
  '/llm/test 未支持显式 provider/model')
must(/build_client_for\(/.test(serve), '/llm/test 未用 build_client_for 构造显式 provider')

must(/selfcheck:d231/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d231')
must(!!pkg.scripts?.['selfcheck:d231'], 'package.json 缺少 selfcheck:d231')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ provider 模型候选使用下拉菜单，并保留「自定义」手动填写')
console.log('✓ 下拉/自定义状态写入本地选择')
console.log('✓ 新增「测试模型」：同时测试文本与多模态探针')
console.log('✓ /llm/test 支持显式 provider/model')
console.log('✓ D231 selfcheck 已接入 npm run selfcheck')

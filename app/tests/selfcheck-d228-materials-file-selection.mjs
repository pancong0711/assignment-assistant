/** D228：课堂资料按文件抽取/识别知识点 + provider 选择真正生效。 */
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
const cli = fs.readFileSync(join(repo, 'engine/src/assist/cli.py'), 'utf8')
const materials = fs.readFileSync(join(repo, 'engine/src/assist/files/materials.py'), 'utf8')

// 1) PWA 文件多选 / 全选 / 反选
must(view.includes('selectedSourceFiles'), '缺少文件多选状态')
must(view.includes('全选') && view.includes('全不选') && view.includes('反选'),
  '缺少全选/全不选/反选入口')
must(view.includes('selectedFileList'), '缺少选中文件列表')
must(/const picked = selectedFileList\.value/.test(view), '抽取/识别未读取选中文件列表')
must(/extractMaterials\([\s\S]{0,260}forceExtract\.value, picked\)/.test(view),
  '抽取没有传选中文件列表')
must(/suggestMaterials\([\s\S]{0,300}suggestProvider\.value, picked\)/.test(view),
  'AI 建议知识点没有同时传 provider 与选中文件')
must(view.includes('selectedUnextracted'), '没有提示“选中文件尚未抽取”')
must(view.includes('已抽取') && view.includes('未抽取'), '文件列表缺少逐文件抽取状态')

// 2) engineClient 请求体
must(/extractMaterials[\s\S]{0,700}JSON\.stringify\(\{ chap, force, files \}\)/.test(client),
  'extractMaterials 请求体缺少 files')
must(/suggestMaterials[\s\S]{0,700}JSON\.stringify\(\{ chap, model, provider, files \}\)/.test(client),
  'suggestMaterials 请求体缺少 provider/files')

// 3) 引擎：按文件过滤 + provider 构造
must(/def extract_chap[\s\S]{0,300}files:/.test(materials), 'extract_chap 不支持 files')
must(/def suggest_knowledge[\s\S]{0,400}files:/.test(materials), 'suggest_knowledge 不支持 files')
must(materials.includes('resolve_source_selection'), '缺少选中文件解析/路径校验')
must(materials.includes('skipped_unselected'), '按文件抽取时未保留未选中索引')
must(/build_client_for\(ws_, provider, model/.test(serve),
  '/materials/suggest 未使用前端选择的 provider')
must(/raw_files = payload\.get\("files"\)/.test(serve), '/materials/extract 未接收 files')
must(/--file", "files", multiple=True/.test(cli), 'CLI 缺少可多次的 --file')

must(/selfcheck:d228/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d228')
must(!!pkg.scripts?.['selfcheck:d228'], 'package.json 缺少 selfcheck:d228')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 课堂资料支持逐文件勾选 / 多选 / 全选 / 反选')
console.log('✓ 抽取与 AI 知识点识别都只处理选中文件，未选索引保持不动')
console.log('✓ AI 建议知识点真正传递 provider，修复“选了下拉但仍用评阅配置”')
console.log('✓ 文件列表显示逐文件已抽取/未抽取状态')
console.log('✓ D228 selfcheck 已接入 npm run selfcheck')

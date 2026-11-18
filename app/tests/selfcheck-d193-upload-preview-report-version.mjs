/** D193：上传前对照表（三态）+ 报告内容哈希版本（静态自检）。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const root = join(appRoot, '..')
const view = fs.readFileSync(join(appRoot, 'src/components/AiGradingPanel.vue'), 'utf8')
const client = fs.readFileSync(join(appRoot, 'src/lib/engineClient.ts'), 'utf8')
const servePy = fs.readFileSync(join(root, 'engine/src/assist/serve.py'), 'utf8')
const draftsPy = fs.readFileSync(join(root, 'engine/src/assist/grading/drafts.py'), 'utf8')
const planPy = fs.readFileSync(join(root, 'engine/src/assist/xxt/grade_plan.py'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

// 1) 上传对照表
must(/export async function fetchXxtUploadPreview/.test(client), 'engineClient 缺少 fetchXxtUploadPreview')
must(/\/xxt\/grade\/upload-preview/.test(servePy), 'serve 缺少 /xxt/grade/upload-preview')
must(/async function openUploadPreview/.test(view), '缺少 openUploadPreview')
must(/async function confirmUploadFromPreview/.test(view), '缺少 confirmUploadFromPreview')
must(/上传前对照/.test(view), '缺少上传前对照 UI')
must(/冲突·需确认/.test(view), '对照表未标出冲突项')
must(/一致·跳过/.test(view), '对照表未标出一致项')
must(/继续将\*\*覆盖\*\*平台内容/.test(view), '冲突覆盖前未二次确认')
must(/按对照表上传/.test(view), '缺少“按对照表上传”动作')

// 2) 三态决策纯函数
must(/def decide\(/.test(planPy), '缺少 decide() 三态决策')
must(/UNCHANGED = "unchanged"/.test(planPy) && /CONFLICT = "conflict"/.test(planPy),
  '缺少 unchanged/conflict 常量')
must(/def summarize\(/.test(planPy), '缺少五类汇总 summarize()')
must(/def text_of\(/.test(planPy), '缺少批语归一 text_of()')
const uploadPy = fs.readFileSync(join(root, 'engine/src/assist/xxt/grade_upload.py'), 'utf8')
must(/decide\(status=/.test(uploadPy), 'upload_grade 未接入三态判断')
must(/platformBefore/.test(uploadPy), '上传结果未记录平台原值')

// 3) 报告内容哈希版本
must(/export async function fetchXxtReportVersions/.test(client), 'engineClient 缺少 fetchXxtReportVersions')
must(/\/xxt\/grade\/report-versions/.test(servePy), 'serve 缺少 report-versions 端点')
must(/report_versions\.record\(/.test(draftsPy), '报告生成未登记版本')
must(/human_patch\["report"\]/.test(draftsPy), '草稿未回写报告版本')
must(/VERSIONS_DIR = "\.versions"/.test(fs.readFileSync(
  join(root, 'engine/src/assist/grading/report_versions.py'), 'utf8')), '版本目录约定缺失')
// 稳定“最新”文件名不变（前端零改动）
must(/base = out_root \/ f"\{student\}"/.test(draftsPy), '报告最新路径不应带时间戳')

// 4) 生成报告提示版本
must(/版本 \$\{vers/.test(view), '生成完成未提示报告版本')

// 5) selfcheck 接入
must(/selfcheck:d193/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d193')
must(!!pkg.scripts?.['selfcheck:d193'], 'package.json 缺少 selfcheck:d193')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 上传前对照表（未批阅/一致/冲突三态）')
console.log('✓ 冲突覆盖需二次确认，并记录 platformBefore')
console.log('✓ 报告内容哈希版本 + .versions 历史，最新文件名不变')
console.log('✓ 只读对照/版本端点与客户端封装')
console.log('✓ D193 selfcheck 已接入 npm run selfcheck')

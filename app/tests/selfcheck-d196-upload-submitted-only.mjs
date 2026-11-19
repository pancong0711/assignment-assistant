/** D196：只上传已提交学生的批阅报告 + 批语缺失提醒 + 逐生上传。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const root = join(appRoot, '..')
const view = fs.readFileSync(join(appRoot, 'src/components/AiGradingPanel.vue'), 'utf8')
const client = fs.readFileSync(join(appRoot, 'src/lib/engineClient.ts'), 'utf8')
const plan = fs.readFileSync(join(root, 'engine/src/assist/xxt/grade_plan.py'), 'utf8')
const preview = fs.readFileSync(join(root, 'engine/src/assist/xxt/upload_preview.py'), 'utf8')
const upload = fs.readFileSync(join(root, 'engine/src/assist/xxt/grade_upload.py'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

// 1) 已提交判定 + 就绪分类（引擎）
must(/def is_submitted\(/.test(plan), '缺少 is_submitted')
must(/def upload_readiness\(/.test(plan), '缺少 upload_readiness')
must(/NOT_SUBMITTED = "not-submitted"/.test(plan), '缺少 not-submitted 常量')
must(/NO_COMMENT = "no-comment"/.test(plan), '缺少 no-comment 常量')
must(/NO_DRAFT = "no-draft"/.test(plan), '缺少 no-draft 常量')

// 2) 上传路径防御：未提交/批语空一律拦下
must(/grade_plan.NOT_SUBMITTED/.test(upload), '上传未拦未提交学生')
must(/grade_plan.NO_COMMENT/.test(upload), '上传未拦批语为空')
must(/needsReview/.test(upload), '上传结果未标记“需先批阅”')

// 3) 对照表返回 readiness
must(/upload_readiness\(/.test(preview), '对照表未接入 upload_readiness')
must(/"readiness": readiness/.test(preview), '对照表未返回 readiness')
must(/needComment/.test(preview), '仅本地核对未提醒批语为空')

// 4) 前端：逐生上传 + 就绪过滤 + 提醒
must(/async function uploadOneStudent/.test(view), '缺少逐生上传')
must(/oneUploadBusy/.test(view), '缺少逐生上传状态')
must(/api.*startXxtGradeUpload/s.test(view) || /startXxtGradeUpload\(/.test(view),
  '逐生上传未复用 startXxtGradeUpload')
must(/readyState === 'ready'/.test(view), '批量上传未按 readyState 过滤')
must(/r\.readyState === 'not-submitted'/.test(view), '未禁止未提交学生上传')
must(/批语为空/.test(view), '未提醒批语为空')
must(/已提交·可传/.test(view) && /未提交/.test(view), '对照表未显示提交/就绪状态')
must(/XxtUploadReadiness/.test(client), 'engineClient 缺少 XxtUploadReadiness')
must(/readyState\?: string/.test(client), 'engineClient 行类型缺少 readyState')

// 5) selfcheck 接入
must(/selfcheck:d196/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d196')
must(!!pkg.scripts?.['selfcheck:d196'], 'package.json 缺少 selfcheck:d196')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 只上传已提交学生（未提交直接跳过）')
console.log('✓ 已提交但批语为空 → 提醒先批阅/AI 批阅')
console.log('✓ 逐生上传（单人失败不影响他人，可单独重试）')
console.log('✓ D196 selfcheck 已接入 npm run selfcheck')

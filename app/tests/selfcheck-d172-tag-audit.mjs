#!/usr/bin/env node
/** D172：tag 审计（PWA 侧静态校验 + 引擎路由位置校验）。
 *
 * 教师红线（docs/117-D172）：
 * - 逐生审核必须有「🛡 审计 tag」列，与 tag 列**并列**；
 * - 不一致行必须**整行高亮**（不只是单元格变色）；
 * - 支持逐人应用 + 批量应用 + **撤销**；
 * - 只读接口 `/grade/audit-tags` 必须登记在引擎 `do_GET`（D171 已因写在 do_POST
 *   → 前端 GET 302 到 Pages 踩过两次）。
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const repoRoot = join(appRoot, '..')
const errors = []

const panel = readFileSync(join(appRoot, 'src/components/AiGradingPanel.vue'), 'utf8')
const client = readFileSync(join(appRoot, 'src/lib/engineClient.ts'), 'utf8')
const serve = readFileSync(join(repoRoot, 'engine/src/assist/serve.py'), 'utf8')

// 1) 表头：审计列与 tag 列相邻
if (!/🛡 审计 tag/.test(panel)) errors.push('缺少「🛡 审计 tag」列表头')
if (!/<th>tag<\/th>\s*<th[^>]*>🛡 审计 tag/.test(panel)) {
  errors.push('「审计 tag」列必须紧跟在 tag 列之后（并列）')
}

// 2) 不一致整行高亮
if (!/function auditRowClass/.test(panel)) errors.push('缺少 auditRowClass（不一致行高亮）')
if (!/:class="auditRowClass\(s\)"/.test(panel)) errors.push('<tr> 未绑定 auditRowClass')
if (!/\.row-audit-bad\s*\{[^}]*background/.test(panel)) {
  errors.push('缺少 .row-audit-bad 样式（整行背景）')
}

// 3) 逐人 + 批量 + 撤销
for (const fn of ['applyAuditOne', 'applyAuditChecked', 'undoAudit', 'runAuditNow',
                  'applyBulkTag', 'undoStudentTag', 'saveManualTag', 'auditDetailStep']) {
  if (!new RegExp(`function ${fn}`).test(panel)) errors.push(`缺少 ${fn}()`)
}

// 3b) D173：过滤必须按 tagDiffers（不是 verdict）——否则 unknown 的学生会被漏掉
if (!/auditFilter\.value === 'differs'\) return !!a\.tagDiffers/.test(panel)) {
  errors.push('「只看 tag 不同」必须按 tagDiffers 过滤（D172 用 verdict 导致列表空）')
}
if (/auditOnlyBad/.test(panel)) errors.push('auditOnlyBad 已废弃（改用 auditFilter）')

// 3c) D173：复选框必须常驻（此前限 mismatch&&high → 教师一个框都看不见）
if (!/type="checkbox"/.test(panel)) errors.push('缺少行复选框')
if (/v-if="auditSelectable/.test(panel)) errors.push('复选框不应再按置信度隐藏')

// 3d) D173：详情页必须包含「逐题对照 + 判据 + 人工确认 + 历史」
for (const [re, msg] of [
  [/逐题对照/, '详情页缺少「逐题对照」'],
  [/学生第 \{\{ p\.no \}\} 题/, '详情页缺少逐题学生题干'],
  [/p\.perPaper/, '详情页缺少每张作业纸的对照'],
  [/怎么判的（判据）/, '详情页缺少「判据」'],
  [/printed_question/, '判据里要说明「只比对题干」'],
  [/人工确认/, '详情页缺少「人工确认」'],
  [/tag 变更历史/, '详情页缺少「tag 变更历史」'],
]) {
  if (!re.test(panel)) errors.push(msg)
}
if (!/改动|改历史/.test(panel)) errors.push('应用 tag 前必须提示「这是改历史」')

// 4) 未转写不可审核（教师 N2）
if (!/未转写/.test(panel)) errors.push('缺少「未转写」状态（未转写不可审核）')

// 5) 前端 API 全部连引擎
for (const fn of ['fetchTagAudit', 'runTagAudit', 'applyTagAudit',
                  'fetchTagAuditHistory', 'undoTagAudit']) {
  if (!new RegExp(`export async function ${fn}`).test(client)) errors.push(`engineClient 缺少 ${fn}`)
  if (!new RegExp(fn).test(panel)) errors.push(`面板未调用 ${fn}`)
}

const tagAudit = readFileSync(join(repoRoot, 'engine/src/assist/grading/tag_audit.py'), 'utf8')

// 6) 引擎路由位置：GET 必须在 do_GET 内，POST 在 do_POST 内
const getStart = serve.indexOf('def do_GET(self)')
const getEnd = serve.length
const postStart = serve.indexOf('def do_POST(self)')
const postEnd = getStart
const getBody = serve.slice(getStart, getEnd)
const postBody = serve.slice(postStart, postEnd)
if (!/elif u\.path == "\/grade\/audit-tags":/.test(getBody)) {
  errors.push('只读接口 /grade/audit-tags 必须登记在 do_GET（否则前端 GET 会 302）')
}
if (!/\/grade\/audit-tags\/run/.test(postBody)) {
  errors.push('写接口 /grade/audit-tags/run 必须登记在 do_POST')
}
// 反面样例：绝不能出现在 do_POST 里当 GET 用
if (/elif u\.path == "\/grade\/audit-tags":/.test(postBody)) {
  errors.push('/grade/audit-tags（只读）不应出现在 do_POST')
}

// 6b) 关键回归（教师实测 bug）：前端**不得**把 taskpad 拼成 questions 传给引擎
if (/function auditPads/.test(panel)) errors.push('auditPads() 已废弃：taskpad 没有题干，必须传 taskpads')
if (!/function auditTaskpads/.test(panel)) errors.push('缺少 auditTaskpads()（传 taskpad 原样给引擎）')
if (!/taskpads: tps/.test(panel)) errors.push('runTagAudit 必须传 taskpads（题干由引擎从题库解析）')
// 引擎侧必须真有解析入口
if (!/def papers_from_taskpads/.test(tagAudit)) {
  errors.push('引擎缺少 papers_from_taskpads（taskpad → 题库题干）')
}
if (/qs\.push\(\{[^}]*content: String\(it\.content/.test(panel)) {
  errors.push('前端仍在从 taskpad.items 读 content（taskpad 没有该字段）')
}

// 7) 审计不调模型
if (/LLMClient|import.*\bllm\b\s*$/.test(tagAudit.replace(/from \. import.*/g, ''))) {
  errors.push('tag_audit.py 不得引入 LLM（教师 D2b：纯编程）')
}

console.log(JSON.stringify({
  hasAuditColumn: /🛡 审计 tag/.test(panel),
  hasRowHighlight: /row-audit-bad/.test(panel),
  hasUndo: /undoAudit/.test(panel),
  hasBulkApply: /applyAuditChecked/.test(panel),
  getRouteInDoGet: /elif u\.path == "\/grade\/audit-tags":/.test(getBody),
  errors,
}, null, 1))

if (errors.length) {
  console.error('FAIL d172-tag-audit：' + errors.join('；'))
  process.exit(1)
}
console.log('OK d172-tag-audit：审计列/整行高亮/逐人与批量应用/撤销/GET 路由位置 全部通过')

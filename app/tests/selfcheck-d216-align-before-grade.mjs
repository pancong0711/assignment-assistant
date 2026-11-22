/** D216：批阅前置「程序对齐」——提示词省 token、结果贯通到 UI/报告。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const root = join(appRoot, '..')
const view = fs.readFileSync(join(appRoot, 'src/components/AiGradingPanel.vue'), 'utf8')
const align = fs.readFileSync(join(root, 'engine/src/assist/grading/align.py'), 'utf8')
const prompts = fs.readFileSync(join(root, 'engine/src/assist/grading/prompts.py'), 'utf8')
const rules = fs.readFileSync(join(root, 'engine/src/assist/grading/rules.py'), 'utf8')
const flow = fs.readFileSync(join(root, 'engine/src/assist/grading/flow.py'), 'utf8')
const inputs = fs.readFileSync(join(root, 'engine/src/assist/grading/inputs.py'), 'utf8')
const drafts = fs.readFileSync(join(root, 'engine/src/assist/grading/drafts.py'), 'utf8')
const report = fs.readFileSync(join(root, 'engine/src/assist/grading/report.py'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

// 1) 对齐引擎（纯 Python）
must(/def align_student\(/.test(align), '缺少 align_student')
must(/VERDICT_MATCH/.test(align) && /VERDICT_MISMATCH/.test(align), '缺少三态常量')
must(/TA\.best_assignment\(/.test(align), '未复用审计匹配器')
must(/questionMap/.test(align), '未输出逐题 kb 映射')
must(/仅警告|仍出分|建议核对 tag/.test(align), 'mismatch 未体现“仅警告仍出分”')

// 2) 阈值并入 tagAudit
must(/coverageMin/.test(rules) && /worksheetMarginMin/.test(rules), '阈值未进 rules')
must(/alignMinChars/.test(rules), '缺少对齐题干最小长度')
must(/"coverageMin": \(0, 1\)/.test(rules), '阈值未进数值校验白名单')

// 3) 提示词：match 省 token
must(/align: "dict \| None" = None/.test(prompts), 'build_grade_prompt 未接收 align')
must(/题目已由程序核对/.test(prompts), 'match 未使用短句')
must(/程序对齐提示/.test(prompts), 'mismatch/unknown 未加对齐提示')

// 4) 流程接入
must(/align_student\(/.test(flow), 'flow 未做前置对齐')
must(/align=align/.test(flow), 'evaluate_student 未接收 align')
must(/"papers": papers/.test(inputs), 'plan 未携带 papers')
must(/def papers_for_plan\(/.test(inputs), '缺少 papers_for_plan 兜底')

// 5) 可见性
must(/ai_set\[_k\] = ev\[_k\]/.test(drafts) || /"align"/.test(drafts), '草稿未保存 align')
must(/题目存在差异/.test(report), '草稿版报告未渲染对齐提示')
must(/评分依据/.test(report), '草稿版报告未渲染评分依据')
must(/alignCell/.test(view), '逐生审核缺 alignCell')
must(/🧭 题目匹配/.test(view), '逐生审核缺「题目匹配」列')
must(/疑似错卷/.test(view), '未显示疑似错卷')

must(/selfcheck:d216/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d216')
must(!!pkg.scripts?.['selfcheck:d216'], 'package.json 缺少 selfcheck:d216')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 程序对齐（纯 Python，复用审计匹配器，三态 + 逐题 kb）')
console.log('✓ match 时提示词改用短句（省 token）；mismatch 仅警告仍出分')
console.log('✓ 阈值并入 tagAudit 且进校验白名单')
console.log('✓ plan/evaluation/草稿/报告/逐生审核表贯通')
console.log('✓ D216 selfcheck 已接入 npm run selfcheck')

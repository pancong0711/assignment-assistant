/** D130-P1c 自检：评阅规则卡可读写 + 逐生审核「报告」页 + 表/弹窗同源（T12）。
 *  运行：node tests/selfcheck-d130-rule-cards.mjs */
import assert from 'node:assert'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const read = (rel) => readFileSync(resolve(appDir, rel), 'utf-8')
const engine = (rel) => readFileSync(resolve(appDir, '..', 'engine/src/assist', rel), 'utf-8')

/* 1) 引擎：规则文件 + 三种开放级别 + 校验 + journal */
{
  const r = engine('grading/rules.py')
  assert.ok(/def read_rules/.test(r) && /def write_rules/.test(r), '规则读写')
  assert.ok(/def validate_rules/.test(r), '规则范围校验')
  assert.ok(/def diff_rules/.test(r) && /journal/.test(r), '改动应记 journal')
  assert.ok(/def reset_rules/.test(r), '应支持恢复默认')
  for (const k of ['problems', 'qa', 'copy', 'distinguish', 'innovation', 'translation', 'summary']) {
    assert.ok(new RegExp(`"${k}":`).test(r), `默认规则应含题型 ${k}`)
  }
  // 三种评阅范式齐备（T3 分派）
  for (const m of ['errorCount', 'missingPoints', 'checklist', 'lengthBased']) {
    assert.ok(r.includes(`"${m}"`), `应支持计分模式 ${m}`)
  }
}

/* 2) serve：规则读写接口 + 报告 HTML 预览接口 */
{
  const srv = engine('serve.py')
  assert.ok(/\/rules\/save/.test(srv), '应有规则保存接口')
  assert.ok(/\/rules\/reset/.test(srv), '应有规则恢复默认接口')
  assert.ok(/\/grade\/report\//.test(srv), '应有报告 HTML 预览接口')
  // 报告预览是纯本地产物，**不得**挂在 /xxt/ 分支下（否则学习通模块不可用时被 503）
  assert.ok(!/\/xxt\/grade\/report\//.test(srv), '报告预览接口不应放在 /xxt/ 下')
  // 报告接口必须限定在 reports 目录之内（防路径穿越）
  assert.ok(/reports/.test(srv) && /resolve\(\)/.test(srv), '报告接口应做路径校验')
}

/* 3) 前端：规则卡组件 + 报告页 + 表/弹窗同源 */
{
  const panel = read('src/components/AiGradingPanel.vue')
  assert.ok(/function draftOf\(/.test(panel), '表格应统一走 draftOf（T12）')
  assert.ok(/draftOf\(s\)\.ai\?\.score/.test(panel), 'AI 分列走 draftOf')
  const modal = read('src/components/StudentReviewModal.vue')
  assert.ok(/altKeys/.test(modal), '弹窗应按备用键兜底（与表格同源）')
  assert.ok(/props\.drafts\[k\]/.test(modal), '弹窗取数应遍历候选键')
  const card = read('src/components/GradingRulesCard.vue')
  assert.ok(/rules/.test(card) && /恢复默认/.test(card), '规则卡应含恢复默认')
  assert.ok(/pub|只读|🔒/.test(card), '规则卡应明示只读部分')
}

/* 4) 报告页：iframe 复用 reports/<学生>.html */
{
  const modal = read('src/components/StudentReviewModal.vue')
  assert.ok(/iframe/.test(modal), '报告页应用 iframe 预览')
  assert.ok(/reportUrl|xxtGradeReportUrl/.test(modal), '报告页应取引擎报告 HTML')
}

console.log('OK d130-rule-cards：规则卡读写/校验/journal/恢复默认 · 报告HTML预览接口 · 表与弹窗同源（T12）')

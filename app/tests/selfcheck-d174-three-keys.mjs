/** D174 自检：逐生批阅三键语义 = 转写 / 批阅（批语+打分）/ 转写+批阅。
 *
 *  背景（教师第 19 轮反馈）：
 *    逐生审核行内「批阅」似乎只批阅、不打分也不出批语，「完整」名不副实。
 *  定版：
 *    ① 转写      steps=[transcribe]                  只转写，不出批语不打分
 *    ② 批阅      steps=[evaluate]                    出批语+打分（写进草稿），不改转写
 *    ③ 转写+批阅 steps=[transcribe,evaluate]          = ① + ②
 *    全局三键与行内三键**同一套语义**（此前全局「完整批阅」不传 force，
 *    评阅被后端静默跳过 → 实际只转写，D171 已修；本自检锁死文案与映射）。
 *
 *  运行：node tests/selfcheck-d174-three-keys.mjs */
import assert from 'node:assert'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const comp = readFileSync(resolve(appDir, 'src/components/AiGradingPanel.vue'), 'utf-8')
const engineFlow = readFileSync(resolve(appDir, '..', 'engine/src/assist/grading/flow.py'), 'utf-8')

/* 1) 全局三键：文案与 steps 映射 */
assert.ok(/① 仅转录/.test(comp), '应有「① 仅转录」')
assert.ok(/② 批阅/.test(comp), '应有「② 批阅」')
assert.ok(/③ 转写\+批阅/.test(comp), '应有「③ 转写+批阅」')
assert.ok(!/完整批阅/.test(comp), '不应再出现「完整批阅」')
assert.ok(/startAi\(\['transcribe'\]\)/.test(comp), '① 传 steps=[transcribe]')
assert.ok(/startAi\(\['evaluate'\]\)/.test(comp), '② 传 steps=[evaluate]')
assert.ok(/startAi\(\['transcribe', 'evaluate'\]\)/.test(comp), '③ 传 steps=[transcribe,evaluate]')
assert.ok(/批语 \+ 打分/.test(comp), '② 的 tooltip 必须写明"出批语 + 打分"')

/* 2) 逐生行内三键：同一套文案（不再叫「完整」） */
const row = comp.slice(comp.indexOf("runOne(s, 'transcribe')"))
assert.ok(/@click="runOne\(s, 'evaluate'\)">批阅</.test(row), '行内「批阅」')
assert.ok(/@click="runOne\(s, 'full'\)"[\s\S]{0,120}转写\+批阅/.test(row),
  '行内第三个键应叫「转写+批阅」（此前叫「完整」名不副实）')
assert.ok(!/rowBusy === s\.name \? '…' : '完整'/.test(comp), '行内不应再有「完整」')
assert.ok(/mode === 'full' \? \['transcribe', 'evaluate'\]/.test(comp),
  '行内 full = 转写+批阅')
assert.ok(/force: true/.test(comp.slice(comp.indexOf('async function runOne'),
  comp.indexOf('async function pollJob'))), '逐生补批应强制重跑（否则结果没变）')

/* 3) 引擎：评阅步即"出批语+打分"（结果落草稿）；「已有结果则跳过」必须可由 force 覆盖 */
assert.ok(/evaluate_student\(/.test(engineFlow), '评阅步应调用 evaluate_student')
assert.ok(/if _ev\.is_file\(\) and not ctx\.get\("force"\)/.test(engineFlow),
  '评阅默认跳过已有结果，force 可覆盖')
assert.ok(/_persist_evaluations_to_drafts/.test(engineFlow),
  '评阅结果必须落草稿（审核才看得到批语+分数）')

console.log('OK d174-three-keys：转写 / 批阅(批语+打分) / 转写+批阅 · 全局与行内同口径 · 强制重做可覆盖')

/** D175c 自检：分数输入必须是"可解析的字符串"，保存不得静默失败。
 *
 *  教师反馈（第 22 轮）：改了最终分数后点「保存（批语+分数一起）」没反应，
 *  界面仍提示"有未保存改动"。
 *
 *  真实原因（浏览器实测）：`<input type="number" v-model="finalScore">` 在 Vue3 会
 *  把值转成 **number**，而 save()/buildPayload() 里调用 `finalScore.value.trim()`
 *  → TypeError: finalScore.value.trim is not a function
 *  → 异常冒泡，请求根本没发出，dirty 仍为 true，故"点了没反应"。
 *
 *  运行：node tests/selfcheck-d175c-score-input.mjs */
import assert from 'node:assert'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const src = readFileSync(resolve(appDir, 'src/components/StudentReviewModal.vue'), 'utf-8')
// 去掉注释后再做"不得出现"类断言（注释里会引用旧代码作说明）
const code = src.replace(/\/\*[\s\S]*?\*\//g, '').split('\n').filter((l) => !/^\s*\/\//.test(l)).join('\n')

/* 1) 分数输入不得用 v-model（会自动转 number） */
assert.ok(!/v-model="finalScore"/.test(code),
  '分数输入不得用 v-model="finalScore"（type=number 会自动转 number）')
assert.ok(/:value="finalScore"/.test(code) && /onScoreInput/.test(code),
  '分数输入应显式绑定字符串 + onScoreInput')

/* 2) 不得对 finalScore 直接调字符串方法 */
assert.ok(!/finalScore\.value\.trim\(\)/.test(code),
  '不得直接 finalScore.value.trim()（值可能是 number）')

/* 3) 统一解析入口 */
assert.ok(/function parseScore\(\)/.test(code), '应有 parseScore() 统一解析分数')
assert.ok(/function rawScore\(\)/.test(code), '应有 rawScore() 统一取原始字符串')
assert.ok(/const n = parseScore\(\)/.test(code), 'save/buildPayload 应使用 parseScore()')
assert.ok(/const scoreOk = n !== null && Number\.isFinite\(n\) \? n : null/.test(code),
  'buildPayload 应由 parseScore 得到 scoreOk')

/* 4) 保存/预览必须有异常兜底：任何错误都要有可见反馈，不能静默 */
const saveBlock = code.slice(code.indexOf('async function save()'), code.indexOf('async function saveRevisionOnly'))
assert.ok(/catch \(e\)/.test(saveBlock) && /保存失败：/.test(saveBlock),
  'save() 必须有 catch 并把错误写进 msg（否则按钮"点了没反应"）')
const prevBlock = code.slice(code.indexOf('async function doPreview()'), code.indexOf('async function save()'))
assert.ok(/catch \(e\)/.test(prevBlock) && /预览失败：/.test(prevBlock),
  'doPreview() 也必须有 catch')

/* 5) 保持原有能力：批语仍写 revision，分数仍写 human.score */
assert.ok(/payload\.revision = \{ text: finalComment\.value \}/.test(code),
  '改批语仍写 revision.text')
assert.ok(/payload\.human = \{ score: scoreOk/.test(code),
  '分数仍写 human.score')

console.log('OK d175c-score-input：分数按字符串解析 · 改分后保存可用 · 异常有可见反馈')

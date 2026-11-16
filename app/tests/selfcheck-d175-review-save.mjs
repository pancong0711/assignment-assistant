/** D175 自检：逐生审核「改批语 + 改分数」必须一次保存、且看到的就是会发出去的。
 *
 *  教师反馈：
 *    修改 AI 批语另存后，再改分数点保存没有变化；没有一个"把改过的批语 + 新分数
 *    一起作为作业批语"的键。设计定版见 docs/118-D175。
 *
 *  运行：node tests/selfcheck-d175-review-save.mjs */
import assert from 'node:assert'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const read = (rel) => readFileSync(resolve(appDir, rel), 'utf-8')
const engine = (rel) => readFileSync(resolve(appDir, '..', 'engine/src/assist', rel), 'utf-8')
const strip = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '')

const modal = read('src/components/StudentReviewModal.vue')
const panel = read('src/components/AiGradingPanel.vue')
const xxetong = read('src/views/XxetongView.vue')
const client = read('src/lib/engineClient.ts')
const modalCode = strip(modal)

/* 1) 一个键：保存 = 批语 + 分数一起写 */
assert.ok(/保存（批语 \+ 分数一起）/.test(modal), '应有「保存（批语 + 分数一起）」主键')
assert.ok(/function buildPayload/.test(modalCode), '保存与预览必须共用 buildPayload（看到的就是发出的）')
assert.ok(/payload\.human = \{ score: scoreOk/.test(modalCode),
  'humanMode=none 时**也必须**写分数（此前被丢弃 → 点保存没变化）')
assert.ok(!/if \(humanMode\.value !== 'none'\) \{\s*payload\.human/.test(modalCode),
  '不得再有"mode=none 就不写 human"的旧逻辑')

/* 2) 改 AI 批语 → 写 revision（报告按行标红），不是另存到看不见的地方 */
assert.ok(/payload\.revision = \{ text: finalComment\.value \}/.test(modalCode),
  '修改后的批语应写 revision.text')
assert.ok(/在 AI 批语基础上修改/.test(modal), '应有「在 AI 批语基础上修改」入口')
assert.ok(/完全替代 AI/.test(modal) && /setCommentMode/.test(modalCode),
  '应有「完全替代 AI（纯人工）」模式')
assert.ok(/追加到 AI 之后/.test(modal) && /commentMode === 'append'/.test(modalCode),
  '应保留「追加到 AI 之后」模式（D175b）')
assert.ok(/修订 AI（标红改动）/.test(modal), '默认应为「修订 AI（标红改动）」')

/* 3) 保存前可预览最终报告，且预览走引擎统一函数 */
assert.ok(/previewXxtGradeDraft/.test(client), '客户端应有 previewXxtGradeDraft')
assert.ok(/预览将发出的报告/.test(modal), '应有「预览将发出的报告」键')
assert.ok(/u\.path == "\/xxt\/grade\/draft\/preview"/.test(engine('serve.py')), '引擎应有预览端点')
assert.ok(/build_draft_report/.test(engine('grading/drafts.py')), '预览与批量生成共用 build_draft_report')

/* 4) watcher 只在切学生时回填（不再靠 justSaved 旗标整段 return） */
assert.ok(!/if \(justSaved\) return/.test(modalCode), '应删除 justSaved 旗标式回填')
assert.ok(/watch\(idx, \(\) => \{ fillFromDraft\(\) \}/.test(modalCode), '切学生才整表回填')
assert.ok(/if \(dirty\.value\) return/.test(modalCode), '有未保存改动时不得被旧草稿覆盖')

/* 5) 列表显示生效分（人工改分可见） */
assert.ok(/function finalScoreOf/.test(panel), '列表应有 finalScoreOf（生效分）')
assert.ok(/scoreOverridden\(s\)/.test(panel), '应标出"人工改过分"')

/* 6) 旧预览页写人工套，不再写顶层旧字段 */
assert.ok(/human_mode: 'replace'/.test(xxetong) && /human: \{ score:/.test(xxetong),
  'XxetongView 保存应写双套人工结构')
assert.ok(!/score: Number\.isFinite\(scoreNum as number\) \? \(scoreNum as number\) : null,\n\s*comment: gradeComment\.value, images: gradeImages\.value/
  .test(strip(xxetong)), '不得再写旧单套顶层 score/comment')

console.log('OK d175-review-save：批语+分数一键保存 · 改批语写修订版 · 预览=最终报告 · 列表显示生效分')

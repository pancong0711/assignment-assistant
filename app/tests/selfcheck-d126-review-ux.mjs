/** D126 自检：逐生审核显示原图/转写/批语；分步文案；报告两部分。
 *
 *  用户反馈：
 *  1. 点「仅转录」仍提示「AI 批阅」；
 *  2. 逐生审核看不到该生作答原图、转写、批阅内容；
 *  3. 报告应包含「转写」与「批阅」两部分（发学生学习对照）。
 *
 *  运行：node tests/selfcheck-d126-review-ux.mjs */
import assert from 'node:assert'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const read = (rel) => readFileSync(resolve(appDir, rel), 'utf-8')
const engine = (rel) => readFileSync(resolve(appDir, '..', 'engine/src/assist', rel), 'utf-8')
const stripComments = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '')
  .split('\n').filter((l) => !/^\s*\/\//.test(l)).join('\n')

/* 1) 文案按 steps 动态（不再写死「AI 批阅」） */
{
  const comp = stripComments(read('src/components/AiGradingPanel.vue'))
  assert.ok(/const jobName = onlyTranscribe \? 'AI 转写'/.test(comp), '应按 steps 生成任务名')
  assert.ok(/`\$\{jobName\}中：/.test(comp), '进行中文案应使用 jobName')
  assert.ok(!/progress\.value = `AI 批阅中：/.test(comp), '不得再写死「AI 批阅中」')
}

/* 2) 逐生审核：作答原图来自 students[].images；含 AI 转写区 */
{
  const modal = stripComments(read('src/components/StudentReviewModal.vue'))
  assert.ok(/cur\.value\?\.images/.test(modal), 'answerImages 应优先用 students[].images')
  assert.ok(/AI 转写/.test(modal), '弹窗应有「AI 转写」区')
  assert.ok(/transcriptText/.test(modal), '应渲染转写内容')
  assert.ok(/images\?: string\[\]/.test(modal), 'props.students 应带 images')

  const comp = stripComments(read('src/components/AiGradingPanel.vue'))
  assert.ok(/images: Array\.isArray\(s\.images\)/.test(comp), 'loadStudents 应保留 images')

  // 后端补齐作答图文件名
  const serve = engine('serve.py')
  assert.ok(/把「作答原件文件名」合并进学生清单/.test(serve) || /补充作答图文件名失败/.test(serve),
    'serve 应把作答图文件名补进学生清单')
}

/* 3) 报告：一、AI 转写 → 二、AI 批阅 */
{
  const rep = engine('grading/report.py')
  assert.ok(/## 一、AI 转写/.test(rep), '报告应有「一、AI 转写」')
  assert.ok(/## 二、AI 批阅/.test(rep), '报告应有「二、AI 批阅」')
  assert.ok(rep.indexOf('## 一、AI 转写') < rep.indexOf('## 二、AI 批阅'), '转写应在批阅之前')
  assert.ok(/识别偏差/.test(rep), '应说明转写仅供对照原图')
}

/* 4) 仅转录也写草稿（否则逐生审核看不到转写） */
{
  const flow = stripComments(engine('grading/flow.py'))
  assert.ok(/save_transcripts_to_drafts/.test(flow), '转录后应写草稿 ai.transcript')
  const dr = engine('grading/drafts.py')
  assert.ok(/def save_transcripts_to_drafts/.test(dr), '应有 save_transcripts_to_drafts')
}

console.log('OK d126-review-ux：分步文案 · 作答原图 · AI 转写区 · 报告(转写→批阅) · 仅转录也写草稿')

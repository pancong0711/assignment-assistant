/** D127 自检：作业包中心流水线 + 结构化报告 + 按钮组语义。
 *  运行：node tests/selfcheck-d127-pack-pipeline.mjs */
import assert from 'node:assert'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const read = (rel) => readFileSync(resolve(appDir, rel), 'utf-8')
const engine = (rel) => readFileSync(resolve(appDir, '..', 'engine/src/assist', rel), 'utf-8')
const strip = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '')
  .split('\n').filter((l) => !/^\s*\/\//.test(l)).join('\n')

/* 1) 包上下文是唯一取题入口（整班预览不得再用全库作业纸） */
{
  const pk = engine('paper/pack.py')
  assert.ok(/def pack_context/.test(pk), '应有 pack_context')
  assert.ok(/def pick_pad_for_tag/.test(pk), '应有 pick_pad_for_tag')
  assert.ok(/def tags_without_pad/.test(pk), '应有前置预警 tags_without_pad')
  const ins = engine('grading/inputs.py')
  assert.ok(/pack_ctx/.test(ins), 'build_plan 应支持作业包上下文')
}

/* 2) 批阅目录以包 id 为准 */
{
  const flow = engine('grading/flow.py')
  assert.ok(/def grading_key/.test(flow), '应有 grading_key')
  assert.ok(/task\.get\("pack_id"\)/.test(flow), '目录名应优先 pack_id')
  assert.ok(/"report"/.test(flow) && /x for x in steps if str\(x\) != "report"/.test(flow),
    '默认步骤不应含 report（历史 report 应被忽略）')
}

/* 3) 转写结构化：题目/作答分开 + 示意图只做描述 */
{
  const pr = engine('grading/prompts.py')
  assert.ok(/printed_question/.test(pr) && /"diagrams"/.test(pr), '转写应输出 items/题目/示意图')
  assert.ok(/禁止 ASCII|不要画图|禁止 SVG/.test(pr), '转写应禁止画图，只做语义描述')
  const tr = engine('grading/transcribe.py')
  assert.ok(/def transcript_to_markdown/.test(tr), '应有 transcript_to_markdown 渲染器')
  assert.ok(/TRANS_VERSION = 2/.test(tr), '转写结构版本应为 2')
}

/* 4) 评阅：先判题目再评阅；无题目不得让模型自己猜 */
{
  const pr = engine('grading/prompts.py')
  assert.ok(/请你先自行判断题目/.test(pr) === false, '旧的"自己猜题目"兜底必须删除')
  assert.ok(/先判断题目是否对应/.test(pr), '评阅 prompt 应先判断题目')
  const ev = engine('grading/evaluate.py')
  assert.ok(/question_match/.test(ev))
  // 只禁止"把它写进 deductions"（文档字符串里说明来历是允许的）
  assert.ok(!/deductions"\]\s*\+?=[\s\S]{0,80}顶替嫌疑/.test(ev)
            && !/f"顶替嫌疑/.test(ev),
    '不得再把"顶替嫌疑"写进学生报告扣分项')
}

/* 5) 报告：先列正确题目；三态产出不同 */
{
  const rep = engine('grading/report.py')
  assert.ok(/_correct_questions_md/.test(rep), '报告应先列作业纸正确题目')
  assert.ok(/教师补充批语/.test(rep), 'append 应有教师补充批语段')
  assert.ok(/hm in \("replace", "human"\)/.test(rep), 'replace 应为纯人工报告')
}

/* 6) PWA：按钮组与逐生审核三键 */
{
  const comp = strip(read('src/components/AiGradingPanel.vue'))
  assert.ok(!/③ 转录\+评阅/.test(comp), '语义重叠的「转录+评阅」应移除')
  assert.ok(/📄 一键生成批阅报告/.test(comp), '报告的独立入口应保留在逐生审核下方')
  assert.ok(/allowPartial/.test(comp), '部分失败仍继续的入口应保留')
  const modal = strip(read('src/components/StudentReviewModal.vue'))
  assert.ok(/人工替代 AI/.test(modal) && /追加到 AI 之后/.test(modal) && /仅 AI/.test(modal),
    '逐生审核应有 仅AI / 替代 / 追加 三键')
}

/* 7) 测试配置：失败也要能看到原因（不再是裸 HTTP 400） */
{
  const srv = engine('serve.py')
  assert.ok(!/200 if ok else 400/.test(srv), '/llm/test 不应再用 HTTP 400 表达业务失败')
  assert.ok(/_llm_test_summary/.test(srv), '应返回可读失败摘要')
  const cli = read('src/lib/engineClient.ts')
  assert.ok(/o\?\.results/.test(cli), '前端应保留 results/error 而不是丢掉')
}

console.log('OK d127-pack-pipeline：包内取题 · 目录按包 · 转写结构化 · 先判题目 · 报告组装 · 三态批语 · 测试可诊断')

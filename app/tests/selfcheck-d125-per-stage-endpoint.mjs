/** D125 自检：转录不得使用评阅段的 base_url/key + 分步批阅。
 *
 *  背景 bug：`_settings_from_workspace` 只把「转录段的模型名」搬进旧字段，
 *  base_url/api_key 仍取 stage_endpoint(默认 evaluation) 那套 →
 *  qwen 模型被发往 opencode 端点 → Playground 能通、批阅报 Model is unavailable。
 *
 *  运行：node tests/selfcheck-d125-per-stage-endpoint.mjs */
import assert from 'node:assert'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const read = (rel) => readFileSync(resolve(appDir, rel), 'utf-8')
const engine = (rel) => readFileSync(resolve(appDir, '..', 'engine/src/assist', rel), 'utf-8')
const stripComments = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '')
  .split('\n').filter((l) => !/^\s*\/\//.test(l)).join('\n')

/* 1) 引擎：两段各返回完整 endpoint；_step_base_key 只读对应那一套 */
{
  const llm = stripComments(engine('grading/llm.py'))
  assert.ok(/"transcription": eps\["transcription"\]/.test(llm),
    '_settings_from_workspace 应返回转录段完整 endpoint')
  assert.ok(/"evaluation": eps\["evaluation"\]/.test(llm),
    '_settings_from_workspace 应返回评阅段完整 endpoint')
  assert.ok(/def _step_endpoint/.test(llm), '应有 _step_endpoint')
  // _step_base_key 必须走 _step_endpoint（而不是直接读 self.base_url）
  assert.ok(/_step_base_key[\s\S]{0,200}ep = self\._step_endpoint\(step\)/.test(llm),
    '_step_base_key 应基于 _step_endpoint')
}

/* 2) 确定性错误不重试 + 报错带定位信息 */
{
  const llm = stripComments(engine('grading/llm.py'))
  assert.ok(/Model is unavailable/.test(llm), '应识别 Model is unavailable')
  assert.ok(/in \(400, 401, 403, 404\)/.test(llm), '400/401/403/404 应不重试')
  assert.ok(/step=\{step or/.test(llm) && /base_url=\{base_url\}/.test(llm) && /model=\{/.test(llm),
    '报错应包含 step/provider/base_url/model')
}

/* 3) 分步批阅：CLI --steps + serve 透传 + 转录部分失败默认中止 */
{
  const cliPy = readFileSync(resolve(appDir, '..', 'engine/src/assist/cli.py'), 'utf-8')
  assert.ok(/--steps/.test(cliPy), 'CLI 应有 --steps')
  assert.ok(/--allow-partial/.test(cliPy), 'CLI 应有 --allow-partial')
  assert.ok(/assist\.cli|llm\.command\("test"\)/.test(cliPy) || /command\("test"\)/.test(cliPy),
    'CLI 应有 llm test')
  const serve = engine('serve.py')
  assert.ok(/u\.path == "\/llm\/test"/.test(serve), 'serve 应有 /llm/test')
  assert.ok(/--steps/.test(serve) && /--allow-partial/.test(serve), 'serve 应透传 steps/allowPartial')
  const flow = stripComments(engine('grading/flow.py'))
  assert.ok(/allow_partial/.test(flow) && /转录有 .*名学生失败/.test(flow),
    '转录部分失败应默认中止')
}

/* 4) PWA：4 个按钮 + 测试配置 */
{
  const comp = read('src/components/AiGradingPanel.vue')
  assert.ok(/🔍 测试配置/.test(comp), '应有「测试配置」按钮')
  assert.ok(/① 仅转录/.test(comp) && /② 仅评阅/.test(comp) && /③ 转录\+评阅/.test(comp),
    '应有分步按钮')
  assert.ok(/startAi\(\['transcribe'\]\)/.test(comp), '仅转录应传 steps=[transcribe]')
  assert.ok(/startAi\(\['evaluate'\]\)/.test(comp), '仅评阅应传 steps=[evaluate]')
  assert.ok(/testLlmStages/.test(comp), '应调用 testLlmStages')
  const ec = stripComments(read('src/lib/engineClient.ts'))
  assert.ok(/export async function testLlmStages/.test(ec), 'engineClient 应有 testLlmStages')
  assert.ok(/steps\?: string\[\]/.test(ec), 'startXxtGradeAi 应支持 steps')
}

console.log('OK d125-per-stage-endpoint：两段 endpoint 分离 · 确定性错误不重试 · 报错带定位 · '
  + '分步批阅(测试/仅转录/仅评阅/转录+评阅) · 转录部分失败默认中止')

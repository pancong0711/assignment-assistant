/** D127-FIX 自检：测试配置可诊断 + 批阅作用域键前后端一致。
 *  运行：node tests/selfcheck-d128-scope-contract.mjs */
import assert from 'node:assert'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const read = (rel) => readFileSync(resolve(appDir, rel), 'utf-8')
const engine = (rel) => readFileSync(resolve(appDir, '..', 'engine/src/assist', rel), 'utf-8')

/* 1) 测试配置：探针图必须够大（阿里云要求宽高 >10，8×8 会被 400） */
{
  const srv = engine('serve.py')
  assert.ok(!/_Im\.new\("RGB",\s*\(8,\s*8\)/.test(srv), '不得再用 8×8 探针图')
  const m = srv.match(/_Im\.new\("RGB",\s*\((\d+),\s*(\d+)\)/)
  assert.ok(m && Number(m[1]) >= 64 && Number(m[2]) >= 64, '探针图应 ≥64×64')
  assert.ok(/def _llm_error_kind/.test(srv), '应区分 config / request 错误')
  assert.ok(/errorKind/.test(srv), '结果里应带 errorKind')
}

/* 2) 作用域键：引擎写入目录必须与前端读取同口径 */
{
  const flow = engine('grading/flow.py')
  assert.ok(/def grading_scope_id/.test(flow), '应有 grading_scope_id')
  assert.ok(/_plan_pack/.test(flow) && /task\["pack_id"\] = _plan_pack/.test(flow),
    'plan.packId 应注入 task.pack_id（否则目录落到 padId）')
  assert.ok(/task_id=grading_scope_id\(task, plan\)/.test(flow),
    '写草稿必须用作用域键')
  const gs = engine('xxt/grade_store.py')
  assert.ok(/alt_task_ids/.test(gs), '读草稿应支持兼容目录键回落')
  const srv = engine('serve.py')
  assert.ok(/altTaskId/.test(srv), 'serve 应接受 altTaskId')
  assert.ok(/payload\.get\("packId"\)/.test(srv), 'serve 应以 payload.packId 为作用域键')
}

/* 3) PWA：启动批阅传 packId；读草稿 taskId 用 packId 优先 */
{
  const comp = read('src/components/AiGradingPanel.vue')
  assert.ok(/packId: packId\.value/.test(comp), '启动批阅应显式传 packId')
  assert.ok(/taskId: packId\.value \|\| padId\.value/.test(comp),
    '读草稿应以 packId 优先（与写入同口径）')
  assert.ok(/altTaskId/.test(comp), '应传兼容读取键')
  const cli = read('src/lib/engineClient.ts')
  assert.ok(/packId\?: string/.test(cli), 'engineClient 请求体应支持 packId')
  assert.ok(/altTaskId\?: string/.test(cli), '草稿查询应支持 altTaskId')
}

/* 4) 空态提示覆盖"目录口径不一致"这一种 */
{
  const modal = read('src/components/StudentReviewModal.vue')
  assert.ok(/目录口径不一致/.test(modal), '空态提示应包含目录口径排查线索')
}

console.log('OK d128-scope-contract：探针图≥64px · config/request 错误可区分 · 作用域键前后端一致 · 旧目录可回落 · 空态可诊断')

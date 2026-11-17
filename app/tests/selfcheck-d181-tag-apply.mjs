/** D181 前端自检：tag 审计 apply / preview 作用域 / 错误可见性。
 *
 * 直接跑：node --experimental-strip-types tests/selfcheck-d181-tag-apply.mjs
 */
import fs from 'node:fs'
import http from 'node:http'
import { applyTagAudit, fetchXxtReviewStudents } from '../src/lib/engineClient.ts'

const PANEL_SRC = new URL('../src/components/AiGradingPanel.vue', import.meta.url)
const panelText = fs.readFileSync(PANEL_SRC, 'utf-8')

function listen(handler) {
  return new Promise((resolve) => {
    const srv = http.createServer(handler)
    srv.listen(0, '127.0.0.1', () => {
      const port = srv.address().port
      resolve({ base: `http://127.0.0.1:${port}`, srv })
    })
  })
}

function ok(msg) { console.log(`✓ ${msg}`) }
function fail(msg) { console.error(`✗ ${msg}`); process.exitCode = 1 }

async function testApplyReturnsOkFalseOn400() {
  const { base, srv } = await listen((req, res) => {
    let body = ''
    req.on('data', (c) => (body += c))
    req.on('end', () => {
      res.writeHead(400, { 'Content-Type': 'application/json; charset=utf-8' })
      res.end(JSON.stringify({ ok: false, error: '该作业包没有 roster-tags 快照' }))
    })
  })
  try {
    const r = await applyTagAudit(base, '', {
      classDir: 'classes/SynthC1', packId: 'pack-d181',
      changes: [{ name: '学生甲', tag: 'translation' }],
    })
    if (r.ok === false && /快照/.test(r.error || '')) {
      ok('applyTagAudit 在 400 + ok:false 时把错误透传出来')
    } else {
      fail(`applyTagAudit 未正确透传错误：${JSON.stringify(r)}`)
    }
  } finally {
    srv.close()
  }
}

async function testPreviewScopeQuery() {
  let gotPath = ''
  const { base, srv } = await listen((req, res) => {
    gotPath = req.url
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' })
    res.end(JSON.stringify({ ok: true, students: [{ name: '学生甲', tag: 'translation' }] }))
  })
  try {
    await fetchXxtReviewStudents(base, '', 'cid1', 'wid1', undefined, {
      taskId: 'pack-d181', altTaskId: 'padA,padB', classDir: 'classes/SynthC1',
    })
    const u = new URL(gotPath, base)
    const checks = [
      u.searchParams.get('taskId') === 'pack-d181',
      u.searchParams.get('altTaskId') === 'padA,padB',
      u.searchParams.get('classDir') === 'classes/SynthC1',
    ]
    if (checks.every(Boolean)) {
      ok('fetchXxtReviewStudents 把 taskId/altTaskId/classDir 正确拼进查询串')
    } else {
      fail(`查询串不正确：${gotPath}`)
    }
  } finally {
    srv.close()
  }
}

function testComponentStaticAssertions() {
  const checks = [
    [panelText.includes('packId.value || padId.value || resolvedScope.value'),
     'applyAuditChanges 使用 resolvedScope 兜底作用域'],
    [/if\s*\(\s*!pid\s*\)\s*\{\s*auditMsg\.value\s*=/.test(panelText),
     '缺少作用域时设置 auditMsg 可见错误'],
    [/if\s*\(\s*!curWorkDir\.value\s*\)\s*\{\s*auditMsg\.value\s*=/.test(panelText),
     '缺少班级目录时设置 auditMsg 可见错误'],
    [!/if\s*\(\s*!w\s*\|\|\s*!pid\s*\)\s*return/.test(panelText),
     '已移除静默 return 的旧写法'],
  ]
  for (const [cond, msg] of checks) {
    if (cond) ok(msg); else fail(msg)
  }
}

async function main() {
  testComponentStaticAssertions()
  await testApplyReturnsOkFalseOn400()
  await testPreviewScopeQuery()
  if (!process.exitCode) console.log('D181 前端自检通过')
}

main().catch((e) => { console.error(e); process.exitCode = 1 })

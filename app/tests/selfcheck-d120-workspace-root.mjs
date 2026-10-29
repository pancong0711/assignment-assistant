/** D120 自检：workspace 根语义收口 + roster/作业纸自动落盘。
 *
 *  背景 bug：`getKbDirHandle()` 被两处按不同语义使用（一处当 workspace 根、一处当 kb 根），
 *  而 UI 文案是「连接本地题库目录」→ 教师选 kb/，roster 被写进 <ws>/kb/classes/
 *  → 引擎读 <ws>/<class_dir>/roster/ 读不到 → AI 批阅报「名单 0 人」。
 *
 *  运行：node tests/selfcheck-d120-workspace-root.mjs */
import assert from 'node:assert'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const read = (rel) => readFileSync(resolve(appDir, rel), 'utf-8')
const stripComments = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '')
  .split('\n').filter((l) => !/^\s*\/\//.test(l)).join('\n')

/* 1) 选目录时必须校验 workspace 根（含 kb/），否则拒绝 */
{
  const kb = stripComments(read('src/stores/kb.ts'))
  assert.ok(/dirHasSubdir\(dir, 'kb'\)/.test(kb), 'connectWorkspaceDir 应校验 kb/ 子目录')
  assert.ok(/不是 workspace 根/.test(kb), '应给出可读错误（不是 workspace 根）')
  assert.ok(/async function dirHasSubdir/.test(kb), '应有 dirHasSubdir 辅助')
}

/* 2) roster 保存即自动落盘（800ms 防抖），不再依赖手动按钮 */
{
  const roster = stripComments(read('src/stores/roster.ts'))
  assert.ok(/scheduleAutoPersistToDisk\(\)/.test(roster), 'persist() 应触发自动落盘')
  assert.ok(/\}, 800\)/.test(roster), '防抖应为 800ms（D120-Q2）')
  assert.ok(/saveRosterToEngine/.test(roster), '应通过引擎写盘（路径由后端决定）')
  assert.ok(/classDirOfRoster/.test(roster), '应把班级映射成 classDir')
  assert.ok(/persistMsg/.test(roster), '写盘结果应可被 UI 展示（不静默失败）')
}

/* 3) 作业纸保存时也落盘（消除"包在纸没"的悬空引用） */
{
  const pad = stripComments(read('src/stores/taskpad.ts'))
  assert.ok(/persistTaskpadToDisk/.test(pad), 'saveToLibrary 应落盘作业纸')
  assert.ok(/saveTaskpadToEngine/.test(pad), '应调用 /taskpad/save')
}

/* 4) 体检支持通用一键修复（fix.type === 'api'） */
{
  const sv = read('src/views/SettingsView.vue')
  assert.ok(/fix\?\.type === 'api'/.test(sv), 'SettingsView 应渲染 api 型修复按钮')
  const st = stripComments(read('src/stores/settings.ts'))
  assert.ok(/async runFixApi/.test(st), 'settings 应有 runFixApi（先演练再确认）')
  assert.ok(/fixWorkspaceLayout\(this\.engineUrl, this\.engineToken, false\)/.test(st),
    '应先演练（apply=false）')
  assert.ok(/window\.confirm/.test(st), '执行前应二次确认')
}

/* 5) 与引擎路径契约一致（前后端不得各写各的） */
{
  const py = readFileSync(resolve(appDir, '..', 'engine/src/assist/files/roster_io.py'), 'utf-8')
  assert.ok(/roster.*\/.*"roster"/.test(py) || /"roster"$/.test(py) || /\/ "roster"/.test(py),
    '引擎应写 <class_dir>/roster/')
  const layout = readFileSync(resolve(appDir, '..', 'engine/src/assist/workspace_layout.py'), 'utf-8')
  assert.ok(/FORBIDDEN_IN_KB/.test(layout), '应定义 kb/ 下禁止出现的目录')
  assert.ok(/"classes"/.test(layout), 'classes 应在禁止清单中')
}

console.log('OK d120-workspace-root：目录根校验 · roster 自动落盘(800ms) · 作业纸落盘 · '
  + '体检一键修复(演练+确认) · 前后端路径契约')

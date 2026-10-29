/** D124 自检：班级名唯一真源 + class_dir 注入 + 目录命名体检。
 *
 *  两个缺陷：
 *  1) cli 把 class_dir 只给了 plan、没写回 task → grading_dir() 拿到空值直接报错
 *     （用户完成②区关联后仍报 class_dir=''）。
 *  2) 目录名用 students[0].class（点名册原始字段，如 2025-化工25班）而非班级名（化工25）
 *     → classes/ 下出现两套目录。
 *
 *  运行：node tests/selfcheck-d124-classname-source.mjs */
import assert from 'node:assert'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const read = (rel) => readFileSync(resolve(appDir, rel), 'utf-8')
const engine = (rel) => readFileSync(resolve(appDir, '..', 'engine/src/assist', rel), 'utf-8')
const stripComments = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '')
  .split('\n').filter((l) => !/^\s*\/\//.test(l)).join('\n')

/* 1) 三处不得再用 students[0].class 决定目录 */
{
  const roster = stripComments(read('src/stores/roster.ts'))
  assert.ok(!/students\[0\]\?\.class\s*\?\?/.test(roster), 'roster 不得用 students[0].class 决定目录')
  assert.ok(/async saveToDir\(dirHandle: FileSystemDirectoryHandle, className\?: string\)/.test(roster),
    'saveToDir 应显式接收 className')
  assert.ok(/班级名为空/.test(roster), '班级名为空应报错（不造 classA 目录）')

  const scv = stripComments(read('src/views/SheetContentView.vue'))
  assert.ok(!/roster\.students\[0\]\?\.class/.test(scv), 'SheetContentView 不得用 students[0].class')

  const vb = stripComments(read('src/lib/variantBatch.ts'))
  assert.ok(/className = ''/.test(vb), 'buildVariantBatchZip 应接收 className')
  assert.ok(!/const cd = students\[0\]\?\.class \|\| 'classA'/.test(vb), '不得兜底 classA')
}

/* 2) 引擎：class_dir 注入（plan > task） */
{
  const flow = stripComments(engine('grading/flow.py'))
  assert.ok(/plan_class_dir|effective_class_dir/.test(flow), 'run_task 应计算 effective class_dir')
  assert.ok(/effective_class_dir[\s\S]{0,200}task\["class_dir"\] = effective_class_dir/.test(flow),
    'run_task 应把 class_dir 写回 task')
  const cliPy = readFileSync(resolve(appDir, '..', 'engine/src/assist/cli.py'), 'utf-8')
  assert.ok(/kwargs\["class_dir"\] = str\(plan\["classDir"\]\)/.test(cliPy),
    'cli 应显式把 plan.classDir 传给 run_task')
}

/* 3) 班级名落盘 + 体检 */
{
  const rio = engine('files/roster_io.py')
  assert.ok(/"className"/.test(rio), 'roster.json 应记录 className')
  const aud = engine('class_dir_audit.py')
  assert.ok(/def audit/.test(aud) && /def fix/.test(aud), '应有 audit/fix')
  assert.ok(/conflict/.test(aud), '目标已存在应归为 conflict（不自动合并）')
  const serve = engine('serve.py')
  assert.ok(/class_dir_names/.test(serve), 'doctor 应有 class_dir_names 检查项')
  assert.ok(/fix-class-dirs/.test(serve), '应有 /workspace/fix-class-dirs 端点')
}

/* 4) PWA 入口 */
{
  const sv = read('src/views/SettingsView.vue')
  assert.ok(/修正班级目录名/.test(sv), '设置中心应有「修正班级目录名」按钮')
  const st = stripComments(read('src/stores/settings.ts'))
  assert.ok(/async runFixClassDirs/.test(st), 'settings 应有 runFixClassDirs')
  assert.ok(/window\.confirm/.test(st), '执行前应二次确认')
}

console.log('OK d124-classname-source：班级名唯一真源(3处) · class_dir 注入(plan→task) · '
  + 'className 落盘 · 体检+一键修正 · PWA 入口')

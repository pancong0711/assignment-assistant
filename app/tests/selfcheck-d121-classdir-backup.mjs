/** D121 自检：班级目录自动绑定 + 假目录根除 + 一键备份/清理入口。
 *
 *  背景：`class_dir` 解析不到时静默回退 → 造出 `<ws>/classes/grading`、
 *  `<ws>/grading` 两个假目录；体检又把 `grading` 误报成"缺 roster 的班级"。
 *
 *  运行：node tests/selfcheck-d121-classdir-backup.mjs */
import assert from 'node:assert'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const read = (rel) => readFileSync(resolve(appDir, rel), 'utf-8')
const engine = (rel) => readFileSync(resolve(appDir, '..', 'engine/src/assist', rel), 'utf-8')
const stripComments = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '')
  .split('\n').filter((l) => !/^\s*\/\//.test(l)).join('\n')

/* 1) 引擎：解析不到不回退、只认精确匹配自动绑定 */
{
  const py = engine('xxt/classmap.py')
  assert.ok(/def resolve_or_raise/.test(py), '应有 resolve_or_raise')
  assert.ok(/class ClassDirResolutionError/.test(py), '应有可读异常类型')
  assert.ok(/def is_class_dir/.test(py), '应有 is_class_dir')
  assert.ok(/RESERVED_CLASS_DIR_NAMES/.test(py), '应有保留名清单')
  assert.ok(/grading/.test(py) && /roster/.test(py), '保留名应含 grading/roster')
  // 只认"完全相同"才自动绑定
  assert.ok(/want in names/.test(py), '自动绑定应基于归一后完全相同')
  const flow = engine('grading/flow.py')
  assert.ok(/批阅产物目录不合法/.test(flow), 'grading_dir 应拒绝空/裸 classes')
  assert.ok(/relative_to\(root\)/.test(flow), 'grading_dir 应有越界断言')
}

/* 2) 体检不再把 grading 误报为班级 */
{
  const serve = engine('serve.py')
  assert.ok(/RESERVED_CLASS_DIR_NAMES/.test(serve), 'roster_persist 应排除保留名')
}

/* 3) 清理假目录：含真实产物必须拒绝删 */
{
  const j = engine('workspace_junk.py')
  assert.ok(/REAL_ARTIFACT_DIRS/.test(j), '应定义真实产物目录')
  assert.ok(/realArtifactBatches/.test(j), '应按批次判断真实产物')
  assert.ok(/protected/.test(j), '应输出 protected 清单')
}

/* 4) 备份：脱敏 + 不含 .runtime */
{
  const b = engine('backup.py')
  assert.ok(/SECRET_KEYS/.test(b) && /def redact/.test(b), '应递归脱敏')
  assert.ok(/EXCLUDE_DIRS = \("\.runtime"/.test(b), '.runtime/ 必须排除')
  assert.ok(/def verify_no_secrets/.test(b), '应有密钥自检')
}

/* 5) PWA：设置中心有「一键备份」「清理假目录」按钮，且都先演练/确认 */
{
  const sv = read('src/views/SettingsView.vue')
  assert.ok(/一键备份/.test(sv), '设置中心应有一键备份按钮')
  assert.ok(/清理假目录/.test(sv), '设置中心应有清理假目录按钮')
  const st = stripComments(read('src/stores/settings.ts'))
  assert.ok(/async runBackup/.test(st), 'settings 应有 runBackup')
  assert.ok(/async runCleanJunk/.test(st), 'settings 应有 runCleanJunk')
  assert.ok(/cleanWorkspaceJunk\(this\.engineUrl, this\.engineToken, false\)/.test(st),
    '清理应先演练')
  assert.ok(/window\.confirm/.test(st), '清理执行前应二次确认')
  const ec = stripComments(read('src/lib/engineClient.ts'))
  assert.ok(/export function collectBrowserData/.test(ec), '应有浏览器数据收集')
}

/* 6) 备份必须收集**所有** store 的 localStorage 键（漏一个就丢一份数据） */
{
  const { readdirSync } = await import('node:fs')
  const storesDir = resolve(appDir, 'src/stores')
  const realKeys = new Set()
  for (const f of readdirSync(storesDir)) {
    const t = readFileSync(resolve(storesDir, f), 'utf-8')
    for (const m of t.matchAll(/'(assignment-assistant\.[a-z0-9.-]+)'/g)) realKeys.add(m[1])
  }
  const ec2 = read('src/lib/engineClient.ts')
  const block = ec2.slice(ec2.indexOf('export function collectBrowserData'))
  const collected = new Set([...block.matchAll(/'(assignment-assistant\.[a-z0-9.-]+)'/g)].map((m) => m[1]))
  // 瞬时状态（提取任务/当前 run）不必备份；其余都必须收集
  const TRANSIENT = ['assignment-assistant.xxt-extract-job.v1',
    'assignment-assistant.xxt-current-run.v1',
    'assignment-assistant.onboarding.v1']
  const missing = [...realKeys].filter((k) => !collected.has(k) && !TRANSIENT.includes(k))
  assert.deepEqual(missing, [], `备份未覆盖这些键（丢了不可恢复）：${missing.join(', ')}`)
  // 水印/题图素材是教师上传的图片，必须收集
  for (const k of ['assignment-assistant.watermark.assets.v1',
    'assignment-assistant.watermark.styles.v1',
    'assignment-assistant.fig.assets.v1']) {
    assert.ok(collected.has(k), `必须收集 ${k}`)
  }
}

/* 7) D122：迁移默认复制；--move 才删源；清理已迁移源须 sha256 一致 */
{
  const wl = engine('workspace_layout.py')
  assert.ok(/def fix_layout\(ws, \*, apply: bool = False, move: bool = False\)/.test(wl),
    'fix_layout 应支持 move 参数')
  assert.ok(/def clean_migrated/.test(wl), '应有 clean_migrated')
  assert.ok(/_file_sha/.test(wl) && /sha256/.test(wl), '一致性校验应使用 sha256')
  assert.ok(!/shutil\.move/.test(wl), '不应使用 shutil.move（复制成功后才删源更安全）')
  const sv = read('src/views/SettingsView.vue')
  assert.ok(/清理已迁移源/.test(sv), '设置中心应有「清理已迁移源」按钮')
  const st = stripComments(read('src/stores/settings.ts'))
  assert.ok(/async runCleanMigrated/.test(st), 'settings 应有 runCleanMigrated')
  const cliPy = readFileSync(resolve(appDir, '..', 'engine/src/assist/cli.py'), 'utf-8')
  assert.ok(/workspace_grp\.command\("clean-migrated"\)/.test(cliPy), 'CLI 应有 clean-migrated')
  assert.ok(/--move/.test(cliPy), 'CLI fix-layout 应有 --move')
}

console.log('OK d121-classdir-backup：解析不回退/精确自动绑定/保留名排除 · '
  + '假目录保护真实产物 · 备份脱敏不含 .runtime · PWA 一键备份+清理（演练+确认）')

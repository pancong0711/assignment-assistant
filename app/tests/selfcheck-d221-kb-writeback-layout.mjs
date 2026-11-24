/** D221：题库写回路径自动识别（不再写到 kb/kb）+ 写前时间戳备份。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const view = fs.readFileSync(join(appRoot, 'src/views/KbEditorView.vue'), 'utf8')
const store = fs.readFileSync(join(appRoot, 'src/stores/kb.ts'), 'utf8')
const fsAccess = fs.readFileSync(join(appRoot, 'src/lib/fsAccess.ts'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

const L = await import('../src/lib/kbLayout.ts')

// 1) 目录识别：连 workspace 根 → kb/<kind>.xlsx
const wsTarget = L.resolveKbWriteTarget('2609assignment', ['kb', 'classes', 'roster'], 'problems')
must(wsTarget.path === 'kb/problems.xlsx', `workspace 根应写 kb/problems.xlsx，实际 ${wsTarget.path}`)
must(wsTarget.kbDir === 'kb' && wsTarget.mode === 'workspace', 'workspace 根的 kbDir/mode 不对')

// 2) 目录识别：连 kb 目录本身 → <kind>.xlsx（不再多一层）
const kbTarget = L.resolveKbWriteTarget('kb', ['problems.xlsx', 'qa.xlsx'], 'problems')
must(kbTarget.path === 'problems.xlsx', `kb 目录应写 problems.xlsx，实际 ${kbTarget.path}`)
must(kbTarget.kbDir === '' && kbTarget.mode === 'kb-dir', 'kb 目录的 kbDir/mode 不对')

// 2b) 目录名不叫 kb，但根下已有 kind.xlsx → 也按 kb 目录处理
const kbTarget2 = L.resolveKbWriteTarget('my-kb', ['innovation.xlsx'], 'innovation')
must(kbTarget2.path === 'innovation.xlsx', '根下已有 kind.xlsx 时应识别为 kb 目录')

// 2c) 新 workspace 空目录 → 仍按 workspace 根（写 kb/）
const emptyTarget = L.resolveKbWriteTarget('new-ws', [], 'problems')
must(emptyTarget.path === 'kb/problems.xlsx', '空 workspace 应写 kb/problems.xlsx')

// 3) 备份路径与时间戳
const stamp = L.historyStamp(new Date(2026, 10, 23, 9, 5, 7))
must(stamp === '20261123-090507', `时间戳格式不对：${stamp}`)
must(L.historyBackupPath('kb', 'problems', stamp) === 'kb/.history/20261123-090507/problems.xlsx',
  'workspace 场景备份路径不对')
must(L.historyBackupPath('', 'qa', stamp) === '.history/20261123-090507/qa.xlsx',
  'kb 目录场景备份路径不对')

// 4) 嵌套 kb/kb 提示
must(L.nestedKbWarning(true, 'workspace').includes('kb/kb'), '未提示 kb/kb 嵌套')
must(L.nestedKbWarning(false, 'workspace') === '', '无嵌套时不应提示')

// 5) 源码契约：store 用识别结果 + 写前备份；fsAccess 提供列目录
must(/resolveKbWriteTarget\(/.test(store), 'store 未使用路径识别')
must(/historyBackupPath\(/.test(store) && /historyStamp\(/.test(store), 'store 未做写前备份')
must(/readFileInDir\(dirHandle, target\.path\)/.test(store), '未读取旧文件做备份')
must(/listDirEntryNames/.test(fsAccess), 'fsAccess 缺少目录列举')
must(/自动识别/.test(view) || /识别为/.test(view), '界面未说明自动识别')

must(/selfcheck:d221/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d221')
must(!!pkg.scripts?.['selfcheck:d221'], 'package.json 缺少 selfcheck:d221')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 连 workspace 根 → 写 kb/<kind>.xlsx；连 kb 目录 → 写 <kind>.xlsx（不再 kb/kb）')
console.log('✓ 覆盖前旧文件备份到 .history/<时间戳>/<kind>.xlsx')
console.log('✓ 检测到 kb/kb 嵌套时给出提示')
console.log('✓ D221 selfcheck 已接入 npm run selfcheck')

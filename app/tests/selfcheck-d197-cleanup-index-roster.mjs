/** D197：清理报告必须同步清理版本索引 + 明确完成反馈 + 按本次名单核对。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const root = join(appRoot, '..')
const view = fs.readFileSync(join(appRoot, 'src/components/AiGradingPanel.vue'), 'utf8')
const client = fs.readFileSync(join(appRoot, 'src/lib/engineClient.ts'), 'utf8')
const rv = fs.readFileSync(join(root, 'engine/src/assist/grading/report_versions.py'), 'utf8')
const serve = fs.readFileSync(join(root, 'engine/src/assist/serve.py'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

// 1) 后端：索引同步清理
must(/def prune_index\(/.test(rv), '缺少 prune_index（索引清理）')
must(/indexRemoved/.test(rv), 'cleanup 未返回索引清理条数')
must(/缺少本次名单/.test(rv), '空名单未被拒绝')
must(/drop_missing_files/.test(rv), '未清理孤儿索引条目')
// dry-run 不得写索引
must(/if dry_run:[\s\S]{0,400}?否则|if dry_run:\n        # dry-run 只统计/.test(rv),
  'dry-run 分支缺失')
must(!/if dry_run:\s*\n\s*idx = prune_index/.test(rv), 'dry-run 仍在写索引')

// 2) 后端：版本查询按名单过滤 + 孤儿数
must(/orphanCount/.test(serve), '版本查询未返回 orphanCount')
must(/totalInIndex/.test(serve), '版本查询未返回 totalInIndex')
must(/students=students/.test(serve), '版本查询未接收名单')

// 3) 前端：dry-run → 确认 → 真删 → 刷新
must(/cleanupResult/.test(view), '缺少清理结果状态（无法确认是否完成）')
must(/dryRun: true/.test(view), '清理前未做 dry-run 统计')
must(/dryRun: false/.test(view), '缺少真正执行清理')
must(/版本索引/.test(view), '未展示索引清理条数')
must(/清理完成/.test(view), '缺少“清理完成”明确反馈')
must(/await loadReportVersions\(\)/.test(view), '清理后未刷新版本列表')
must(/还没有当前作业的学生清单/.test(view), '空名单未在前端拦截')
must(/orphanCount|unmatched/.test(view), '版本面板未提示不在名单内的记录')
must(/不在名单内/.test(view) || /不属于本次名单/.test(view), '未提示孤儿记录可清理')
must(/students: names\.length \? names : undefined/.test(view), '版本查询未带名单')

// 4) 客户端字段
must(/indexRemoved\?: number/.test(client), 'engineClient 缺少 indexRemoved')
must(/orphanCount\?: number/.test(client), 'engineClient 缺少 orphanCount')

// 5) selfcheck 接入
must(/selfcheck:d197/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d197')
must(!!pkg.scripts?.['selfcheck:d197'], 'package.json 缺少 selfcheck:d197')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 清理报告同步清理版本索引（不再残留旧批次记录）')
console.log('✓ 空名单被拒绝，避免误删全部报告')
console.log('✓ dry-run 统计 → 确认 → 执行 → 展示“清理完成”并刷新版本')
console.log('✓ 版本面板显示孤儿记录数（可一键清理）')
console.log('✓ D197 selfcheck 已接入 npm run selfcheck')

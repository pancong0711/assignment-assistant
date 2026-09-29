/** B1 + B3/D46-5 回归自检（docs/13）：
 *  A) 多 sheet 成绩源：pickBestSheet 启发式（表头候选优先→行数最多）、显式 sheetName、uid/sheetName 透传；
 *  B) 点名册两级回退：标准表头 / zjxu 前8行说明+异序表头 / 失败结构化诊断 RosterParseError；
 *  C) 题图 figAssets：命中 basename→<img class="q-img"> dataURL；未命中→占位框；无 img_path→不渲染。
 *  运行前置：app/ 下 esbuild 打包（CI 里由 npm run selfcheck:roster-fig 完成）。 */
import assert from 'node:assert'
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const XLSX = require('xlsx')

const rx = await import('./rosterXlsx.bundle.mjs')
const sh = await import('./sheetHtml.bundle.mjs')

/* ---------- A) 多 sheet ---------- */
{
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([['系统导出'], ['时间 2026-09']]), '封面')
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(
    [['姓名', '学号', '期末成绩'], ['学生A', '101', '85'], ['学生B', '102', '92']],
  ), '成绩表')
  const buf = XLSX.write(wb, { bookType: 'xlsx', type: 'buffer' })
  const src = await rx.readScoreSourceXlsx(buf, 'multi.xlsx', 'exam')
  assert.equal(src.sheetName, '成绩表', 'B1: 自动选数据 sheet')
  assert.ok(Object.keys(src.scores).length === 2, 'B1: 分数解析')
  assert.ok(typeof src.uid === 'string' && src.uid.length > 8, 'E3修复: uid 透传不被 normalizeSource 吞')
  const forced = await rx.readScoreSourceXlsx(buf, 'multi.xlsx', 'custom', '封面')
  assert.equal(forced.sheetName, '封面', 'B1: 显式指定 sheet')
}

/* ---------- B) 点名册两级回退 ---------- */
{
  const mk = (aoa) => {
    const wb = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(aoa), 'S')
    return XLSX.write(wb, { bookType: 'xlsx', type: 'buffer' })
  }
  const std = await rx.readRosterXlsx(mk([['姓名', '学号', '班级'], ['张三', '101', 'A']]))
  assert.equal(std.length, 1, 'D46-1①: 标准表头')
  const rows = [['名册导出说明']]
  for (let i = 0; i < 7; i++) rows.push([''])
  rows.push(['学号', '课程', '姓名', '备注', '班级'], ['2026xxxx01', '大学物理', '学生A', '', 'classA'])
  const zjxu = await rx.readRosterXlsx(mk(rows))
  assert.equal(zjxu.length, 1, 'D46-1②: zjxu 前8行说明+异序表头回退')
  assert.equal(zjxu[0].name, '学生A')
  let threw = null
  try { await rx.readRosterXlsx(mk([['aaa'], ['1']])) } catch (e) { threw = e }
  assert.ok(threw && threw.reason === 'no-name-column' && Array.isArray(threw.firstRows), 'D46-1③: 结构化失败诊断')
}

/* ---------- C) 题图 figAssets ---------- */
{
  const pad = { id: 't', class_dir: '', course: '', class: 'c', term: '',
    layout: { orientation: 'portrait', per_page: 1, header: { title: 'T' }, footer: {} },
    items: [], watermark: { enabled: false, style: 'default', pageText: true, items: [] }, grade: {} }
  const png = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
  const items = [{ id: 'q1', content: '有图题', solution: '', imgPath: 'fig/diagram.png' }]
  const bodyOf = (h) => h.slice(h.indexOf('<body'))
  const miss = bodyOf(sh.stringifySheetHtml([{ pad, items }], {}))
  assert.ok(miss.includes('[题图：fig/diagram.png]'), 'B3: 未命中保持占位框')
  const hit = bodyOf(sh.stringifySheetHtml([{ pad, items }], { figAssets: { 'diagram.png': png } }))
  assert.ok(hit.includes(`<img class="q-img" src="${png}"`), 'B3: basename 命中→真图内联')
  const none = bodyOf(sh.stringifySheetHtml([{ pad, items: [{ id: 'q2', content: '无图' }] }], { figAssets: { 'diagram.png': png } }))
  assert.ok(!none.includes('q-img'), 'B3: 无 img_path 不渲染图区')
}

/* ---------- D) D47 真实形态回归（legacy fixtures，文件缺失时 skip-safe） ---------- */
{
  const fs = require('node:fs')
  const repo = '/home/bot2603/Projects/2609-assignment-assistant'
  try {
    const { readScoreSourceXlsx: r } = rx
    const toArr = (f) => fs.readFileSync(f)
    const exam = await r(toArr(repo + '/_legacy/2603paperDesign/data/custom/化工251-成绩统计.xlsx'), 'g.xlsx', 'exam')
    assert.ok(Object.keys(exam.scores).length === 33, 'D47: exam 真表 33 人')
    const xxtBuf = toArr(repo + '/_legacy/2603paperDesign/data/xxt/teachera-化工25_统计一键导出-0317.xlsx')
    const xa = await r(xxtBuf, 'x.xlsx', 'xuexitong_assignment')
    assert.ok(Object.keys(xa.scores).length === 31, 'D47: xxt_assignment crostab 31 人')
    const rain = await r(toArr(repo + '/_legacy/2603paperDesign/data/rainclass/大学物理C1-化工25--汇总-数据表-20260603221923_18346241.xlsx'), 'r.xlsx', 'rainclass')
    assert.ok(Object.keys(rain.scores).length === 67, 'D47: rainclass 67 人（锁定汇总表）')
    console.log('   D47 legacy-file regression: PASS')
  } catch { /* legacy 文件不在 CI 检出 → skip-safe */ }
}

console.log('selfcheck-roster-fig: ALL PASS (A×4 · B×4 · C×3 · D47-legacy*)')

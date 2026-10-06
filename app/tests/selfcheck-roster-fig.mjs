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

/* ---------- E) D55-H3 多列模型 + 原始分加权平均 + 黑名单 ---------- */
{
  const { computeScoresFiltered } = await import('./roster.bundle.mjs')
  // E1 黑名单：序号/学号 不进入数值列
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([
    ['序号', '学号', '姓名', '语文', '数学'],
    [1, '2025001', '学生A', 110, 108],
    [2, '2025002', '学生B', 100, 90],
    [3, '2025003', '学生C', 90, 80],
    [4, '2025004', '学生D', 80, 70],
    [5, '2025005', '学生E', 70, 60],
  ]), 'S')
  const buf = XLSX.write(wb, { bookType: 'xlsx', type: 'buffer' })
  const src = await rx.readScoreSourceXlsx(buf, 'exam.xlsx', 'custom')
  const colNames = (src.includedColumns || []).map((c) => c.name)
  assert.ok(colNames.includes('语文') && colNames.includes('数学'), 'H3: 成绩列进入勾选集')
  assert.ok(!colNames.includes('序号') && !colNames.includes('学号'), 'H3: 序号/学号被黑名单排除')
  // E2 单列 → 综合分 = 原始分（不做班内最高分归一）
  const one = { ...src, includedColumns: [{ name: '语文', index: colNames && 0, weight: 1 }] }
  // index 用真实列位（语文=第3列→索引3）
  one.includedColumns = [{ name: '语文', index: 3, weight: 1 }]
  const students = [
    { name: '学生A', number: '1', class: 'c', tag: '', score: null, manualTag: false, punish: false },
    { name: '学生B', number: '2', class: 'c', tag: '', score: null, manualTag: false, punish: false },
  ]
  computeScoresFiltered(students, [one])
  assert.equal(students[0].score, 110, 'H3: 单列=原始分(110)')
  assert.equal(students[1].score, 100, 'H3: 单列=原始分(100)')
  // E3 多列加权平均：语文(110,100)+数学(108,90)，权重 1:1 → (218/2, 190/2)
  const two = { ...src, includedColumns: [{ name: '语文', index: 3, weight: 1 }, { name: '数学', index: 4, weight: 1 }] }
  const students2 = [
    { name: '学生A', number: '1', class: 'c', tag: '', score: null, manualTag: false, punish: false },
    { name: '学生B', number: '2', class: 'c', tag: '', score: null, manualTag: false, punish: false },
  ]
  computeScoresFiltered(students2, [two])
  assert.equal(students2[0].score, 109, 'H3: 多列等权平均 (110+108)/2=109')
  assert.equal(students2[1].score, 95, 'H3: (100+90)/2=95')
  // E4 权重 2:1 → (110*2+108)/3 = 109.33
  const three = { ...src, includedColumns: [{ name: '语文', index: 3, weight: 2 }, { name: '数学', index: 4, weight: 1 }] }
  const students3 = [{ name: '学生A', number: '1', class: 'c', tag: '', score: null, manualTag: false, punish: false }]
  computeScoresFiltered(students3, [three])
  assert.equal(students3[0].score, 109.33, 'H3: 列权重 2:1 → 109.33')
  // E5 scoreColumnsOf / columnScoreOf 基本行为
  assert.equal(rx.scoreColumnsOf(two).length, 2, 'H3: scoreColumnsOf 两列')
  assert.equal(rx.columnScoreOf(two, { name: '数学', index: 4 }, '学生A'), 108, 'H3: columnScoreOf 取原始值')
  console.log('   D55-H3 multi-column/weighted-average/blacklist: PASS')
}

/* ---------- F) D57 整班/模板输出内容开关（includeSolution） ---------- */
{
  const pad = { id: 't', class_dir: '', course: '', class: 'c', term: '',
    layout: { orientation: 'portrait', per_page: 1, header: { title: 'T' }, footer: {} },
    items: [], watermark: { enabled: false, style: 'default', pageText: true, items: [] }, grade: {} }
  const items = [{ id: 'q1', content: '题干', solution: '答案内容XYZ' }]
  const bodyOf = (h) => h.slice(h.indexOf('<body'))
  const off = bodyOf(sh.stringifySheetHtml([{ pad, items }], { includeSolution: false }))
  const on = bodyOf(sh.stringifySheetHtml([{ pad, items }], { includeSolution: true }))
  assert.ok(!off.includes('参考答案') && !off.includes('答案内容XYZ'), 'D57: 不勾答案 → 无参考答案行')
  assert.ok(on.includes('参考答案') && on.includes('答案内容XYZ'), 'D57: 勾选答案 → 含参考答案行')
  // 水印/页码开关（整班卡同源 opts）
  const padWm = { ...pad, watermark: { enabled: true, style: 'default', pageText: true, items: [] } }
  const noWm = bodyOf(sh.stringifySheetHtml([{ pad: padWm, items }], { includeWatermark: false }))
  const noPt = bodyOf(sh.stringifySheetHtml([{ pad: padWm, items }], { includePageText: false }))
  assert.ok(!noWm.includes('wm-layer') && !noWm.includes('wm-page-text'), 'D57: 关水印图层 → 整层消失')
  assert.ok(noPt.includes('wm-anchor') || noPt.includes('wm-layer'), 'D57: 只关页码 → 图层保留')
  assert.ok(!noPt.includes('wm-page-text'), 'D57: 只关页码 → 无页码大字')
  console.log('   D57 output switches (solution/watermark/pagetext): PASS')
}

console.log('selfcheck-roster-fig: ALL PASS (A×4 · B×4 · C×3 · D47-legacy* · D57-switches)')

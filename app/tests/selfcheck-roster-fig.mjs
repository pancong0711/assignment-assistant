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

  // D83 修复回归：插图四态对齐口径（右下角 bug）
  // - row（text-*）里 align-self 是纵向对齐 → 一律顶部 flex-start；
  // - column（below-*）里是横向对齐 → flex-start=左 / flex-end=右；
  // - .q-img 静态 CSS 不得用 margin-left:auto（column 下会压过 align-self 把 below-left 推右）。
  const anyHtml = bodyOf(sh.stringifySheetHtml([{ pad, items }], {}))
  for (const rule of anyHtml.match(/\.q-img\s*\{[^}]*\}/g) || []) {
    assert.ok(!rule.includes('margin-left: auto'), `D83: .q-img 不得回归 margin-left:auto：${rule}`)
  }
  for (const [pos, align] of [['text-right', 'flex-start'], ['text-left', 'flex-start'],
    ['below-left', 'flex-start'], ['below-right', 'flex-end']]) {
    const pp = structuredClone(pad)
    pp.layout.figure = { scale: 1, pos, max_w_mm: 40, max_h_mm: 35 }
    const h = bodyOf(sh.stringifySheetHtml([{ pad: pp, items }], {}))
    assert.ok(h.includes(`class="sheet-frame pos-${pos}"`), `D83: pos-${pos} 帧 class 缺失`)
    assert.ok(h.includes(`align-self:${align}`), `D83: pos-${pos} 应为 align-self:${align}`)
    if (pos !== 'below-right') assert.ok(!h.includes('align-self:flex-end'), `D83: pos-${pos} 不得出现 flex-end`)
  }
}

/* ---------- D) D47 真实形态回归（legacy fixtures，文件缺失时 skip-safe） ---------- */
{
  // legacy 目录不在 CI 检出：逐个 case 独立 skip-safe，避免一个文件缺失吞掉全部断言。
  // 期望值 = 引擎同口径实测（engine/roster/scores.py ADAPTERS），保证 PWA↔engine 对齐。
  const fs = require('node:fs')
  const path = require('node:path')
  const { fileURLToPath } = require('node:url')
  const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
  const ROOT = path.join(repo, '_legacy', '2603paperDesign', 'data')
  const firstMatch = (dir, re) => {
    try {
      const hit = fs.readdirSync(dir).find((f) => re.test(f))
      return hit ? path.join(dir, hit) : null
    } catch { return null }
  }
  const { readScoreSourceXlsx: r } = rx
  const toArr = (f) => fs.readFileSync(f)
  let ran = 0

  // ① xuexitong_assignment：真实"统计一键导出"（须锁定"作业统计" sheet 且解析出人）
  const xxt = firstMatch(path.join(ROOT, 'xxt'), /化工25_统计一键导出-0317\.xlsx$/)
  if (xxt) {
    const xa = await r(toArr(xxt), 'x.xlsx', 'xuexitong_assignment')
    assert.equal(xa.sheetName, '作业统计', 'D47: xxt_assignment 锁定"作业统计"表')
    assert.ok(Object.keys(xa.scores).length > 30, 'D47: xxt_assignment 解析出学生（>30）')
    ran++
  }

  // ② rainclass：真实汇总表（须锁定"汇总"sheet 且解析出人；人数随日期增长，不硬编码）
  const rain = firstMatch(path.join(ROOT, 'rainclass'), /化工25--汇总-数据表-.*\.xlsx$/)
  if (rain) {
    const rr = await r(toArr(rain), 'r.xlsx', 'rainclass')
    assert.ok(/汇总/.test(rr.sheetName), 'D47: rainclass 锁定"汇总"表')
    assert.ok(Object.keys(rr.scores).length > 30, 'D47: rainclass 解析出学生（>30）')
    ran++
  }

  // ③ exam：真实"成绩统计"表含**标题行**（首行非表头），engine read_exam 尚不能三段式定位，
  //    属已知 PWA/engine 待对齐项（docs/12 §E5 后续）——此处只记录、不硬断言 parity。
  const exam = firstMatch(path.join(ROOT, 'custom'), /化工251-成绩统计\.xlsx$/)
  if (exam) {
    const ex = await r(toArr(exam), 'g.xlsx', 'exam')
    assert.ok(Object.keys(ex.scores).length > 0, 'D47: exam 真表可解析（人数口径待与 engine 对齐）')
    ran++
  }

  if (ran === 0) console.log('   D47 legacy-file regression: SKIP（legacy 文件不在当前检出）')
  else console.log(`   D47 legacy-file regression: PASS（${ran} 个真实文件）`)
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

/* ---------- G) B2 学号匹配回退 ---------- */
{
  const { computeScoresFiltered, normalizeSource } = await import('./roster.bundle.mjs')
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([
    ['学号', '姓名', '数学'],
    ['2025001', '张三', 80],
    ['2025002', '李四', 90],
  ]), 'S')
  const buf = XLSX.write(wb, { bookType: 'xlsx', type: 'buffer' })
  const src = await rx.readScoreSourceXlsx(buf, 'custom.xlsx', 'custom')
  // 姓名对不上（多空格），学号能对上 → 原始行回退
  assert.equal(rx.columnScoreOf(src, { name: '数学', index: 2 }, '张 三', '2025001'), 80, 'B2: 原始行列按学号回退')
  // 聚合分数（index<0）也支持 numbers 回退
  const agg = normalizeSource({
    name: '聚合源', family: 'custom', nameColumn: '姓名', numberColumn: '学号',
    scoreColumn: '均分', scores: { '张三': 80 }, numbers: { '2025001': 80 },
    includedColumns: [{ name: '均分', index: -1, weight: 1 }], rows: [],
  })
  const students = [{ name: '张 三', number: '2025001', class: '', tag: '', score: null, manualTag: false, punish: false }]
  computeScoresFiltered(students, [agg])
  assert.equal(students[0].score, 80, 'B2: 聚合 scores 按学号回退')
  console.log('   B2 number fallback: PASS')
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

console.log('selfcheck-roster-fig: ALL PASS (A×4 · B×4 · C×3+D83四态 · D47-legacy* · D57-switches · B2-number)')

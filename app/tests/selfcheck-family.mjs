/** app 成绩源格式预设（family 语义，docs/05-D19）自检：
 *  esbuild 打包 src/lib/rosterXlsx.ts → node 运行，对固定四类+custom
 *  用合成 xlsx 验证列名 family 语义解析（与 engine scores.py ADAPTERS 对齐）。
 *  运行：node tools/selfcheck-family.mjs（在 app/ 下先 esbuild bundle） */
import assert from 'node:assert'
import * as XLSX from 'xlsx'

const mod = await import('./rosterXlsx.bundle.mjs')
const { readScoreSourceXlsx, buildTaskPackage } = mod

function bufOf(rows, sheetNames = ['Sheet1'], sheetIdx = null) {
  const wb = XLSX.utils.book_new()
  sheetNames.forEach((name, i) => {
    const aoa = (sheetIdx === null ? i === 0 : sheetIdx === i) ? rows : [['占位']]
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(aoa), name)
  })
  return XLSX.write(wb, { bookType: 'xlsx', type: 'buffer' })
}

/* xlsx 读原始单元格值：数字 90 读回可能仍是数字，str() 后为 "90"。 */
async function run(family, buf) {
  return readScoreSourceXlsx(buf, 'test.xlsx', family)
}

/* 1) custom：常规表头 */
{
  const buf = bufOf([
    ['姓名', '高考数学', '备注'],
    ['学生A', 90, ''], ['学生B', 60, ''], ['学生C'],
  ])
  const src = await run('custom', buf)
  assert.equal(src.family, 'custom')
  assert.equal(src.scoreColumn, '高考数学')
  assert.equal(src.scores['学生A'], 90)
  assert.equal(src.scores['学生B'], 60)
  assert.equal(src.scores['学生C'], undefined)
  console.log('1) custom … ok')
}

/* 2) exam：教务期末，列"期末(必填)" */
{
  const buf = bufOf([
    ['姓名', '学号', '期末(必填)', '平时'],
    ['学生A', 'S1', 88, 100], ['学生B', 'S2', 55, 90],
  ])
  const src = await run('exam', buf)
  assert.equal(src.family, 'exam')
  assert.ok(src.scoreColumn.includes('期末'))
  assert.equal(src.scores['学生A'], 88)
  assert.equal(src.scores['学生B'], 55)
  console.log('2) exam … ok')
}

/* 3) xuexitong_assignment：前 8 行扫描"成绩"行 + 上行作业标题 + 数据行 */
{
  const buf = bufOf([
    [], [],
    ['', '作业1', '', '作业2'],
    ['', '作业1成绩', '', '作业2成绩'],
    ['学生A', 80, '', 70],
    ['学生B', 100, '', 40],
  ])
  const src = await run('xuexitong_assignment', buf)
  assert.equal(src.family, 'xuexitong_assignment')
  // 成绩行 = 首个含"成绩"的行（index 3），每生取各"成绩"列均分
  assert.equal(Math.round(src.scores['学生A'] * 100) / 100, 75, `A=${src.scores['学生A']}`)
  assert.equal(Math.round(src.scores['学生B'] * 100) / 100, 70, `B=${src.scores['学生B']}`)
  console.log('3) xuexitong_assignment … ok')
}

/* 4) xuexitong_stat：第 4 行表头找"成绩"列，非 0 计入取均分 */
{
  const buf = bufOf([
    ['占位1'], ['占位2'], ['占位3'],
    ['姓名', '第1章成绩', '第2章成绩'],
    ['学生A', 20, 0],
    ['学生B', 10, 30],
  ], ['章节测验'])
  const src = await run('xuexitong_stat', buf)
  assert.equal(src.family, 'xuexitong_stat')
  assert.equal(src.scores['学生A'], 20) // 0 不计入
  assert.equal(src.scores['学生B'], 20)
  console.log('4) xuexitong_stat … ok')
}

/* 5) rainclass：无表头，第2行标题，前3列学号/姓名/汇总，每课2列取均值（数据自索引3，同 engine） */
{
  const buf = bufOf([
    ['汇总'],
    ['第1课满分', '', '单选满分', '多选满分', '弹幕满分', '', '第2课满分', '', '单选2满分', '多选2满分'],
    ['占位说明行（engine body[1:] 语义跳过）'],
    ['S1', '学生A', 100, 60, 40, 20, 20, 60, 40, 20],
    ['S2', '学生B', 100, 30, 20, 10, 10, 30, 20, 10],
  ])
  const src = await run('rainclass', buf)
  assert.equal(src.family, 'rainclass')
  // 每课得分列 j=3+2c+1 → A: (40+20+40)/3 ≈ 33.33，B: (20+10+20)/3 ≈ 16.67
  assert.equal(Math.round(src.scores['学生A'] * 100) / 100, 33.33, `A=${src.scores['学生A']}`)
  assert.equal(Math.round(src.scores['学生B'] * 100) / 100, 16.67)
  console.log('5) rainclass … ok')
}

/* 6) roster（教务点名册）：仅接表，不计分 */
{
  const buf = bufOf([
    ['姓名', '学号', '班级'],
    ['学生A', 'S1', 'classA'],
  ])
  const src = await run('roster', buf)
  assert.equal(src.family, 'roster')
  assert.ok(Object.keys(src.scores).length === 0, '点名册不产生分数')
  console.log('6) roster（仅接表） … ok')
}

/* 7) 任务包 JSON：score_sources[].family 记录（CLI --score family:file:col:w 对齐） */
{
  const students = [{ name: '学生A', number: 'S1', class: 'classA', tag: 'copy', score: 90, manualTag: false, punish: false }]
  const sources = [
    { name: 'xx', fileName: 'a.xlsx', family: 'xuexitong_stat', scoreColumn: '第1章成绩', nameColumn: '姓名', weight: 2, rows: [], scores: { 学生A: 20 } },
    { name: 'yy', fileName: 'b.xlsx', family: 'custom', scoreColumn: '期末', nameColumn: '姓名', weight: 1, rows: [], scores: { 学生A: 88 } },
  ]
  const pkg = JSON.parse(buildTaskPackage(students, sources, [{ tag: 'copy', ratio: 1 }]))
  assert.equal(pkg.score_sources[0].family, 'xuexitong_stat')
  assert.equal(pkg.score_sources[1].family, 'custom')
  assert.equal(pkg.score_sources[0].score_column, '第1章成绩')
  console.log('7) 任务包 score_sources[].family … ok')
}

console.log('\n全部 family 语义自检通过 ✔（docs/05-D19 固定四类 + custom）')

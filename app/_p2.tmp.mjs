import * as XLSX from 'xlsx'
const fs = require('fs')
const repo = '/home/bot2603/Projects/2609-assignment-assistant'
// 学习通 统计一键导出：作业统计 sheet 找"成绩"行
for (const sheet of ['作业统计', '章节测验统计']) {
  const ws = wb0(sheet)
  const m = XLSX.utils.sheet_to_json(ws, { header: 1, defval: '' })
  console.log('===', sheet, 'rows:', m.length)
  for (let i = 0; i < Math.min(10, m.length); i++) {
    console.log(`  row${i}:`, JSON.stringify((m[i]??[]).slice(0,9).map(c=>String(c).slice(0,14))))
  }
}
function wb0(n){ }

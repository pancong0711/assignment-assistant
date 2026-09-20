/** LAN（http://非安全上下文）场景自检：在真实 Chromium headless 中经
 *  http://<LAN IP>:8602/selftest.html 加载，验证：
 *  1) isSecureContext=false、showOpenFilePicker/showDirectoryPicker 不存在；
 *  2) detectCapabilities() 静默降级（insecure=true、无错误横幅文案、picker 全 false）；
 *  3) 名单 xlsx（readRosterXlsx）与固定格式成绩源（readScoreSourceXlsx）
 *     经 ArrayBuffer/FileReader 路径解析正常（file input 等价路径）；
 *  4) <input type=file> + DataTransfer 装载文件（真实的 file input DOM 路径）读取成功。 */
import * as XLSX from 'xlsx'
import { readRosterXlsx, readScoreSourceXlsx } from '../src/lib/rosterXlsx'
import { detectCapabilities } from '../src/lib/fsAccess'

const results: string[] = []
const ok = (name: string, cond: boolean, extra = '') => {
  results.push(`${cond ? 'PASS' : 'FAIL'} ${name}${extra ? ' :: ' + extra : ''}`)
}

const envEl = document.getElementById('env')!
envEl.textContent = JSON.stringify({
  href: location.href,
  isSecureContext: window.isSecureContext,
  showOpenFilePicker: typeof window.showOpenFilePicker,
  showDirectoryPicker: typeof window.showDirectoryPicker,
})

/* 1) 环境断言（LAN http 必为非安全上下文） */
ok('isSecureContext=false（LAN http）', window.isSecureContext === false)
ok('showOpenFilePicker 不可用（非安全上下文）', typeof window.showOpenFilePicker !== 'function')
ok('showDirectoryPicker 不可用（非安全上下文）', typeof window.showDirectoryPicker !== 'function')

/* 2) detectCapabilities：静默降级、无错误横幅文案 */
const caps = detectCapabilities()
ok('caps.insecure=true', caps.insecure === true)
ok('caps.directoryPicker=false（写能力禁用）', caps.directoryPicker === false)
ok('caps.filePicker=false', caps.filePicker === false)
ok('caps.full=false', caps.full === false)
ok('caps.browserHint 为空（不弹"浏览器不支持"横幅）', caps.browserHint === '')

/* 3) 名单 xlsx 导入：FileReader→ArrayBuffer 路径（file input 的读取方式） */
function toFile(rows: unknown[][], name: string): File {
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(rows as XLSX.CellObject[][]), 'Sheet1')
  const bin = XLSX.write(wb, { bookType: 'xlsx', type: 'array' }) as ArrayBuffer
  const f = new File([bin], name)
  return f
}

const rosterFile = toFile([
  ['姓名', '学号', '班级'],
  ['学生A', 'S1', 'classA'],
  ['学生B', 'S2', 'classA'],
  ['学生C', 'S3', 'classA'],
], 'roster.xlsx')
const students = await readRosterXlsx(await rosterFile.arrayBuffer())
ok('readRosterXlsx（FileReader/ArrayBuffer 路径）解析 3 人', students.length === 3 && students[0].name === '学生A')

/* 4) 真实的 file input DOM 路径：<input type=file> + DataTransfer 装载 → 读取 */
const input = document.createElement('input')
input.type = 'file'
input.accept = '.xlsx'
const dt = new DataTransfer()
dt.items.add(rosterFile)
input.files = dt.files
ok('file input 装载成功（LAN 下 file input 可用）',
  input.files?.length === 1 && input.files[0].name === 'roster.xlsx')
const viaInput = await readRosterXlsx(await input.files![0].arrayBuffer())
ok('file input 文件内容经 readRosterXlsx 解析', viaInput.length === students.length && viaInput[1].name === '学生B')

/* 5) 成绩源：学习通·章节测验（固定格式 family）解析 */
const statFile = toFile([
  ['占位1'], ['占位2'], ['占位3'],
  ['姓名', '第1章成绩', '第2章成绩'],
  ['学生A', 20, 0],
  ['学生B', 10, 30],
], '章节测验.xlsx')
const src = await readScoreSourceXlsx(await statFile.arrayBuffer(), '章节测验.xlsx', 'xuexitong_stat')
ok('readScoreSourceXlsx(xuexitong_stat) 解析分数', src.scores['学生A'] === 20 && src.scores['学生B'] === 20,
  JSON.stringify(src.scores))

const examFile = toFile([
  ['姓名', '学号', '期末(必填)', '平时'],
  ['学生A', 'S1', 88, 100],
  ['学生B', 'S2', 55, 90],
], '期末.xlsx')
const srcExam = await readScoreSourceXlsx(await examFile.arrayBuffer(), '期末.xlsx', 'exam')
ok('readScoreSourceXlsx(exam) 取"期末"列', srcExam.scoreColumn.includes('期末') && srcExam.scores['学生A'] === 88)

const out = document.getElementById('out')!
out.textContent = results.join('\n')
out.dataset.done = '1'
document.title = results.every((r) => r.startsWith('PASS')) ? 'SELFTEST-OK' : 'SELFTEST-FAIL'

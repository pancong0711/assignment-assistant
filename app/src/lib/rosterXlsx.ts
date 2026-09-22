/** 名单/成绩 xlsx 读写与导出（M5 成绩管理，docs/05-D18/D19）。
 *  名单列结构与 engine files/roster.py 兼容（name/number/class/tag；
 *  中文表头 姓名/学号/班级 自适应映射）；tag 恒写英文值，
 *  导出的 roster xlsx 可直接供 engine `assist sheet make --roster` 使用。
 *  D19：成绩源新增"格式预设"（family）——固定四类按列名/表结构 family 语义
 *  自动定位分数列（与 engine assist/roster/scores.py ADAPTERS 同口径），
 *  无需用户选列；custom 保留手动选列。 */

import * as XLSX from 'xlsx'
import type { RosterStudent, ScoreFamily, ScoreSource } from './roster'
import { normalizeSource } from './roster'

/** roster 导出列（与 engine `_HEADERS` 一致，顺序=engine 读取顺序） */
export const ROSTER_COLUMNS = ['name', 'number', 'class', 'tag'] as const
export const ROSTER_COLUMN_LABELS: Record<string, string> = {
  name: '姓名', number: '学号', class: '班级', tag: 'tag',
}

/** 名单表头自适应（engine roster.py 同款映射 + 常见变体，宽松策略） */
const HEADER_MAP: Record<string, string> = {
  '姓名': 'name', 'name': 'name', 'student': 'name', '学生': 'name',
  '学号': 'number', 'number': 'number', 'id': 'number', '学籍号': 'number',
  '班级': 'class', 'class': 'class',
  'tag': 'tag', '标签': 'tag',
}

export const FAMILIES: ScoreFamily[] = [
  'roster', 'exam', 'xuexitong_assignment', 'xuexitong_stat', 'rainclass', 'custom',
]

/** 读名单 xlsx（File/ArrayBuffer）：中文/英文表头自适应 → RosterStudent[]。
 *  tag 列原样带入（教师既有 tag 名单可直接续用）；manualTag 按是否已有 tag 置位。 */
export async function readRosterXlsx(source: Blob | ArrayBuffer): Promise<RosterStudent[]> {
  const buf = source instanceof Blob ? await source.arrayBuffer() : source
  const wb = XLSX.read(buf, { type: 'array' })
  const sheet = wb.Sheets[wb.SheetNames[0]]
  if (!sheet) return []
  const raw = XLSX.utils.sheet_to_json<Record<string, unknown>>(sheet, { defval: '' })
  const out: RosterStudent[] = []
  for (const r of raw) {
    const stu: RosterStudent = { name: '', number: '', class: '', tag: '', score: null, manualTag: false, punish: false }
    for (const [k, v] of Object.entries(r)) {
      const key = HEADER_MAP[String(k).trim().toLowerCase()] ?? HEADER_MAP[String(k).trim()]
      if (!key) continue
      if (key === 'tag') {
        stu.tag = str(v)
        stu.manualTag = stu.tag !== ''
      } else if (key === 'name' || key === 'number' || key === 'class') {
        stu[key] = str(v)
      }
    }
    if (stu.name) out.push(stu)
  }
  return out
}

/* ---------- 成绩源：原始矩阵读取（保留表头行位置信息，供固定格式解析） ---------- */

interface RawSheet {
  fileName: string
  sheetNames: string[]
  /** 第一个 sheet 的整表矩阵（含表头行；单元格已转字符串，空为 ''） */
  matrix: string[][]
}

function readRawSheet(buf0: ArrayBuffer, fileName: string): RawSheet {
  const wb = XLSX.read(buf0, { type: 'array' })
  const sheetNames = wb.SheetNames
  const matrix: string[][] = sheetNames.length
    ? (XLSX.utils.sheet_to_json<unknown[]>(wb.Sheets[sheetNames[0]], { header: 1, defval: '' }) as unknown[])
        .map((r) => (Array.isArray(r) ? r.map((c) => str(c)) : []))
    : []
  return { fileName, sheetNames, matrix }
}

/* ---------- 固定四类 family 语义解析（对齐 engine scores.py ADAPTERS） ---------- */

function num(v: string): number | null {
  if (v === '') return null
  const f = Number(v.replace(/[^\d.eE+-]/g, ''))
  return Number.isFinite(f) ? f : null
}

/** exam（教务期末）：表头行找含"期末"的列（engine read_exam：col="期末" 子串匹配）。 */
function parseExam(m: RawSheet): { scores: Record<string, number>; nameColumn: string; scoreColumn: string } {
  const headers = m.matrix[0] ?? []
  const nameI = Math.max(0, headers.findIndex((h) => HEADER_MAP[h] === 'name'))
  const scoreI = headers.findIndex((h) => h.includes('期末'))
  const col = scoreI >= 0 ? headers[scoreI] : headers[headers.length - 1] ?? ''
  const scores: Record<string, number> = {}
  for (const r of m.matrix.slice(1)) {
    const name = (r[nameI] ?? '').trim()
    const v = scoreI >= 0 ? num(r[scoreI] ?? '') : null
    if (name && v !== null) scores[name] = v
  }
  return { scores, nameColumn: headers[nameI] ?? '', scoreColumn: col }
}

/** xuexitong_assignment（作业统计）：前 8 行找含"成绩"的单元格行，
 *  其上一行为作业标题；每生取各"成绩"列均分（engine read_xuexitong_assignment）。 */
function parseXuexitongAssignment(m: RawSheet): { scores: Record<string, number>; nameColumn: string; scoreColumn: string } {
  const rows = m.matrix
  let sr = -1
  for (let i = 0; i < Math.min(8, rows.length); i++) {
    if (rows[i].some((c) => c.includes('成绩'))) { sr = i; break }
  }
  if (sr < 1) return { scores: {}, nameColumn: rows[0]?.[0] ?? '姓名', scoreColumn: '（前8行未找到"成绩"行）' }
  const titles = rows[sr - 1] ?? []
  const perStu: Record<string, number[]> = {}
  for (let k = 0; k < rows[sr].length; k++) {
    if (!rows[sr][k].includes('成绩')) continue
    for (const r of rows.slice(sr + 1)) {
      const name = (r[0] ?? '').trim()
      const v = num(r[k] ?? '')
      if (name && v !== null) (perStu[name] ??= []).push(v)
    }
  }
  const scores: Record<string, number> = {}
  for (const [nm, list] of Object.entries(perStu)) {
    if (list.length) scores[nm] = list.reduce((a, b) => a + b, 0) / list.length
  }
  return { scores, nameColumn: rows[sr + 1]?.[0] ?? rows[0]?.[0] ?? '姓名', scoreColumn: `${titles.filter((t) => t).length || '?'} 个"成绩"列均分` }
}

/** xuexitong_stat（章节测验统计）：sheet 名含"章节测验"优先，第 4 行(索引3)为表头，
 *  找"成绩"列，非 0 计入取均分（engine read_xuexitong_stat）。 */
function parseXuexitongStat(m: RawSheet): { scores: Record<string, number>; nameColumn: string; scoreColumn: string } {
  const rows = m.matrix
  if (rows.length <= 4) return { scores: {}, nameColumn: '', scoreColumn: '（行数不足：需第4行表头+数据行）' }
  const heads = rows[3]
  const cols = heads.map((h, j) => (h.includes('成绩') ? j : -1)).filter((j) => j >= 0)
  const perStu: Record<string, number[]> = {}
  for (const r of rows.slice(4)) {
    const name = (r[0] ?? '').trim()
    if (!name) continue
    for (const j of cols) {
      const v = num(r[j] ?? '')
      if (v !== null && v !== 0) (perStu[name] ??= []).push(v) // 迁移语义：非 0 才计入
    }
  }
  const scores: Record<string, number> = {}
  for (const [nm, list] of Object.entries(perStu)) {
    if (list.length) scores[nm] = list.reduce((a, b) => a + b, 0) / list.length
  }
  return { scores, nameColumn: rows[4]?.[0] ?? '姓名', scoreColumn: cols.map((j) => heads[j]).join('|') || '（第4行未见"成绩"列）' }
}

/** rainclass（雨课堂汇总）：无表头，第 2 行(索引1)为列标题，
 *  前 3 列 = 学号/姓名/汇总，其后每课 2 列（方式+得分），取每课得分均值
 *  （engine read_rainclass：body=rows[2:] 后再 body[1:]，即数据行自索引 3 起——
 *  与 legacy 逐条迁移语义保持一致）。 */
function parseRainclass(m: RawSheet): { scores: Record<string, number>; nameColumn: string; scoreColumn: string } {
  const rows = m.matrix
  if (rows.length < 3) return { scores: {}, nameColumn: '', scoreColumn: '（行数不足）' }
  const nCourses = Math.max(0, Math.floor(((rows[1]?.length ?? 0) - 3) / 2))
  const scores: Record<string, number> = {}
  for (const r of rows.slice(3)) {
    const name = (r[1] ?? '').trim()
    if (!name) continue
    const list: number[] = []
    for (let c = 0; c < nCourses; c++) {
      const v = num(r[3 + 2 * c + 1] ?? '')
      if (v !== null) list.push(v)
    }
    if (list.length) scores[name] = list.reduce((a, b) => a + b, 0) / list.length
  }
  return { scores, nameColumn: '（第2列·雨课堂无表头）', scoreColumn: `每课得分列均值（${nCourses} 课）` }
}

/* ---------- 入口：按格式预设读成绩源 ---------- */

/** 读成绩源 xlsx → ScoreSource。family 决定解析方式：
 *  - 固定四类（roster/exam/xuexitong_assignment/xuexitong_stat/rainclass）：
 *    按列名/表结构 family 语义自动定位，无需用户选列；
 *  - custom：第 1 个 sheet 常规表头，猜姓名列/分数列，教师可在界面换列。
 *  roster（教务点名册）仅接表：不计分（scores 留空）。 */
export async function readScoreSourceXlsx(
  source: Blob | ArrayBuffer, fileName: string, family: ScoreFamily = 'custom',
): Promise<ScoreSource> {
  const buf = source instanceof Blob ? await source.arrayBuffer() : source
  const m = readRawSheet(buf, fileName)
  if (!m.matrix.length || m.matrix.every((r) => r.every((c) => c === ''))) {
    throw new Error(`文件无数据：${fileName}`)
  }
  const base = {
    name: fileName.replace(/\.xlsx$/i, ''),
    fileName,
    family,
    weight: 1,
    rows: m.matrix.slice(1)
      .filter((r) => r.some((c) => c !== ''))
      .map((r) => {
        const out: Record<string, string> = {}
        const headers = m.matrix[0] ?? []
        for (let i = 0; i < r.length; i++) out[headers[i] || `列${i + 1}`] = r[i]
        return out
      }),
    scores: {} as Record<string, number>,
  }
  if (family === 'roster') {
    return normalizeSource({ ...base, scoreColumn: '（点名册：仅接表，不计分）', nameColumn: (m.matrix[0] ?? []).find((h) => HEADER_MAP[h] === 'name') ?? '姓名' })
  }
  if (family === 'exam') return normalizeSource({ ...base, ...parseExam(m) })
  if (family === 'xuexitong_assignment') return normalizeSource({ ...base, ...parseXuexitongAssignment(m) })
  if (family === 'xuexitong_stat') return normalizeSource({ ...base, ...parseXuexitongStat(m) })
  if (family === 'rainclass') return normalizeSource({ ...base, ...parseRainclass(m) })
  // custom：常规表头表，宽松猜列（沿用既有策略），教师可在界面手动换列
  const headers = m.matrix[0] ?? []
  const guessName = headers.find((h) => HEADER_MAP[h] === 'name') ?? headers[0] ?? ''
  const nameI = Math.max(0, headers.indexOf(guessName))
  // 分数列：先按关键词猜；猜不到时用"数值最多列"回退（engine read_flex_auto 同款）
  const countNums = (j: number) => m.matrix.slice(1, 21).filter((r) => num(r[j] ?? '') !== null).length
  let scoreI = headers.findIndex((h, j) => j !== nameI && /分数|成绩|得分|score/i.test(h))
  if (scoreI < 0) {
    let best = 0
    for (let j = 0; j < headers.length; j++) {
      if (j === nameI) continue
      const nNums = countNums(j)
      if (nNums > best) { best = nNums; scoreI = j }
    }
  }
  if (scoreI < 0) scoreI = headers.length - 1
  const guessScore = headers[scoreI] ?? ''
  const scores: Record<string, number> = {}
  for (const r of m.matrix.slice(1)) {
    const name = (r[nameI] ?? '').trim()
    const v = num(r[scoreI] ?? '')
    if (name && v !== null) scores[name] = v
  }
  return normalizeSource({ ...base, scoreColumn: guessScore, nameColumn: guessName, scores })
}

/** 名单（含 tag）→ xlsx 二进制：列名用 name/number/class/tag（engine 直读）。 */
export function writeRosterXlsx(students: RosterStudent[]): ArrayBuffer {
  const aoa: (string | number)[][] = [[...ROSTER_COLUMNS]]
  for (const s of students) aoa.push([s.name, s.number, s.class, s.tag])
  const sheet = XLSX.utils.aoa_to_sheet(aoa)
  sheet['!cols'] = [{ wch: 14 }, { wch: 16 }, { wch: 18 }, { wch: 14 }]
  const wb = XLSX.utils.book_new()
  wb.Props = { Title: 'roster（assignment-assistant 导出，engine assist sheet make --roster 可直接用）' }
  XLSX.utils.book_append_sheet(wb, sheet, 'roster')
  return XLSX.write(wb, { bookType: 'xlsx', type: 'array' }) as ArrayBuffer
}

/** 任务包（分组比例 + special_tag 覆盖 + 成绩源 family）→ JSON 字符串（CLI/AI 可读）。
 *  D19：score_sources 记录 family 字段，与 engine CLI
 *  `--score family:file[:col[:weight]]`（family 可省=custom）同口径。 */
export function buildTaskPackage(
  students: RosterStudent[],
  sources: ScoreSource[],
  ratios: Array<{ tag: string; ratio: number }>,
): string {
  const specialTag: Record<string, string[]> = {}
  for (const s of students) {
    if (!s.manualTag || s.tag === '') continue
    ;(specialTag[s.tag] ??= []).push(s.name)
  }
  const punishList = students.filter((s) => s.punish).map((s) => s.name)
  const pkg = {
    kind: 'assignment-assistant.roster-task-package',
    version: 1,
    note: '合成示例占位说明：分组比例 + special_tag 参数任务包（M5 成绩管理，docs/05-D18/D19）',
    group_cfg: ratios.map((g) => ({ group_name: g.tag, group_ratio: g.ratio })),
    special_tag_cfg: specialTag,
    punish: punishList,
    // score_sources[].family 与 engine `--score family:file[:col[:weight]]` 对齐（family 可省=custom）
    score_sources: sources.map((s) => ({
      family: s.family,
      name: s.name, file: s.fileName,
      score_column: s.scoreColumn, name_column: s.nameColumn,
      weight: s.weight,
    })),
    generated_at: new Date().toISOString(),
  }
  return JSON.stringify(pkg, null, 2)
}

/** 任务包附带说明文档（md，随 zip 下载） */
export function taskPackageReadme(): string {
  return `# 分组比例 + special_tag 任务包（M5 成绩管理 · 附带说明）

本包由 app「班级与标签」选项卡导出（纯前端计算，docs/05-D18/D19），供
engine \`assist sheet make --roster\` / CLI / AI 阅读。全部示例均为占位
（学生A / classA），不含真实数据。

## 文件
- \`roster.xlsx\` — 名单表（name/number/class/tag，tag 恒为英文值，
  与 engine files/roster.py 的 _HEADER_MAP/_HEADERS 兼容，可直接 --roster 使用）。
- \`roster.json\` — 同一名单的 JSON 版（供 CLI/AI 使用）。
- \`task-package.json\` — 分组比例 + special_tag + score_sources 参数（本说明对应的机器读件）。

## 成绩源格式预设（docs/05-D19，与 engine scores.py ADAPTERS 同口径）
- 固定四类（无需选列，按列名/表结构 family 语义自动定位）：
  - exam（教务期末成绩表：列"期末(必填)"）
  - xuexitong_assignment（学习通作业统计：前 8 行"成绩"行 + 上行作业标题）
  - xuexitong_stat（学习通章节测验：第 4 行"成绩"列，非 0 均分）
  - rainclass（雨课堂汇总：第 2 行标题，前 3 列学号/姓名/汇总，每课 2 列取均值）
- roster（教务点名册）：仅接表，不计分。
- custom：教师手动选列/列名 list + 权重。
- CLI 对应：\`--score family:file[:col[:weight]]\`（family 可省=custom）。

## 切分规则（与 _legacy student.py 对齐）
1. 按综合得分（各成绩源按权重加权、源内按最大值归一到 0~100）降序排序；
2. 自上而下逐比例切分档次：int(人数×比例)，余数补到最后一个非 translation 项；
3. translation 特殊：按比例随机散布到全名单（legacy 同款"随机挑选"语义）；
4. special_tag_cfg / punish：手动指定学生 tag 覆盖，不被自动切分冲掉；
5. punish 不参与比例，仅手动勾选覆盖（期末补交统一题集，docs/05-D17）。

## group_cfg 结构
\`group_cfg: [{ group_name, group_ratio }]\`（比例之和 ≤ 1）。
`
}

function str(v: unknown): string {
  if (v == null) return ''
  return String(v).trim()
}

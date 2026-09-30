/** 名单/成绩 xlsx 读写与导出（M5 成绩管理，docs/05-D18/D19）。
 *  名单列结构与 engine files/roster.py 兼容（name/number/class/tag；
 *  中文表头 姓名/学号/班级 自适应映射）；tag 恒写英文值，
 *  导出的 roster xlsx 可直接供 engine `assist sheet make --roster` 使用。
 *  D19：成绩源新增"格式预设"（family）——固定四类按列名/表结构 family 语义
 *  自动定位分数列（与 engine assist/roster/scores.py ADAPTERS 同口径），
 *  无需用户选列；custom 保留手动选列。 */

import * as XLSX from 'xlsx'
import type { RosterStudent, ScoreFamily, ScoreSource } from './roster'
import { isIncluded, normalizeSource } from './roster'

/** roster 导出列（与 engine `_HEADERS` 一致，顺序=engine 读取顺序） */
export const ROSTER_COLUMNS = ['name', 'number', 'class', 'tag'] as const
export const ROSTER_COLUMN_LABELS: Record<string, string> = {
  name: '姓名', number: '学号', class: '班级', tag: 'tag',
}

/** D46-3：成绩源唯一 id（IndexedDB raw 键）。crypto.randomUUID 优先，回退时间戳+随机。 */
export function newUid(): string {
  try { return crypto.randomUUID() } catch { return `src-${Date.now()}-${Math.random().toString(36).slice(2, 8)}` }
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
/** 点名册读取的结构化失败（D46-1：给 UI 前 3 行原文诊断素材）。 */
export interface RosterParseError extends Error {
  reason: 'no-sheet' | 'no-name-column'
  firstRows: string[][]
  sheetNames: string[]
}

function rosterFail(reason: RosterParseError['reason'], matrix: string[][], sheetNames: string[]): never {
  const e = new Error(reason === 'no-sheet' ? '文件内无 sheet' : '未识别出姓名列（表头自适应与关键词找表头行两级均失败）') as RosterParseError
  e.reason = reason
  e.firstRows = matrix.slice(0, 3)
  e.sheetNames = sheetNames
  throw e
}

/** 从"表头行 + 数据行矩阵"按 HEADER_MAP 映射成学生列表（两级回退共用内核）。 */
function mapStudentsFromMatrix(matrix: string[][], headerI: number): RosterStudent[] {
  const headers = (matrix[headerI] ?? []).map((c) => c.trim())
  const cols: Array<{ j: number; key: 'name' | 'number' | 'class' | 'tag' }> = []
  headers.forEach((h, j) => {
    const key = HEADER_MAP[h.toLowerCase()] ?? HEADER_MAP[h]
    if (key === 'name' || key === 'number' || key === 'class' || key === 'tag') cols.push({ j, key })
  })
  const out: RosterStudent[] = []
  for (let i = headerI + 1; i < matrix.length; i++) {
    const row = matrix[i]
    if (!row) continue
    const stu: RosterStudent = { name: '', number: '', class: '', tag: '', score: null, manualTag: false, punish: false }
    for (const { j, key } of cols) {
      const v = str(row[j] ?? '')
      if (key === 'tag') { stu.tag = v; stu.manualTag = v !== '' }
      else stu[key] = v
    }
    if (stu.name) out.push(stu)
  }
  return out
}

/** 读名单 xlsx（D46-1 两级回退，zjxu 名册形态修复；去 pandas 思路用 openpyxl 等价物 SheetJS）：
 *  ① 主路径：第 1 行为表头 → HEADER_MAP 自适应（姓名/学号/班级/tag）；
 *  ② 回退：0 人时在前 15 行扫描含"姓名/名字/name/学生/student"的单元格行作为表头行重跑
 *     （教务系统名册常见前 8~10 行为说明文字、无标准表头——旧 _legacy iloc[8:-3] 硬切片的稳健替代）；
 *  ③ 仍 0 人 → 抛 RosterParseError{firstRows 前 3 行原文}（UI 红条+预览卡诊断）。 */
export async function readRosterXlsx(source: Blob | ArrayBuffer): Promise<RosterStudent[]> {
  const buf = source instanceof Blob ? await source.arrayBuffer() : source
  const wb = XLSX.read(buf, { type: 'array' })
  const sheet = wb.Sheets[wb.SheetNames[0]]
  if (!sheet) rosterFail('no-sheet', [], wb.SheetNames)
  const matrix = XLSX.utils.sheet_to_json<unknown[]>(sheet!, { header: 1, defval: '' })
    .map((r) => ((r as unknown[]) ?? []).map((c) => str(c)))
  // ① 首行表头
  let students = mapStudentsFromMatrix(matrix, 0)
  if (students.length) return students
  // ② 关键词找表头行（前 15 行）
  const NAME_TOKENS = ['姓名', '名字', 'name', '学生', 'student']
  for (let hi = 1; hi < Math.min(15, matrix.length); hi++) {
    const row = matrix[hi] ?? []
    if (row.some((c) => NAME_TOKENS.includes(String(c).trim().toLowerCase()))) {
      students = mapStudentsFromMatrix(matrix, hi)
      if (students.length) return students
    }
  }
  // ③ 结构化失败
  rosterFail('no-name-column', matrix, wb.SheetNames)
}

/* ---------- 成绩源：原始矩阵读取（保留表头行位置信息，供固定格式解析） ---------- */

interface RawSheet {
  fileName: string
  sheetNames: string[]
  /** 选中 sheet 的整表矩阵（B1：默认启发式选 sheet，可指定 sheetName） */
  matrix: string[][]
  /** 实际选中的 sheet 名（notes/预览显示用） */
  sheetName?: string
}

/** B1 多 sheet：读全部 sheet 矩阵；matrix = **数据行最多的非空 sheet**（默认启发式），
 *  教师可在 UI 切换 sheetName 重解析（rescoreWithFamily 传 sheet 参数）。 */
interface SheetMatrix { name: string; matrix: string[][] }

function allSheetMatrices(wb: XLSX.WorkBook): SheetMatrix[] {
  return wb.SheetNames.map((name) => ({
    name,
    matrix: (XLSX.utils.sheet_to_json<unknown[]>(wb.Sheets[name], { header: 1, defval: '' }) as unknown[])
      .map((r) => (Array.isArray(r) ? r.map((c) => str(c)) : [])),
  }))
}

/** 启发式选 sheet：① 有可映射表头（HEADER_MAP 命中姓名列，含前 15 行关键词回退）优先；
 *  ② 其次非空数据行数最多者。与 engine scores.py `next(s for s in sheetnames if ...)` 的
 *  名称匹配相比更通用；engine 侧按名过滤仍兼容（CLI --sheet 语义不变）。 */
export function pickBestSheet(ms: SheetMatrix[]): SheetMatrix | null {
  if (!ms.length) return null
  const nonEmpty = ms.filter((m) => m.matrix.some((r) => r.some((c) => c !== '')))
  if (!nonEmpty.length) return ms[0]
  const NAME_TOKENS = ['姓名', '名字', 'name', '学生', 'student']
  const hasNameHeader = (m: SheetMatrix) =>
    m.matrix.slice(0, 15).some((row) => (row ?? []).some((c) => NAME_TOKENS.includes(String(c).trim().toLowerCase())))
  const withHeader = nonEmpty.filter(hasNameHeader)
  const pool = withHeader.length ? withHeader : nonEmpty
  const dataRows = (m: SheetMatrix) => m.matrix.filter((r) => r.some((c) => c !== '')).length
  return pool.reduce((best, cur) => (dataRows(cur) > dataRows(best) ? cur : best))
}

/* ---------- D47 成绩源解析内核（真实形态适配大修） ----------
 * 数据获取：readRawSheet (B1) → matrix；
 * 路径A crostab（学习通 assignment/stat 的"标题行+成绩标记行"结构）→ buildCrostabSource；
 * 路径B 通用三段式：locateHeader（姓名语义行）→ 表头/姓名列 → dataNumericColumns 全数值列
 *                     → perColumn 勾选（exam/custom 全勾默认）；
 * 路径C parseRainclass（无表头+第2行列题，保留原实现）。
 * roster 接表族仍不计分。
 */
function readRawSheet(buf0: ArrayBuffer, fileName: string, sheetName?: string, family?: string): RawSheet {
  const wb = XLSX.read(buf0, { type: 'array' })
  const sheetNames = wb.SheetNames
  const ms = allSheetMatrices(wb)
  // D47 rainclass：锁定名称含"汇总/统计"的 sheet（真实文件第一张常是逐课子表；行数启发式会误选）
  let chosen: SheetMatrix | undefined
  if (sheetName) chosen = ms.find((x) => x.name === sheetName)
  else if (family === 'rainclass') {
    const sum = ms.filter((x) => /汇总|统计/.test(x.name))
    chosen = sum.length ? sum[0] : pickBestSheet(ms) ?? undefined
  } else chosen = pickBestSheet(ms) ?? undefined
  return { fileName, sheetNames, matrix: chosen?.matrix ?? [], sheetName: chosen?.name ?? '' }
}

interface RawSheet {
  fileName: string
  sheetNames: string[]
  /** 选中 sheet 的整表矩阵（B1/D47） */
  matrix: string[][]
  sheetName?: string
}

function num(v: string): number | null {
  if (v === '') return null
  const f = Number(v.replace(/[^\d.eE+-]/g, ''))
  return Number.isFinite(f) ? f : null
}

/** D47-1：定位"表头行 + 姓名列"（readRosterXlsx 三段式与 readScoreSourceXlsx 通用）。 */
function locateHeader(matrix: string[][], scanLimit = 20): { headerI: number; nameI: number } | null {
  const NAME_TOKENS = ['姓名', '名字', 'name', '学生', 'student']
  for (let i = 0; i < Math.min(scanLimit, matrix.length); i++) {
    const row = matrix[i] ?? []
    const nameI = row.findIndex((c) => NAME_TOKENS.includes(String(c).trim().toLowerCase()))
    if (nameI >= 0 && row.filter((c) => String(c).trim() !== '').length >= 2) {
      // 校验：下一行有数据（姓名列首个非空）
      const next = matrix[i + 1] ?? []
      if (String(next[nameI] ?? '').trim() !== '' || matrix.slice(i + 1, i + 4).some((r) => String((r ?? [])[nameI] ?? '').trim() !== '')) {
        return { headerI: i, nameI }
      }
    }
  }
  return null
}

/** D47-5：枚举数据区数值列（≥50% 行可数值化）。 */
/* D54/D55-H3：非成绩列黑名单（序号/学号/班级等元数据列不得进入勾选与加权）。 */
const META_HEADER_TOKENS = ['序号', '编号', '学号', '工号', '学籍号', '班级', '班号', '姓名', '名字',
  '备注', '排名', '层次', '专业', '函授站', '任课', '教师', '时间', '日期']
const META_HEADER_ASCII = new Set(['name', 'id', 'number', 'class', 'tag', 'punish', 'no', 'index'])

function isMetaHeader(h: string): boolean {
  const raw = h.trim()
  const low = raw.toLowerCase()
  if (META_HEADER_TOKENS.some((k) => raw.includes(k))) return true
  if (META_HEADER_ASCII.has(low)) return true
  if (/^(id|no|index)[-_ ]?\d*$/i.test(low)) return true
  return false
}

/** 启发式：整列取值唯一且恰为 1..n 连续整数 = 行号/序号列（防御无表头命名的元数据列）。 */
function looksLikeRowIndex(rows: string[][], j: number): boolean {
  const vals: number[] = []
  for (const r of rows) {
    const v = num(r[j] ?? '')
    if (v === null) continue
    if (!Number.isInteger(v)) return false
    vals.push(v)
  }
  if (vals.length < 5 || vals.length !== rows.length) return false
  const uniq = new Set(vals)
  if (uniq.size !== vals.length) return false
  const sorted = [...vals].sort((a, b) => a - b)
  return sorted.every((v, i) => v === i + 1)
}

function dataNumericColumns(matrix: string[][], headerI: number): Array<{ name: string; index: number }> {
  const headers = (matrix[headerI] ?? []).map((c) => String(c).trim())
  const rows = matrix.slice(headerI + 1).filter((r) => r.some((c) => String(c).trim() !== ''))
  if (!rows.length) return []
  const out: Array<{ name: string; index: number }> = []
  for (let j = 0; j < headers.length; j++) {
    const h = headers[j] || `列${j + 1}`
    if (isMetaHeader(headers[j] ?? '')) continue          // D54/H3 黑名单
    if (looksLikeRowIndex(rows, j)) continue               // 行号启发式
    let numeric = 0
    for (const r of rows) if (num(r[j] ?? '') !== null) numeric++
    if (numeric > 0 && numeric >= rows.length * 0.5) out.push({ name: h, index: j })
  }
  return out
}

/** D55-H3：某源参与总览/加权的列集合（缺省=主列；缺口数据源按 includedColumns）。
 *  返回 [{name, index, weight}]；index<0 表示用聚合 scores（雨课堂/旧数据）。 */
export function scoreColumnsOf(src: ScoreSource): Array<{ name: string; index: number; weight: number }> {
  if (src.includedColumns && src.includedColumns.length) {
    return src.includedColumns.map((c) => ({ name: c.name, index: c.index, weight: c.weight ?? 1 }))
  }
  const main = src.scoreColumn && src.scoreColumn !== '' ? src.scoreColumn : ''
  if (main) return [{ name: main, index: -1, weight: src.weight ?? 1 }]
  return []
}

/** D55-H3：某源某列在某生上的原始分（index>=0 走 rows 原表；<0 走聚合 scores）。 */
export function columnScoreOf(src: ScoreSource, col: { name: string; index: number }, name: string): number | null {
  if (col.index >= 0) {
    const row = src.rows.find((r) => str(r[src.nameColumn]) === name)
    if (row) {
      const v = row[col.name] ?? row[`列${col.index + 1}`] ?? ''
      const n = num(v)
      if (n !== null) return n
    }
    return null
  }
  const v = src.scores?.[name]
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

/** D47-3：学习通 crostab 探测（"学生姓名"标题行 + 下一行"成绩"标记行）。 */
function detectCrostab(matrix: string[][]): { titleI: number; markI: number } | null {
  for (let i = 0; i < Math.min(12, matrix.length - 1); i++) {
    const title = (matrix[i] ?? []).map((c) => String(c).trim())
    const mark = (matrix[i + 1] ?? []).map((c) => String(c).trim())
    const hasNameHeader = title.some((c) => /学生姓名|姓名|name/i.test(c))
    const scoreMarks = mark.filter((c) => c === '成绩').length
    if (hasNameHeader && scoreMarks >= 2) {
      // 数据行校验：标记行下第二行（数据首个）姓名列非空数字列存在
      return { titleI: i, markI: i + 1 }
    }
  }
  return null
}

/** D47-3：学习通 crostab 源构造（assignment/stat 同构）：
 *  title 行 = 作业/测验标题；mark 行 = "成绩"标记；数据自 titleI+2 起；
 *  姓名列 = title 行"学生姓名"列；每生 = 型 scoreCols 均分；scoreCols 各列 → allNumeric/included 全勾。 */
function buildCrostabSource(m: RawSheet, family: ScoreFamily, cr: { titleI: number; markI: number }): ScoreSource {
  const title = (m.matrix[cr.titleI] ?? []).map((c) => String(c).trim())
  const mark = (m.matrix[cr.markI] ?? []).map((c) => String(c).trim())
  const ni = Math.max(0, title.findIndex((c) => /学生姓名|姓名|name/i.test(c)))
  const scoreCols: Array<{ name: string; index: number }> = []
  for (let k = 0; k < Math.max(title.length, mark.length); k++) {
    if (mark[k] === '成绩') scoreCols.push({ name: title[k] || `作业/测验${k}`, index: k })
  }
  const dataRows = m.matrix.slice(cr.markI + 1).filter((r) => r.some((c) => String(c).trim() !== ''))
  const rows = dataRows.map((r) => {
    const out: Record<string, string> = {}
    for (let i = 0; i < r.length; i++) out[title[i] || `列${i + 1}`] = r[i]
    return out
  })
  const perStu: Record<string, number> = {}
  for (const r of dataRows) {
    const nm = String(r[ni] ?? '').trim()
    if (!nm) continue
    const vals: number[] = []
    for (const c of scoreCols) {
      const v = num(r[c.index] ?? '')
      if (v !== null) vals.push(v)
    }
    if (vals.length) perStu[nm] = vals.reduce((a, b) => a + b, 0) / vals.length
  }
  return normalizeSource({
    uid: newUid(),
    sheetName: m.sheetName ?? '',
    name: m.fileName.replace(/\.xlsx$/i, ''),
    fileName: m.fileName,
    family,
    weight: 1,
    rows,
    allNumericColumns: scoreCols,
    includedColumns: scoreCols.map((c) => ({ ...c, weight: 1 })),
    scores: perStu,
    nameColumn: title[ni] ?? '学生姓名',
    scoreColumn: `${scoreCols.length} 个作业/测验均分`,
  })
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

/** 读成绩源 xlsx → ScoreSource（D47 大修骨架；原 parse* fn 全部废弃为三段式统一实现）。 */
export async function readScoreSourceXlsx(
  source: Blob | ArrayBuffer, fileName: string, family: ScoreFamily = 'custom',
  sheetName?: string,
): Promise<ScoreSource> {
  const buf = source instanceof Blob ? await source.arrayBuffer() : source
  const m = readRawSheet(buf, fileName, sheetName, family)
  if (!m.matrix.length || m.matrix.every((r) => r.every((c) => c === ''))) {
    throw new Error(`文件无数据：${fileName}`)
  }
  // D47-3 crostab 前置（扩为全文匹配：xuexitong_* 家族在全部 sheet 里找 crostab 命中者，
  //    避免 B1 pickBestSheet 行数启发式误选"任务点完成详情"等无关表）
  if (family === 'xuexitong_assignment' || family === 'xuexitong_stat') {
    const wbAll = XLSX.read(buf, { type: 'array' })
    for (const sn of wbAll.SheetNames) {
      const mm: string[][] = (XLSX.utils.sheet_to_json(wbAll.Sheets[sn], { header: 1, defval: '' }) as unknown[])
        .map((r) => (Array.isArray(r) ? r.map((c) => String(c)) : []))
      const hit = detectCrostab(mm)
      if (hit) {
        const m2: RawSheet = { fileName, sheetNames: wbAll.SheetNames, matrix: mm, sheetName: sn }
        return buildCrostabSource(m2, family, hit)
      }
    }
  }
  const cr = detectCrostab(m.matrix)
  if (cr && (family === 'xuexitong_assignment' || family === 'xuexitong_stat')) {
    return buildCrostabSource(m, family, cr)
  }
  // D47-1 通用三段式
  const loc = locateHeader(m.matrix, 20)
  const headerI = loc?.headerI ?? 0
  const headers = (m.matrix[headerI] ?? []).map((c) => String(c).trim())
  const nameI = loc?.nameI ?? Math.max(0, headers.findIndex((h) => HEADER_MAP[h] === 'name'))
  const dataRows = m.matrix.slice(headerI + 1).filter((r) => r.some((c) => String(c).trim() !== ''))
  const base = {
    uid: newUid(),
    sheetName: m.sheetName ?? '',
    name: fileName.replace(/\.xlsx$/i, ''),
    fileName,
    family,
    weight: 1,
    rows: dataRows.map((r) => {
      const out: Record<string, string> = {}
      for (let i = 0; i < r.length; i++) out[headers[i] || `列${i + 1}`] = r[i]
      return out
    }),
    scores: {} as Record<string, number>,
  }
  // D47-5：全部数值列（exam/custom 默认全勾、随教师取消）——**排除姓名列本身**
  const numericCols = dataNumericColumns(m.matrix, headerI).filter((c) => c.index !== nameI)
  if (family === 'exam' || family === 'custom') {
    Object.assign(base, {
      allNumericColumns: numericCols,
      includedColumns: numericCols.map((c) => ({ ...c, weight: 1 })),
    })
  }
  if (family === 'roster') {
    return normalizeSource({ ...base, scoreColumn: '（点名册：仅接表，不计分）', nameColumn: headers[nameI] ?? '姓名' })
  }
  if (family === 'exam') {
    // D47-2：分数列放宽 = /期末|成绩|得分|总分|score/；未命中=最末数值列
    const hit = headers.findIndex((h, j) => j !== nameI && /期末|成绩|得分|总分|score/i.test(h))
    const scoreI = hit >= 0 ? hit : (numericCols.length ? numericCols[numericCols.length - 1].index : headers.length - 1)
    const perStu: Record<string, number> = {}
    for (const r of dataRows) {
      const nm = String(r[nameI] ?? '').trim()
      const v = num(r[scoreI] ?? '')
      if (nm && v !== null) perStu[nm] = v
    }
    return normalizeSource({
      ...base, scores: perStu,
      nameColumn: headers[nameI] ?? '姓名',
      scoreColumn: headers[scoreI] ?? '',
    })
  }
  if (family === 'rainclass') {
    const r = parseRainclass(m)
    const colName = r.scoreColumn || '雨课堂汇总（每课均值）'
    return normalizeSource({
      ...base, ...r,
      allNumericColumns: [{ name: colName, index: -1 }],
      includedColumns: [{ name: colName, index: -1, weight: 1 }],
    })
  }
  // custom：宽松猜列（分数列关键词→数值最多列）——不变；教师可在源行手动换列
  const cntNums = (j: number) => dataRows.slice(0, 20).filter((r) => num(r[j] ?? '') !== null).length
  let scoreI = headers.findIndex((h, j) => j !== nameI && /分数|成绩|得分|score/i.test(h))
  if (scoreI < 0) {
    let best = 0
    for (let j = 0; j < headers.length; j++) {
      if (j === nameI) continue
      const n = cntNums(j)
      if (n > best) { best = n; scoreI = j }
    }
  }
  if (scoreI < 0) scoreI = headers.length - 1
  const guessScore = headers[scoreI] ?? ''
  const scores: Record<string, number> = {}
  for (const r of dataRows) {
    const nm = String(r[nameI] ?? '').trim()
    const v = num(r[scoreI] ?? '')
    if (nm && v !== null) scores[nm] = v
  }
  return normalizeSource({ ...base, scoreColumn: guessScore, nameColumn: headers[nameI] ?? '姓名', scores })
}

/* ---------- VC-4 / VC-6 导入预览（docs/14 §VC-4/6：表头 + 前 3 行 + 列映射说明） ---------- */

/** 导入预览模型：与引擎同款宽松列名 rule 的"所见即所读"快照。
 *  表头 = 原始 xlsx 第一行；rows = 前 3 个非空数据行；cols = 引擎映射说明。 */
export interface PreviewTable {
  headers: string[]
  rows: string[][]
  /** 列映射说明（VC-4 名单：姓名=name/学号=number…；VC-6 成绩源：分数列/姓名列定位） */
  notes: string[]
  /** 实际解析出的行数（全部数据行，非仅预览前 3 行） */
  rowCount: number
}

const PREVIEW_ROW_LIMIT = 500

function previewFromMatrix(headers: string[], dataRows: string[][], notes: string[]): PreviewTable {
  const rows = dataRows
    .filter((r) => r.some((c) => c.trim() !== ''))
    .slice(0, PREVIEW_ROW_LIMIT)
    .map((r) => headers.map((_, j) => r[j] ?? ''))
  return { headers, rows, notes, rowCount: dataRows.filter((r) => r.some((c) => c.trim() !== '')).length }
}

/** 名单 xlsx 预览（VC-4）：宽松表头自适应 rule 与 readRosterXlsx 完全同款
 *  （HEADER_MAP + trim + 小写回退），教师可在导入前即时核对列映射。 */
/** 名单 xlsx 预览（D46-1 与 readRosterXlsx 同两级回退：表头自适应 → 关键词找表头行；
 *  notes 报告实际采用的模式 + 前 3 行原文诊断）。 */
export async function buildRosterPreview(source: Blob | ArrayBuffer): Promise<PreviewTable> {
  const buf = source instanceof Blob ? await source.arrayBuffer() : source
  const wb = XLSX.read(buf, { type: 'array' })
  const sheet = wb.Sheets[wb.SheetNames[0]]
  if (!sheet) return { headers: [], rows: [], notes: ['（文件内无 sheet）'], rowCount: 0 }
  const matrix = XLSX.utils.sheet_to_json<unknown[]>(sheet, { header: 1, defval: '' })
    .map((r) => ((r as unknown[]) ?? []).map((c) => str(c)))
  const NAME_TOKENS = ['姓名', '名字', 'name', '学生', 'student']
  let headerI = 0
  let modeNote = '表头自适应（第 1 行）'
  if (mapStudentsFromMatrix(matrix, 0).length === 0) {
    const hit = matrix.slice(1, 15).findIndex((row) => (row ?? []).some((c) => NAME_TOKENS.includes(String(c).trim().toLowerCase())))
    if (hit >= 0) {
      headerI = hit + 1
      modeNote = `关键词定位表头行（第 ${headerI + 1} 行含"姓名/name"——zjxu 名册形态，前 ${headerI} 行为说明文字已跳过）`
    } else {
      modeNote = '⚠ 两级回退均未找到姓名列：读入将失败（请核对前几行内容；若为教务名册且表头缺失，删至仅剩表头行后重试）'
    }
  }
  const headers = (matrix[headerI] ?? []).map((c) => str(c))
  const rows = matrix.slice(headerI + 1).map((r) => (r ?? []).map((c) => str(c)))
  const notes = [modeNote, ...headers
    .filter((h) => HEADER_MAP[h] || HEADER_MAP[h.trim().toLowerCase()])
    .map((h) => {
      const key = HEADER_MAP[h] ?? HEADER_MAP[h.trim().toLowerCase()]
      return `${h} → ${key}${key === 'tag' ? '（原样带入，可后续覆盖）' : ''}`
    })]
  return previewFromMatrix(headers, rows, notes)
}

/** 成绩源 xlsx 预览（VC-6）：表头 + 前 3 行 + 按所选 family 的解析定位说明。
 *  固定四类说明分数列语义（与 readScoreSourceXlsx 的解析器同口径）；
 *  custom 说明宽松猜列策略。 */
export async function buildScoreSourcePreview(
  source: Blob | ArrayBuffer, family: ScoreFamily = 'custom', sheetName?: string,
): Promise<PreviewTable> {
  const buf = source instanceof Blob ? await source.arrayBuffer() : source
  const wb = XLSX.read(buf, { type: 'array' })
  const ms = allSheetMatrices(wb)
  const chosen = (sheetName ? ms.find((x) => x.name === sheetName) : undefined) ?? pickBestSheet(ms)
  if (!chosen) return { headers: [], rows: [], notes: ['（文件内无 sheet）'], rowCount: 0 }
  const matrix = chosen.matrix
  const headers = (matrix[0] ?? []).map((c) => str(c))
  const rows = matrix.slice(1).map((r) => (r ?? []).map((c) => str(c)))
  const notes: string[] = [
    `sheet：${chosen.name || '（无名）'}${wb.SheetNames.length > 1 ? `（B1 自动选择，共 ${wb.SheetNames.length} 张：${wb.SheetNames.join(' / ')}；可在源行切换）` : ''} · 格式预设：${family}`,
  ]
  if (family === 'roster') {
    notes.push('教务点名册：仅接表不计分，按 姓名/name 列识别。')
  } else if (family === 'exam') {
    const hit = headers.find((h) => h.includes('期末'))
    notes.push(hit ? `教务期末：分数列定位 = 含"期末"的列「${hit}」。` : '教务期末：表头未见含"期末"的列，将回退取最后一列。')
  } else if (family === 'xuexitong_assignment') {
    notes.push('学习通·作业统计：前 8 行内找"成绩"行，其上一行为作业标题，每生取各"成绩"列均分。')
  } else if (family === 'xuexitong_stat') {
    notes.push('学习通·章节测验：按 sheet 名含"章节测验"匹配（当前第 1 个 sheet），第 4 行为表头找"成绩"列，非 0 计入取均分。')
  } else if (family === 'rainclass') {
    notes.push('雨课堂汇总：无表头（第 1 行按数据行跳过），第 2 行为列标题，前 3 列 = 学号/姓名/汇总，其后每课 2 列取均值。')
  } else {
    const nameHit = headers.find((h) => HEADER_MAP[h] === 'name') ?? headers[0] ?? ''
    const scoreHit = headers.find((h, j) => j !== headers.indexOf(nameHit) && /分数|成绩|得分|score/i.test(h))
    notes.push(`custom 宽松猜列：姓名列 ≈「${nameHit || '第 1 列'}」` + (scoreHit ? `，分数列 ≈「${scoreHit}」（也可导入后在源行手动换列）。` : '，分数列 ≈ 数值最多的列（可导入后手动换列）。'))
  }
  return previewFromMatrix(headers, rows, notes)
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

/** 作业纸（分组比例 + special_tag 覆盖 + 成绩源 family）→ JSON 字符串（CLI/AI 可读）。
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
    note: '合成示例占位说明：分组比例 + special_tag 参数作业纸（M5 成绩管理，docs/05-D18/D19）',
    group_cfg: ratios.map((g) => ({ group_name: g.tag, group_ratio: g.ratio })),
    special_tag_cfg: specialTag,
    punish: punishList,
    // score_sources[].family 与 engine `--score family:file[:col[:weight]]` 对齐（family 可省=custom）
    // VC-5：include_in_aggregation=false = 教师取消勾选（score excluding），
    // 教师综合得分为 PWA 端按勾选集合计算；引擎 CLI 侧需手动省略对应 --score
    // （作业纸 JSON 的该标记为核对提示）。
    // D55-H3：一个源可勾多列 → 每列一条（engine `--score family:file:col:weight` 天然支持多条，
    // merge_scores 即"原始分加权平均"，与 PWA 综合分同口径；未勾选的源展开为一条 excluded 记录供核对）。
    score_sources: sources.flatMap((s) => {
      const cols = scoreColumnsOf(s)
      if (!isIncluded(s)) {
        return [{ family: s.family, name: s.name, file: s.fileName, score_column: s.scoreColumn,
                  name_column: s.nameColumn, weight: s.weight, include_in_aggregation: false, excluded: true }]
      }
      if (!cols.length) {
        return [{ family: s.family, name: s.name, file: s.fileName, score_column: s.scoreColumn,
                  name_column: s.nameColumn, weight: s.weight, include_in_aggregation: true }]
      }
      return cols.map((c) => ({
        family: s.family,
        name: s.name, file: s.fileName,
        score_column: c.name, name_column: s.nameColumn,
        weight: c.weight,
        include_in_aggregation: true,
      }))
    }),
    generated_at: new Date().toISOString(),
  }
  return JSON.stringify(pkg, null, 2)
}

/** 作业纸附带说明文档（md，随 zip 下载） */
export function taskPackageReadme(): string {
  return `# 分组比例 + special_tag 作业纸（M5 成绩管理 · 附带说明）

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
5. punish 不参与比例，仅手动勾选覆盖（期末补交统一题集，docs/05-D17）；
6. score_sources[].include_in_aggregation：false = 该源被教师取消勾选
   （score excluding，docs/14 §VC-5），PWA 端综合得分不含该源；
   引擎 CLI 执行时请对应省略该源的 --score 参数（本标记为人工核对提示）。

## group_cfg 结构
\`group_cfg: [{ group_name, group_ratio }]\`（比例之和 ≤ 1）。
`
}

function str(v: unknown): string {
  if (v == null) return ''
  return String(v).trim()
}

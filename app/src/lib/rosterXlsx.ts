/** 名单/成绩 xlsx 读写与导出（M5 成绩管理，docs/05-D18）。
 *  名单列结构与 engine files/roster.py 兼容（name/number/class/tag；
 *  中文表头 姓名/学号/班级 自适应映射）；tag 恒写英文值，
 *  导出的 roster xlsx 可直接供 engine `assist sheet make --roster` 使用。 */

import * as XLSX from 'xlsx'
import type { RosterStudent, ScoreSource } from './roster'

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

/** 读成绩源 xlsx：任意表（第 1 个 sheet），返回原始行（列名→字符串值），
 *  教师在界面上手动选"分数来源列"并起名/给权重。 */
export async function readScoreSourceXlsx(
  source: Blob | ArrayBuffer, fileName: string,
): Promise<{ name: string; fileName: string; scoreColumn: string; nameColumn: string; weight: number; rows: Array<Record<string, string>> }> {
  const buf = source instanceof Blob ? await source.arrayBuffer() : source
  const wb = XLSX.read(buf, { type: 'array' })
  const sheet = wb.Sheets[wb.SheetNames[0]]
  if (!sheet) throw new Error(`文件无数据：${fileName}`)
  const rows = XLSX.utils.sheet_to_json<Record<string, unknown>>(sheet, { defval: '' })
    .map((r) => {
      const out: Record<string, string> = {}
      for (const [k, v] of Object.entries(r)) out[String(k)] = str(v)
      return out
    })
  const headers = rows.length ? Object.keys(rows[0]) : []
  const guessName = headers.find((h) => HEADER_MAP[h] === 'name') ?? headers[0] ?? ''
  const guessScore = headers.find((h) => /分数|成绩|得分|score/i.test(h)) ?? headers[headers.length - 1] ?? ''
  return {
    name: fileName.replace(/\.xlsx$/i, ''),
    fileName,
    scoreColumn: guessScore,
    nameColumn: guessName,
    weight: 1,
    rows,
  }
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

/** 任务包（分组比例 + special_tag 覆盖）→ JSON 字符串（CLI/AI 可读；说明见附带 md）。 */
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
    note: '合成示例占位说明：分组比例 + special_tag 参数任务包（M5 成绩管理，docs/05-D18）',
    group_cfg: ratios.map((g) => ({ group_name: g.tag, group_ratio: g.ratio })),
    special_tag_cfg: specialTag,
    punish: punishList,
    score_sources: sources.map((s) => ({
      name: s.name, file: s.fileName, score_column: s.scoreColumn,
      name_column: s.nameColumn, weight: s.weight,
    })),
    generated_at: new Date().toISOString(),
  }
  return JSON.stringify(pkg, null, 2)
}

/** 任务包附带说明文档（md，随 zip 下载） */
export function taskPackageReadme(): string {
  return `# 分组比例 + special_tag 任务包（M5 成绩管理 · 附带说明）

本包由 app「班级与成绩」选项卡导出（纯前端计算，docs/05-D18），供
engine \`assist sheet make --roster\` / CLI / AI 阅读。全部示例均为占位
（学生A / classA），不含真实数据。

## 文件
- \`roster.xlsx\` — 名单表（name/number/class/tag，tag 恒为英文值，
  与 engine files/roster.py 的 _HEADER_MAP/_HEADERS 兼容，可直接 --roster 使用）。
- \`roster.json\` — 同一名单的 JSON 版（供 CLI/AI 使用）。
- \`task-package.json\` — 分组比例 + special_tag 参数（本说明对应的机器读件）。

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

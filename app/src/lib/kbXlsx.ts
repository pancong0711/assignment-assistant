import * as XLSX from 'xlsx'
import {
  KB_COLUMNS, KB_COLUMN_WIDTHS, KB_KIND_LABELS,
  type KbBook, type KbChapter, type KbKind, type KbRow,
} from './kb'

/** 读取一个题库 xlsx（Blob/File/ArrayBuffer）→ KbBook。多 sheet = 多章。
 *  兼容旧文件的列序/缺列：缺失列补空字符串。 */
export async function readKbXlsx(source: Blob | ArrayBuffer, kind: KbKind): Promise<KbBook> {
  const buf = source instanceof Blob ? await source.arrayBuffer() : source
  const wb = XLSX.read(buf, { type: 'array' })
  // D40 (方案 C)：translation.xlsx 为中文例外表头（名言/作者/出处），generic reader 不适用 →
  // 用专用解析器（与引擎 kb_io.read_translation 同语义）。
  if (kind === 'translation') {
    const chapters: KbChapter[] = wb.SheetNames.map((name) => {
      const sheet = wb.Sheets[name]
      const aoa = XLSX.utils.sheet_to_json<unknown[]>(sheet, { defval: '', header: 1 })
      const rows = parseTranslationAoA(aoa)
      return { name, rows }
    })
    return { kind, chapters }
  }
  const chapters: KbChapter[] = wb.SheetNames.map((name) => {
    const sheet = wb.Sheets[name]
    const raw = XLSX.utils.sheet_to_json<Record<string, unknown>>(sheet, { defval: '' })
    const rows: KbRow[] = raw.map((r) => ({
      id: str(r.id), content: str(r.content), img_path: str(r.img_path),
      page: str(r.page), related: str(r.related), type: str(r.type),
      solution: str(r.solution), note: str(r.note),
    }))
    return { name, rows }
  })
  return { kind, chapters }
}

/** KbBook → xlsx 二进制（每章一个 sheet；列结构与 engine 兼容）。
 *  说明：SheetJS 社区版（Apache-2.0 / mit 标记版本）不支持写单元格样式，
 *  生成的是纯数据 xlsx —— 列宽可写，字体/边框等样式会丢失（教师侧如需
 *  精细样式，可交由引擎 openpyxl 写回；见 docs/05-D3）。 */
export function writeKbXlsx(book: KbBook): ArrayBuffer {
  const wb = XLSX.utils.book_new()
  wb.Props = { Title: `kb ${book.kind}（assignment-assistant 导出）` }
  for (const ch of book.chapters) {
    const aoa: (string | number)[][] = [[...KB_COLUMNS]]
    for (const row of ch.rows) {
      aoa.push(KB_COLUMNS.map((c) => (row[c] ?? '') as string))
    }
    const sheet = XLSX.utils.aoa_to_sheet(aoa)
    sheet['!cols'] = KB_COLUMNS.map((c) => ({ wch: KB_COLUMN_WIDTHS[c] }))
    const safeName = ch.name.replace(/[[\]:*?/\\]/g, '_').slice(0, 31) || 'Sheet1'
    XLSX.utils.book_append_sheet(wb, sheet, safeName)
  }
  return XLSX.write(wb, { bookType: 'xlsx', type: 'array' }) as ArrayBuffer
}

export function kbFileName(kind: KbKind): string {
  return `${kind}.xlsx`
}

export function kindLabel(kind: KbKind): string {
  return KB_KIND_LABELS[kind] ?? kind
}

function str(v: unknown): string {
  if (v == null) return ''
  return String(v)
}

/* ---------- D40 (方案 C)：translation.xlsx 中文例外表头解析（PWA 侧） ----------
 *  与引擎 read_translation（kb_io.read_translation）同语义：
 *    名言/作者/出处/年份/备注 → 逐行拼接"请翻译以下内容…"
 */
const TRANSLATION_HEAD_MAP: Record<string, 'name' | 'author' | 'source' | 'year' | 'note'> = {
  '名言': 'name', '作者': 'author', '出处': 'source',
  '书名': 'source', '年份': 'year', '备注': 'note', '备注2': 'note',
}

export function parseTranslationAoA(aoa: unknown[][]): KbRow[] {
  const rows: KbRow[] = []
  if (!aoa.length) return rows
  const heads = (aoa[0] as unknown[]).map((h) => String(h ?? '').trim())
  const colMap: Record<string, number | undefined> = {}
  heads.forEach((h, i) => {
    const k = TRANSLATION_HEAD_MAP[h]
    if (k && colMap[k] === undefined) colMap[k] = i
  })
  for (let i = 1; i < aoa.length; i++) {
    const r = (aoa[i] as unknown[])
    if (!r || r.length === 0) continue
    const name = colMap.name !== undefined ? String(r[colMap.name] ?? '').trim()
               : String(r[0] ?? '').trim()
    if (!name) continue
    const author = String(colMap.author !== undefined ? r[colMap.author] ?? '' : '').trim()
    const source = String(colMap.source !== undefined ? r[colMap.source] ?? '' : '').trim()
    const year = String(colMap.year !== undefined ? r[colMap.year] ?? '' : '').trim()
    let content = `请翻译以下内容：\n${name} (by ${author}`
    if (source) content += `, ${source}`
    if (year) content += `, ${year}`
    content += '）\n并回答：（1）介绍一下作者及相关理论，'
    content += '（2）结合个人经验谈一谈对上述内容的理解。'
    rows.push({
      id: 'T' + String(i).padStart(3, '0'), content,
      img_path: '', page: '', related: '', type: 'translation',
      solution: '', note: String(colMap.note !== undefined ? r[colMap.note] ?? '' : '').trim(),
    })
  }
  return rows
}

export function isTranslationXlsx(aoa: unknown[][]): boolean {
  if (!aoa.length) return false
  const heads = (aoa[0] as unknown[]).map((h) => String(h ?? '').trim())
  return heads.some((h) => h.includes('名言')) && !heads.some((h) => h === 'id' || h === 'content')
}

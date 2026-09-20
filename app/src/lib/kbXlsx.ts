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

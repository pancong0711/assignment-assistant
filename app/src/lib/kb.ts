/** 题库（kb）数据模型：xlsx 为 source of truth（docs/05-D3）。
 *  列结构保持与 engine `assist kb` 完全兼容：
 *  id / content / img_path / page / related / type / solution / note；
 *  多个 sheet = 多章。 */

/** 题库 kind（分层/题型文件名，不含 .xlsx） */
export const KB_KINDS = [
  'problems',    // 常规作业题
  'copy',        // 抄写/完整性（copy 只查完整性等规则）
  'qa',          // 问答
  'distinguish', // 辨析/防顶替
  'innovation',  // 创新/开放
  'translation', // 翻译（docs/04 §1 提及）
] as const

export type KbKind = (typeof KB_KINDS)[number]

export const KB_KIND_LABELS: Record<KbKind, string> = {
  problems: '常规题 problems',
  copy: '抄写 copy',
  qa: '问答 qa',
  distinguish: '辨析 distinguish',
  innovation: '创新 innovation',
  translation: '翻译 translation',
}

/** 一行 = 一道题（xlsx 一行） */
export interface KbRow {
  id: string
  content: string
  img_path: string
  page: string
  related: string
  type: string
  solution: string
  note: string
}

/** 一个文件 = 一种 kind；一个 sheet = 一章 */
export interface KbChapter {
  /** sheet 名，如 chap10 */
  name: string
  rows: KbRow[]
}

export interface KbBook {
  kind: KbKind
  chapters: KbChapter[]
}

export const KB_COLUMNS: (keyof KbRow)[] = [
  'id', 'content', 'img_path', 'page', 'related', 'type', 'solution', 'note',
]

export const KB_COLUMN_WIDTHS: Record<keyof KbRow, number> = {
  id: 10, content: 50, img_path: 24, page: 8,
  related: 12, type: 12, solution: 40, note: 20,
}

export function emptyRow(id = ''): KbRow {
  return { id, content: '', img_path: '', page: '', related: '', type: '', solution: '', note: '' }
}

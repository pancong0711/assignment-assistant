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

/** 分层标签（tag）——与旧 2603/2601 的学生分组标签 1:1 对齐（docs/04 §1、05-D17）。
 *  summary 没有独立 xlsx（从点名/成绩打标签）；punish 为期末补作业专用（新增强化）。 */
export const STUDENT_TAGS = [
  'copy', 'copySp', 'copyOnly',
  'qa', 'summary',
  'distinguish', 'innovation', 'translation',
  'punish',       // 期末补作业（惩罚作业：统一题集，不按层次分层）
] as const

export const STUDENT_TAG_LABELS: Record<string, string> = {
  copy: '抄写 copy（只查完整性）',
  copySp: '抄写特 copySp',
  copyOnly: '纯抄写 copyOnly',
  qa: '问答 qa',
  summary: '综述 summary',
  distinguish: '辨析 distinguish',
  innovation: '创新 innovation',
  translation: '翻译 translation',
  punish: '补作业 punish（期末统一补交）',
}

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

/* ---------------- D111：题库题号全局唯一（自动章节前缀） ----------------
 * 背景：题号只在**章内**唯一（真实题库里 `01` 在 9 个章节重复），导致答案版本库
 * 按 qid 存储时跨章串味、批阅报告错配。约定题库 id = `<chap>-<原id>`（如 chap04-01）。
 * 与引擎 `files/kb_io.scope_question_id` **同一语义**（parity 自检护航）。 */

/** 片段安全化：去掉路径分隔符/控制字符（与引擎 safe_id_part 同口径）。 */
export function safeIdPart(v: string): string {
  return String(v ?? '').trim().replace(/[\\/:*?"<>|\x00-\x1f]/g, '-').trim()
}

/** `<chap>` + 原始题号 → 全局唯一 id（幂等：已带本章前缀则原样返回）。 */
export function scopeQuestionId(chap: string, qid: string): string {
  const q = safeIdPart(qid)
  if (!q) return ''
  const c = safeIdPart(chap)
  if (!c) return q
  const head = `${c}-`
  if (q === c || q.startsWith(head)) return q
  return `${head}${q}`
}

/** 找出加前缀后仍重复的 id（应视为数据错误）。
 *  计数口径：**出现次数**，因此同一 sheet 内重复（`[a,a]`）与跨 sheet 撞名都能检出。 */
export function findDuplicateIds(chapters: Array<{ name: string; rows: KbRow[] }>): Record<string, string[]> {
  const seen: Record<string, string[]> = {}
  for (const ch of chapters) {
    for (const r of ch.rows) {
      const id = scopeQuestionId(ch.name, r.id)
      if (!id) continue
      ;(seen[id] ||= []).push(ch.name)
    }
  }
  return Object.fromEntries(Object.entries(seen).filter(([, v]) => v.length > 1))
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

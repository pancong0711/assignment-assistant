/** 任务包（taskpad）模型 —— schema 与 docs/04 §1 完全一致。
 *  任务包 = CLI 完整参数 + Web 按钮的后台实体 + 可携带执行记录（docs/05-D2）。
 *  拿到任务包后：`assist sheet make --task <taskpad.json>` 即可出 PDF（D1 CLI 超集）。 */

export type Orientation = 'portrait' | 'landscape'

export interface TaskpadLayoutHeader {
  title?: string
  [k: string]: unknown
}

export interface TaskpadLayoutFooter {
  [k: string]: unknown
}

export interface TaskpadLayout {
  orientation: Orientation
  /** 每页题数：竖版 1 / 横版 2（横版 A4 左右两半各一题，阶段1 已在 engine 落地） */
  per_page: 1 | 2
  header: TaskpadLayoutHeader
  footer: TaskpadLayoutFooter
}

export interface TaskpadItem {
  /** 题库 kind（kb 文件名，不含 .xlsx）：problems/copy/qa/distinguish/innovation... */
  kb: string
  /** 章（sheet 名），如 chap10 */
  chap: string
  /** 题号列表（kb 行 id） */
  ids: string[]
  /** 分层标签 */
  tag: string
}

export interface TaskpadWatermark {
  enabled: boolean
  style: string
}

export interface TaskpadGrade {
  /** 空对象/缺省 = 仅出作业纸，不批阅 */
  steps?: string[]
  students?: { mode: string; tag_value?: string[] }
  models?: { transcription?: string; evaluation?: string }
}

export interface TaskpadJournalEntry {
  ts: string
  run_id: string
  steps_done: string[]
  log: string
}

export interface Taskpad {
  id: string
  /** 相对 workspace 的班级目录，如 classes/2026S1-大学物理-classA；可为空 */
  class_dir: string
  course?: string
  class?: string
  term?: string
  layout: TaskpadLayout
  items: TaskpadItem[]
  watermark: TaskpadWatermark
  /** 可留空 = 仅出作业纸 */
  grade: TaskpadGrade
  journal?: TaskpadJournalEntry[]
}

export function makeTaskpadId(term = '2026S1', classDir = '', chap = 'chap1'): string {
  const cls = classDir.split('/').pop() || 'classA'
  const n = Math.floor(Math.random() * 900) + 100
  return `${term}-${cls}-${chap}-${n}`
}

export function emptyTaskpad(): Taskpad {
  return {
    id: makeTaskpadId(),
    class_dir: '',
    course: '',
    class: '',
    term: '',
    layout: {
      orientation: 'landscape',
      per_page: 2,
      header: { title: '大学物理 作业纸' },
      footer: {},
    },
    items: [],
    watermark: { enabled: true, style: 'default' },
    grade: {},
  }
}

/** 从外部 JSON 解析任务包，做最小校验（容错：grade/journal 可缺省）。 */
export function parseTaskpad(raw: unknown): Taskpad {
  if (typeof raw !== 'object' || raw == null) throw new Error('任务包 JSON 顶层应为对象')
  const o = raw as Record<string, unknown>
  if (typeof o.id !== 'string' || !o.id) throw new Error('任务包缺少 id')
  const layout = (o.layout ?? {}) as Record<string, unknown>
  const orientation = layout.orientation === 'portrait' ? 'portrait' : 'landscape'
  return {
    id: o.id,
    class_dir: typeof o.class_dir === 'string' ? o.class_dir : '',
    course: typeof o.course === 'string' ? o.course : undefined,
    class: typeof o.class === 'string' ? o.class : undefined,
    term: typeof o.term === 'string' ? o.term : undefined,
    layout: {
      orientation,
      per_page: orientation === 'landscape' ? 2 : 1,
      header: (layout.header ?? {}) as TaskpadLayoutHeader,
      footer: (layout.footer ?? {}) as TaskpadLayoutFooter,
    },
    items: Array.isArray(o.items)
      ? (o.items as Record<string, unknown>[]).map((it) => ({
          kb: String(it.kb ?? ''),
          chap: String(it.chap ?? ''),
          ids: Array.isArray(it.ids) ? (it.ids as unknown[]).map(String) : [],
          tag: String(it.tag ?? ''),
        }))
      : [],
    watermark: {
      enabled: Boolean((o.watermark as Record<string, unknown> | undefined)?.enabled ?? true),
      style: String((o.watermark as Record<string, unknown> | undefined)?.style ?? 'default'),
    },
    grade: (o.grade ?? {}) as TaskpadGrade,
    journal: Array.isArray(o.journal) ? (o.journal as TaskpadJournalEntry[]) : [],
  }
}

export function serializeTaskpad(pad: Taskpad): string {
  return JSON.stringify(pad, null, 2)
}

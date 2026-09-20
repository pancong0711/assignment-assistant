/** 任务包（taskpad）模型 —— schema 与 docs/04 §1 完全一致。
 *  任务包 = CLI 完整参数 + Web 按钮的后台实体 + 可携带执行记录（docs/05-D2）。
 *  拿到任务包后：`assist sheet make --task <taskpad.json>` 即可出 PDF（D1 CLI 超集）。
 *  D19 反馈：per_page 可设 1–4（layout.per_page；缺省 竖1横2；竖版为上下行、
 *  横版为左右栏）；引擎帧按 per_page 切分，多题/页时打印版式加实线分隔
 *  （横版=栏间竖线、竖版=行间横线），app 预览同口径。 */

export type Orientation = 'portrait' | 'landscape'

export type PerPage = 1 | 2 | 3 | 4

export interface TaskpadLayoutHeader {
  title?: string
  [k: string]: unknown
}

export interface TaskpadLayoutFooter {
  [k: string]: unknown
}

export interface TaskpadLayout {
  orientation: Orientation
  /** 每页题数 1–4（D19 反馈；缺省 竖1横2；横版 A4 左右栏、竖版上下行） */
  per_page: PerPage
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

/** layout.per_page 规范化：1–4 之外回落到方向缺省（竖1横2），与引擎同口径。 */
export function normalizePerPage(v: unknown, orientation: Orientation): PerPage {
  const n = Number(v)
  if (n === 1 || n === 2 || n === 3 || n === 4) return n
  return orientation === 'landscape' ? 2 : 1
}

/** 从外部 JSON 解析任务包，做最小校验（容错：grade/journal 可缺省；
 *  per_page 1–4，越界/缺失按方向缺省 竖1横2）。 */
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
      per_page: normalizePerPage(layout.per_page, orientation),
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

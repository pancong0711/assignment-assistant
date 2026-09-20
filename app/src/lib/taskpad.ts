/** 任务包（taskpad）模型 —— schema 与 docs/04 §1 完全一致。
 *  任务包 = CLI 完整参数 + Web 按钮的后台实体 + 可携带执行记录（docs/05-D2）。
 *  拿到任务包后：`assist sheet make --task <taskpad.json>` 即可出 PDF（D1 CLI 超集）。
 *  D19 反馈：per_page 可设 1–4（layout.per_page；缺省 竖1横2；竖版为上下行、
 *  横版为左右栏）；引擎帧按 per_page 切分，多题/页时打印版式加实线分隔
 *  （横版=栏间竖线、竖版=行间横线），app 预览同口径。
 *
 *  阶段4a 水印编辑器（D20 方向，父代并线实现 engine list 支持）：
 *  watermark 由 {enabled, style} 升级为 {enabled, style, items:[...]}；
 *  items 为 0..N 项水印图层，每项 {image, pos, ratio, alpha}：
 *  - image：本地图片的 file 相对路径 hint（dataURL 只存浏览器 localStorage，
 *    不进任务包 JSON——任务包可携带、不含内嵌大图）；
 *  - pos：九宫格 3x3（lt/mt/rt/lm/mm/rm/lb/mb/rb），与 engine logo_draw 的
 *    pos_sp 同口径；ratio：相对页宽比例；alpha：透明度 0..1。
 *  兼容 legacy 三槽 university/text/boat：读旧配置时自动映射为 items
 *  （university→pos rt、text→pos lc、boat→pos lb），并保留原字段双写。 */

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

/** 水印九宫格位置（3x3，与 engine logo_draw pos_sp 同口径）。 */
export type WatermarkPos = 'lt' | 'mt' | 'rt' | 'lm' | 'mm' | 'rm' | 'lb' | 'mb' | 'rb'

export const WATERMARK_POS_LABELS: Record<WatermarkPos, string> = {
  lt: '左上', mt: '中上', rt: '右上',
  lm: '左中', mm: '正中', rm: '右中',
  lb: '左下', mb: '中下', rb: '右下',
}

/** 单个水印图层（阶段4a items 列表）。 */
export interface WatermarkItem {
  /** 图片 file 相对路径 hint（如 kb/fig/logo.png；相对 workspace/assets）。
   *  本地上传的 dataURL 只存浏览器，导出时替换为文件名 hint。 */
  image: string
  /** 九宫格位置（3x3） */
  pos: WatermarkPos
  /** 相对页宽比例（engine logo_draw ratio，默认 0.125~0.3 量级） */
  ratio: number
  /** 透明度 0..1（engine logo_draw transparency=1-alpha 量级） */
  alpha: number
}

/** legacy 三槽兼容字段（engine watermark_gen preset "2603" 现行消费的形状）。 */
export interface WatermarkSlotOverride {
  path?: string
  pos?: string
  ratio?: number
  alpha?: number
}

export interface TaskpadWatermark {
  enabled: boolean
  style: string
  /** 页码文字水印开关（engine text_draw"第 n 页"大字；缺省 true） */
  pageText?: boolean
  /** 阶段4a：水印图层列表（0..N 项；为空 = 无自定义图层，引擎走默认三槽） */
  items?: WatermarkItem[]
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
    watermark: { enabled: true, style: 'default', pageText: true, items: [] },
    grade: {},
  }
}

/** layout.per_page 规范化：1–4 之外回落到方向缺省（竖1横2），与引擎同口径。 */
export function normalizePerPage(v: unknown, orientation: Orientation): PerPage {
  const n = Number(v)
  if (n === 1 || n === 2 || n === 3 || n === 4) return n
  return orientation === 'landscape' ? 2 : 1
}

const POS_VALUES = new Set(['lt', 'mt', 'rt', 'lm', 'mm', 'rm', 'lb', 'mb', 'rb'])

function normPos(v: unknown, fallback: WatermarkPos): WatermarkPos {
  return typeof v === 'string' && POS_VALUES.has(v) ? (v as WatermarkPos) : fallback
}

function normRatio(v: unknown, fallback = 0.2): number {
  const n = Number(v)
  return Number.isFinite(n) && n > 0 && n <= 1 ? n : fallback
}

function normAlpha(v: unknown, fallback = 0.5): number {
  const n = Number(v)
  return Number.isFinite(n) && n >= 0 && n <= 1 ? n : fallback
}

/** 解析 watermark 节（兼容三种形状）：
 *  1) 新 items 列表 {enabled, items:[{image,pos,ratio,alpha}]}
 *  2) legacy 三槽覆盖 {enabled, university/text/boat: 路径|{path,pos,ratio,alpha}}
 *     → 自动映射为 items（university→rt、text→lc→lm 最近宫格、boat→lb）
 *  3) 仅 {enabled, style}（阶段2 原始形状） */
export function parseWatermark(raw: unknown): TaskpadWatermark {
  const w = (typeof raw === 'object' && raw != null ? raw : {}) as Record<string, unknown>
  const enabled = w.enabled === undefined ? true : Boolean(w.enabled)
  const style = String(w.style ?? 'default')
  const items: WatermarkItem[] = []
  if (Array.isArray(w.items)) {
    for (const it of w.items as Record<string, unknown>[]) {
      if (!it || typeof it !== 'object') continue
      items.push({
        image: String(it.image ?? ''),
        pos: normPos(it.pos, 'mm'),
        ratio: normRatio(it.ratio),
        alpha: normAlpha(it.alpha),
      })
    }
  } else {
    // legacy 三槽 → items（D20 兼容映射；text 槽旧 pos "lc" 映射到 lm）
    const legacy: Array<[string, WatermarkPos, number, number]> = [
      ['university', 'rt', 0.125, 0.5],
      ['text', 'lm', 0.1, 0.3],
      ['boat', 'lb', 0.3, 0.5],
    ]
    for (const [slot, pos, ratio, alpha] of legacy) {
      const v = w[slot]
      // null/undefined/false/布尔 true（=“用默认槽位”，无自定义图片）/空串：跳过
      if (v === undefined || v === null || typeof v === 'boolean' || v === '') continue
      const o = (typeof v === 'object' ? v : { path: String(v) }) as Record<string, unknown>
      const img = String(o.path ?? o.image ?? (typeof v === 'string' ? v : '') ?? '')
      if (!img) continue
      items.push({
        image: img,
        pos: normPos(o.pos, pos),
        ratio: normRatio(o.ratio, ratio),
        alpha: normAlpha(o.alpha, alpha),
      })
    }
  }
  const pt = w.pageText
  return { enabled, style, pageText: pt === undefined ? true : Boolean(pt), items }
}

/** 从任意 JSON 解析任务包，做最小校验（容错：grade/journal 可缺省；
 *  per_page 1–4，越界/缺失按方向缺省 竖1横2；watermark 兼容 items 与
 *  legacy 三槽，见 parseWatermark）。 */
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
    watermark: parseWatermark(o.watermark),
    grade: (o.grade ?? {}) as TaskpadGrade,
    journal: Array.isArray(o.journal) ? (o.journal as TaskpadJournalEntry[]) : [],
  }
}

/** 导出用的 watermark 节（双写：items 列表 + legacy 三槽兼容字段）。
 *  - items[]：阶段4a 新 schema（engine 按 D20 升级为 list 后直接消费）；
 *  - university/text/boat：engine 现行 preset "2603" 的 overrides 形状
 *    （{path?, pos?, ratio?, alpha?}，engine/src/assist/paper/watermark.py
 *    _watermark_paths/_ovarg），按三槽语义取 items 中对应位置的图层；
 *  - dataURL 图片不进任务包：image 为 file 相对路径 hint（调用方在
 *    DesignerView 把 dataURL 项映射为文件名 hint）。 */
export function watermarkForExport(wm: TaskpadWatermark): Record<string, unknown> {
  const out: Record<string, unknown> = {
    enabled: wm.enabled, style: wm.style,
    pageText: wm.pageText === undefined ? true : wm.pageText,
    items: wm.items ?? [],
  }
  const slots = ['university', 'text', 'boat'] as const
  const posToSlot: Record<WatermarkPos, string> = {
    rt: 'university', mt: 'university', lt: 'university',
    lm: 'text', mm: 'text', rm: 'text',
    lb: 'boat', mb: 'boat', rb: 'boat',
  }
  for (const slot of slots) {
    const hit = (wm.items ?? []).find((it) => posToSlot[it.pos] === slot && it.image)
    if (hit) out[slot] = { path: hit.image, pos: hit.pos, ratio: hit.ratio, alpha: hit.alpha }
  }
  return out
}

/** 任务包导出序列化：watermark 双写 items + 三槽兼容字段（向后兼容
 *  engine 已实现的三槽消费，见 watermarkForExport）。 */
export function serializeTaskpad(pad: Taskpad): string {
  const payload: Record<string, unknown> = {
    id: pad.id,
    class_dir: pad.class_dir,
    course: pad.course,
    class: pad.class,
    term: pad.term,
    layout: pad.layout,
    items: pad.items,
    watermark: watermarkForExport(pad.watermark),
    grade: pad.grade,
  }
  if (pad.journal?.length) payload.journal = pad.journal
  return JSON.stringify(payload, null, 2)
}

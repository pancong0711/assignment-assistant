/** 作业纸（taskpad）模型 —— schema 与 docs/04 §1 完全一致。
 *  作业纸 = CLI 完整参数 + Web 按钮的后台实体 + 可携带执行记录（docs/05-D2）。
 *  拿到作业纸后：`assist sheet make --task <taskpad.json>` 即可出 PDF（D1 CLI 超集）。
 *  D61（取代 D19/D53 的固定档位）：per_page = 每页题数 N（1..12），
 *  grid_rows/grid_cols = 显式网格（缺省时兼容旧任务：竖版 2/3/4=rowsN、
 *  横版 2/3=colsN、4=2×2）。竖版帧按行优先、横版按列优先；rows×cols≥N，
 *  多余格留空（空位在阅读顺序末尾），app/HTML/PDF 三端同口径。
 *
 *  阶段4a 水印编辑器（D20 方向，父代并线实现 engine list 支持）：
 *  watermark 由 {enabled, style} 升级为 {enabled, style, items:[...]}；
 *  items 为 0..N 项水印图层，每项 {image, pos, ratio, alpha}：
 *  - image：本地图片的 file 相对路径 hint（dataURL 只存浏览器 localStorage，
 *    不进作业纸 JSON——作业纸可携带、不含内嵌大图）；
 *  - pos：九宫格 3x3（lt/mt/rt/lm/mm/rm/lb/mb/rb），与 engine logo_draw 的
 *    pos_sp 同口径；ratio：相对页宽比例；alpha：透明度 0..1。
 *  兼容 legacy 三槽 university/text/boat：读旧配置时自动映射为 items
 *  （university→pos rt、text→pos lc、boat→pos lb），并保留原字段双写。 */

export type Orientation = 'portrait' | 'landscape'

export type PerPage = number
export const MAX_PER_PAGE = 12
export const MAX_GRID_DIM = 12

export interface TaskpadLayoutHeader {
  title?: string
  [k: string]: unknown
}

export interface TaskpadLayoutFooter {
  [k: string]: unknown
}

export interface TaskpadLayout {
  orientation: Orientation
  /** 每页题数 1..MAX_PER_PAGE（缺省 竖1横2；显式网格由 grid_rows/grid_cols 控制） */
  per_page: PerPage
  /** D61：显式网格行数；缺省（旧任务）按 orientation+per_page 兼容推导 */
  grid_rows?: number
  /** D61：显式网格列数；缺省（旧任务）按 orientation+per_page 兼容推导 */
  grid_cols?: number
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
  /** D23 变体编排：作业纸绑定的学生分组 tag（engine batch pad_tag 首选字段）。
   *  为空 = 由 items 的唯一 tag 推断；混合 tag 包须显式标注（否则引擎报
   *  "未与唯一 tag 绑定"）。仅显式指定时写入 JSON（空值不写字段，兼容引擎）。 */
  target_tag?: string
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
      grid_rows: 1,
      grid_cols: 2,
      header: { title: '大学物理 作业纸' },
      footer: {},
    },
    items: [],
    watermark: { enabled: true, style: 'default', pageText: true, items: [] },
    grade: {},
  }
}

/** layout.per_page 规范化：1..MAX_PER_PAGE 之外回落到方向缺省（竖1横2），与引擎同口径。 */
export function normalizePerPage(v: unknown, orientation: Orientation): PerPage {
  const n = Number(v)
  if (Number.isInteger(n) && n >= 1 && n <= MAX_PER_PAGE) return n
  return orientation === 'landscape' ? 2 : 1
}

export interface ResolvedGrid {
  rows: number
  cols: number
  perPage: number
  order: 'row' | 'col'
  capacity: number
  empty: number
  legacy: boolean
}

/** 旧任务包（无 grid_rows/grid_cols）兼容网格：竖版 2/3/4=rowsN；横版 2/3=colsN、4=2x2。 */
export function legacyGrid(orientation: Orientation, perPage: number): { rows: number; cols: number } {
  if (perPage <= 1) return { rows: 1, cols: 1 }
  if (orientation === 'portrait') return { rows: perPage, cols: 1 }
  if (perPage === 4) return { rows: 2, cols: 2 }
  return { rows: 1, cols: perPage }
}

/** D61 新 UI 默认：N/2 x 2（N=1 特例 1x1）。 */
export function defaultGrid(perPage: number): { rows: number; cols: number } {
  if (perPage <= 1) return { rows: 1, cols: 1 }
  return { rows: Math.max(1, Math.ceil(perPage / 2)), cols: 2 }
}

/** 均匀方阵：因子对里选最接近平方的一对；质数回退 1xN。 */
export function autoSquareGrid(perPage: number): { rows: number; cols: number } {
  if (perPage <= 1) return { rows: 1, cols: 1 }
  let best = { rows: 1, cols: perPage }
  let bestDelta = Math.abs(1 - perPage)
  for (let r = 2; r <= Math.floor(Math.sqrt(perPage)); r++) {
    if (perPage % r) continue
    const c = perPage / r
    const delta = Math.abs(r - c)
    if (delta < bestDelta || (delta === bestDelta && r < best.rows)) {
      best = { rows: r, cols: c }; bestDelta = delta
    }
  }
  return best
}

function positiveDim(v: unknown): number | undefined {
  const n = Number(v)
  return Number.isInteger(n) && n >= 1 && n <= MAX_GRID_DIM ? n : undefined
}

/** 解析实际网格：显式 rows×cols 合法且容量>=perPage 时使用；否则回退旧兼容网格。 */
export function resolveGrid(layout: Pick<TaskpadLayout, 'orientation' | 'per_page' | 'grid_rows' | 'grid_cols'>): ResolvedGrid {
  const perPage = normalizePerPage(layout.per_page, layout.orientation)
  const rows = positiveDim(layout.grid_rows)
  const cols = positiveDim(layout.grid_cols)
  let legacy = false
  let r = rows
  let c = cols
  if (!r || !c || r * c < perPage) {
    legacy = true
    const g = legacyGrid(layout.orientation, perPage)
    r = g.rows; c = g.cols
  }
  return {
    rows: r!, cols: c!, perPage,
    order: layout.orientation === 'portrait' ? 'row' : 'col',
    capacity: r! * c!,
    empty: Math.max(0, r! * c! - perPage),
    legacy,
  }
}

/** 内部虚线：返回 {dir, style}（与 engine paper/grid.grid_line_styles 同口径）。 */
export function gridLineStyles(rows: number, cols: number): Array<{ dir: 'v' | 'h'; style: string }> {
  const out: Array<{ dir: 'v' | 'h'; style: string }> = []
  for (let i = 1; i < cols; i++) {
    out.push({ dir: 'v', style: `left:${Math.round(i * 10000 / cols) / 100}%` })
  }
  for (let j = 1; j < rows; j++) {
    out.push({ dir: 'h', style: `top:${Math.round(j * 10000 / rows) / 100}%` })
  }
  return out
}

/** HTML .sheet-body 内联 CSS Grid 样式（PWA/j2 同口径）。 */
export function gridBodyStyle(rows: number, cols: number, order: 'row' | 'col'): string {
  const flow = order === 'col' ? 'column' : 'row'
  return `display:grid;grid-template-columns:repeat(${cols}, minmax(0, 1fr));grid-template-rows:repeat(${rows}, minmax(0, 1fr));grid-auto-flow:${flow};`
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

/** 从任意 JSON 解析作业纸，做最小校验（容错：grade/journal 可缺省；
 *  per_page 1..MAX_PER_PAGE，越界/缺失按方向缺省 竖1横2；
 *  grid_rows/grid_cols 可选，非法/缺失时渲染层走 legacy 兼容网格；
 *  watermark 兼容 items 与 legacy 三槽，见 parseWatermark）。 */
export function parseTaskpad(raw: unknown): Taskpad {
  if (typeof raw !== 'object' || raw == null) throw new Error('作业纸 JSON 顶层应为对象')
  const o = raw as Record<string, unknown>
  if (typeof o.id !== 'string' || !o.id) throw new Error('作业纸缺少 id')
  const layout = (o.layout ?? {}) as Record<string, unknown>
  const orientation = layout.orientation === 'portrait' ? 'portrait' : 'landscape'
  return {
    id: o.id,
    class_dir: typeof o.class_dir === 'string' ? o.class_dir : '',
    course: typeof o.course === 'string' ? o.course : undefined,
    class: typeof o.class === 'string' ? o.class : undefined,
    term: typeof o.term === 'string' ? o.term : undefined,
    target_tag: typeof o.target_tag === 'string' && o.target_tag ? o.target_tag : undefined,
    layout: {
      orientation,
      per_page: normalizePerPage(layout.per_page, orientation),
      grid_rows: positiveDim(layout.grid_rows),
      grid_cols: positiveDim(layout.grid_cols),
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
 *  - dataURL 图片不进作业纸：image 为 file 相对路径 hint（调用方在
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

/** 作业纸导出序列化：watermark 双写 items + 三槽兼容字段（向后兼容
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
  // D23：为空不写 target_tag 字段，保持与缺字段的作业纸（engine 兼容）完全一致
  if (pad.target_tag) payload.target_tag = pad.target_tag
  if (pad.journal?.length) payload.journal = pad.journal
  return JSON.stringify(payload, null, 2)
}

/* ---------- D23 变体编排纯逻辑（与 engine paper/batch.py 同口径） ---------- */

/** 作业纸归属 tag 推断，镜像 engine `pad_tag`：target_tag 优先；items 唯一
 *  tag 次之；无任何 tag → 'default'；混合 tag → null（需显式绑定/映射）。 */
export function padInferredTag(items: TaskpadItem[], targetTag?: string): string | null {
  if (targetTag) return targetTag
  const tags = [...new Set(items.map((i) => String(i.tag ?? '')).filter(Boolean))].sort()
  if (tags.length === 1) return tags[0]
  if (tags.length === 0) return 'default'
  return null
}

/** 绑定记录（变体编排视图行）：tag 为空 = 未绑定（回退到 items 推断）。 */
export interface PadBinding {
  id: string
  /** 下拉绑定（target_tag 绑定值；'' = 未显式绑定） */
  binding: string
  items: TaskpadItem[]
}

/** 解析实际生效 tag：binding 优先，否则 items 推断（可缺 = 未绑定）。 */
export function resolveBindTag(b: PadBinding): string | null {
  if (b.binding) return b.binding
  return padInferredTag(b.items)
}

/** 名单 tag 分布中缺包的 tag：名单里有该 tag 的学生、但没有任何作业纸
 *  实际绑定/可推断到它（engine 会 log warning 跳过这些人；前端给出
 *  "可加 --default 兜底"或补绑定的黄色提示）。 */
export function missingBoundTags(
  tagCounts: Record<string, number>,
  bindings: PadBinding[],
): string[] {
  const bound = new Set(bindings.map((b) => resolveBindTag(b)).filter((t): t is string => Boolean(t)))
  return Object.keys(tagCounts).filter((t) => t && !bound.has(t))
}

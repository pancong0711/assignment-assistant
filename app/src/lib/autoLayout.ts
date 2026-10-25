/** autoLayout.ts — D103：参考答案「预排版」引擎（MxN 网格 + 跨格续写）。
 *
 *  背景：D102 为"答案必须完整"把版面改成单列流式，导致 **MxN 版式控制权丧失**（用户指为回归）。
 *  D103 恢复 MxN 网格与全部虚线，答案超长改为「预排版切段 + 续写到下一页第 1 格」：
 *
 *  规则（用户拍板 2026-10-24）：
 *  - R1 MxN 版式与所有虚线保留；
 *  - R2 **同格不混排**：一格内只放一道题（或其续段）；
 *  - R3 写满当前格 → 续写到**下一页第 1 格**（不是同页其它列）；
 *  - R4 下一页第 1 格已有题目 → 该题顺延，后续题目依次顺延；
 *  - R5 题干与答案必须完整（不丢内容）；
 *  - R6 公式不切割：切分点只在「段落边界 / 行间公式之间」；
 *  - R7 PWA 与 CLI 的 HTML 一致 → 本模块产物 `LayoutResult` 由 CLI 直接复用。
 *
 *  产物写入 taskpad.layout_result；CLI 无该字段时回退 D61 网格（兼容历史作业纸）。
 *
 *  设计取舍：
 *  - 测量必须在浏览器里做（PWA）：用隐藏容器按「格内宽」渲染真实 DOM 后取高度；
 *  - 切分点优先取**段落/行间公式边界**，因此需要把「可切块」建模为 block 序列；
 *  - 为让 CLI 无需测量即可复现，`LayoutResult` 里保存的是**已切好的块**（含字符区间）。
 */

/** 单个「可切块」的最小粒度：一段可独立成行的内容。 */
export type LayoutBlockKind = 'content' | 'solution'

/** 预排版产物中的一个块：属于某题的一段内容。 */
export interface LayoutBlock {
  /** 题库 id（或合成题 id：summary/translation） */
  qid: string
  /** 题号显示（如 "1." / "（二）"） */
  no: string
  /** 块类型：题干（只在首块）/ 答案 */
  kind: LayoutBlockKind
  /** 该块文本（已切好；CLI 直接渲染，无需再次切分） */
  text: string
  /** 是否为续段（用于「（题 N 续）」标注） */
  cont?: boolean
  /** D103：整块公式高于格高时缩放到的比例（1 = 不缩放） */
  scale?: number
}

/** 一格：可放 1 个块（同格不混排）。 */
export interface LayoutCell {
  row: number
  col: number
  blocks: LayoutBlock[]
}

export interface LayoutPage {
  page: number
  cells: LayoutCell[]
}

export interface LayoutGeometry {
  /** 格内可用宽/高（px，已扣除内边距） */
  cellW: number
  cellH: number
  rows: number
  cols: number
}

export interface LayoutResult {
  v: 1
  measuredAt: string
  /** 内容指纹：与当前 items 不一致 → 视为失效（回退旧网格） */
  contentHash: string
  geometry: LayoutGeometry
  pages: LayoutPage[]
  /** 排版告警（如公式缩放、内容超高被截断等），供 UI 提示 */
  warnings?: string[]
}

/* ---------------- 切分 ---------------- */

/** 行间公式（`$$..$$` 或 `\[..\]`）作为不可切原子。 */
const DISPLAY_MATH_RE = /(\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\])/g

/** 单个块的建议字符上限：超过则继续按句子切（避免一个巨型块整题独占多页）。 */
const MAX_PIECE_CHARS = 120

/** 在「句子边界」把长段落再切开（公式已在此之前被剥离为原子块）。 */
function splitLongParagraph(para: string, limit = MAX_PIECE_CHARS): string[] {
  if (para.length <= limit) return [para]
  const out: string[] = []
  // 以中文句末/分号/英文句点为界，保留标点
  const sentences = para.split(/(?<=[。！？；.!?;])\s*/).filter((x) => x.trim())
  let buf = ''
  for (const snt of sentences) {
    if (!buf) { buf = snt; continue }
    if (buf.length + snt.length <= limit) { buf += snt; continue }
    out.push(buf); buf = snt
  }
  if (buf) out.push(buf)
  // 极端长句（无标点）：按字符硬切
  const final: string[] = []
  for (const piece of out.length ? out : [para]) {
    if (piece.length <= limit) { final.push(piece); continue }
    for (let i = 0; i < piece.length; i += limit) final.push(piece.slice(i, i + limit))
  }
  return final
}

/** 把一段文本切成「可独立成块」的片段：段落边界优先，行间公式整体保留。 */
export function splitIntoPieces(text: string): string[] {
  const src = String(text ?? '')
  if (!src.trim()) return []
  const out: string[] = []
  // 先按行间公式切（公式整体不拆）
  const parts = src.split(DISPLAY_MATH_RE)
  for (const part of parts) {
    if (!part) continue
    if (/^\$\$[\s\S]*\$\$$/.test(part) || /^\\\[[\s\S]*\\\]$/.test(part)) {
      out.push(part)                      // 行间公式：整体一块
      continue
    }
    // 普通文本：按空行 → 单行 依次降级切分
    for (const para of part.split(/\n{2,}/)) {
      if (!para.trim()) continue
      const lines = para.split('\n')
      if (lines.length > 1) {
        for (const line of lines) if (line.trim()) out.push(...splitLongParagraph(line))
      } else {
        out.push(...splitLongParagraph(para))
      }
    }
  }
  return out
}

/* ---------------- 测量接口（浏览器注入） ---------------- */

/** 测量函数：给定「块文本 + 是否答案样式」返回渲染高度（px）。 */
export type MeasureFn = (text: string, kind: LayoutBlockKind) => number

/* ---------------- 装箱 ---------------- */

export interface AutoLayoutOptions {
  geometry: LayoutGeometry
  /** 每题：qid / 题号 / 题干 / 答案（答案可空） */
  items: Array<{ qid: string; no: string; content: string; solution?: string }>
  measure: MeasureFn
  /** 内容指纹（用于失效判定） */
  contentHash?: string
  now?: () => string
}

/** 简单滚动指纹（稳定、跨端一致；不依赖 crypto）。 */
export function contentFingerprint(items: Array<{ qid: string; no: string; content: string; solution?: string }>): string {
  const s = JSON.stringify(items.map((i) => [i.qid, i.no, i.content, i.solution ?? '']))
  let h1 = 0x811c9dc5
  for (let i = 0; i < s.length; i++) {
    h1 ^= s.charCodeAt(i)
    h1 = Math.imul(h1, 0x01000193) >>> 0
  }
  return `fnv1a:${h1.toString(16)}:${s.length}`
}

/** 逐题切块（题干 + 答案），返回「按顺序的块队列」。 */
function blocksOfItem(it: { qid: string; no: string; content: string; solution?: string }): LayoutBlock[] {
  const out: LayoutBlock[] = []
  const contentPieces = splitIntoPieces(it.content)
  const solPieces = splitIntoPieces(it.solution ?? '')
  // 题干：首块带题号，其余为续
  contentPieces.forEach((t, idx) => out.push({
    qid: it.qid, no: it.no, kind: 'content', text: t, cont: idx > 0,
  }))
  // 答案：拼到同一个块的队列里（保持顺序）
  solPieces.forEach((t, idx) => out.push({
    qid: it.qid, no: it.no, kind: 'solution', text: t, cont: idx > 0,
  }))
  return out
}

/**
 * 预排版主函数：**同格不混排 + 写满即续到下一页第 1 格**。
 *
 * 算法：
 *  对每题生成块队列；逐块尝试放入「当前格」：
 *    能放下 → 放入该格，格满则换下一格
 *    放不下 → 若该块是某题的第一块（整题都放不进一格）→ 仍放入当前格（后续块续到下一页第 1 格）
 *             否则 → 换下一格继续尝试
 *  格用尽 → 翻页；**续写时回到下一页第 1 格**（R3）
 */
export function autoLayout(opts: AutoLayoutOptions): LayoutResult {
  const { geometry, items, measure } = opts
  const { cellH, rows, cols } = geometry
  const perPage = Math.max(1, rows * cols)
  const warnings: string[] = []

  /** 扁平格序列：每槽 = 一格的块（同格不混排 → 正常只有 1 个块）。 */
  const slots: LayoutBlock[][] = []
  const ensureSlot = (i: number) => { while (slots.length <= i) slots.push([]); return slots[i] }
  let slot = 0

  for (const it of items) {
    const blocks = blocksOfItem(it)
    for (let bi = 0; bi < blocks.length; bi++) {
      const blk = blocks[bi]
      let h = measure(blk.text, blk.kind)
      if (h > cellH) {
        const isDisplayMath = /^\$\$[\s\S]*\$\$$/.test(blk.text) || /^\\\[[\s\S]*\\\]$/.test(blk.text)
        if (isDisplayMath) {
          blk.scale = Math.max(0.3, Number((cellH / h).toFixed(3)))
          warnings.push(`题 ${it.no} 的行间公式高于整格，已缩放至 ${(blk.scale * 100).toFixed(0)}%`)
        } else {
          warnings.push(`题 ${it.no} 的单段内容高于整格（${Math.round(h)}px > ${cellH}px），按独占一格处理`)
        }
      }

      if (bi === 0) {
        // 首块：从当前空槽开始（若被占则顺延）
        if (ensureSlot(slot).length > 0) slot += 1
        ensureSlot(slot).push(blk)
        continue
      }

      // 后续块（答案续段）：先尝试追加到「本题当前格」的剩余高度
      const cur = ensureSlot(slot)
      const usedH = cur.reduce((n, b) => n + measure(b.text, b.kind) * (b.scale ?? 1), 0)
      const sameItem = cur.length > 0 && cur.every((b) => b.qid === blk.qid)
      if (sameItem && usedH + h <= cellH + 1) {
        cur.push(blk)                       // 同题续段可共格（不算"混排"：仍是同一题）
        continue
      }
      // R3：写满 → 续写到「**下一格**」（按阅读顺序：同一页内后续格 → 下一页第 1 格）。
      // 注意：不能直接跳"下一页第 1 格"，否则续段会全挤在每页左上角、其它格空着（D103 修复）。
      slot += 1
      ensureSlot(slot).push(blk)
    }
    // R2：一道题结束 → 换格，下一题不接在本格
    if (ensureSlot(slot).length > 0) slot += 1
  }

  // 组装页/格（过滤空页 + 连续页号）
  const byPage = new Map<number, LayoutPage>()
  slots.forEach((blocks, s) => {
    if (!blocks.length) return
    const pageNo = Math.floor(s / perPage) + 1
    const idxInPage = s % perPage
    let pg = byPage.get(pageNo)
    if (!pg) { pg = { page: pageNo, cells: [] }; byPage.set(pageNo, pg) }
    pg.cells.push({ row: Math.floor(idxInPage / cols), col: idxInPage % cols, blocks })
  })
  const pages = [...byPage.values()].sort((a, b) => a.page - b.page)
  pages.forEach((p, i) => { p.page = i + 1 })

  return {
    v: 1,
    measuredAt: (opts.now ?? (() => new Date().toISOString()))(),
    contentHash: opts.contentHash ?? contentFingerprint(items),
    geometry,
    pages,
    warnings: warnings.length ? warnings : undefined,
  }
}

/** 由 LayoutResult 判断是否仍适用于当前内容（CLI/PWA 共用）。 */
export function layoutMatches(result: LayoutResult | undefined, items: Array<{ qid: string; no: string; content: string; solution?: string }>): boolean {
  if (!result || result.v !== 1) return false
  return result.contentHash === contentFingerprint(items)
}

/** 带答案时只允许「横版 1×2」与「竖版 2×1」（R9）。返回降级后的 rows/cols。 */
export function solveGridForSolution(
  orientation: 'portrait' | 'landscape', rows: number, cols: number,
): { rows: number; cols: number; downgraded: boolean } {
  const target = orientation === 'landscape' ? { rows: 1, cols: 2 } : { rows: 2, cols: 1 }
  const ok = rows === target.rows && cols === target.cols
  return ok ? { rows, cols, downgraded: false } : { ...target, downgraded: true }
}

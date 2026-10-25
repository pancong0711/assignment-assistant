/** measureLayout.ts — D103：在浏览器里测量并生成 `layout_result`（T5 自动重排）。
 *
 *  为什么必须测：CSS 无法表达"答案跨格续写"，切分点必须知道每块真实渲染高度。
 *  测量方式：离屏容器（与格内宽一致、与 .q-solution 同字号），渲染 + KaTeX 后取
 *  `getBoundingClientRect().height`。
 *
 *  只在 PWA 运行（CLI 直接复用产物，无需浏览器）——满足 R7「PWA 与 CLI HTML 一致」。
 */
import { autoLayout, solveGridForSolution, type LayoutResult } from './autoLayout'
import { renderMathIn } from './katexRender'
import { resolveGrid, type Taskpad } from './taskpad'
import type { SheetHtmlItem } from './sheetHtml'

/** 格内可用尺寸（px）：A4 纵向 296mm / 横向 209mm，扣除页边距与题框内边距后的近似值。 */
const MM_PER_PX = 25.4 / 96

export function cellGeometry(orientation: 'portrait' | 'landscape'): { cellW: number; cellH: number; rows: number; cols: number } {
  // 与 printCss 一致：.sheet-page padding 12mm 14mm；.sheet-frame padding 3mm(4mm divided)
  const pageWmm = orientation === 'landscape' ? 297 : 210
  const pageHmm = orientation === 'landscape' ? 209 : 296
  const padXmm = 14 * 2
  const padYmm = 12 * 2
  const headerMm = 18          // 页眉（标题 + 信息行）估算
  const footerMm = 12          // 页脚
  const framePadMm = 4 * 2     // divided 题框内边距
  const innerW = pageWmm - padXmm
  const innerH = pageHmm - padYmm - headerMm - footerMm
  // 带答案时：横版 1x2 / 竖版 2x1（R9）
  const g = orientation === 'landscape' ? { rows: 1, cols: 2 } : { rows: 2, cols: 1 }
  return {
    cellW: Math.max(120, Math.round((innerW / g.cols - framePadMm) / MM_PER_PX)),
    cellH: Math.max(120, Math.round((innerH / g.rows - framePadMm) / MM_PER_PX)),
    rows: g.rows, cols: g.cols,
  }
}

/** 创建离屏测量容器（宽度 = 格内宽，样式对齐 .q-content/.q-solution）。 */
function createProbe(cellW: number): HTMLDivElement {
  const el = document.createElement('div')
  el.setAttribute('data-d103-probe', '1')
  el.style.cssText = [
    'position:absolute', 'left:-10000px', 'top:0', `width:${cellW}px`,
    'font-size:10pt', 'line-height:1.5', 'white-space:pre-wrap', 'word-break:break-word',
    'visibility:hidden', 'pointer-events:none',
  ].join(';')
  document.body.appendChild(el)
  return el
}

/** 测量一块的渲染高度（含 KaTeX）。 */
async function makeMeasure(cellW: number): Promise<{ measure: (t: string, k: 'content' | 'solution') => number; dispose: () => void }> {
  const probe = createProbe(cellW)
  const cache = new Map<string, number>()
  const measure = (text: string, kind: 'content' | 'solution') => {
    const key = `${kind}::${text}`
    const hit = cache.get(key)
    if (hit !== undefined) return hit
    probe.style.fontSize = kind === 'content' ? '11.5pt' : '10pt'
    probe.textContent = text
    // 公式渲染（同步；renderMathIn 是异步的，这里直接调 auto-render 以获得同步高度）
    const fn = (window as unknown as { renderMathInElement?: (e: Element, o: unknown) => void }).renderMathInElement
    if (fn) {
      const B = String.fromCharCode(92)
      try {
        fn(probe, { delimiters: [
          { left: '$$', right: '$$', display: true },
          { left: B + '[', right: B + ']', display: true },
          { left: '$', right: '$', display: false },
          { left: B + '(', right: B + ')', display: false },
        ], throwOnError: false })
      } catch { /* 降级：按纯文本高度 */ }
    }
    const h = probe.getBoundingClientRect().height
    probe.textContent = ''
    cache.set(key, h)
    return h
  }
  return { measure, dispose: () => probe.remove() }
}

export interface ReflowResult { layout: LayoutResult; downgraded: boolean }

/**
 * 生成某作业纸的预排版结果（T5）。仅在「带参考答案」时启用（R9）；
 * 无答案时返回旧网格行为所需的最少信息（downgraded=false + 空 pages 表示不启用）。
 */
export async function reflowPad(pad: Taskpad, items: SheetHtmlItem[]): Promise<ReflowResult | null> {
  const g0 = resolveGrid(pad.layout)
  const orientation = pad.layout.orientation === 'landscape' ? 'landscape' : 'portrait'
  const { rows, cols, downgraded } = solveGridForSolution(orientation, g0.rows, g0.cols)
  const geo = cellGeometry(orientation)
  // 确保 KaTeX 资源就绪（否则公式按源码测高，会偏小）
  try { await renderMathIn(document.createElement('div')) } catch { /* 忽略 */ }
  const { measure, dispose } = await makeMeasure(geo.cellW)
  try {
    const layout = autoLayout({
      geometry: { cellW: geo.cellW, cellH: geo.cellH, rows, cols },
      items: items.map((it) => ({
        qid: it.id, no: String(it.no ?? ''), content: String(it.content ?? ''), solution: it.solution ?? '',
      })),
      measure,
    })
    return { layout, downgraded }
  } finally {
    dispose()
  }
}

/** 判断某作业纸是否应启用预排版（带答案 → 启用）。 */
export function shouldReflow(pad: Taskpad, includeSolution: boolean): boolean {
  return includeSolution && pad.items.length > 0
}

/** katexRender.ts — D101：PWA 内联区域的 KaTeX 渲染（题库编辑器等非 iframe 场景）。
 *
 *  与打印模板（`sheetHtml.ts:katexScript` / `assignment.html.j2`）**同一套定界符**：
 *  `$$..$$`（display）、`\[..\]`（display）、`$..$`、`\(..\)`；长定界符在前
 *  （避免 `$$x$$` 被 `$..$` 拆成两个行内公式）。
 *
 *  设计：
 *  - 资源走 PWA 同源自托管 `./katex/`（随 dist 发布，离线可用；docs/13 D43-3）；
 *  - 懒加载 + 模块级 Promise 缓存（多次调用只注入一次 <link>/<script>）；
 *  - 渲染**幂等**：已渲染元素打 `data-katex-done="1"`，重复调用不重复处理（KaTeX 二次
 *    渲染会破坏已生成的 DOM）；
 *  - 任何失败都**静默降级**为源码（教师仍能读到 LaTeX 原文），绝不抛错阻断 UI。
 */
import { KATEX_VERSION } from './sheetHtml'

/** KaTeX auto-render 的定界符配置（与打印模板逐字同口径）。 */
export const KATEX_DELIMITERS = [
  { left: '$$', right: '$$', display: true },
  { left: '\\[', right: '\\]', display: true },
  { left: '$', right: '$', display: false },
  { left: '\\(', right: '\\)', display: false },
] as const

export const KATEX_OPTS = { delimiters: KATEX_DELIMITERS as unknown as
  Array<{ left: string; right: string; display: boolean }>, throwOnError: false }

/** 已渲染标记属性（幂等依据）。 */
export const KATEX_DONE_ATTR = 'data-katex-done'
/** 原始 HTML 快照属性（force 重渲染前据此还原，避免在 KaTeX DOM 上二次渲染）。
 *  D111：必须存 **innerHTML**（含标签），不能只存 textContent，否则会丢示意图/表格。 */
export const KATEX_SRC_ATTR = 'data-katex-src'

let katexLoad: Promise<boolean> | null = null

/** 确保 KaTeX + auto-render 已就绪（幂等）。返回 false = 资源不可用（调用方降级）。 */
export function ensureKatex(): Promise<boolean> {
  if (katexLoad) return katexLoad
  katexLoad = (async () => {
    if (typeof window === 'undefined') return false
    const hasFn = () => typeof (window as unknown as { renderMathInElement?: unknown })
      .renderMathInElement === 'function'
    if (hasFn()) return true
    const base = new URL('./katex/', document.baseURI)
    try {
      if (!document.querySelector('link[data-katex="1"]')) {
        const css = document.createElement('link')
        css.rel = 'stylesheet'
        css.href = new URL('katex.min.css', base).href
        css.setAttribute('data-katex', '1')
        document.head.appendChild(css)
      }
      /** 顺序注入：katex.min.js 必须先于 auto-render（后者依赖 window.katex）。 */
      const inject = (file: string) => new Promise<void>((resolve, reject) => {
        const s = document.createElement('script')
        s.src = new URL(file, base).href
        s.setAttribute('data-katex', '1')
        s.onload = () => resolve()
        s.onerror = () => reject(new Error(`KaTeX 资源不可达：${file}`))
        document.head.appendChild(s)
      })
      if (typeof (window as unknown as { katex?: unknown }).katex === 'undefined') {
        await inject('katex.min.js')
      }
      if (!hasFn()) await inject('contrib/auto-render.min.js')
      return hasFn()
    } catch {
      return false
    }
  })()
  return katexLoad
}

/** 就地渲染元素内公式（幂等、不抛错）。返回是否真的做了渲染。 */
export async function renderMathIn(el: Element | null | undefined, force = false): Promise<boolean> {
  if (!el) return false
  if (!force && el.getAttribute(KATEX_DONE_ATTR) === '1') return false
  const ok = await ensureKatex()
  if (!ok) return false
  const fn = (window as unknown as { renderMathInElement?: (e: Element, o: unknown) => void })
    .renderMathInElement
  if (typeof fn !== 'function') return false
  try {
    // D111：重渲染前用 **innerHTML** 还原，绝不能用 textContent。
    // 旧实现 `el.textContent = original` 会把"文本快照"写回元素，
    // 直接抹掉全部标签结构：<svg> 消失（→"未见示意图"）、表格塌成一行、
    // KaTeX 生成的 MathML+HTML 双份文本被拼在一起（→ "F=maF=ma"，看着像文字截断/重复）。
    if (force && el.hasAttribute(KATEX_DONE_ATTR)) {
      const original = el.getAttribute(KATEX_SRC_ATTR)
      if (original !== null) el.innerHTML = original
    }
    const src = el.innerHTML
    fn(el, KATEX_OPTS)
    el.setAttribute(KATEX_DONE_ATTR, '1')
    el.setAttribute(KATEX_SRC_ATTR, src)   // 记住原始 **HTML**，供下次 force 重渲染还原
    return true
  } catch {
    return false
  }
}

/** 批量渲染（选择器 → 元素列表；跳过已渲染）。 */
export async function renderMathInAll(selector: string): Promise<number> {
  const els = Array.from(document.querySelectorAll(selector))
  let n = 0
  for (const el of els) if (await renderMathIn(el)) n += 1
  return n
}

/** 供界面显示："公式渲染资源版本"（排查用）。 */
export const KATEX_RENDER_VERSION = KATEX_VERSION

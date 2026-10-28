/** richdoc.ts — D105：参考答案 md+html 的安全渲染与纯文本派生（PWA 侧）。
 *
 *  与引擎 `engine/src/assist/paper/richdoc.py` **同一份白名单**（双端一致）。
 *
 *  - 输入：Markdown + HTML 白名单子集（SVG / data:image / 表格 / 列表…）
 *  - 输出：可安全插入 DOM 的 HTML（先 markdown-it 解析，再 DOMPurify 白名单净化）
 *  - 纯文本：`stripMarkup()` 供检索 / Excel 摘要 / xlsx solution 列
 */
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'

/** 允许的标签（与 Python ALLOWED_TAGS 逐项对齐）。 */
export const ALLOWED_TAGS = [
  'p', 'br', 'hr', 'div', 'span', 'blockquote', 'pre', 'code',
  'strong', 'b', 'em', 'i', 'del', 's', 'sub', 'sup', 'u',
  'ul', 'ol', 'li', 'dl', 'dt', 'dd',
  'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'caption', 'colgroup', 'col',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'img',
  'svg', 'g', 'path', 'line', 'rect', 'circle', 'ellipse', 'polygon',
  'polyline', 'text', 'tspan', 'defs', 'marker', 'title', 'desc',
]

/** 允许的属性（与 Python ALLOWED_ATTRS 对齐）。 */
export const ALLOWED_ATTRS = [
  'class', 'title', 'alt', 'src', 'width', 'height', 'colspan', 'rowspan',
  'align', 'valign', 'scope',
  'viewBox', 'viewbox', 'xmlns', 'd', 'fill', 'stroke', 'stroke-width',
  'stroke-linecap', 'stroke-linejoin', 'stroke-dasharray', 'x', 'y', 'x1',
  'y1', 'x2', 'y2', 'cx', 'cy', 'r', 'rx', 'ry', 'points', 'transform',
  'font-size', 'font-family', 'text-anchor', 'dominant-baseline',
  'marker-end', 'marker-start', 'marker-mid', 'id', 'opacity',
  'fill-opacity', 'stroke-opacity',
]

/** 仅允许 data:image/*;base64（禁外链）。 */
const DATA_IMG_RE = /^data:image\/(png|jpeg|jpg|gif|webp|svg\+xml);base64,[A-Za-z0-9+/=\s]+$/i

let md: MarkdownIt | null = null
function mdParser(): MarkdownIt {
  if (!md) md = new MarkdownIt({ html: true, linkify: false, breaks: true })
  return md
}

/** 整段删除危险标签（连内容），避免 JS/CSS 文本泄漏成可见乱码。 */
const DROP_WITH_CONTENT = ['script', 'style', 'iframe', 'object', 'embed', 'noscript',
  'foreignObject', 'form', 'textarea', 'select', 'audio', 'video', 'link', 'meta', 'base']

function dropDangerousBlocks(src: string): string {
  let out = src
  for (const tag of DROP_WITH_CONTENT) {
    out = out.replace(new RegExp(`<\\s*${tag}\\b[\\s\\S]*?<\\s*/\\s*${tag}\\s*>`, 'gi'), '')
    out = out.replace(new RegExp(`<\\s*${tag}\\b[^>]*/>`, 'gi'), '')
    out = out.replace(new RegExp(`<\\s*${tag}\\b[^>]*>`, 'gi'), '')
  }
  return out
}

/** DOMPurify 在无 DOM 环境（Node 自检/SSR）下不可用 → 用保守字符串净化兜底。
 *
 *  注意：这是**仅在无 DOM 时**使用的降级路径（浏览器始终走 DOMPurify）。
 *  实现要点：保留 `</tag>` 的闭合斜杠，只过滤标签名与属性。
 */
function sanitizeWithoutDom(html: string): string {
  const TAG_RE = /<(\/?)([a-zA-Z][\w:-]*)((?:"[^"]*"|'[^']*'|[^>"'])*)>/g
  return html.replace(TAG_RE, (_m, closing: string, rawTag: string, rawAttrs: string) => {
    const tag = rawTag.toLowerCase()
    if (!ALLOWED_TAGS.includes(tag)) return ''            // 非白名单标签整段删除
    if (closing) return `</${tag}>`
    const attrs = rawAttrs.replace(
      /([\w:-]+)(?:\s*=\s*("[^"]*"|'[^']*'|[^\s"'>]+))?/g,
      (_a, rawName: string, rawVal?: string) => {
        const name = rawName.toLowerCase()
        const val = rawVal ? rawVal.replace(/^["']|["']$/g, '') : ''
        if (name.startsWith('on')) return ''
        if (name === 'href' || name === 'xlink:href') return ''
        if (name === 'src' && !DATA_IMG_RE.test(val.trim())) return ''
        if (val.toLowerCase().includes('javascript:')) return ''
        const canon = ALLOWED_ATTRS.find((a) => a.toLowerCase() === name)
        if (!canon) return ''
        return ` ${canon}="${val.replace(/"/g, '&quot;')}"`
      })
    return `<${tag}${attrs}>`
  })
}

/** 受保护的公式片段（避免 markdown-it 把 \( \[ 当转义吃掉，或把 _ * 当强调）。 */
const MATH_PLACEHOLDER = 'D105MATHPLACEHOLDER'

/** 把公式片段抽出占位，避免被 Markdown 规则改写；渲染后再还原。
 *
 *  D113：行间公式（$$..$$ / \[..\]）与行内公式（\(..\) / $..$）**分开处理**：
 *  - 行间公式占位前后**强制补空行** → 独立成 Markdown 段落；
 *    否则 `breaks:true` 会把它和正文挤进同一个 <p> 并插入 <br>，
 *    定界符被拆到多个文本节点 → KaTeX auto-render 匹配不到 → 整块显示成源码；
 *  - 行内公式原位替换，**保持行内语义**。
 *  与引擎 `richdoc._protect_math` 同口径（parity 自检护航）。
 */
function protectMath(src: string): { text: string; math: string[] } {
  const math: string[] = []
  const push = (m: string): string => {
    const idx = math.length
    math.push(m)
    return `${MATH_PLACEHOLDER}${idx}END`
  }
  // 顺序要求：先长后短（$$ 先于 $、\[ 先于 \(）
  const displayPatterns = [/\$\$[\s\S]*?\$\$/g, /\\\[[\s\S]*?\\\]/g]
  const inlinePatterns = [/\\\([\s\S]*?\\\)/g, /\$(?:\\.|[^$\\])+\$/g]
  let out = src
  for (const re of displayPatterns) {
    out = out.replace(re, (m) => `\n\n${push(m)}\n\n`)
  }
  for (const re of inlinePatterns) {
    out = out.replace(re, (m) => push(m))
  }
  return { text: out, math }
}

/** 还原公式占位（在 markdown 渲染后、净化前）。 */
/** 与引擎 `richdoc._restore_math` 同口径的 HTML 转义。
 *  D112：公式里的 `<`（如 `$R_1<R_2$`）若不转义还原，会被 DOMPurify 当标签开头，
 *  `<R_2$),单位长度…` 整段被丢弃 → 答案在 `$R_1` 后被截断。 */
function escapeForHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function restoreMath(html: string, math: string[]): string {
  return html.replace(new RegExp(MATH_PLACEHOLDER + '(\\d+)END', 'g'), (_m, i: string) => {
    const v = math[Number(i)]
    return v === undefined ? '' : escapeForHtml(v)
  })
}

/** D109：给无 width/height 的 `<svg>` 补按 viewBox 比例的内联尺寸。
 *  否则浏览器会让 `<svg>` 撑满容器（实测 684×513px），示意图被放大变形并挤占整格。
 *  与引擎 `richdoc._normalize_svg_size` 同口径（PWA/CLI 一致）。 */
export function normalizeSvgSize(html: string): string {
  return String(html ?? '').replace(/<svg\b([^>]*)>/gi, (whole: string, attrs: string) => {
    if (/\bwidth\s*=/i.test(attrs) && /\bheight\s*=/i.test(attrs)) return whole
    const vb = attrs.match(/\bviewbox\s*=\s*["']\s*[\d.+-]+[\s,]+[\d.+-]+[\s,]+([\d.+-]+)[\s,]+([\d.+-]+)/i)
    if (!vb) return whole
    const w = Number(vb[1]); const h = Number(vb[2])
    if (!(w > 0) || !(h > 0)) return whole
    const maxH = 45                                  // mm：与引擎一致
    const widthMm = Math.min(80, maxH * w / h)
    const heightMm = widthMm * h / w
    return `<svg${attrs} width="${widthMm.toFixed(1)}mm" height="${heightMm.toFixed(1)}mm">`
  })
}

/** Markdown + HTML 白名单 → 安全 HTML。 */
export function renderRich(text: string): string {
  const src = String(text ?? '')
  if (!src.trim()) return ''
  const { text: guarded, math } = protectMath(dropDangerousBlocks(src))
  const parsed = normalizeSvgSize(restoreMath(mdParser().render(guarded), math))
  // 无 DOM（Node/SSR）时 DOMPurify 无 sanitize → 走保守兜底
  if (typeof (DOMPurify as unknown as { sanitize?: unknown }).sanitize !== 'function') {
    return sanitizeWithoutDom(parsed)
  }
  // D117 关键修复：**不要**用 ALLOWED_URI_REGEXP。
  // 它是**全局**生效的：DOMPurify 会对所有属性值跑该正则，不只 src/href。
  // 于是 `viewBox="0 0 200 150"`、`width="60mm"`、`cx="100"` 等都不匹配
  // `data:image/...` → 被当成非法 URI **全部剥掉**，SVG 变成空壳：
  //     <svg viewBox=... width=...><circle cx=.../></svg>
  //   → <svg xmlns="..."><circle></circle></svg>
  // 浏览器里就是"一片空白"（引擎侧 bleach 的 protocols 只查 URI 属性，故 CLI 正常）。
  // 改为用 hook **只校验 src**，其余属性交给 ALLOWED_ATTR 白名单。
  const previousHook = (DOMPurify as unknown as { hooks?: unknown }).hooks
  void previousHook
  DOMPurify.addHook('uponSanitizeAttribute', (_node: unknown, data: {
    attrName?: string; attrValue?: string; keepAttr?: boolean }) => {
    if (String(data.attrName || '').toLowerCase() === 'src') {
      if (!DATA_IMG_RE.test(String(data.attrValue || '').trim())) data.keepAttr = false
    }
  })
  try {
    return DOMPurify.sanitize(parsed, {
      ALLOWED_TAGS,
      ALLOWED_ATTR: ALLOWED_ATTRS,
      ALLOW_DATA_ATTR: false,
      // 注意：此处**不能**设置 ALLOWED_URI_REGEXP（见上）
      FORBID_TAGS: ['foreignObject', 'use', 'image', 'script', 'style', 'iframe', 'object', 'embed', 'form', 'input'],
      FORBID_ATTR: ['href', 'xlink:href', 'srcset'],
      // 允许 svg（DOMPurify 默认支持）
      USE_PROFILES: { html: true, svg: true, svgFilters: false, mathMl: false },
    })
  } finally {
    DOMPurify.removeAllHooks()
  }
}

/** 属性级的 data:image 校验（DOMPurify 的 URI 正则在 img src 上再兜一层）。 */
export function isDataImage(src: string): boolean {
  return DATA_IMG_RE.test(String(src ?? '').trim())
}

/** 行内渲染：去掉最外层 `<p>...</p>` 包裹，使「题号 + 正文」能排在同一行。
 *
 *  D105 修复：之前题干用 renderRich 直接插在题号后，`<p>` 是块级元素 →
 *  题号独占一行、正文另起一行（用户反馈的"题号后空一行"）。
 *  仅当内容为**单一段落**时去包裹；多段/表格/SVG 等保持原样（需要块级）。
 */
export function renderRichInline(text: string): string {
  const html = renderRich(text)
  if (!html) return ''
  const trimmed = html.trim()
  // 必须**整体**就是一个 <p>…</p>（内部不得再出现 </p> 或块级标签）
  const m = /^<p>((?:(?!<\/p>)[\s\S])*)<\/p>$/.exec(trimmed)
  if (!m) return html
  const inner = m[1]
  if (/<(table|ul|ol|li|h[1-6]|blockquote|pre|svg|div|p|br\/?)>/i.test(inner)) return html
  return inner
}

/** md+html → 纯文本（检索 / Excel 摘要 / xlsx solution 列）。 */
export function stripMarkup(text: string, limit = 0): string {
  let s = String(text ?? '')
  if (!s.trim()) return ''
  s = s.replace(/<svg\b[\s\S]*?<\/svg\s*>/gi, ' [图] ')
  s = s.replace(/<img\b[^>]*>/gi, ' [图] ')
  s = s.replace(/<[^>]+>/g, '')
  s = s.replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<')
       .replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'")
  s = s.replace(/(\*\*|__|`|~~|^#{1,6}\s+|^\s*[-*+]\s+|^\s*\d+\.\s+)/gm, '')
  s = s.replace(/[ \t]+/g, ' ').replace(/\n{2,}/g, '\n').trim()
  if (limit && s.length > limit) s = s.slice(0, Math.max(0, limit - 1)).trimEnd() + '…'
  return s
}

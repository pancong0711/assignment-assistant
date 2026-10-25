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

/** Markdown + HTML 白名单 → 安全 HTML。 */
export function renderRich(text: string): string {
  const src = String(text ?? '')
  if (!src.trim()) return ''
  const parsed = mdParser().render(dropDangerousBlocks(src))
  // 无 DOM（Node/SSR）时 DOMPurify 无 sanitize → 走保守兜底
  if (typeof (DOMPurify as unknown as { sanitize?: unknown }).sanitize !== 'function') {
    return sanitizeWithoutDom(parsed)
  }
  return DOMPurify.sanitize(parsed, {
    ALLOWED_TAGS,
    ALLOWED_ATTR: ALLOWED_ATTRS,
    ALLOW_DATA_ATTR: false,
    ALLOWED_URI_REGEXP: DATA_IMG_RE,   // 只放行 data:image
    FORBID_TAGS: ['foreignObject', 'use', 'image', 'script', 'style', 'iframe', 'object', 'embed', 'form', 'input'],
    FORBID_ATTR: ['href', 'xlink:href', 'srcset'],
    // 允许 svg（DOMPurify 默认支持）
    USE_PROFILES: { html: true, svg: true, svgFilters: false, mathMl: false },
  })
}

/** 属性级的 data:image 校验（DOMPurify 的 URI 正则在 img src 上再兜一层）。 */
export function isDataImage(src: string): boolean {
  return DATA_IMG_RE.test(String(src ?? '').trim())
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

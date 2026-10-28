/** answerHtml.ts — D113：参考答案独立预览/打印（竖版单列 · 一题一页）
 *
 *  定位：与「作业纸预览」**完全分开**的两个功能区。
 *  - 作业纸预览 = 给学生设计用（不含答案，shelter 版式）；
 *  - 参考答案预览 = 给教师看答案/要点用（原生带答案）。
 *
 *  版式（用户 Q7/Q9 拍板）：
 *  - 只有**竖版单列**（不做横板双列：HTML 的 column-count 无法与分页衔接，
 *    实测 12 题只排出 10 题、其余被裁；LaTeX multicol 是排版引擎原生能力，HTML 无对等物）；
 *  - 一题接一题连续排；**一题答案排完 → 新题另起一页**（`.answer-card + .answer-card { break-before: page }`）；
 *  - 单题超过一整页 → 允许自然跨页（break-inside: auto），但不与其它题交错；
 *  - **题级切分**：只在题与题之间分页，绝不切公式/图/段落。
 *
 *  公式语义（R7）：行内 $..$ / \(..\) 保持行内；$$..$$ / \[..\] 保持独立成行且突出。
 *  渲染与「题库编辑器/作业纸」共用 richdoc.renderRich（同一白名单 + 同一 KaTeX 定界符）。
 */
import { renderRich } from './richdoc'

export interface AnswerItem {
  /** 题库 id（全局唯一）。 */
  id: string
  /** 题号显示（与作业纸同口径：1./2. 或 labels 覆盖值）。 */
  no?: string
  content?: string
  solution?: string
  tag?: string
}

export interface AnswerSection {
  /** 节标题（作业纸 id / 目标 tag）；单张预览时可为空。 */
  title?: string
  items: AnswerItem[]
}

export interface AnswerHtmlOptions {
  /** 是否显示题干（默认显示，便于教师对照）。 */
  includeContent?: boolean
  /** 是否显示题号（默认显示）。 */
  includeNo?: boolean
  /** 标题（打印在页眉）。 */
  docTitle?: string
  /** 一题一页起步（默认 true）：一题排完 → 新题另起一页。false = 连排。 */
  onePagePerQuestion?: boolean
  /** KaTeX 资源模式：relative = 同源自托管（PWA iframe）；raw = 内联自包含（下载/打印）。 */
  katex?: 'relative' | 'raw'
  katexRaw?: { css: string; js: string; autoRender: string }
}

function esc(s: string): string {
  return String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;')
}

/** 参考答案打印样式（竖版单列 · 一题一页起步 · 题级分页）。 */
export const ANSWER_CSS = `
  @page { size: A4 portrait; margin: 16mm 14mm; }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: "Noto Sans SC", "Microsoft YaHei", "Source Han Sans SC", system-ui, sans-serif;
    color: #1f2937; font-size: 10.5pt; line-height: 1.75; background: #fff;
  }
  .answer-doc { max-width: 210mm; margin: 0 auto; }
  .answer-doc-head {
    font-size: 12pt; font-weight: 700; color: #2456c4;
    border-bottom: 1px solid #c3cad6; padding-bottom: 3mm; margin-bottom: 6mm;
  }
  .answer-section-title {
    font-size: 11pt; font-weight: 700; color: #2456c4;
    background: #eef2ff; border-left: 3px solid #2456c4;
    padding: 2mm 3mm; margin: 0 0 4mm;
  }
  /* D113：一题一卡片 */
  /* 题内允许拆分：单题超过一整页时必须能跨页，否则 break-inside:avoid 会把整卡推到
     下一页，导致上一页只剩标题（实测首题 2493px / 页高 1002px → 首页空白）。
     与其它题的隔离靠下面的 "新题 break-before:page"，不依赖不可拆分。 */
  .answer-card {
    break-inside: auto; page-break-inside: auto;
    margin: 0 0 6mm;
  }
  /* 一题排完 → 新题另起一页（Q7 拍板的"不与前题答案混在一起"） */
  .answer-card + .answer-card { break-before: page; page-break-before: always; }
  /* 题内块级元素尽量不拆（公式/图/表格保持完整） */
  .answer-sol p, .answer-sol table, .answer-sol pre,
  .answer-sol .katex-display, .answer-sol svg, .answer-sol img {
    break-inside: avoid; page-break-inside: avoid;
  }
  .answer-no {
    font-weight: 700; color: #2456c4; font-size: 11pt; margin: 0 0 2mm;
  }
  .answer-q {
    color: #374151; font-size: 10pt; background: #f8fafc;
    border-left: 3px solid #cbd5e1; padding: 2mm 3mm; margin: 0 0 3mm;
  }
  .answer-sol { color: #111827; }
  .answer-sol p { margin: 0 0 .7em; }
  .answer-sol img, .answer-sol svg { max-width: 100%; height: auto; }
  .answer-sol table { border-collapse: collapse; max-width: 100%; margin: .5em 0; }
  .answer-sol th, .answer-sol td { border: 1px solid #c3cad6; padding: 2px 6px; }
  .answer-sol pre { background: #f5f7fa; padding: 2mm 3mm; border-radius: 4px; overflow-x: auto; }
  /* R7：行间公式突出显示（行内公式不受影响，KaTeX 自己给 display:inline） */
  .answer-sol .katex-display { margin: .8em 0; padding: .3em 0; }
  .answer-empty { color: #6b7280; font-style: italic; }
  @media print { .answer-doc { margin: 0; } }
`

/** KaTeX 资源标签（relative = 同源 ./katex/；raw = 内联自包含）。 */
function katexHead(opts: AnswerHtmlOptions): string {
  if (opts.katex === 'raw' && opts.katexRaw) {
    return `<style>${opts.katexRaw.css}</style>
<script>${opts.katexRaw.js}</script>
<script>${opts.katexRaw.autoRender}</script>`
  }
  return `<link rel="stylesheet" href="./katex/katex.min.css">
<script defer src="./katex/katex.min.js"></script>
<script defer src="./katex/contrib/auto-render.min.js"></script>`
}

/** KaTeX 渲染脚本（幂等；与作业纸模板同一定界符顺序）。 */
function katexScript(): string {
  return `<script>
(function () {
  var opts = {
    delimiters: [
      { left: '$$', right: '$$', display: true },
      { left: '\\\\[', right: '\\\\]', display: true },
      { left: '$', right: '$', display: false },
      { left: '\\\\(', right: '\\\\)', display: false }
    ],
    throwOnError: false
  };
  function render() {
    document.querySelectorAll('.answer-sol, .answer-q').forEach(function (el) {
      if (el.getAttribute('data-katex-done') === '1') return;
      try {
        window.renderMathInElement(el, opts);
        el.setAttribute('data-katex-done', '1');
      } catch (e) { /* 降级：保留源码 */ }
    });
  }
  var tries = 0;
  function waitReady() {
    if (typeof window.renderMathInElement === 'function') { render(); return; }
    if (++tries > 50) return;
    setTimeout(waitReady, 100);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', waitReady);
  else waitReady();
  window.addEventListener('load', render);
})();
</script>`
}

/** 单题卡片 HTML。 */
function cardHtml(it: AnswerItem, opts: AnswerHtmlOptions): string {
  const showNo = opts.includeNo !== false
  const showQ = opts.includeContent !== false
  const no = String(it.no || it.id || '')
  const sol = renderRich(String(it.solution || ''))
  const q = renderRich(String(it.content || ''))
  const parts: string[] = [`<section class="answer-card" data-qid="${esc(it.id)}">`]
  if (showNo && no) parts.push(`<p class="answer-no">${esc(no)}</p>`)
  if (showQ && q) parts.push(`<div class="answer-q">${q}</div>`)
  parts.push(`<div class="answer-sol">${sol || '<span class="answer-empty">（本题暂无参考答案）</span>'}</div>`)
  parts.push('</section>')
  return parts.join('\n')
}

/** 生成参考答案文档 HTML（竖版单列 · 一题一页起步）。 */
export function buildAnswerHtml(sections: AnswerSection[], opts: AnswerHtmlOptions = {}): string {
  const title = String(opts.docTitle || '参考答案')
  const bodyParts: string[] = []
  for (const sec of sections) {
    if (sec.title) bodyParts.push(`<p class="answer-section-title">${esc(sec.title)}</p>`)
    for (const it of sec.items || []) bodyParts.push(cardHtml(it, opts))
  }
  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title>
${katexHead(opts)}
<style>${ANSWER_CSS}${opts.onePagePerQuestion === false
  ? '\n.answer-card + .answer-card { break-before: auto; page-break-before: auto; }\n'
  : ''}</style>
</head>
<body>
<div class="answer-doc">
  <div class="answer-doc-head">${esc(title)}</div>
${bodyParts.join('\n') || '<p class="answer-empty">（尚未选题：参考答案为空）</p>'}
</div>
${katexScript()}
</body>
</html>`
}

/** 由作业纸 items 构造参考答案条目（保持 items 顺序；题号沿用作业纸口径）。 */
export function answerItemsOf(
  items: Array<{ id: string; no?: string; content?: string; solution?: string; tag?: string }>,
): AnswerItem[] {
  return items.map((it) => ({
    id: String(it.id ?? ''),
    no: it.no,
    content: it.content,
    solution: it.solution,
    tag: it.tag,
  }))
}

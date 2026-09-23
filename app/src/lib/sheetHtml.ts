/** sheetHtml.ts — VB-1/2/4 + VC-1/2：作业纸 HTML 打印主通道的 PWA 同构实现
 *  （docs/14 §VB / §VC-1/2，docs/05-D30 输出主通道 = HTML + 浏览器打印）。
 *
 *  与 engine/templates/assignment.html.j2（CLI `assist sheet html` 的单一事实源模板）
 *  保持**完全相同的结构与 CSS**（D1 超集铁律，docs/14 §VB 验收 4：CLI 与 PWA 同一模板）：
 *  - PRINT_CSS：与 j2 模板 <style> 块逐字同步（@page 方向为参数）；
 *  - 页块结构：section.sheet-page[data-student][data-page] >（wm-layer 水印层）+
 *    sheet-header + sheet-body[data-grid]（sf-line 分隔虚线 + sheet-frame 题帧）+
 *    sheet-footer —— 类名/嵌套/标记（data-wm-item / data-wm-pos）一致；
 *  - KaTeX 走同一 CDN（0.16.4）：CDN 不可达时 renderMathInElement 不存在，
 *    公式按 $..$ 源码降级显示（不报错，分页/水印/版式不受影响）。
 *  engine/tests/test_sheet_html.py 有 parity 哨兵（标记清单两处必须同时存在）。
 *  修改本文件的结构/CSS 时必须两处同改。
 *
 *  与引擎的取材差异（预览语义，非差异化输出）：PWA 无本地文件系统，
 *  题图按 kb 行 img_path hint 显示占位框；水印图从本浏览器 settings.wmAssets
 *  （dataURL 库）按文件名解析，未命中显示占位标记 —— 引擎 CLI 通道负责
 *  base64 内嵌真实图片。整班名单缺省用合成 学生A/B（informational）。
 */

import { normalizePerPage, type Taskpad } from './taskpad'
import type { KbBook, KbKind } from './kb'

export interface SheetHtmlStudent {
  name: string
  number: string
  class: string
  tag?: string
}

export interface SheetHtmlItem {
  id: string
  content: string
  solution?: string
  /** kb 行 img_path（file 相对路径 hint；PWA 无文件系统 → 打印预览显示占位框） */
  imgPath?: string
  tag?: string
}

export interface SheetHtmlPadInput {
  pad: Taskpad
  items: SheetHtmlItem[]
}

export interface SheetHtmlOptions {
  /** 名单（缺省 = 合成 学生A/B，informational，不含真实学生数据） */
  students?: SheetHtmlStudent[]
  /** 本浏览器水印素材库（basename → dataURL；来自 settings.wmAssets） */
  wmAssets?: Record<string, string>
  /** 页脚/页眉日期（缺省 = 今天，YYYY-MM-DD） */
  date?: string
}

export const KATEX_VERSION = '0.16.4'

/** 合成名单（与 engine paper/htmlfile.py SYNTHETIC_STUDENTS 同口径） */
export const SYNTHETIC_STUDENTS: SheetHtmlStudent[] = [
  { name: '学生A', number: '2026xxxx01', class: 'classA', tag: '' },
  { name: '学生B', number: '2026xxxx02', class: 'classB', tag: '' },
]

/** 页宽 mm（@page A4；水印 ratio 相对页宽，engine logo_draw 同口径） */
const PAGE_W_MM: Record<string, number> = { portrait: 210, landscape: 297 }

/* ---------- 转义 / 小工具 ---------- */

function escapeHtml(s: unknown): string {
  return String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;')
}

export function todayStr(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/** data-grid 键（与 engine htmlfile._grid_key / SheetLayoutView gridClass 同口径） */
function gridKey(orientation: string, perPage: number): string {
  if (perPage === 4) return 'cross'
  if (perPage === 3) return orientation === 'portrait' ? 'rows3' : 'cols3'
  return orientation === 'portrait' ? 'rows2' : 'cols2'
}

/** 页内分隔虚线类（engine layout.grid_lines / app sf-line 同口径） */
function gridLines(orientation: string, perPage: number): string[] {
  if (perPage === 4) return ['v', 'h']
  if (perPage === 3) return orientation === 'landscape' ? ['v31', 'v32'] : ['h31', 'h32']
  if (perPage === 2) return orientation === 'landscape' ? ['v'] : ['h']
  return []
}

/* ---------- PRINT_CSS（与 assignment.html.j2 <style> 块逐字同步；@page 方向参数化） ---------- */

export function printCss(orientation: 'portrait' | 'landscape'): string {
  return `/* ===== assignment.html.j2 打印主通道样式（与 app/src/lib/sheetHtml.ts PRINT_CSS 逐字同步） ===== */
:root { --ink:#1f2937; --line:#333; --muted:#6b7280; --accent:#2456c4; --hairline:#c3cad6; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: #e8ecf3; color: var(--ink);
  font-family: "Noto Sans SC", "Microsoft YaHei", "PingFang SC", "Source Han Sans SC", sans-serif;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
.doc-hint { max-width: 210mm; margin: 8mm auto 2mm; font-size: 11px; color: #475569;
  background: #fff; border: 1px dashed var(--hairline); border-radius: 8px; padding: 6px 10px; }
.sheet-page {
  position: relative; background: #fff; overflow: hidden;
  width: 210mm; height: 296mm; margin: 10mm auto; padding: 12mm 14mm;
  display: flex; flex-direction: column; gap: 2mm;
  box-shadow: 0 2px 10px rgba(31, 41, 55, 0.18);
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
.sheet-page.landscape { width: 297mm; height: 209mm; }
.sheet-header { border-bottom: 2px solid var(--line); text-align: center; font-weight: 700; padding-bottom: 2mm; }
.sh-title { font-size: 16pt; }
.sh-info { display: flex; justify-content: space-between; gap: 3mm; flex-wrap: wrap;
  font-weight: 400; font-size: 10.5pt; text-align: left; margin-top: 1.6mm; color: #222; }
.sh-assign { color: var(--muted); }
.sheet-body { flex: 1; display: flex; flex-direction: column; gap: 3mm; min-height: 0; }
.sheet-page.landscape .sheet-body { flex-direction: row; }
.sheet-body[data-grid="cols2"], .sheet-body[data-grid="cols3"] { flex-direction: row; }
.sheet-body[data-grid="rows2"], .sheet-body[data-grid="rows3"] { flex-direction: column; }
.sheet-body[data-grid="cross"] { flex-wrap: wrap; }
.sheet-body.divided { gap: 0; position: relative; }
.sheet-frame { flex: 1 1 0; min-width: 0; min-height: 0; border: 1px dashed var(--hairline);
  border-radius: 2mm; padding: 3mm; overflow: hidden; display: flex; flex-direction: column; gap: 2mm; }
.sheet-body.divided .sheet-frame { border: none; border-radius: 0; padding: 3mm 4mm; }
.sheet-body[data-grid="cross"] .sheet-frame { flex: 0 0 50%; height: 50%; }
.q-id { font-weight: 700; color: var(--accent); font-size: 11pt; }
.q-tag { font-weight: 400; color: var(--muted); font-size: 9pt; }
.q-content { font-size: 11.5pt; line-height: 1.8; white-space: pre-wrap; }
.q-img { max-width: 100%; max-height: 52mm; object-fit: contain; align-self: center; }
.q-img-ph { color: var(--muted); font-size: 10pt; font-style: italic; border: 1px dashed var(--hairline);
  border-radius: 2mm; padding: 4mm; text-align: center; }
.q-solution { color: var(--muted); font-size: 10pt; border-top: 1px dashed #dfe3ea;
  padding-top: 1.5mm; margin-top: auto; }
.sheet-footer { border-top: 1px solid var(--line); padding-top: 1.5mm; font-size: 10pt;
  color: var(--muted); display: flex; justify-content: space-between; gap: 3mm; }
/* 多题/页分隔线（虚线，止于内容区，不穿页眉页脚；与 CSS 预览/引擎 PDF 同口径） */
.sf-line { position: absolute; pointer-events: none; z-index: 2; }
.sf-line.v { left: 50%; top: 0; width: 1px; height: 100%; }
.sf-line.h { left: 0; top: 50%; width: 100%; height: 1px; }
.sf-line.v31 { left: 33.3%; top: 0; width: 1px; height: 100%; }
.sf-line.v32 { left: 66.6%; top: 0; width: 1px; height: 100%; }
.sf-line.h31 { left: 0; top: 33.3%; width: 100%; height: 1px; }
.sf-line.h32 { left: 0; top: 66.6%; width: 100%; height: 1px; }
.sf-line.v, .sf-line.v31, .sf-line.v32 { background-image: repeating-linear-gradient(to bottom, #777 0 5px, transparent 5px 10px); }
.sf-line.h, .sf-line.h31, .sf-line.h32 { background-image: repeating-linear-gradient(to right, #777 0 5px, transparent 5px 10px); }
/* 水印层（每页重建；items 逐层 + 页码大字） */
.wm-layer { position: absolute; inset: 0; pointer-events: none; z-index: 5; }
.wm-page-text { position: absolute; left: 16%; top: 38%; font-size: 46pt; color: #333;
  opacity: 0.08; transform: rotate(-24deg); white-space: nowrap; }
.wm-anchor { position: absolute; pointer-events: none; line-height: 0; }
.wm-lt { left: 4%; top: 4%; } .wm-mt { left: 50%; top: 4%; transform: translateX(-50%); } .wm-rt { right: 4%; top: 4%; }
.wm-lm { left: 4%; top: 45%; } .wm-mm { left: 50%; top: 45%; transform: translate(-50%, -50%); } .wm-rm { right: 4%; top: 45%; }
.wm-lb { left: 4%; bottom: 4%; } .wm-mb { left: 50%; bottom: 4%; transform: translateX(-50%); } .wm-rb { right: 4%; bottom: 4%; }
.wm-img { height: auto; }
.wm-placeholder { line-height: normal; font-size: 9pt; color: #9aa3b2; background: rgba(255,255,255,0.72);
  border: 1px dashed var(--hairline); border-radius: 4px; padding: 1px 4px; white-space: nowrap; }
@page { size: A4 ${orientation}; margin: 0; }
@media print {
  body { background: #fff; }
  .doc-hint { display: none !important; }
  .sheet-page { margin: 0; box-shadow: none; page-break-after: always; break-after: page; }
  .sheet-page.last { page-break-after: auto; break-after: auto; }
}`
}

/* ---------- 水印解析（items / legacy 三槽 / 默认三槽；PWA 从 wmAssets 取图） ---------- */

interface WmResolved {
  pos: string
  ratio: number
  alpha: number
  widthMm: number
  /** dataURL（data:<mime>;base64,<b64>）或空 = 占位标记 */
  dataUrl: string
  label: string
}

function dataUrlParts(url: string): { mime: string; b64: string } | null {
  const m = /^data:([^;,]+);base64,(.+)$/s.exec(url.trim())
  return m ? { mime: m[1], b64: m[2] } : null
}

function resolveWmItems(pad: Taskpad, wmAssets: Record<string, string> | undefined,
                        orientation: string): WmResolved[] {
  const pageW = PAGE_W_MM[orientation] ?? 210
  const raw = (pad.watermark.items ?? []).filter((it) => it && it.image)
  const list = raw.length
    ? raw.map((it) => ({ image: it.image, pos: it.pos, ratio: it.ratio, alpha: it.alpha }))
    : [
        // 空 items = 默认三槽占位（engine watermark preset 2603 缺省；PWA 无文件 → 占位标记）
        { image: 'university', pos: 'rt', ratio: 0.125, alpha: 0.5, defaultLogo: 'logo-university.png' },
        { image: 'text', pos: 'lm', ratio: 0.1, alpha: 0.3, defaultLogo: 'logo-text.png' },
        { image: 'boat', pos: 'lb', ratio: 0.3, alpha: 0.5, defaultLogo: 'logo-boat.png' },
      ]
  return list.map((it) => {
    let dataUrl = ''
    let label = it.image
    if (it.image.startsWith('data:')) {
      dataUrl = it.image
      label = '（本浏览器内嵌图片）'
    } else {
      const base = it.image.split('/').pop() ?? it.image
      const hit = wmAssets?.[base] ?? wmAssets?.[it.image]
      if (hit) {
        dataUrl = hit
        label = base
      }
    }
    return {
      pos: it.pos,
      ratio: it.ratio,
      alpha: it.alpha,
      widthMm: Math.round(pageW * it.ratio * 10) / 10,
      dataUrl,
      label,
    }
  })
}

function wmLayerHtml(wm: WmResolved[], pageText: boolean, pageN: number): string {
  const parts: string[] = ['<div class="wm-layer" aria-hidden="true">']
  if (pageText) parts.push(`<span class="wm-page-text">第 ${pageN} 页</span>`)
  wm.forEach((it, i) => {
    parts.push(`<div class="wm-anchor wm-${escapeHtml(it.pos)}" data-wm-item="${i + 1}" data-wm-pos="${escapeHtml(it.pos)}" style="opacity: ${it.alpha};">`)
    if (it.dataUrl) {
      const p = dataUrlParts(it.dataUrl)
      parts.push(p
        ? `<img class="wm-img" src="data:${p.mime};base64,${p.b64}" style="width: ${it.widthMm}mm;" alt="">`
        : `<img class="wm-img" src="${escapeHtml(it.dataUrl)}" style="width: ${it.widthMm}mm;" alt="">`)
    } else {
      parts.push(`<span class="wm-placeholder">[水印：${escapeHtml(it.label)}（${escapeHtml(it.pos)}）]</span>`)
    }
    parts.push('</div>')
  })
  parts.push('</div>')
  return parts.join('')
}

/* ---------- KaTeX（与模板同一段 include + 同一段渲染脚本） ---------- */

function katexHead(): string {
  return `<!-- KaTeX ${KATEX_VERSION}（CDN）：题干/答案中 $..$、$$..$$ 自动渲染。
     离线场景：CDN 不可达时 renderMathInElement 不存在，公式按 $..$ 源码降级显示。 -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@${KATEX_VERSION}/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@${KATEX_VERSION}/dist/katex.min.js"><\/script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@${KATEX_VERSION}/dist/contrib/auto-render.min.js"><\/script>`
}

function katexScript(): string {
  return `<script>
/* KaTeX 自动渲染（仅题干/答案；CDN 不可达时跳过=源码降级，不报错） */
document.addEventListener('DOMContentLoaded', function () {
  if (typeof window.renderMathInElement !== 'function') return;
  var opts = {
    delimiters: [
      { left: '$$', right: '$$', display: true },
      { left: '$', right: '$', display: false }
    ],
    throwOnError: false
  };
  document.querySelectorAll('.q-content, .q-solution').forEach(function (el) {
    try { window.renderMathInElement(el, opts); } catch (e) { /* 降级：保留源码 */ }
  });
});
<\/script>`
}

/* ---------- 页块构建（与 j2 模板 <section class="sheet-page">… 同构） ---------- */

function pageBlockHtml(pad: Taskpad, items: SheetHtmlItem[], stu: SheetHtmlStudent,
                       pagesTotal: number, pageN: number, isVeryLast: boolean,
                       wm: WmResolved[], date: string): string {
  const layout = pad.layout
  const orientation = layout.orientation === 'landscape' ? 'landscape' : 'portrait'
  const perPage = normalizePerPage(layout.per_page, layout.orientation)
  const lines = gridLines(orientation, perPage)
  const title = String(layout.header.title ?? '') || '作业纸'
  const footerText = String(layout.footer.text ?? '')
  const course = String(pad.course ?? '')
  const cls = stu.class || String(pad.class ?? '') || 'classA'

  const frames = lines.length
    ? lines.map((ln) => `<div class="sf-line ${ln}"></div>`).join('\n    ') + '\n    '
    : ''
  // 该页题帧（调用方已按 per_page 切好）
  return `<section class="sheet-page${orientation === 'landscape' ? ' landscape' : ''}${isVeryLast ? ' last' : ''}" data-student="${escapeHtml(stu.name)}" data-page="${pageN}">
  ${pad.watermark.enabled ? wmLayerHtml(wm, pad.watermark.pageText !== false, pageN) : ''}
  <div class="sheet-header">
    <div class="sh-title">${escapeHtml(title)}</div>
    <div class="sh-info">
      ${course ? `<span>课程：${escapeHtml(course)}</span>\n      ` : ''}<span>班级：${escapeHtml(cls)}</span>
      <span>学号：${escapeHtml(stu.number)}</span>
      <span>姓名：${escapeHtml(stu.name)}</span>
      <span class="sh-assign">作业：${escapeHtml(pad.id)}</span>
      <span class="sh-assign">日期：${escapeHtml(date)}</span>
    </div>
  </div>
  <div class="sheet-body${lines.length ? ' divided' : ''}" data-grid="${gridKey(orientation, perPage)}">
    ${frames}${items.map((fr) => `<div class="sheet-frame">
      <div class="q-id">${escapeHtml(fr.id)}${fr.tag ? ` <span class="q-tag">【${escapeHtml(fr.tag)}】</span>` : ''}</div>
      <div class="q-content">${escapeHtml(fr.content)}</div>
      ${fr.imgPath ? `<div class="q-img-ph">[题图：${escapeHtml(fr.imgPath)}]</div>` : ''}
      ${fr.solution ? `<div class="q-solution">参考答案：${escapeHtml(fr.solution)}</div>` : ''}
    </div>`).join('\n    ')}
  </div>
  <div class="sheet-footer">
    <span>${footerText ? `${escapeHtml(footerText)} · ` : ''}${escapeHtml(pad.id)}-第 ${pageN}/${pagesTotal}页</span>
    <span>签名：</span>
    <span>日期：${escapeHtml(date)}</span>
  </div>
</section>`
}

/* ---------- 主入口：任务包 → 自包含 HTML（与 CLI 同一模板） ---------- */

/**
 * 任务包（1 份 = VB-4 打印 / VC-1 模板预览；多份 = VC-2 清单连排预览，
 * 多包不分页：包间不加封面/额外分页，页块仍按每生 page-break）。
 * 文档级 @page 方向取第一份任务包（CSS 分页媒体查询限制；预览语义）。
 */
export function stringifySheetHtml(
  inputs: SheetHtmlPadInput | SheetHtmlPadInput[],
  opts: SheetHtmlOptions = {},
): string {
  const pads = Array.isArray(inputs) ? inputs : [inputs]
  if (!pads.length) throw new Error('stringifySheetHtml：至少需要一份任务包')
  const students = opts.students?.length ? opts.students : SYNTHETIC_STUDENTS
  const date = opts.date ?? todayStr()
  const first = pads[0].pad
  const orientation = first.layout.orientation === 'landscape' ? 'landscape' : 'portrait'
  const docTitle = String(first.layout.header.title ?? '') || '作业纸'

  const pageSections: string[] = []
  for (let padIdx = 0; padIdx < pads.length; padIdx++) {
    const { pad, items } = pads[padIdx]
    const perPage = normalizePerPage(pad.layout.per_page, pad.layout.orientation)
    const chunks: SheetHtmlItem[][] = []
    for (let i = 0; i < items.length; i += perPage) chunks.push(items.slice(i, i + perPage))
    if (!chunks.length) chunks.push([])
    const wm = resolveWmItems(pad, opts.wmAssets, pad.layout.orientation === 'landscape' ? 'landscape' : 'portrait')
    for (let si = 0; si < students.length; si++) {
      const stu = students[si]
      chunks.forEach((chunk, pi) => {
        const veryLast = padIdx === pads.length - 1
          && si === students.length - 1 && pi === chunks.length - 1
        pageSections.push(pageBlockHtml(pad, chunk, stu, chunks.length, pi + 1, veryLast, wm, date))
      })
    }
  }

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(docTitle)} · ${escapeHtml(first.id)}</title>
${katexHead()}
<style>
${printCss(orientation)}
</style>
</head>
<body>
<div class="doc-hint">
  打印（Ctrl/Cmd+P）：纸张=A4 · 边距=无 · 页眉页脚=关 · 背景图形=开（水印层依赖背景图形，docs/14 §VB-6）。
  目标选「另存为 PDF」可保存整班 PDF。公式由 KaTeX CDN 渲染：离线时按 $..$ 源码降级显示。
</div>
${pageSections.join('\n')}
${katexScript()}
</body>
</html>`
}

/* ---------- 交付动作：下载（保存 PDF 用） / 隐藏 iframe 打印 ---------- */

/** 生成 HTML Blob 下载（浏览器打开后 Ctrl/Cmd+P → 另存为 PDF） */
export function downloadSheetHtml(html: string, filename: string): void {
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

/**
 * 浏览器打印（VB-4）：把 HTML 注入隐藏 iframe 后调用其 window.print()——
 * 打印的是作业纸文档本身而非 PWA 界面。iframe 在打印结束后移除。
 */
export function printSheetHtml(html: string): void {
  const iframe = document.createElement('iframe')
  iframe.setAttribute('aria-hidden', 'true')
  iframe.style.position = 'fixed'
  iframe.style.right = '0'
  iframe.style.bottom = '0'
  iframe.style.width = '0'
  iframe.style.height = '0'
  iframe.style.border = '0'
  iframe.srcdoc = html
  const cleanup = () => { try { iframe.remove() } catch { /* noop */ } }
  iframe.onload = () => {
    setTimeout(() => {
      try {
        iframe.contentWindow?.focus()
        iframe.contentWindow?.print()
      } catch {
        // 某些浏览器禁止跨 srcdoc 打印：降级为提示用户打开下载的 HTML 打印
      }
      // afterprint 在部分浏览器不触发：兜底延迟清理
      setTimeout(cleanup, 60_000)
    }, 300)
  }
  document.body.appendChild(iframe)
}

/* ---------- 题目展开辅助（VC-2：清单里任一任务包直接预览） ---------- */

/** 任务包 items → 模板题帧：从 kb store 取 content/solution/img_path（未命中即跳过）。 */
export function expandPadItems(
  pad: Taskpad,
  bookOf: (kind: KbKind) => KbBook | undefined,
): SheetHtmlItem[] {
  const out: SheetHtmlItem[] = []
  for (const item of pad.items) {
    const chap = bookOf(item.kb as KbKind)?.chapters.find((c) => c.name === item.chap)
    if (!chap) continue
    for (const id of item.ids) {
      const r = chap.rows.find((x) => x.id === id)
      if (r) out.push({ id, content: r.content, solution: r.solution, imgPath: r.img_path, tag: item.tag })
    }
  }
  return out
}

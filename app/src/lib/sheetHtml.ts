/** sheetHtml.ts — VB-1/2/4 + VC-1/2：作业纸 HTML 打印主通道的 PWA 同构实现
 *  （docs/14 §VB / §VC-1/2，docs/05-D30 输出主通道 = HTML + 浏览器打印）。
 *
 *  与 engine/templates/assignment.html.j2（CLI `assist sheet html` 的单一事实源模板）
 *  保持**完全相同的结构与 CSS**（D1 超集铁律，docs/14 §VB 验收 4：CLI 与 PWA 同一模板）：
 *  - PRINT_CSS：与 j2 模板 <style> 块逐字同步（@page 方向为参数）；
 *  - 页块结构：section.sheet-page[data-student][data-page] >（wm-layer 水印层）+
 *    sheet-header + sheet-body[data-grid]（sf-line 分隔虚线 + sheet-frame 题帧）+
 *    sheet-footer —— 类名/嵌套/标记（data-wm-item / data-wm-pos）一致；
 *  - KaTeX 三种资源模式（docs/13 D43-3/D43-6，PWA 先行；引擎 j2 仍 CDN，parity 后续）：
 *    'cdn'（缺省，现状/引擎 parity 哨兵口径，断网公式源码降级）；
 *    'relative'（同源 ./katex/，PWA 预览/隐藏 iframe 打印用 —— assets 随 dist
 *      发布（app/public/katex，600KB，含 contrib/auto-render.min.js），断网照样渲染）；
 *    'raw'（配合 fetchSelfContainedKatex()：下载/分发 HTML 时把 css+js+字体 base64
 *      内联成自包含文件，教师本地 file:// 打开也渲染公式，零环境管理）。
 *  engine/tests/test_sheet_html.py 有 parity 哨兵（标记清单两处必须同时存在）。
 *  修改本文件的结构/CSS 时必须两处同改。
 *
 *  与引擎的取材差异（预览语义，非差异化输出）：PWA 无本地文件系统，
 *  题图按 kb 行 img_path hint 显示占位框；水印图从本浏览器 settings.wmAssets
 *  （dataURL 库）按文件名解析，未命中显示占位标记 —— 引擎 CLI 通道负责
 *  base64 内嵌真实图片。整班名单缺省用合成 学生A/B（informational）。
 */

import { gridBodyStyle, gridLineStyles, resolveGrid,
  seedIndex, copyContent, SUMMARY_ID, SUMMARY_CONTENT, TRANSLATION_ID,
  type Taskpad } from './taskpad'
import type { KbBook, KbKind } from './kb'
import { scopeQuestionId } from './kb'
import { renderRich, renderRichInline, stripMarkup } from './richdoc'

export interface SheetHtmlStudent {
  name: string
  number: string
  class: string
  tag?: string
}

export interface SheetHtmlItem {
  id: string
  no?: string
  content: string
  solution?: string
  /** D100：答案来源（pinned|latest|fallback|xlsx），供 UI 标注"AI 版/未置顶"。 */
  solutionFrom?: string
  /** D100：生效版本号（如 v3）与来源（ai|human）。 */
  solutionVersion?: string
  solutionSource?: string
  /** kb 行 img_path（file 相对路径 hint；PWA 无文件系统 → 打印预览显示占位框） */
  imgPath?: string
  tag?: string
  /** D103：预排版后的块（有值时按块渲染，不再用 content/solution 整体渲染）。 */
  blocks?: SheetHtmlBlock[]
}
/** D103：预排版结果的结构化视图（与 `autoLayout.LayoutResult` 兼容；仅类型引用，避免循环依赖）。 */
export interface LayoutLike {
  v: number
  contentHash?: string
  geometry?: { cellW: number; cellH: number; rows: number; cols: number }
  pages: Array<{ page: number; cells: Array<{ row: number; col: number
    blocks: Array<{ qid: string; no: string; kind: 'content' | 'solution'; text: string; cont?: boolean; scale?: number }> }> }>
  warnings?: string[]
}

/** 把 `layout_result` 的某页转成渲染用的格视图（按 (row,col) 填满整个网格，空格留白）。 */
export function layoutCellsForPage(
  layout: LayoutLike | null | undefined, pageNo: number, items: SheetHtmlItem[],
): SheetHtmlCellView[] | undefined {
  const pg = layout?.pages?.find((x) => x.page === pageNo)
  if (!pg) return undefined
  const byId = new Map(items.map((i) => [i.id, i]))
  return pg.cells.map((c) => {
    const first = c.blocks[0]
    const qid = String(first?.qid ?? '')
    const item = byId.get(qid)
    const isFirstPart = !first?.cont
    return {
      row: c.row, col: c.col, qid, no: String(first?.no ?? item?.no ?? ''),
      blocks: c.blocks.map((b) => ({ kind: b.kind, text: b.text, cont: b.cont, scale: b.scale })),
      // 题图只在该题的**首个**格渲染（续格不重复出图）
      imgPath: isFirstPart ? item?.imgPath : undefined,
    }
  })
}

/** D103：预排版块（与 autoLayout.LayoutBlock 同构，供渲染层使用）。 */
export interface SheetHtmlBlock {
  kind: 'content' | 'solution'
  text: string
  /** 续段 → 渲染「（题 N 续）」标注 */
  cont?: boolean
  /** 超高行间公式的缩放比例 */
  scale?: number
}

export interface SheetHtmlPadInput {
  pad: Taskpad
  items: SheetHtmlItem[]
  /** D103：预排版结果（自动排版引擎产物）。有值 → 按"页/格"渲染（MxN + 答案续格）；
   *  无值 → 旧行为（按 per_page 切片，整题铺满）。 */
  layout?: LayoutLike | null
  /** D43-6 整班分段（班级与标签页 VC-3）/ 模板态覆盖：该包只给这些学生出页；
   *  缺省 = opts.students（再缺省 = SYNTHETIC_STUDENTS）。 */
  students?: SheetHtmlStudent[]
}

export interface SheetHtmlOptions {
  /** 名单（缺省 = 合成 学生A/B，informational，不含真实学生数据） */
  students?: SheetHtmlStudent[]
  /** D88：名单缺省时是否回落"合成示例学生"（模板态 true；整班预览 false → 空学生的包跳过） */
  syntheticFallback?: boolean
  /** D88：页眉班级的回退名（学生 class 为空时使用；缺省 = 空，不再回落 'classA'） */
  groupName?: string
  /** 本浏览器水印素材库（basename → dataURL；来自 settings.wmAssets） */
  wmAssets?: Record<string, string>
  /** D93-S3：命名水印样式库（name → {items,pageText,enabled}；来自 settings.wmStyles）。
   *  用于解析 pad.watermark.style_ref（内联 items 优先；否则命中样式；否则默认三槽）。 */
  wmStyles?: WmStyleLike[]
  /** B3/D46-5：题图素材库（basename → dataURL；来自 settings.figAssets）。
   *  命中 → <img class="q-img" src=dataURL>（与引擎 base64 内嵌同视觉）；未命中 → 原占位框。 */
  figAssets?: Record<string, string>
  /** 页脚/页眉日期（缺省 = 今天，YYYY-MM-DD） */
  date?: string
  /** D43-6 内容开关：是否渲染"参考答案：…"行；缺省 true（CLI/zip 现状）。
   *  PWA 预览/打印/导出按「显示参考答案」勾选传入（默认不勾=false）。 */
  includeSolution?: boolean
  /** D43-7 水印图层开关：false = 整层不画（含三槽占位框）；缺省 true。
   *  PWA ③段「显示水印图层」勾选传入（默认勾=现状）。与 pad.watermark.enabled（属性）是 AND 关系。 */
  includeWatermark?: boolean
  /** D93-S5：整班预览连续页码（跨所有学生/页块递增；缺省 false = 每生从 1 起）。
   *  页脚 "第 N/总页数" 的 N/total 同步为整班连续值。 */
  continuousPage?: boolean
  /** D43-7 页码大字水印开关：false = 「第 N 页」大字不画（图层不受影响）；缺省 true。 */
  includePageText?: boolean
  /** D113-D1：多份作业纸连排时，**每份前插入分节标题页**（作业纸 id / 目标 tag），
   *  并把该份的页码重置为从 1 起（避免多张纸页码连成一串分不清归属）。
   *  缺省 false = 旧行为（纯连排）。 */
  sectionTitles?: Array<{ title: string; subtitle?: string }>
  /** D113-D1：配合 sectionTitles —— 每份作业纸页码各自从 1 起（缺省 true 当 sectionTitles 存在）。 */
  resetPagePerSection?: boolean
  /** KaTeX 资源模式（见文件头注释）：'cdn' 缺省 | 'relative' 同源 | 'raw' 内联 */
  katex?: 'relative' | 'cdn' | 'raw'
  /** katex='raw' 时由 fetchSelfContainedKatex() 注入的完整资源 */
  katexRaw?: KaTeXAssets
}

export const KATEX_VERSION = '0.16.4'

/** D43-6 学生示例开关未勾选时的"空白学籍"学生（页眉 班级/学号/姓名 → 手写空位线） */
export const BLANK_STUDENT: SheetHtmlStudent = { name: '', number: '', class: '', tag: '' }

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

/* ---------- D61 网格：rows×cols 显式布局（旧任务无字段时 resolveGrid 兼容回退） ---------- */

/** 页内分隔虚线（generic：竖线 left%、横线 top%；与 engine grid_line_styles 同口径）。 */
function gridLines(rows: number, cols: number): Array<{ dir: 'v' | 'h'; style: string }> {
  return gridLineStyles(rows, cols)
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
/* D103：恢复固定页高（MxN 版式需要确定的格高；答案续写由预排版解决，不再靠页高自适应）。 */
.sheet-page {
  position: relative; background: #fff; overflow: hidden;
  width: 210mm; height: 296mm; margin: 10mm auto; padding: 12mm 14mm;
  display: flex; flex-direction: column; gap: 2mm;
  box-shadow: 0 2px 10px rgba(31, 41, 55, 0.18);
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
/* D113-D1：多份作业纸连排时的分节标题页（每份一张，标明 id/目标 tag） */
.section-title-page { display: flex; align-items: center; justify-content: center; }
.section-title-box { text-align: center; }
.section-title-main { font-size: 20pt; font-weight: 700; color: var(--accent, #2456c4); margin-bottom: 4mm; }
.section-title-sub { font-size: 11pt; color: var(--muted, #6b7280); }
.sheet-page.landscape { width: 297mm; height: 209mm; }
.sheet-header { border-bottom: 2px solid var(--line); text-align: center; font-weight: 700; padding-bottom: 2mm; }
.sh-title { font-size: 16pt; }
/* D83-4：信息行各 span 等宽左对齐、铺满整行；页眉不放日期（页脚保留） */
.sh-info { display: grid; grid-auto-flow: column; grid-auto-columns: 1fr; gap: 2mm;
  font-weight: 400; font-size: 10.5pt; text-align: left; margin-top: 1.6mm; color: #222; }
.sh-assign { color: var(--muted); }
/* D103：恢复 MxN 等分网格（版式控制权回到教师；虚线按格边界绘制）。
   行/列由内联 gridBodyStyle(rows, cols, order) 决定。 */
.sheet-body { flex: 1; display: grid; gap: 0; min-height: 0; min-width: 0; }
.sheet-body.divided { gap: 0; position: relative; }
.sheet-body.divided .sheet-frame { word-break: break-word; }
/* D103：格内裁剪 —— 溢出的答案由「预排版」切段放到后续格（D103-T3/T4），
   因此这里恢复 overflow:hidden，保证不会覆盖虚线、也不会顶破版面。 */
.sheet-frame { min-width: 0; min-height: 0; border: 1px dashed var(--hairline);
  border-radius: 2mm; padding: 3mm; overflow: hidden;
  display: flex; flex-direction: row; align-items: flex-start; gap: 3mm;
  break-inside: avoid; page-break-inside: avoid; }
/* D83-2：四态位置 —— text-right/left 同行两列；below-* 题文满宽、图下一行 */
.sheet-frame.pos-text-left { flex-direction: row-reverse; }
.sheet-frame.pos-below-left, .sheet-frame.pos-below-right { flex-direction: column; align-items: stretch; }
.sheet-frame.pos-below-left .q-img, .sheet-frame.pos-below-left .q-img-ph { align-self: flex-start; }
.sheet-frame.pos-below-right .q-img, .sheet-frame.pos-below-right .q-img-ph { align-self: flex-end; }
/* D83 修复：column 方向下 .q-body flex:1 会撑满整帧、把图挤到帧底；below-* 正文按内容高度排 */
.sheet-frame.pos-below-left .q-body, .sheet-frame.pos-below-right .q-body { flex: none; }
.q-body { flex: 1; min-width: 0; }
.q-body.indent-first { text-indent: 2em; }
.q-body.indent-hanging { padding-left: 7mm; text-indent: -7mm; }
/* D103：divided = 有分隔虚线的版式（>=2 题）→ 题框去边框（虚线由 .sf-line 绘制）。 */
.sheet-body.divided .sheet-frame { border: none; border-radius: 0; padding: 3mm 4mm; }
.sheet-body.divided .sheet-frame + .sheet-frame { border-top: none; }
.sheet-body:not(.divided) .sheet-frame { border-bottom: none; }
.q-id { font-weight: 700; color: var(--accent); font-size: 11pt; }
.q-tag { font-weight: 400; color: var(--muted); font-size: 9pt; }
.q-content { font-size: 11.5pt; line-height: 1.8; white-space: pre-wrap; }
.q-img { max-width: 100%; max-height: 52mm; object-fit: contain; align-self: flex-start; }
.q-img-ph { color: var(--muted); font-size: 10pt; font-style: italic; border: 1px dashed var(--hairline);
  border-radius: 2mm; padding: 4mm; text-align: center; }
/* D111：虚线只在「一道题的答案首次出现」时画一次；续段/q-solution-cont 不再重复画，
   否则连续多格答案会出现一排平行虚线。 */
.q-solution { color: var(--muted); font-size: 10pt;
  padding-top: 1.5mm; margin-top: auto; }
.q-solution.q-sol-first { border-top: 1px dashed #dfe3ea; }
.q-solution-cont { margin-top: 0; padding-top: 0.5mm; }
  padding-top: 1.5mm; margin-top: auto; }
/* D105：md+html 答案内的图片/SVG/表格限宽，避免撑破格子 */
.q-solution img, .q-content img { max-width: 100%; height: auto; }
.q-solution svg, .q-content svg { max-width: 100%; height: auto; }
.q-solution table, .q-content table { border-collapse: collapse; max-width: 100%; }
.q-solution th, .q-solution td, .q-content th, .q-content td { border: 1px solid var(--hairline); padding: 1px 4px; }
/* 页脚不参与收缩，贴在页内容之后（margin-top:auto 兜到页底）。 */
.sheet-footer { border-top: 1px solid var(--line); padding-top: 1.5mm; font-size: 10pt;
  color: var(--muted); display: flex; justify-content: space-between; gap: 3mm;
  flex: none; margin-top: auto; }
/* D103：恢复虚线（横+竖）。MxN 等分网格下「百分比定位」与格边界完全重合，语义正确。 */
.sf-line { position: absolute; pointer-events: none; z-index: 2; }
.sf-line.v { top: 0; bottom: 0; width: 1px; background-image: repeating-linear-gradient(to bottom, #777 0 5px, transparent 5px 10px); }
.sf-line.h { left: 0; right: 0; height: 1px; background-image: repeating-linear-gradient(to right, #777 0 5px, transparent 5px 10px); }
/* D103：分隔虚线由 .sf-line 按网格百分比绘制（见上），题框不再单独画底边线。 */
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
  /* D103：每页内容由预排版保证不溢出，页高固定 → 不会出现"内容被裁"或"跨页错位"。 */
  .sheet-page { margin: 0; box-shadow: none; page-break-after: always; break-after: page; }
  .sheet-page.last { page-break-after: auto; break-after: auto; }
  /* D103：仍保留页脚绝对贴底（防止 flex 在打印时的解析差异）。 */
  .sheet-page { position: relative; }
  .sheet-footer { position: absolute; bottom: 6mm; left: 14mm; right: 14mm; margin-top: 0; }
  .sheet-frame { break-inside: avoid; page-break-inside: avoid; }
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

export interface WmStyleLike { name: string; enabled?: boolean; pageText?: boolean; default?: boolean
  items?: { image?: string; pos?: string; ratio?: number; alpha?: number }[] }

/** D93-S3：解析作业纸生效水印图层。优先级：内联 items > style_ref（命名样式）> 默认样式 > 内置三槽。
 *  与引擎 htmlfile._watermark_items / watermark_styles.resolve_pad_watermark 同口径。 */
function resolveWmItems(pad: Taskpad, wmAssets: Record<string, string> | undefined,
                        orientation: string, wmStyles?: WmStyleLike[]): WmResolved[] {
  const pageW = PAGE_W_MM[orientation] ?? 210
  const inline = (pad.watermark.items ?? []).filter((it) => it && it.image)
  let effective: { image: string; pos: string; ratio: number; alpha: number }[] | null = null
  if (inline.length) {
    effective = inline.map((it) => ({ image: it.image, pos: it.pos, ratio: it.ratio, alpha: it.alpha }))
  } else {
    const styles = wmStyles || []
    const ref = String(pad.watermark.style_ref || '').trim()
    let st = ref ? styles.find((x) => x.name === ref) : undefined
    if (ref && !st) st = styles.find((x) => x.default) || styles.find((x) => x.name === '_default')
    if (!st && !ref) st = styles.find((x) => x.default) || styles.find((x) => x.name === '_default')
    const items = (st?.items || []).filter((it) => it && it.image)
    if (items.length) {
      effective = items.map((it) => ({ image: String(it.image), pos: String(it.pos || 'rb'),
                                       ratio: Number(it.ratio ?? 0.25), alpha: Number(it.alpha ?? 0.5) }))
    }
  }
  const raw = effective || []
  const list = raw.length
    ? raw
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

/** D83-2：题图位置四态归一 + 旧值兼容（与引擎 paper/layout.normalize_figure_pos 同口径）。 */
export function normalizeFigurePos(pos?: string): 'text-right' | 'text-left' | 'below-left' | 'below-right' {
  const p = String(pos ?? 'text-right').trim().toLowerCase()
  const legacy: Record<string, string> = { lt: 'text-left', rt: 'text-right', center: 'below-right' }
  const v = legacy[p] ?? p
  return (['text-right', 'text-left', 'below-left', 'below-right'].includes(v)
    ? v : 'text-right') as 'text-right' | 'text-left' | 'below-left' | 'below-right'
}

/** D83-3：题号缩进三态归一（none 默认 / first / hanging）。 */
export function normalizeIndent(indent?: string): 'none' | 'first' | 'hanging' {
  const i = String(indent ?? 'none').trim().toLowerCase()
  return (['none', 'first', 'hanging'].includes(i) ? i : 'none') as 'none' | 'first' | 'hanging'
}

/** B3/D46-5：题图渲染——有 img_path 且 figAssets 命中 basename → 真图；否则占位框（现状）。 */
function figHtml(imgPath?: string, figAssets?: Record<string, string>,
                 figure?: { scale?: number; pos?: string; max_w_mm?: number; max_h_mm?: number }): string {
  if (!imgPath) return ''
  const base = imgPath.split('/').pop() ?? imgPath
  const hit = figAssets?.[base]
  const scale = Math.max(0.2, Math.min(2, Number(figure?.scale ?? 1)))
  const pos = normalizeFigurePos(figure?.pos)
  // D83 修复：sheet-frame 为 row（text-*）时 align-self 控制的是**纵向**对齐 → 一律顶部
  // flex-start；为 column（below-*）时才是横向对齐 → flex-start=左 / flex-end=右。
  // （此前 text-right 误用 flex-end，导致图被压到行底右下角。）
  const align = pos === 'below-right' ? 'flex-end' : 'flex-start'
  const maxH = Number(figure?.max_h_mm ?? 52)
  const maxW = Number(figure?.max_w_mm ?? 45)
  const style = `max-height:${(maxH * scale).toFixed(1)}mm; max-width:${(Math.max(10, maxW) * scale).toFixed(1)}mm; align-self:${align}`
  if (hit && hit.startsWith('data:')) {
    return `<img class="q-img" src="${escapeHtml(hit)}" style="${style}" alt="题图">`
  }
  return `<div class="q-img-ph" style="${style}">[题图：${escapeHtml(imgPath)}]</div>`
}

/* ---------- KaTeX（与模板同一段 include + 同一段渲染脚本） ---------- */

/** Mechanism docs/13 D43-3：cdn = 现状（引擎 j2 同款）；relative = 同源 ./katex/（app/public/katex
 *  随 dist 发布；srcdoc iframe 相对路径按宿主页 base 解析 → Pages / engine serve / vite dev 全同源）；
 *  raw = 调用方注入完整内联资源（fetchSelfContainedKatex 预取后传入）。 */
function katexIncludeHtml(mode: 'relative' | 'cdn' | 'raw' = 'cdn', raw?: KaTeXAssets): string {
  if (mode === 'raw' && raw) {
    return [
      `<!-- KaTeX ${KATEX_VERSION}（内联自包含：css+js+woff2 全部内联；file:// 离线可开） -->`,
      '<style>',
      raw.css,
      '</style>',
      '<script>',
      raw.katexJs,
      '</script>',
      '<script>',
      raw.autoRenderJs,
      '</script>',
    ].join('\n')
  }
  if (mode === 'relative') {
    return `<!-- KaTeX ${KATEX_VERSION}（同源自托管 ./katex/，随 PWA dist 发布；离线可渲染） -->
<link rel="stylesheet" href="./katex/katex.min.css">
<script defer src="./katex/katex.min.js"><\/script>
<script defer src="./katex/contrib/auto-render.min.js"><\/script>`
  }
  return `<!-- KaTeX ${KATEX_VERSION}（CDN）：题干/答案中 $..$、$$..$$ 自动渲染。
     离线场景：CDN 不可达时 renderMathInElement 不存在，公式按 $..$ 源码降级显示。 -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@${KATEX_VERSION}/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@${KATEX_VERSION}/dist/katex.min.js"><\/script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@${KATEX_VERSION}/dist/contrib/auto-render.min.js"><\/script>`
}

/** D43-3 自包含导出资源：同源拉取 app/public/katex（css + katex.min.js + auto-render + 全部**
 *  woff2 字体 base64），缓存模块级。供「下载 HTML（自包含）」把公式渲染资源写进文件本体
 *  —— 教师 file:// 离线打开即渲染，无需任何环境安装。 */
export interface KaTeXAssets { css: string; katexJs: string; autoRenderJs: string }

let katexBundleCache: KaTeXAssets | null = null

function blobToDataUrl(buf: ArrayBuffer): string {
  let bin = ''
  const bytes = new Uint8Array(buf)
  const chunk = 0x8000
  for (let i = 0; i < bytes.length; i += chunk) {
    bin += String.fromCharCode(...bytes.subarray(i, i + chunk))
  }
  return 'data:font/woff2;base64,' + btoa(bin)
}

export async function fetchSelfContainedKatex(): Promise<KaTeXAssets> {
  if (katexBundleCache) return katexBundleCache
  const base = document.baseURI
  const [cssRes, jsRes, arRes] = await Promise.all([
    fetch(new URL('./katex/katex.min.css', base).href),
    fetch(new URL('./katex/katex.min.js', base).href),
    fetch(new URL('./katex/contrib/auto-render.min.js', base).href),
  ])
  if (!cssRes.ok || !jsRes.ok || !arRes.ok) {
    throw new Error('KaTeX 自托管资源拉取失败（需 Pages/引擎同源环境提供 ./katex/）')
  }
  let css = await cssRes.text()
  const js = await jsRes.text()
  const autoRenderJs = await arRes.text()
  // 字体引用内联：woff2 → dataURL；woff/ttf 引用删除（自托管 dist 仅带 woff2）
  const names = new Set<string>()
  for (const m of css.matchAll(/url\(fonts\/([^)'"\s]+)\.(woff2|woff|ttf)\)/g)) names.add(m[1])
  const b64 = new Map<string, string>()
  for (const name of names) {
    const res = await fetch(new URL(`katex/fonts/${name}.woff2`, base).href)
    if (res.ok) b64.set(name, blobToDataUrl(await res.arrayBuffer()))
  }
  css = css
    .replace(/url\(fonts\/([^)'"\s]+)\.woff2\)/g, (m, n: string) => (b64.get(n) ? `url(${b64.get(n)})` : m))
    .replace(/,\s*url\(fonts\/[^)]+\.woff\)\s*format\("woff"\)/g, '')
    .replace(/,\s*url\(fonts\/[^)]+\.ttf\)\s*format\("truetype"\)/g, '')
  katexBundleCache = { css, katexJs: js, autoRenderJs }
  return katexBundleCache
}

/** D53-G3：收集同源 KaTeX 选择集文件（css/js/auto-render + css 内 url(fonts/*.woff2) 引用清单），
 *  供「安装到 workspace」用（FSA 递归写 sheets/katex/**；无 FSA 降级 zip 下载）。
 *  仓库零容量占用不变：来源=npm 依赖构建期注入的 dist 同源资产。 */
export async function collectKatexFiles(): Promise<Array<{ relPath: string; blob: Blob }>> {
  const base = new URL('./katex/', document.baseURI).href
  const cssRes = await fetch(base + 'katex.min.css')
  if (!cssRes.ok) throw new Error('同源 katex.min.css 不可达（需 Pages/引擎同源环境）')
  const css = await cssRes.text()
  const files: Array<{ relPath: string; blob: Blob }> = [
    { relPath: 'katex.min.css', blob: new Blob([css], { type: 'text/css' }) },
  ]
  for (const f of ['katex.min.js', 'contrib/auto-render.min.js']) {
    const r = await fetch(base + f)
    if (!r.ok) throw new Error(`同源 ${f} 不可达`)
    files.push({ relPath: f, blob: await r.blob() })
  }
  const names = new Set<string>()
  for (const m of css.matchAll(/url\(fonts\/([^)'"\s]+)\.woff2\)/g)) names.add(m[1])
  for (const n of names) {
    const r = await fetch(`${base}fonts/${n}.woff2`)
    if (r.ok) files.push({ relPath: `fonts/${n}.woff2`, blob: await r.blob() })
  }
  return files
}

/** 「⬇ 下载 HTML（自包含·离线可开）」：stringifySheetHtml(katex='raw')；资源拉取失败时
 *  回退相对路径/同源缺失场景 → CDN 现状输出（公式断网源码降级，其余完整）。 */
export async function buildSelfContainedHtml(
  inputs: SheetHtmlPadInput | SheetHtmlPadInput[],
  opts: SheetHtmlOptions = {},
): Promise<string> {
  try {
    const assets = await fetchSelfContainedKatex()
    return stringifySheetHtml(inputs, { ...opts, katex: 'raw', katexRaw: assets })
  } catch {
    return stringifySheetHtml(inputs, opts)
  }
}

function katexScript(): string {
  return `<script>
/* KaTeX 自动渲染（仅题干/答案）。
   D93-S5：不依赖 DOMContentLoaded 与 defer 的时序——轮询等待 renderMathInElement 就绪后再渲染，
   最多等 ~5s；始终不可用则保留源码降级（不报错）。
   D101：② 补 \(..\)、\[..\] 两个 LaTeX 定界符（AI/人工都有可能产出；此前只有 $ 系列，
   导致 \[a=\frac{dv}{dt}\] 原样显示）；③ 渲染幂等（已渲染节点打 data-katex-done，
   srcdoc 重建/load 补渲染都不会重复处理）。 */
(function () {
  var opts = {
    // 顺序要求：长定界符在前（$$ 先于 $、\[ 先于 \()，否则 $$x$$ 会被拆成两个行内公式
    delimiters: [
      { left: '$$', right: '$$', display: true },
      { left: '\\\\[', right: '\\\\]', display: true },
      { left: '$', right: '$', display: false },
      { left: '\\\\(', right: '\\\\)', display: false }
    ],
    throwOnError: false
  };
  function render() {
    document.querySelectorAll('.q-content, .q-solution').forEach(function (el) {
      if (el.getAttribute('data-katex-done') === '1') return;   // 幂等
      try {
        window.renderMathInElement(el, opts);
        el.setAttribute('data-katex-done', '1');
      } catch (e) { /* 降级：保留源码 */ }
    });
  }
  var tries = 0;
  function waitReady() {
    if (typeof window.renderMathInElement === 'function') { render(); return; }
    if (++tries > 100) return;                 // ~5s（50ms × 100）
    setTimeout(waitReady, 50);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', waitReady);
  } else {
    waitReady();
  }
  // D101：srcdoc 实时重建时 DOMContentLoaded 可能已过/首帧未就绪 —— load 后无条件补一次
  window.addEventListener('load', function () {
    if (typeof window.renderMathInElement === 'function') render();
  });
})();
<\/script>`
}

/* ---------- D103：预排版格渲染（MxN 网格 + 答案续格） ---------- */

/** 一格要渲染的内容（由 layout_result + items 合并而来）。 */
export interface SheetHtmlCellView {
  row: number
  col: number
  /** 该格的题目 id + 预先切好的块 */
  qid: string
  no: string
  blocks: SheetHtmlBlock[]
  /** 题图（只在该题首格渲染） */
  imgPath?: string
}

/** 渲染一格的内部内容：题干（带题号）/ 答案（带「（题 N 续）」标注）。 */
function cellBodyHtml(cell: SheetHtmlCellView, includeSolution: boolean, indentCls: string): string {
  const parts: string[] = []
  for (const b of cell.blocks) {
    const contMark = b.cont ? `<span class="q-cont">（题 ${escapeHtml(cell.no.replace(/\.$/, ''))} 续）</span>` : ''
    if (b.kind === 'content') {
      const no = b.cont ? '' : (cell.no ? `${cell.no}  ` : '')
      // D105 修复：题干用**行内**渲染，题号与正文同一行（此前 renderRich 的 <p>
      // 让题号独占一行 → 用户反馈"题号后空一行"）
      const body = renderRichInline(b.text) || escapeHtml(stripMarkup(b.text))
      parts.push(`<div class="q-content">${contMark}${escapeHtml(no)}${body}</div>`)
    } else if (includeSolution) {
      const scaleStyle = b.scale && b.scale < 1
        ? ` style="display:inline-block;transform:scale(${b.scale});transform-origin:left top;"`
        : ''
      const body = renderRich(b.text) || escapeHtml(stripMarkup(b.text))
      // D105 修复：「参考答案：」只在本格**首个**答案块前出现一次
      // （此前每个切分段都重复一次，与「题 N 续」曾出现的问题同源）
      const isFirstSol = !parts.some((x) => x.includes('q-solution'))
      const label = isFirstSol ? '<span class="q-sol-label">参考答案：</span>' : ''
      // D111：只有本条答案的**首个**块画顶部虚线；续段用 -cont 类，避免一排平行虚线
      const solCls = isFirstSol ? 'q-solution q-sol-first' : 'q-solution q-solution-cont'
      parts.push(`<div class="${solCls}">${contMark}${label}`
        + `<span${scaleStyle}>${body}</span></div>`)
    }
  }
  return `<div class="q-body ${indentCls}">${parts.join('\n        ') || '<span class="hint">（空白）</span>'}</div>`
}

/* ---------- 页块构建（与 j2 模板 <section class="sheet-page">… 同构） ---------- */

function pageBlockHtml(pad: Taskpad, items: SheetHtmlItem[], stu: SheetHtmlStudent,
                       pagesTotal: number, pageN: number, isVeryLast: boolean,
                       wm: WmResolved[], date: string, groupName = '',
                       includeSolution = true,
                       includeWatermark = true,
                       includePageText = true,
                       figAssets?: Record<string, string>,
                       /** D103：预排版结果（有值 → 按格渲染；无 → 旧行为整题铺满） */
                       layoutCells?: SheetHtmlCellView[]): string {
  const layout = pad.layout
  const orientation = layout.orientation === 'landscape' ? 'landscape' : 'portrait'
  const grid = resolveGrid(layout)
  const lines = gridLines(grid.rows, grid.cols)
  const title = String(layout.header.title ?? '') || '作业纸'
  const footerText = String(layout.footer.text ?? '')
  const course = String(pad.course ?? '')
  // D88-c：班级显示顺序 = 学生自身 class → 调用方给的班级名（学习通班级名/class_dir 派生）→ 空
  // （不再回落 pad.class / 硬编码 'classA'）
  const cls = String(stu.class || groupName || '')
  // D43-6 学生示例未勾选 → BLANK_STUDENT（页眉学籍三空位 = 手写空位线；作业/日期照常）
  const blank = !stu.name && !stu.number && !stu.class
  const rosterSpan = blank
    ? '<span>班级：＿＿＿＿＿＿</span>\n      <span>学号：＿＿＿＿＿＿</span>\n      <span>姓名：＿＿＿＿＿＿</span>'
    : `<span>班级：${escapeHtml(cls)}</span>\n      <span>学号：${escapeHtml(stu.number)}</span>\n      <span>姓名：${escapeHtml(stu.name)}</span>`

  const frames = lines.length
    ? lines.map((ln) => `<div class="sf-line ${ln.dir}" style="${ln.style}"></div>`).join('\n    ') + '\n    '
    : ''
  // 该页题帧（调用方已按 per_page 切好）
  return `<section class="sheet-page${orientation === 'landscape' ? ' landscape' : ''}${isVeryLast ? ' last' : ''}" data-student="${escapeHtml(stu.name)}" data-page="${pageN}">
  ${pad.watermark.enabled && includeWatermark ? wmLayerHtml(wm, pad.watermark.pageText !== false && includePageText, pageN) : ''}
  <div class="sheet-header">
    <div class="sh-title">${escapeHtml(title)}</div>
    <div class="sh-info">
      ${course ? `<span>课程：${escapeHtml(course)}</span>\n      ` : ''}${rosterSpan}
      <span class="sh-assign">作业：${escapeHtml(pad.id)}</span>
    </div>
  </div>
  <div class="sheet-body${lines.length ? ' divided' : ''}" data-grid="${grid.rows}x${grid.cols}" data-order="${grid.order}" data-rows="${grid.rows}" data-cols="${grid.cols}"${layoutCells ? ' data-layout="d103"' : ''} style="${gridBodyStyle(grid.rows, grid.cols, grid.order)}">
    ${frames}${layoutCells
      ? layoutCells.map((c) => `<div class="sheet-frame pos-${normalizeFigurePos(pad.layout.figure?.pos)}" data-cell="${c.row},${c.col}" data-qid="${escapeHtml(c.qid)}">
      ${cellBodyHtml(c, includeSolution, `indent-${normalizeIndent(pad.layout.indent)}`)}
      ${figHtml(c.imgPath, figAssets, pad.layout.figure)}
    </div>`).join('\n    ')
      : items.map((fr) => `<div class="sheet-frame pos-${normalizeFigurePos(pad.layout.figure?.pos)}">
      <div class="q-body indent-${normalizeIndent(pad.layout.indent)}">
        <div class="q-content">${escapeHtml(fr.no ? `${fr.no}  ` : '')}${renderRichInline(fr.content) || escapeHtml(fr.content)}</div>
        ${(includeSolution && fr.solution) ? `<div class="q-solution">参考答案：${renderRich(fr.solution)}</div>` : ''}
      </div>
      ${figHtml(fr.imgPath, figAssets, pad.layout.figure)}
    </div>`).join('\n    ')}
  </div>
  <div class="sheet-footer">
    <span>${footerText ? `${escapeHtml(footerText)} · ` : ''}${escapeHtml(pad.id)}-第 ${pageN}/${pagesTotal}页</span>
    <span>签名：</span>
    <span>日期：${escapeHtml(date)}</span>
  </div>
</section>`
}

/* ---------- 主入口：作业纸 → 自包含 HTML（与 CLI 同一模板） ---------- */

/**
 * 作业纸（1 份 = VB-4 打印 / VC-1 模板预览；多份 = VC-2 清单连排预览，
 * 多包不分页：包间不加封面/额外分页，页块仍按每生 page-break）。
 * 文档级 @page 方向取第一份作业纸（CSS 分页媒体查询限制；预览语义）。
 */
export function stringifySheetHtml(
  inputs: SheetHtmlPadInput | SheetHtmlPadInput[],
  opts: SheetHtmlOptions = {},
): string {
  const pads = Array.isArray(inputs) ? inputs : [inputs]
  if (!pads.length) throw new Error('stringifySheetHtml：至少需要一份作业纸')
  // 缺省名单（单包/全部预览模板态时由视图显式传 SYNTHETIC 或 [BLANK_STUDENT]）
  const synthetic = opts.syntheticFallback !== false
  const students = opts.students?.length ? opts.students : (synthetic ? SYNTHETIC_STUDENTS : [])
  const groupName = String(opts.groupName ?? '')
  const date = opts.date ?? todayStr()
  const mode = opts.katex ?? 'cdn'
  // D43-6：参考答案开关（缺省 true = CLI/zip 现状口径；PWA 模板态默认 false）
  const includeSolution = opts.includeSolution !== false
  // D43-7：水印图层/页码大字开关（缺省 true = 现状；PWA ③段两 checkbox 默认勾）
  const includeWatermark = opts.includeWatermark !== false
  const includePageText = opts.includePageText !== false
  const first = pads[0].pad
  const orientation = first.layout.orientation === 'landscape' ? 'landscape' : 'portrait'
  const docTitle = String(first.layout.header.title ?? '') || '作业纸'

  const pageSections: string[] = []
  const continuous = !!opts.continuousPage
  // D93-S5：连续页码需先算总页块数（= 各 pad 各学生各页之和）
  const blocksByPad: number[][] = []   // blocksByPad[padIdx][si] = 该生页块数
  let totalBlocks = 0
  if (continuous) {
    for (let padIdx = 0; padIdx < pads.length; padIdx++) {
      const perPage = resolveGrid(pads[padIdx].pad.layout).perPage
      // D103：有预排版 → 页数取排版结果（答案续格会产生额外页）
      const nChunks = pads[padIdx].layout?.pages?.length
        || Math.max(1, Math.ceil(pads[padIdx].items.length / perPage))
      const stuList = (pads[padIdx].students?.length ? pads[padIdx].students : students) as SheetHtmlStudent[]
      const arr: number[] = []
      for (let si = 0; si < stuList.length; si++) { arr.push(nChunks); totalBlocks += nChunks }
      blocksByPad.push(arr)
    }
  }
  let runPage = 0
  const sectionTitles = opts.sectionTitles ?? []
  const resetPerSection = opts.resetPagePerSection ?? (sectionTitles.length > 0)
  for (let padIdx = 0; padIdx < pads.length; padIdx++) {
    const { pad, items } = pads[padIdx]
    // D113-D1：每份作业纸前插入分节标题页（避免多张纸连排后分不清归属）
    const sec = sectionTitles[padIdx]
    if (sec) {
      pageSections.push(
        `<section class="sheet-page section-title-page" data-section="${escapeHtml(String(padIdx + 1))}">`
        + `<div class="section-title-box">`
        + `<div class="section-title-main">${escapeHtml(sec.title || '')}</div>`
        + (sec.subtitle ? `<div class="section-title-sub">${escapeHtml(sec.subtitle)}</div>` : '')
        + `</div></section>`,
      )
      if (resetPerSection) runPage = 0
    }
    const perPage = resolveGrid(pad.layout).perPage
    // D103：有预排版结果 → 直接用其页数（避免被 per_page 切片整除影响）；否则旧切片
    const layoutPages = pads[padIdx].layout?.pages?.length ?? 0
    const nPages = layoutPages || Math.max(1, Math.ceil(items.length / perPage))
    // D103：无 layout 时按 per_page 切片（旧行为）；有 layout 时仅为占位（每页数量以排版结果为准）
    const chunks: Array<SheetHtmlItem[] | null> = layoutPages
      ? Array.from({ length: nPages }, () => null)
      : Array.from({ length: nPages }, (_, i) => items.slice(i * perPage, (i + 1) * perPage))
    const wm = resolveWmItems(pad, opts.wmAssets, pad.layout.orientation === 'landscape' ? 'landscape' : 'portrait', opts.wmStyles)
    // D43-6 整班分段：每包可带自己的 students 子集（班级与标签页 VC-3 用）
    const stuList: SheetHtmlStudent[] = (pads[padIdx].students?.length
      ? pads[padIdx].students
      : students) as SheetHtmlStudent[]
    // D88-a：整班模式（syntheticFallback=false）下，没有学生的包直接跳过，不出"示例学生"页
    if (!stuList.length) continue
    for (let si = 0; si < stuList.length; si++) {
      const stu = stuList[si]
      chunks.forEach((_chunk, pi) => {
        const veryLast = padIdx === pads.length - 1
          && si === stuList.length - 1 && pi === chunks.length - 1
        // D93-S5：连续页码（跨整班） vs 每生从 1 起
        let pageN = pi + 1
        let pagesTotal = chunks.length
        if (continuous) {
          runPage += 1
          pageN = runPage
          pagesTotal = totalBlocks
        }
        // D103：本页的格视图（有 layout 时按格渲染；否则旧行为整题铺满）
        const cells = layoutCellsForPage(pads[padIdx].layout, pi + 1, items)
        pageSections.push(pageBlockHtml(pad, _chunk ?? [], stu, pagesTotal, pageN, veryLast, wm, date,
          groupName, includeSolution, includeWatermark, includePageText, opts.figAssets, cells))
      })
    }
  }

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(docTitle)} · ${escapeHtml(first.id)}</title>
${katexIncludeHtml(mode, opts.katexRaw)}
<style>
${printCss(orientation)}
</style>
</head>
<body>
<div class="doc-hint">
  打印（Ctrl/Cmd+P）：纸张=A4 · 边距=无 · 页眉页脚=关 · 背景图形=开（水印层依赖背景图形，docs/14 §VB-6）。
  目标选「另存为 PDF」可保存整班 PDF。公式由 KaTeX 渲染：预览/打印用 PWA 同源自托管 ./katex/（离线可渲染）；导出 HTML 自包含内联（file:// 离线可开）；CDN 版断网时按 $..$ 源码降级。
</div>
${pageSections.join('\n')}
${katexScript()}
</body>
</html>`
}

/** D94-T2：整班 HTML —— **按点名册顺序逐人输出**（不按 pack/tag 分组）。
 *  @param students 已按点名册顺序的学生列表
 *  @param resolve  某生 → { pad, items } | null（null = 无匹配作业纸 → 跳过，计入未出页）
 *  连续页码跨整班递增；其余（KaTeX/水印/开关）与 stringifySheetHtml 同口径。 */
export function stringifyClassHtml(
  students: SheetHtmlStudent[],
  resolve: (stu: SheetHtmlStudent) => { pad: Taskpad; items: SheetHtmlItem[] } | null,
  opts: SheetHtmlOptions = {},
): { html: string; skipped: string[] } {
  if (!students.length) throw new Error('stringifyClassHtml：学生名单为空')
  const groupName = String(opts.groupName ?? '')
  const date = opts.date ?? todayStr()
  const mode = opts.katex ?? 'cdn'
  const includeSolution = opts.includeSolution !== false
  const includeWatermark = opts.includeWatermark !== false
  const includePageText = opts.includePageText !== false
  // 预解析每生 → {pad, items, chunks, wm}
  type Row = { stu: SheetHtmlStudent; pad: Taskpad; chunks: SheetHtmlItem[][]; wm: WmResolved[] }
  const rows: Row[] = []
  const skipped: string[] = []
  for (const stu of students) {
    const r = resolve(stu)
    if (!r) { skipped.push(stu.name); continue }
    const { pad, items } = r
    const perPage = resolveGrid(pad.layout).perPage
    const chunks: SheetHtmlItem[][] = []
    for (let i = 0; i < items.length; i += perPage) chunks.push(items.slice(i, i + perPage))
    if (!chunks.length) chunks.push([])
    const wm = resolveWmItems(pad, opts.wmAssets,
      pad.layout.orientation === 'landscape' ? 'landscape' : 'portrait', opts.wmStyles)
    rows.push({ stu, pad, chunks, wm })
  }
  if (!rows.length) return { html: '', skipped }
  const first = rows[0].pad
  const orientation = first.layout.orientation === 'landscape' ? 'landscape' : 'portrait'
  const docTitle = String(first.layout.header.title ?? '') || '作业纸'
  const totalBlocks = rows.reduce((n, r) => n + r.chunks.length, 0)
  const pageSections: string[] = []
  let runPage = 0
  rows.forEach((r, ri) => {
    r.chunks.forEach((chunk, pi) => {
      runPage += 1
      const veryLast = ri === rows.length - 1 && pi === r.chunks.length - 1
      pageSections.push(pageBlockHtml(r.pad, chunk, r.stu, totalBlocks, runPage, veryLast,
        r.wm, date, groupName, includeSolution, includeWatermark, includePageText, opts.figAssets))
    })
  })
  const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(docTitle)} · 整班</title>
${katexIncludeHtml(mode, opts.katexRaw)}
<style>
${printCss(orientation)}
</style>
</head>
<body>
<div class="doc-hint">
  整班作业纸（**按点名册顺序逐人**）：打印（Ctrl/Cmd+P）纸张=A4 · 边距=无 · 页眉页脚=关 · 背景图形=开。
  公式由 KaTeX 渲染（同源自托管 ./katex/，离线可渲染）。
</div>
${pageSections.join('\n')}
${katexScript()}
</body>
</html>`
  return { html, skipped }
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

/* ---------- D100：参考答案「生效版」解析（与引擎 effective_solution 同语义） ---------- */

/** 版本库文档（GET /kb/solutions/<qid> 或批量索引条目）→ 生效答案。
 *  优先级与 `engine/src/assist/files/solutions.py:effective_solution` 逐条一致：
 *  pinned 版 > 最新版 > fallback（xlsx `solution` 列）> 空。 */
export interface SolutionLike {
  text?: string; source?: string; model?: string; at?: string
  version?: string; from?: string; pinned?: boolean; id?: string
  versions?: SolutionLike[]
}

export function pickEffectiveSolution(
  doc: SolutionLike | null | undefined, fallback = '',
): SolutionLike {
  const vs = (doc?.versions ?? []).filter((v) => String(v?.text ?? '').trim())
  if (vs.length) {
    const pinned = vs.find((v) => v.pinned)
    const v = pinned ?? vs[vs.length - 1]
    return {
      text: String(v.text ?? ''), source: String(v.source ?? ''), model: String(v.model ?? ''),
      at: String(v.at ?? ''), version: String(v.version ?? v.id ?? ''),
      from: pinned ? 'pinned' : 'latest', pinned: !!pinned,
    }
  }
  // 扁平条目（`GET /kb/solutions` 批量索引已算好生效版：{id, text, from, pinned}）直接采用
  const flat = String(doc?.text ?? '')
  if (!doc?.versions && flat.trim()) {
    return {
      text: flat, source: String(doc?.source ?? ''), model: String(doc?.model ?? ''),
      at: String(doc?.at ?? ''), version: String(doc?.version ?? doc?.id ?? ''),
      from: String(doc?.from ?? (doc?.pinned ? 'pinned' : 'latest')),
      pinned: !!doc?.pinned,
    }
  }
  const fb = String(fallback ?? '')
  return fb.trim()
    ? { text: fb, source: '', model: '', at: '', version: '', from: 'fallback', pinned: false }
    : { text: '', source: '', model: '', at: '', version: '', from: 'xlsx', pinned: false }
}

/** 生效答案解析器（注入点）：qid + xlsx 列 fallback → {text, from, version, ...}。
 *  PWA 侧由 kb store 提供（版本库索引 → 回退 xlsx 列）；缺省（不传）时等价旧行为。 */
export type SolutionResolver = (qid: string, fallback: string,
  scope?: { kb?: string; chap?: string }) => SolutionLike

/** 缺省解析器：只读 xlsx 列（引擎离线 / 未接线时的保守回落，与 D100 前行为一致）。 */
export const xlsxOnlySolutions: SolutionResolver = (_qid, fallback) => pickEffectiveSolution(null, fallback)

/* ---------- 题目展开辅助（VC-2：清单里任一作业纸直接预览） ---------- */

/** 作业纸 items → 模板题帧：从 kb store 取 content/solution/img_path（未命中即跳过）。
 *
 *  D100-T5：`solOf` 注入「参考答案生效版」解析器（pinned > 最新版 > xlsx 列）。
 *  不传时回落 xlsx 列（`r.solution`）——旧行为，保证引擎离线也能出同一份预览。 */
export function expandPadItems(
  pad: Taskpad,
  bookOf: (kind: KbKind) => KbBook | undefined,
  solOf: SolutionResolver = xlsxOnlySolutions,
): SheetHtmlItem[] {
  const out: SheetHtmlItem[] = []
  let seq = 0
  const auto = (pad.layout.numbering ?? 'auto') !== 'id'
  const seed = Number(pad.random_seed ?? 0)
  const seen = new Set<string>()
  // D93-translation：从 translation 题库确定性随机抽 1 道（同 seed → 同题）
  const transRows = (bookOf('translation')?.chapters || []).flatMap((c) => c.rows)
  for (const item of pad.items) {
    const chap = bookOf(item.kb as KbKind)?.chapters.find((c) => c.name === item.chap)
    const tag = String(item.tag || '')
    for (const id of item.ids) {
      // D111：历史作业纸存的是**裸题号**，而题库 row.id 现在是 `chap-前缀` 全局 id。
      // 用 scopeQuestionId 归一后再比，两种写法都能命中。
      const wantId = scopeQuestionId(item.chap, String(id))
      const r = chap?.rows.find((x) => x.id === wantId || x.id === id)
      if (!r) continue
      seq += 1
      // labels 可能以裸 id 或全局 id 为键
      const label = item.labels?.[r.id] ?? item.labels?.[String(id)] ?? ''
      // D93-copy：抄写题有 page → 改写题干
      const isCopy = item.kb === 'copy' || tag === 'copy'
      const content = (isCopy && r.page) ? copyContent(r.page, r.content, id) : r.content
      // D100-T5：生效答案（版本库置顶/最新版优先；引擎离线回落 xlsx solution 列）
      // D110：带上 (kb, chap) 作用域，跨章同号题各取各的答案
      const eff = solOf(String(r.id), r.solution || '', { kb: item.kb, chap: item.chap })
      out.push({ id: r.id, no: label || (auto ? `${seq}.` : r.id), content,
                 solution: eff.text || r.solution,
                 solutionFrom: eff.from, solutionVersion: eff.version || '',
                 solutionSource: eff.source || '', imgPath: r.img_path, tag })
      seen.add(r.id)
    }
    // D93-summary：该 tag 命中 → 追加 1 道（除非已手工加过 id=summary）
    if (tag === 'summary' && !seen.has(SUMMARY_ID)) {
      seq += 1
      out.push({ id: SUMMARY_ID, no: auto ? `${seq}.` : SUMMARY_ID, content: SUMMARY_CONTENT,
                 solution: '', imgPath: '', tag: tag || 'summary' })
      seen.add(SUMMARY_ID)
    }
  }
  // D93：合成题统一收口（覆盖"仅设 target_tag、items 为空/无对应 tag 分组"）——
  // 触发 tag = pad.target_tag 优先，否则 items 里出现过的 tag。
  const tagsPresent = new Set(pad.items.map((it) => String(it.tag || it.kb || '')))
  const tgt = String(pad.target_tag || '')
  const eff = (tgt === 'summary' || tgt === 'translation') ? tgt : ''
  const wantSummary = eff === 'summary' || tagsPresent.has('summary')
  const wantTranslation = eff === 'translation' || tagsPresent.has('translation')
  if (wantSummary && !seen.has(SUMMARY_ID)) {
    seq += 1
    out.push({ id: SUMMARY_ID, no: auto ? `${seq}.` : SUMMARY_ID, content: SUMMARY_CONTENT,
               solution: '', imgPath: '', tag: 'summary' })
    seen.add(SUMMARY_ID)
  }
  if (wantTranslation && !seen.has(TRANSLATION_ID) && transRows.length) {
    const picked = transRows[seedIndex(seed, transRows.length)]
    seq += 1
    const effT = solOf(String(picked.id ?? TRANSLATION_ID), picked.solution || '')
    out.push({ id: TRANSLATION_ID, no: auto ? `${seq}.` : TRANSLATION_ID,
               content: picked.content, solution: effT.text || picked.solution, imgPath: picked.img_path,
               solutionFrom: effT.from, solutionVersion: effT.version || '',
               solutionSource: effT.source || '', tag: 'translation' })
    seen.add(TRANSLATION_ID)
  }
  return out
}

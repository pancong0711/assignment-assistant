/** VC-3 整班作业纸预览（docs/14 §VC-3）：按"tag→任务包"映射为整班名单生成
 *  一个自包含多页 HTML overlay（每生一页块 + @page A4 + @media print 自动分页），
 *  纯前端、不依赖引擎（在线/离线均可）。
 *
 *  与并行 S2a（VB-1 HTML 打印模板，engine/templates/assignment.html.j2 +
 *  其规划的 app/src/lib/sheetHtml.ts stringifySheetHtml）**互不重名、互不冲突**：
 *  本文件是 VC-3 整班预览的 fallback 静态生成层（不承载 per-pad 的
 *  stringifySheetHtml）。S2a 模板就位后，把 buildClassPages 的页块数据
 *  （students/pages/frames 形状，见 StudentSheetPage）喂给其 stringifySheetHtml
 *  即可切换为同一模板交付——本文件的 buildBatchManifest（无引擎 fallback：
 *  README/manifest 展示）与数据装配逻辑保持不变。
 *
 *  数据来源全部为 PWA 端已有 store（roster.students / taskpad.saved），
 *  不产生任何网络/引擎调用；图片/KaTeX 在 fallback 层不内嵌（占位框说明）。
 */

import type { RosterStudent } from './roster'
import { STUDENT_TAG_LABELS } from './kb'
import { parseTaskpad, padInferredTag, type Taskpad } from './taskpad'

/** 题库取数接口（避免直接依赖 kb store / 保持纯函数可 node 自测） */
export interface SheetTextSource {
  text(kind: string, chap: string, id: string): string
}

/** 页块（一名学生一页；per_page 语义：1=单题页、2=两题/页（横版左右栏）、
 *  3/4=网格列——fallback 以 CSS grid 呈现，与引擎"帧切分"同口径）。 */
export interface StudentSheetPage {
  student: RosterStudent
  pad: Taskpad | null
  /** (题干, 来源 kind/chap/id) 列表（含未在 kb 命中的占位） */
  questions: Array<{ text: string; ref: string }>
  perPage: 1 | 2 | 3 | 4
  orientation: 'portrait' | 'landscape'
}

/** 按名单顺序展开每个学生的页块（tag→pad 映射；未绑定 tag 的学生落到
 *  fallbackPad（--default 语义）或 null（页内标注"未匹配变体"）。 */
export function buildClassPages(
  students: RosterStudent[],
  padJsons: Array<{ id: string; json: string }>,
  kb: SheetTextSource,
  fallbackPadId = '',
): StudentSheetPage[] {
  const pads: Array<{ id: string; pad: Taskpad; tag: string | null }> = []
  for (const { id, json } of padJsons) {
    try {
      const pad = parseTaskpad(JSON.parse(json))
      pads.push({ id, pad, tag: padInferredTag(pad.items, pad.target_tag) })
    } catch { /* JSON 损坏包跳过（与 batch 引擎"拒收后进"口径一致，仅跳过） */ }
  }
  const byTag = new Map<string, Taskpad>()
  for (const p of pads) if (p.tag) byTag.set(p.tag, p.pad)
  const fallback: Taskpad | undefined = fallbackPadId
    ? pads.find((p) => p.id === fallbackPadId)?.pad
    : undefined

  const pages: StudentSheetPage[] = []
  for (const stu of students) {
    const pad = (stu.tag && byTag.get(stu.tag)) || fallback || null
    const questions: StudentSheetPage['questions'] = []
    if (pad) {
      for (const it of pad.items) {
        for (const id of it.ids) {
          questions.push({ text: kb.text(it.kb, it.chap, id), ref: `${it.kb}/${it.chap}/${id}` })
        }
      }
    }
    pages.push({
      student: stu,
      pad,
      questions,
      perPage: pad ? pad.layout.per_page : 1,
      orientation: pad ? pad.layout.orientation : 'portrait',
    })
  }
  return pages
}

function esc(s: string): string {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

/** 单页块 HTML（供 stringifySheetHtml 与未来父代理模板复用的最小单元） */
export function pageBlockHtml(page: StudentSheetPage, index: number): string {
  const s = page.student
  const headerTitle = esc(page.pad?.layout.header?.title ?? '作业纸')
  const tagLabel = s.tag ? (STUDENT_TAG_LABELS[s.tag] ?? s.tag) : '（未打 tag）'
  const per = page.perPage
  const gridCols = per === 1 ? '1fr' : per === 2 ? '1fr 1fr' : per === 3 ? '1fr 1fr 1fr' : '1fr 1fr'
  const cells = page.questions.length
    ? page.questions.map((q, i) =>
      `<div class="q"><div class="q-no">${i + 1}.</div><div class="q-text">${esc(q.text) || '<span class="ph">（题干未在题库命中：载入题库 xlsx 后重试）</span>'}</div></div>`)
    : [`<div class="q"><div class="q-no">!</div><div class="q-text ph">未匹配到变体任务包（tag=${esc(s.tag || '空')} 未绑定）——请在「作业纸内容」页为该 tag 绑定任务包，或生成 batch 包时指定 --default 兜底。</div></div>`]
  return `<section class="sheet" id="p${index}">
  <header class="sheet-head">
    <span class="t">${headerTitle}</span>
    <span class="meta">${esc(s.class || '—')} · ${esc(s.number || '—')} · ${esc(s.name || '—')}（tag: ${esc(tagLabel)}）</span>
    <span class="date">${esc(new Date().toISOString().slice(0, 10))}</span>
  </header>
  <div class="sheet-body" style="grid-template-columns:${gridCols}">${cells.join('\n')}</div>
  <footer class="sheet-foot"><span>签名：＿＿＿＿＿＿＿＿</span><span>日期：＿＿＿＿＿＿＿＿</span></footer>
</section>`
}

/** 整班多页 HTML（自包含、可直接浏览器打开 → Ctrl+P 打印/存 PDF）。
 *  每生 page-break-after；landscape 用 @page size 切换。 */
export function buildClassOverlayHtml(
  students: RosterStudent[],
  padJsons: Array<{ id: string; json: string }>,
  kb: SheetTextSource,
  opts: { title?: string; classDir?: string; fallbackPadId?: string } = {},
): string {
  const pages = buildClassPages(students, padJsons, kb, opts.fallbackPadId)
  const landscape = pages.some((p) => p.orientation === 'landscape')
  const blocks = pages.map((p, i) => pageBlockHtml(p, i)).join('\n')
  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>${esc(opts.title ?? '整班作业纸预览')}</title>
<style>
  /* 与 engine/VB-1 模板同排版语义的 fallback 静态层（D30：HTML 主通道） */
  @page { size: A4 ${landscape ? 'landscape' : 'portrait'}; margin: 12mm; }
  * { box-sizing: border-box; }
  body { font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", system-ui, sans-serif; color: #1f2937; margin: 0; background: #e5e7eb; }
  .sheet {
    background: #fff; margin: 10px auto; padding: 14mm 12mm; width: 210mm; min-height: 296mm;
    box-shadow: 0 1px 6px rgba(0,0,0,.18); display: flex; flex-direction: column; position: relative;
    page-break-after: always; break-after: page;
  }
  .sheet-head { display: flex; justify-content: space-between; gap: 12px; align-items: baseline;
    border-bottom: 2px solid #1f2937; padding-bottom: 6px; }
  .sheet-head .t { font-size: 18px; font-weight: 700; }
  .sheet-head .meta { font-size: 13px; color: #374151; }
  .sheet-head .date { font-size: 12px; color: #6b7280; }
  .sheet-body { flex: 1; display: grid; gap: 8mm; padding: 8mm 0; align-content: start; }
  .q { display: flex; gap: 6px; align-items: flex-start; }
  .q-no { font-weight: 700; min-width: 2em; }
  .q-text { font-size: 14px; line-height: 1.7; white-space: pre-wrap; }
  .ph { color: #92400e; background: #fef3c7; border-radius: 4px; padding: 2px 6px; }
  .sheet-foot { border-top: 1px solid #9ca3af; padding-top: 6px; display: flex; justify-content: space-between;
    font-size: 13px; color: #374151; }
  @media print {
    body { background: #fff; }
    .sheet { margin: 0; width: auto; min-height: 0; box-shadow: none; }
    .no-print { display: none !important; }
  }
</style>
</head>
<body>
<div class="no-print" style="text-align:center;padding:10px;font-size:13px;color:#374151">
  整班作业纸预览（VC-3，纯前端静态生成，不依赖引擎）· ${pages.length} 名学生 / ${pages.length} 页 ·
  浏览器打印：Ctrl/Cmd+P（A4、边距=默认、页眉页脚=关、背景图形=开）
</div>
${blocks}
</body>
</html>`
}

/** fallback 口径（docs/14 §VC-3"若未实现 fallback"）：无引擎也不空转——
 *  生成 batch zip 同款 README/manifest 的文本展示（教师核对 tag→包绑定）。 */
export function buildBatchManifest(
  students: RosterStudent[],
  padJsons: Array<{ id: string; json: string }>,
): string {
  const tagCounts: Record<string, number> = {}
  for (const s of students) if (s.tag) tagCounts[s.tag] = (tagCounts[s.tag] ?? 0) + 1
  const lines: string[] = ['# 整班预览 manifest（fallback：静态生成，无引擎）', '']
  lines.push(`- 名单：${students.length} 人；tag 分布：${
    Object.entries(tagCounts).map(([t, n]) => `${STUDENT_TAG_LABELS[t] ?? t}×${n}`).join('、') || '（无）'}`)
  lines.push('')
  lines.push('## tag → 任务包 绑定（引擎 batch 同口径）')
  for (const { id, json } of padJsons) {
    try {
      const pad = parseTaskpad(JSON.parse(json))
      const tag = padInferredTag(pad.items, pad.target_tag)
      lines.push(`- ${id} → ${tag ?? '⚠ 混合 tag 未绑定'}（${pad.items.length} 组 / ${
        pad.items.reduce((n, i) => n + i.ids.length, 0)} 题 · ${pad.layout.orientation === 'landscape' ? '横版' : '竖版'}${pad.layout.per_page}题页）`)
    } catch {
      lines.push(`- ${id} → ⚠ JSON 损坏，引擎 batch 将拒收`)
    }
  }
  lines.push('')
  lines.push('（说明：父代理 S2a 的 stringifySheetHtml 模板实现就位后，本预览将切换为同一模板交付；当前为 fallback 静态层。）')
  return lines.join('\n')
}

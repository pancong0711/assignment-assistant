/**
 * D64-d：批阅报告渲染器（作业纸式报告，docs/16 §25.2 用户拍板版式）。
 *
 * 版式定案：
 * - 竖版（portrait）：逐题评阅——每道题占满一行顺次排（题号+题干转录 → 学生作答 → 评阅/得分），
 *   题多续页；不做 2×2 十字花（评阅内容多，四格塞不下）；
 * - 横版（landscape）：分左右两半（左半=前半题，右半=其余；每半内部仍逐题纵向）。
 * 结构基因沿用作业纸（页眉学籍三空位/页脚页码/题干渲染）；content=逐题行语义（报告页无答题留白）。
 *
 * 双实现口径（VB-1 同铁律的暂缓版）：本 TS 为首期功能权威（PWA 预览/打印）；
 * engine html 管线接 report 模式属于后续批次（届时加 parity 哨兵，docs/16 §25.2 备案）。
 *
 * 输入 SubmissionReport（数据来源预告）：学生分组 + 每题 {题目(题干), 作答图片/转录, 评语, 得分}。
 * 示例值由调用方明示 `demo:true`（不冒充真批阅）。
 */

export interface ReportQuestion {
  /** 题号（如 1-1 / 6.2 / 5.5.2） */
  no: string
  /** 题干（可含 $..$ 公式） */
  stem: string
  /** 学生作答转录（AI 转写；空=未见作答） */
  transcript: string
  /** 作答图片 URL/本地 blob/dataURL（R1 原图；可多张） */
  images?: string[]
  /** AI/教师评阅文字 */
  review: string
  /** 得分/满分 */
  score?: { got: number; full: number }
}

export interface ReviewReport {
  student: { name: string; number: string; classDisplay?: string }
  assignment: { id: string; title: string; course: string; className: string; date: string }
  orientation: 'portrait' | 'landscape'
  questions: ReportQuestion[]
  /** 总评（可选：总得分与总评语） */
  total?: { score: number; full: number; comment: string }
  /** 示例数据标记（演示用，不冒充真批阅） */
  demo?: boolean
}

const A4_PRINT_CSS = `
  @page { size: A4 ${'{ORI}'}; margin: 14mm 12mm 16mm 12mm; }
  body { font-family: "Times New Roman", SimSun, serif; color:#111; background:#fff; margin:0; }
  .page { width: 100%; }
  .hdr { display:flex; justify-content:space-between; align-items:baseline; border-bottom:2px solid #333; padding-bottom:4px; margin-bottom:10px; }
  .hdr .blank { display:inline-block; min-width:80px; border-bottom:1px solid #999; margin-left:4px; }
  .qrow { display:block; break-inside:avoid; border-bottom:1px dashed #999; padding:6px 0 8px 0; }
  ${'{LAND}'}
  .qno { font-weight:bold; margin-right:6px; }
  .sec-t { font-weight:bold; color:#456; margin:2px 0; font-size:0.92em; }
  .sec-body { margin-left:1em; white-space:pre-wrap; }
  .sub-imgs img { max-width:100%; max-height:52mm; border:1px solid #ccc; margin:2px 4px; }
  .review-box { margin-left:1em; padding:4px 8px; border-left:3px solid #7ab06a; background:#f6fbf4; }
  .score-chip { float:right; border:1px solid #666; border-radius:6px; padding:1px 8px; }
  .ftr { border-top:1px solid #999; margin-top:8px; padding-top:4px; display:flex; justify-content:space-between; font-size:0.85em; }
  .demo-badge { color:#a00; border:1px dashed #a00; display:inline-block; padding:0 6px; border-radius:6px; }
  @media print { .page { width:auto } }
`

function headerHtml(r: ReviewReport): string {
  const s = r.student
  return `<div class="hdr">
    <div><b>${r.assignment.course}</b> · 批阅报告 ${r.demo ? '<span class="demo-badge">示例数据</span>' : ''}</div>
    <div>姓名${s.name ? `：${s.name}` : '<span class="blank"></span>'}
      学号${s.number ? `：${s.number}` : '<span class="blank"></span>'}
      班级${s.classDisplay ? `：${s.classDisplay}` : '<span class="blank"></span>'}</div>
  </div>`
}

function questionHtml(q: ReportQuestion, idx: number): string {
  const img = (q.images && q.images.length)
    ? `<div class="sub-imgs">${q.images.map((u) => `<img src="${u}" alt="作答图${idx + 1}">`).join('')}</div>` : ''
  const sc = q.score ? `<span class="score-chip">${q.score.got} / ${q.score.full}</span>` : ''
  return `<div class="qrow">
    ${sc}<div class="sec-t"><span class="qno">${q.no}</span> 题目</div>
    <div class="sec-body">${q.stem}</div>
    ${q.transcript ? `<div class="sec-t">作答（转录）</div><div class="sec-body">${q.transcript}</div>` : `${img || ''}
      ${q.images?.length ? '' : '<div class="sec-body" style="color:#888">（未见作答）</div>'}`}
    ${img}
    <div class="sec-t">评阅</div>
    <div class="review-box">${q.review || '（无评阅）'}</div>
  </div>`
}

function footerHtml(r: ReviewReport): string {
  const t = r.total
  return `<div class="ftr">
    <span>${r.assignment.title} · ${r.assignment.className} · ${r.assignment.date}</span>
    <span>${t ? `总评：${t.score} / ${t.full}` : ''}　页 1/1</span>
  </div>`
}

/** 渲染自包含 HTML（样式内联；打印=A4；预览=新窗口/iframe 同构）。 */
export function stringifyReviewReportHtml(r: ReviewReport): string {
  const ori = r.orientation === 'landscape' ? 'landscape' : 'portrait'
  let css = A4_PRINT_CSS.replace('{ORI}', ori)
  css = css.replace('{LAND}', ori === 'landscape'
    ? `.qwrap { display:flex; gap:18px }
      .qcol { flex:1; min-width:0 }
      .qcol + .qcol { border-left:1px dashed #bbb; padding-left:18px }`
    : '.qwrap { display:block }')

  let body: string
  if (ori === 'landscape') {
    const half = Math.ceil(r.questions.length / 2)
    const mk = (qs: ReportQuestion[]) => qs.map((q, i) => questionHtml(q, i)).join('')
    body = `<div class="qwrap"><div class="qcol">${mk(r.questions.slice(0, half))}</div>` +
      `<div class="qcol">${mk(r.questions.slice(half))}</div></div>`
  } else {
    body = `<div class="qwrap">${r.questions.map((q, i) => questionHtml(q, i)).join('')}</div>`
  }

  const total = r.total
    ? `<div class="qrow"><div class="sec-t">总评</div><div class="review-box">${r.total.comment ||
      ''}</div></div>` : ''

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>批阅报告 · ${r.student.name || '学生'}</title>
<style>${css}</style></head>
<body><div class="page">
${headerHtml(r)}
${body}
${total}
${footerHtml(r)}
</div></body></html>`
}

/** demo 示例（5 大题 A4 卷简化两题演示件）——显示用，绝不冒充真实批阅产物。 */
export function demoReport(orientation: 'portrait' | 'landscape' = 'portrait'): ReviewReport {
  return {
    student: { name: '学生A', number: '20245678901', classDisplay: '示例241' },
    assignment: { id: 'demo', title: '示例作业（演示版式）', course: '大学物理C',
                  className: '示例班', date: new Date().toISOString().slice(0, 10) },
    orientation,
    demo: true,
    questions: [
      { no: '1-1', stem: '已知质点沿 $x$ 轴运动，$x=x(t)$，求速度与加速度。',
        transcript: '由 $v=\\frac{dx}{dt}$ 得…',
        review: '求导链条正确，量纲自洽；建议补一阶导的物理意义说明。',
        score: { got: 8, full: 10 } },
      { no: '1-2', stem: '抛体运动：给出初速度与仰角，求最高点高度。',
        transcript: '竖直分量 $v_y=v_0\\sin\\theta$，由能量守恒…',
        review: '第二句应改用运动学公式；结果等效但推理链不符题意。',
        score: { got: 6, full: 10 } },
    ],
    total: { score: 14, full: 20, comment: '概念主体牢固，计算链需扩写画图支撑。' },
  }
}

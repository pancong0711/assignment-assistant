/** D129 自检：逐生审核 / 报告预览的 LaTeX 公式必须真正渲染（不只是 Markdown 转 HTML）。
 *  背景：renderRich() 只做 Markdown→HTML + 净化，**不含 KaTeX**；
 *  用 v-html 插入后必须再调 renderMathIn()/renderMathInElement()，否则公式显示 $...$ 源码。
 *  运行：node tests/selfcheck-d129-katex-preview.mjs */
import assert from 'node:assert'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const read = (rel) => readFileSync(resolve(appDir, rel), 'utf-8')

/* 1) richdoc 本身不含 KaTeX —— 这是"必须额外渲染"的前提 */
{
  const richdoc = read('src/lib/richdoc.ts')
  assert.ok(!/renderMathInElement|katex\.render/.test(richdoc),
    'richdoc 不含 KaTeX（结论：v-html 之后必须额外渲染公式）')
}

/* 2) 逐生审核：转写区与 AI 批语区都要跑 KaTeX */
{
  const modal = read('src/components/StudentReviewModal.vue')
  assert.ok(/renderMathIn/.test(modal), '逐生审核应调用 renderMathIn 渲染公式')
  assert.ok(/from '\.\.\/lib\/katexRender'/.test(modal), '应引入 katexRender')
  assert.ok(/ref="transcriptEl"/.test(modal), '转写容器应有 ref（供 KaTeX 渲染）')
  assert.ok(/ref="aiCommentEl"/.test(modal), 'AI 批语容器应有 ref')
  assert.ok(/removeAttribute\(KATEX_DONE_ATTR\)/.test(modal),
    '内容变化时应清除幂等标记再重渲染')
  assert.ok(/renderFormulas/.test(modal) && /watch\(/.test(modal),
    '应在内容/学生切换后重渲染公式')
}

/* 3) 报告预览 HTML：必须自带 KaTeX 资源与自动渲染脚本 */
{
  const rep = read('src/lib/reports.ts')
  assert.ok(/katex\/katex\.min\.css/.test(rep), '报告 HTML 应引入 KaTeX CSS')
  assert.ok(/katex\.min\.js/.test(rep), '报告 HTML 应引入 katex.min.js')
  assert.ok(/auto-render\.min\.js/.test(rep), '报告 HTML 应引入 auto-render')
  assert.ok(/renderMathInElement/.test(rep), '报告 HTML 应有自动渲染脚本')
  assert.ok(rep.includes("left: '\\\\['"), "应含 \\[..\\] 定界符")
  assert.ok(rep.indexOf("left: '$$'") < rep.indexOf("left: '$',"),
    "长定界符 $$ 必须排在 $ 之前")
}

/* 4) 逐生审核名单：固定高度 + 滚轮 + 粘性表头 */
{
  const comp = read('src/components/AiGradingPanel.vue')
  assert.ok(/review-list-scroll/.test(comp), '名单应使用固定高度滚动容器')
  assert.ok(/max-height:\s*420px/.test(comp) && /overflow:\s*auto/.test(comp),
    '滚动容器应有 max-height + overflow:auto')
  assert.ok(/position:\s*sticky/.test(comp), '表头应粘性（滚动时可见）')
}

console.log('OK d129-katex-preview：转写/AI批语公式渲染 · 报告HTML带KaTeX · 名单固定高度滚动+粘性表头')

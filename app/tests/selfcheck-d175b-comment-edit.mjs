/** D175b 自检：逐生审核「改批语」必须真的可见、可再次修改、保存后不回退。
 *
 *  教师反馈（第 21 轮）：
 *    点「保存（批语+分数一起）」没有效果；
 *    点「继续修改」删除/修改后「应用到批语」没有效果，又恢复旧版本，
 *    似乎"已修改的批语无法继续修改"。
 *
 *  真实原因（浏览器挂载 + 抓包确认，保存请求本身是正确的）：
 *    A. 只读区 v-html 绑的是 `aiCommentHtml`（永远 AI 原文）→ 改完看不见；
 *    B. `finalCommentNow` 漏了本地 `finalComment` → 再次「继续修改」回退旧版本；
 *    C. 「继续修改」文案只看 `savedRevision`（未保存的修改不算）。
 *
 *  运行：node tests/selfcheck-d175b-comment-edit.mjs */
import assert from 'node:assert'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const src = readFileSync(resolve(appDir, 'src/components/StudentReviewModal.vue'), 'utf-8')
const code = src.replace(/\/\*[\s\S]*?\*\//g, '')

/* A. 只读区必须渲染「最终批语」，不能渲染 AI 原文 */
assert.ok(/const finalCommentHtml = computed/.test(code), '应有 finalCommentHtml（最终批语的富文本）')
assert.ok(/v-html="finalCommentHtml"/.test(src),
  '只读区必须绑定 finalCommentHtml（此前绑 aiCommentHtml → 改完看不见）')
const readOnlyBlock = src.slice(src.indexOf('只读：**当前最终批语**'), src.indexOf('编辑态：这就是'))
assert.ok(!/v-html="aiCommentHtml"/.test(readOnlyBlock),
  '只读区不得再渲染 AI 原文')

/* B. 再次编辑必须从「当前最终批语」初始化 */
assert.ok(/return finalComment\.value \|\| savedRevision\.value \|\| aiOriginal\.value/
  .test(code), 'finalCommentNow 必须优先本地 finalComment（否则继续修改会回退旧版本）')
assert.ok(/revDraft\.value = finalCommentNow\.value/.test(code),
  'startEditComment 必须用 finalCommentNow 初始化编辑框')

/* C. 「继续修改」文案要认未保存的修改 */
assert.ok(/\(savedRevision \|\| commentChanged\) \? '✏ 继续修改'/.test(src),
  '有未保存修改时也应显示「继续修改」')

/* D. 修改后要有明确提示，并保留 AI 原文对照 */
assert.ok(/已修改（尚未保存）/.test(src), '未保存时应提示"已修改（尚未保存）"')
assert.ok(/对照 AI 原文/.test(src), '应保留 AI 原文折叠对照')
assert.ok(/commentChanged/.test(code), '应有 commentChanged 计算')

/* E. 依赖顺序：watch 必须晚于 finalCommentHtml 声明（否则 TDZ 白屏） */
const iDecl = src.indexOf('const finalCommentHtml = computed')
const iWatch = src.indexOf('watch([transcriptHtml, finalCommentHtml')
assert.ok(iDecl > 0 && iWatch > iDecl,
  'watch 必须声明在 finalCommentHtml 之后（watch 创建时会立即读取依赖，否则 TDZ 白屏）')

console.log('OK d175b-comment-edit：改批语可见 · 可连续修改 · 保存后不回退 · AI 原文可对照')

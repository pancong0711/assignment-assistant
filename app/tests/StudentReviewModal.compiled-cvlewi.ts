import { defineComponent as _defineComponent } from 'vue'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { saveXxtGradeDraft, previewXxtGradeDraft, xxtReviewFileUrl, xxtGradeReportUrl } from './../src/lib/engineClient'
import { renderRich } from './../src/lib/richdoc'
import { renderMathIn, KATEX_DONE_ATTR } from './../src/lib/katexRender'


const __sfc_main = /*@__PURE__*/_defineComponent({
  __name: 'StudentReviewModal',
  props: {
    engineAddr: { type: String, required: true },
    token: { type: String, required: false },
    classId: { type: String, required: true },
    workId: { type: String, required: true },
    taskId: { type: String, required: false },
    classDir: { type: String, required: false },
    students: { type: Array, required: true },
    drafts: { type: Object, required: true },
    startIndex: { type: Number, required: false }
  },
  emits: ["close", "saved", "notify"],
  setup(__props: any, { expose: __expose, emit: __emit }) {

/** D92-R4：逐生审核弹窗（左右两栏；与「作业预览-学习通」的只读逐生预览不同——
 *  右上=AI 批语（只读，可"另存修订版"）；右下=人工批阅 + 模式（不批阅/覆盖/人工在前+附件AI/修订AI）。
 *  左=学生作答图（可上/下一位、旋转）。保存写回双套草稿（不覆盖 AI 原文）。 */
const props = __props
const emit = __emit

const idx = ref(props.startIndex ?? 0)
const rotate = ref(0)
/** D126：AI 转写区是否展开（默认展开，教师最关心 AI 认没认对） */
const showTranscript = ref(true)
/** D130-T10：右栏页签 —— 批阅 / 📄 报告（iframe 预览已生成的 reports/<学生>.html） */
const pane = ref<'review' | 'report'>('review')
/** 报告 URL（切换学生/页签时重算；加 nonce 强制 iframe 重新加载，避免缓存旧报告） */
const reportNonce = ref(0)
const reportUrl = computed<string>(() => {
  const s = cur.value
  if (!s || !props.classDir || !props.taskId) return ''
  return xxtGradeReportUrl(props.engineAddr, props.token, {
    classDir: props.classDir, taskId: props.taskId, student: s.name,
  }) + `&_=${reportNonce.value}`
})
/** 报告是否已生成（有报告图 = 生成过；用于「📄 报告」页签的可点击提示） */
const hasReport = computed<boolean>(() => (draft.value.human?.reportImages?.length || 0) > 0)
function openReport() {
  reportNonce.value += 1
  pane.value = 'report'
}
/** 父级生成报告后调用：自动切到报告页（验收 8）。 */
function showReportTab() { openReport() }
__expose({ showReportTab })
const layout = ref<'cols' | 'rows'>('cols')
const msg = ref('')

const cur = computed(() => props.students[idx.value] || null)
/** D130-T12：与表格**同源**取草稿（先按引擎 key，再按备用键兜底）——
 *  否则会出现"表里说未跑、弹窗里却有内容"的错位。 */
const draft = computed(() => {
  const s = cur.value
  if (!s) return {}
  const keys = [s.key, ...(s.altKeys || []), s.name].filter(Boolean) as string[]
  for (const k of keys) {
    const d = props.drafts[k]
    if (d && Object.keys(d).length) return d
  }
  return {}
})
const aiSet = computed(() => draft.value.ai || {})
const revisionText = computed(() => String((draft.value.revision || {}).text || ''))

/** 作答原件文件名。
 *  D126：**优先用 students[].images**（来自 `<XXT_HOME>/pages/review/<classId>/<workId>/`
 *  的实际文件名，由 `/xxt/preview/students` 补齐）；老数据回落 draft.images。
 *  此前只读 draft.images（草稿里其实没有该字段）→ 永远看不到原图。
 */
const answerImages = computed<string[]>(() => {
  const fromStudent = cur.value?.images
  if (Array.isArray(fromStudent) && fromStudent.length) return fromStudent
  const legacy = draft.value.images
  return Array.isArray(legacy) ? (legacy as string[]) : []
})

/** D126：AI 转写内容（由父级按 (classDir, taskId, student) 拉取后传入）。 */
const transcriptText = computed<string>(() => String(draft.value.ai?.transcript || ''))
/** D127：转写正文已是"### 第 N 题 / **题目：** / **作答：** / **受力图：**"结构，
 *  按富文本渲染（纯文本 pre-wrap 会把 ** 和 $..$ 原样露出来）。
 *  D127-FIX：`renderRich` 只做 Markdown→HTML + 净化，**不含 KaTeX**；
 *  必须再对容器调 `renderMathIn()`，否则公式仍显示 `$...$` 源码。 */
const transcriptHtml = computed<string>(() => (transcriptText.value ? renderRich(transcriptText.value) : ''))

const transcriptEl = ref<HTMLElement | null>(null)
const aiCommentEl = ref<HTMLElement | null>(null)

/** 对两个富文本容器做 KaTeX 渲染（幂等；内容变化时先清除标记再强制重渲染）。 */
async function renderFormulas() {
  await nextTick()
  for (const el of [transcriptEl.value, aiCommentEl.value]) {
    if (!el) continue
    el.removeAttribute(KATEX_DONE_ATTR)
    await renderMathIn(el, true)
  }
}


/* ---------------- D175：人工批阅 / 修订 / 分数 的**一体化**编辑态 ----------------
 *
 *  教师实际想要的是**一件事**：「把 AI 批语改一改，连分数一起作为最终批语保存」。
 *  旧界面把它拆成了三个互不相认的入口（另存修订版 / 人工替代 AI / 人工批阅分数），
 *  且「保存」键在 mode=none 时**不写分数**（以为没生效），报告又是另一个拼法 →
 *  "改了批语又改分数，保存没变化"。
 *
 *  现在（心智模型：一份批语 + 一个分数 = 你要发给学生的东西）：
 *   - `finalComment`：最终批语。默认=AI 原文（或已保存的修订版）；
 *     点「✏ 在 AI 批语基础上修改」后进入编辑，保存时写 `revision.text`（报告按行标红）；
 *   - `finalScore`：最终分数。默认=AI 分；
 *   - `replaceWithHuman`：勾选 =「用我的批语完全替代 AI」（纯人工报告），
 *     此时批语写 `human.comment` + `humanMode=replace`；
 *   - **保存永远同时写批语与分数**（此前 mode=none 时分数被丢弃——"点了保存没变化"）。
 */
const finalComment = ref(''); const finalScore = ref('')
/** 人工批语（= human.comment）：replace/append 模式下使用 */
const comment = ref('')
/** D175b：批语与 AI 的关系 —— keep(保留AI+修订标红) / replace(纯人工) / append(AI + 教师补充) */
const commentMode = ref<'keep' | 'replace' | 'append'>('keep')
const replacing = computed(() => commentMode.value === 'replace')
const appending = computed(() => commentMode.value === 'append')
const editingComment = ref(false)     // 是否展开最终批语编辑框
const revDraft = ref('')              // 编辑中的最终批语
const dirty = ref(false)              // 有未保存改动
const saving = ref(false)
const previewMd = ref(''); const previewKind = ref(''); const previewBusy = ref(false)
const showPreview = ref(false)

const aiOriginal = computed<string>(() => String(aiSet.value.comment || ''))
const savedRevision = computed<string>(() => revisionText.value)
/** D175-FIX：只读区必须渲染**当前最终批语**（含本地已应用、尚未保存的修改）。
 *  此前绑的是 `aiCommentHtml`（永远 AI 原文）→「应用到批语」和「保存」都看着没效果。
 *  注意：必须声明在 `finalComment`/`aiOriginal` 之后 —— `watch` 会立即读取 computed。 */
const finalCommentHtml = computed<string>(() => {
  const t = String(finalComment.value || '')
  return t ? renderRich(t) : ''
})
/** 当前最终批语与 AI 原文不同 → 视为"已修改"（用于提示与按钮文案）。 */
const commentChanged = computed<boolean>(() => {
  const cur = String(finalComment.value || '').trim()
  const org = String(aiOriginal.value || '').trim()
  return Boolean(cur) && cur !== org
})

// 内容或当前学生变化 → 重渲染公式（v-html 更新后 DOM 已替换，必须重新跑 KaTeX）
// 注意：必须放在 finalCommentHtml 声明**之后**（watch 创建时会立即读取依赖）。
watch([transcriptHtml, finalCommentHtml, showTranscript], () => { void renderFormulas() },
  { flush: 'post' })
onMounted(() => { void renderFormulas() })
/** 最终批语（当前应发出的内容）：人工替换 > 已存修订版 > AI 原文 */
const finalCommentNow = computed<string>(() => {
  if (replacing.value) return comment.value
  if (appending.value) return comment.value
  // 本地已应用的修改优先（此前漏了 finalComment → 再次"继续修改"会退回旧版本）
  return finalComment.value || savedRevision.value || aiOriginal.value
})
const aiScoreNow = computed<string>(() => (aiSet.value.score !== undefined && aiSet.value.score !== null
  ? String(aiSet.value.score) : ''))
const humanUsed = computed<boolean>(() => Boolean(draft.value.human?.used))
/** 分数来源说明（让教师知道"这个分数现在是哪来的"） */
const scoreHint = computed<string>(() => {
  if (replacing.value) return '用人工分数（纯人工报告）'
  if (appending.value) return '人工分数优先（AI 批语 + 教师补充）'
  if (humanUsed.value && draft.value.human?.score !== undefined && draft.value.human?.score !== null) {
    return '已保存人工分数（覆盖 AI 分）'
  }
  return aiScoreNow.value !== '' ? `AI 评分 ${aiScoreNow.value}` : '尚无 AI 评分'
})
const commentHint = computed<string>(() => {
  if (replacing.value) return '纯人工批语（报告里不出现 AI 原文）'
  if (appending.value) return 'AI 原文 + 教师补充批语（报告分两段）'
  if (commentChanged.value) {
    return dirty.value ? '已修改（尚未保存）' : '已修改（报告按行标红改动）'
  }
  if (savedRevision.value) return '已保存修订版（报告按行标红改动）'
  return aiOriginal.value ? 'AI 原文（未修改）' : '（还没有 AI 批语）'
})

/** D175：只有切换学生时才整表回填；保存后只更新「已保存基线」，保留教师这次输入。
 *  旧实现用 `justSaved` 旗标+全量 return，一旦某处忘了置位就会用旧值覆盖输入。 */
function fillFromDraft() {
  const d = draft.value || {}
  const h = d.human || {}
  const a = d.ai || {}
  const savedRev = String((d.revision || {}).text || '')
  comment.value = String(h.comment || '')
  finalScore.value = h.score !== undefined && h.score !== null ? String(h.score)
    : (a.score !== undefined && a.score !== null ? String(a.score) : '100')
  const hm = String(d.humanMode || 'none')
  commentMode.value = (['replace', 'human'].includes(hm) && h.used) ? 'replace'
    : (hm === 'append' && h.used) ? 'append' : 'keep'
  revDraft.value = savedRev || String(a.comment || '')
  editingComment.value = false
  finalComment.value = savedRev || String(a.comment || '')
  dirty.value = false
  showPreview.value = false; previewMd.value = ''
}
watch(idx, () => { fillFromDraft() }, { immediate: true })
// 父级重拉草稿（保存成功后）→ 只刷新"已保存基线"，不覆盖正在编辑的输入
watch(() => props.drafts, () => {
  if (dirty.value) return
  fillFromDraft()
})

function prev() { if (idx.value > 0) idx.value-- }
function next() { if (idx.value < props.students.length - 1) idx.value++ }
function imgUrl(f: string) { return xxtReviewFileUrl(props.engineAddr, props.token, props.classId, props.workId, f) }

function startEditComment() {
  editingComment.value = true
  revDraft.value = finalCommentNow.value
  dirty.value = true
}
function cancelEditComment() {
  editingComment.value = false
  revDraft.value = finalCommentNow.value
}
function applyEditComment() {
  if (!revDraft.value.trim()) { msg.value = '批语不能为空'; return }
  if (replacing.value || appending.value) comment.value = revDraft.value
  else finalComment.value = revDraft.value
  editingComment.value = false
  dirty.value = true
  previewMd.value = ''                     // 内容变了 → 旧预览作废
}
/** 切换"批语与 AI 的关系"；切到 replace/append 时把当前批语带进编辑框。 */
function setCommentMode(m: 'keep' | 'replace' | 'append') {
  const prev = commentMode.value
  commentMode.value = m
  dirty.value = true
  previewMd.value = ''
  if (m !== 'keep' && prev === 'keep' && !comment.value.trim()) {
    comment.value = finalComment.value
  }
  if (m === 'keep' && prev !== 'keep') comment.value = ''
}
/** 「恢复 AI 原文」：清掉修订版与人工批语，回到纯 AI（保存后生效）。 */
function useAiOriginal() {
  if (!window.confirm('清除你的修改，恢复 AI 原文与 AI 分数？\n（点「保存」后才会真正写入本地草稿）')) return
  editingComment.value = false
  revDraft.value = aiOriginal.value
  finalComment.value = aiOriginal.value
  comment.value = ''
  commentMode.value = 'keep'
  finalScore.value = aiScoreNow.value || '100'
  dirty.value = true
  previewMd.value = ''
}

/** 组装保存/预览用的请求体（两者**同一份**，保证"看到的就是会发出的"）。 */
function buildPayload() {
  const c = cur.value
  if (!c) return null
  const n = finalScore.value.trim() === '' ? null : Number(finalScore.value)
  const scoreOk = n !== null && Number.isFinite(n) ? n : null
  const payload: Record<string, unknown> = {
    classId: props.classId, workId: props.workId, key: c.key, student: c.name,
    taskId: props.taskId, classDir: props.classDir,
  }
  if (replacing.value) {
    // 纯人工：批语 + 分数都写人工套
    payload.human_mode = 'replace'
    payload.human = { score: scoreOk, comment: comment.value, used: true }
  } else if (appending.value) {
    // 追加：AI 批语在前 + 教师补充批语在后；人工分数优先
    payload.human_mode = 'append'
    payload.human = { score: scoreOk, comment: comment.value, used: true }
  } else {
    // 保留 AI 批语，只覆盖分数（human.score 优先），批语改动写修订版
    payload.human_mode = 'none'
    payload.human = { score: scoreOk, comment: '', used: true }
    if (finalComment.value.trim() && finalComment.value !== aiOriginal.value) {
      payload.revision = { text: finalComment.value }
    }
  }
  return payload
}

/** D175：先预览最终报告（不写盘），确认后再保存。 */
async function doPreview() {
  const payload = buildPayload()
  if (!payload) return
  previewBusy.value = true
  msg.value = ''
  try {
    const r = await previewXxtGradeDraft(props.engineAddr, props.token, payload)
    if (r?.ok) {
      previewMd.value = String(r.markdown || '')
      previewKind.value = String(r.kind || '')
      showPreview.value = true
      msg.value = `预览生成（${r.kind || 'ai'}）——下发前请确认分数与批语`
    } else msg.value = r?.error || '预览失败'
  } finally { previewBusy.value = false }
}

/** D175：**保存** = 批语 + 分数一起写（此前 mode=none 时分数被丢弃）。 */
async function save() {
  const c = cur.value
  if (!c) return
  const payload = buildPayload()
  if (!payload) return
  const n = Number(finalScore.value)
  if (finalScore.value.trim() !== '' && (!Number.isFinite(n) || n < 0 || n > 100)) {
    msg.value = '分数必须是 0~100 的数字'; return
  }
  saving.value = true
  try {
    const r = await saveXxtGradeDraft(props.engineAddr, props.token, payload as any)
    if (r?.ok) {
      dirty.value = false
      msg.value = replacing.value
        ? '✅ 已保存：纯人工批语 + 分数'
        : appending.value
          ? '✅ 已保存：AI 批语 + 教师补充批语 + 分数'
          : '✅ 已保存：批语（AI 原文为基线，改动按行标红）+ 分数'
      emit('notify', `已保存 ${c.name} 的审核`)
      emit('saved')
      showPreview.value = false
    } else msg.value = r?.error || '保存失败'
  } finally { saving.value = false }
}

/** D171-T5 保留：只存修订版（快捷入口，避免重写整份人工批阅）。 */
const savingRev = ref(false)
async function saveRevisionOnly() {
  const c = cur.value
  if (!c) return
  if (!revDraft.value.trim()) { msg.value = '修订内容为空'; return }
  savingRev.value = true
  try {
    const r = await saveXxtGradeDraft(props.engineAddr, props.token, {
      classId: props.classId, workId: props.workId, key: c.key, student: c.name,
      taskId: props.taskId, classDir: props.classDir,
      revision: { text: revDraft.value },
    })
    if (r?.ok) {
      dirty.value = false
      finalComment.value = revDraft.value
      editingComment.value = false
      msg.value = '✅ 修订版已保存（AI 原文不受影响；导出报告时按行标红）'
      emit('saved')
    } else msg.value = r?.error || '保存修订版失败'
  } finally { savingRev.value = false }
}

const __returned__ = { props, emit, idx, rotate, showTranscript, pane, reportNonce, reportUrl, hasReport, openReport, showReportTab, layout, msg, cur, draft, aiSet, revisionText, answerImages, transcriptText, transcriptHtml, transcriptEl, aiCommentEl, renderFormulas, finalComment, finalScore, comment, commentMode, replacing, appending, editingComment, revDraft, dirty, saving, previewMd, previewKind, previewBusy, showPreview, aiOriginal, savedRevision, finalCommentHtml, commentChanged, finalCommentNow, aiScoreNow, humanUsed, scoreHint, commentHint, fillFromDraft, prev, next, imgUrl, startEditComment, cancelEditComment, applyEditComment, setCommentMode, useAiOriginal, buildPayload, doPreview, save, savingRev, saveRevisionOnly }
Object.defineProperty(__returned__, '__isScriptSetup', { enumerable: false, value: true })
return __returned__
}

})
import { toDisplayString as _toDisplayString, createElementVNode as _createElementVNode, createTextVNode as _createTextVNode, createCommentVNode as _createCommentVNode, renderList as _renderList, Fragment as _Fragment, openBlock as _openBlock, createElementBlock as _createElementBlock, normalizeStyle as _normalizeStyle, normalizeClass as _normalizeClass, vModelText as _vModelText, withDirectives as _withDirectives, withModifiers as _withModifiers } from "vue"

const _hoisted_1 = {
  class: "modal",
  style: {"max-width":"min(1200px,96vw)","width":"96vw","max-height":"92vh","overflow":"auto"}
}
const _hoisted_2 = { style: {"display":"flex","align-items":"center","gap":"8px","flex-wrap":"wrap"} }
const _hoisted_3 = { style: {"margin":"0"} }
const _hoisted_4 = {
  class: "hint",
  style: {"font-weight":"400"}
}
const _hoisted_5 = ["disabled"]
const _hoisted_6 = ["disabled"]
const _hoisted_7 = { style: {"border":"1px solid var(--c-border)","border-radius":"8px","padding":"6px","max-height":"62vh","overflow":"auto","display":"flex","flex-direction":"column","gap":"8px"} }
const _hoisted_8 = ["src", "alt"]
const _hoisted_9 = {
  key: 0,
  class: "hint"
}
const _hoisted_10 = { class: "pane-tabs" }
const _hoisted_11 = {
  key: 0,
  class: "hint",
  style: {"margin-top":"8px"}
}
const _hoisted_12 = ["src"]
const _hoisted_13 = { style: {"display":"flex","align-items":"center","gap":"6px"} }
const _hoisted_14 = ["innerHTML"]
const _hoisted_15 = {
  key: 1,
  class: "hint",
  style: {"margin":"2px 0 8px"}
}
const _hoisted_16 = { style: {"margin-top":"12px","display":"flex","align-items":"center","gap":"6px","flex-wrap":"wrap"} }
const _hoisted_17 = {
  class: "hint",
  style: {"font-weight":"400"}
}
const _hoisted_18 = {
  key: 2,
  style: {"border":"1px solid var(--c-border)","border-radius":"8px","padding":"8px","min-height":"80px","max-height":"34vh","overflow":"auto","background":"var(--c-bg-soft,#f8fafc)"}
}
const _hoisted_19 = ["innerHTML"]
const _hoisted_20 = { key: 1 }
const _hoisted_21 = {
  key: 3,
  style: {"margin":"4px 0 0"}
}
const _hoisted_22 = {
  class: "hint",
  style: {"cursor":"pointer"}
}
const _hoisted_23 = {
  class: "rich-box",
  style: {"border":"1px dashed var(--c-border)","border-radius":"8px","padding":"8px","margin-top":"4px","max-height":"30vh","overflow":"auto","white-space":"pre-wrap"}
}
const _hoisted_24 = { key: 4 }
const _hoisted_25 = { style: {"margin":"4px 0","display":"flex","gap":"8px","align-items":"center","flex-wrap":"wrap"} }
const _hoisted_26 = ["disabled"]
const _hoisted_27 = { style: {"display":"flex","gap":"10px","align-items":"center","flex-wrap":"wrap","margin":"0 0 6px"} }
const _hoisted_28 = { class: "field" }
const _hoisted_29 = { class: "hint" }
const _hoisted_30 = { style: {"margin":"4px 0","display":"flex","gap":"6px","flex-wrap":"wrap"} }
const _hoisted_31 = ["placeholder"]
const _hoisted_32 = {
  key: 6,
  class: "hint",
  style: {"margin":"2px 0 0"}
}
const _hoisted_33 = { style: {"margin":"10px 0 0","display":"flex","gap":"8px","align-items":"center","flex-wrap":"wrap"} }
const _hoisted_34 = ["disabled"]
const _hoisted_35 = ["disabled"]
const _hoisted_36 = {
  key: 0,
  class: "hint",
  style: {"color":"#b45309"}
}
const _hoisted_37 = {
  key: 1,
  class: "hint"
}
const _hoisted_38 = {
  key: 7,
  class: "hint",
  style: {"margin":"2px 0","color":"#b45309"}
}
const _hoisted_39 = {
  key: 8,
  style: {"margin-top":"8px","border":"1px solid #0369a1","border-radius":"8px","padding":"8px","max-height":"38vh","overflow":"auto","background":"#fff"}
}
const _hoisted_40 = {
  class: "hint",
  style: {"margin":"0 0 6px"}
}
const _hoisted_41 = { style: {"white-space":"pre-wrap","font-family":"inherit","margin":"0"} }

export function render(_ctx, _cache, $props, $setup, $data, $options) {
  return (_openBlock(), _createElementBlock("div", {
    class: "backdrop",
    onClick: _cache[15] || (_cache[15] = _withModifiers($event => ($setup.emit('close')), ["self"]))
  }, [
    _createElementVNode("div", _hoisted_1, [
      _createElementVNode("div", _hoisted_2, [
        _createElementVNode("h3", _hoisted_3, [
          _createTextVNode("逐生审核：" + _toDisplayString($setup.cur?.name || '—') + " ", 1 /* TEXT */),
          _createElementVNode("span", _hoisted_4, "（第 " + _toDisplayString($setup.idx + 1) + " / " + _toDisplayString($props.students.length) + " 位 · tag " + _toDisplayString($setup.cur?.tag || '—') + "）", 1 /* TEXT */)
        ]),
        _cache[16] || (_cache[16] = _createElementVNode("span", { style: {"flex":"1"} }, null, -1 /* CACHED */)),
        _createElementVNode("button", {
          class: "btn",
          disabled: $setup.idx <= 0,
          onClick: $setup.prev
        }, "← 上一位", 8 /* PROPS */, _hoisted_5),
        _createElementVNode("button", {
          class: "btn",
          disabled: $setup.idx >= $props.students.length - 1,
          onClick: $setup.next
        }, "下一位 →", 8 /* PROPS */, _hoisted_6),
        _createElementVNode("button", {
          class: "btn",
          onClick: _cache[0] || (_cache[0] = $event => ($setup.rotate = ($setup.rotate - 90 + 360) % 360))
        }, "↺ 左旋"),
        _createElementVNode("button", {
          class: "btn",
          onClick: _cache[1] || (_cache[1] = $event => ($setup.rotate = ($setup.rotate + 90) % 360))
        }, "↻ 右旋"),
        _createElementVNode("button", {
          class: "btn",
          onClick: _cache[2] || (_cache[2] = $event => ($setup.layout = $setup.layout === 'cols' ? 'rows' : 'cols'))
        }, _toDisplayString($setup.layout === 'cols' ? '⇵ 上下布局' : '⇋ 左右布局'), 1 /* TEXT */),
        _createElementVNode("button", {
          class: "btn",
          onClick: _cache[3] || (_cache[3] = $event => ($setup.emit('close')))
        }, "关闭")
      ]),
      _createElementVNode("div", {
        style: _normalizeStyle([{"display":"flex","gap":"14px","align-items":"flex-start","flex-wrap":"wrap","margin-top":"10px"}, { flexDirection: $setup.layout === 'rows' ? 'column' : 'row' }])
      }, [
        _createCommentVNode(" 左栏：学生作答 "),
        _createElementVNode("div", {
          style: _normalizeStyle({ flex: $setup.layout === 'rows' ? 'none' : '1', minWidth: '280px', width: $setup.layout === 'rows' ? '100%' : 'auto' })
        }, [
          _cache[17] || (_cache[17] = _createElementVNode("h4", null, "学生作答", -1 /* CACHED */)),
          _createElementVNode("div", _hoisted_7, [
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.answerImages, (f) => {
              return (_openBlock(), _createElementBlock("img", {
                key: f,
                src: $setup.imgUrl(f),
                alt: f,
                style: _normalizeStyle({ width:'100%', height:'auto', objectFit:'contain', transform:`rotate(${$setup.rotate}deg)`, borderRadius:'6px' })
              }, null, 12 /* STYLE, PROPS */, _hoisted_8))
            }), 128 /* KEYED_FRAGMENT */)),
            (!$setup.answerImages.length)
              ? (_openBlock(), _createElementBlock("span", _hoisted_9, " （该生没有已下载的作答图；请先到「作业预览-学习通」对该作业点「⬇ 下载作答/批语」。） "))
              : _createCommentVNode("v-if", true)
          ])
        ], 4 /* STYLE */),
        _createCommentVNode(" 右栏：AI 批语（上）/ 人工批阅（下） "),
        _createElementVNode("div", {
          style: _normalizeStyle({ flex: $setup.layout === 'rows' ? 'none' : '1.1', minWidth: '300px', width: $setup.layout === 'rows' ? '100%' : 'auto' })
        }, [
          _createCommentVNode(" D130-T10：页签 —— 批阅 / 报告（报告复用 reports/<学生>.html，iframe 预览） "),
          _createElementVNode("div", _hoisted_10, [
            _createElementVNode("button", {
              class: _normalizeClass(["btn small", { primary: $setup.pane === 'review' }]),
              onClick: _cache[4] || (_cache[4] = $event => ($setup.pane = 'review'))
            }, "✏ 批阅", 2 /* CLASS */),
            _createElementVNode("button", {
              class: _normalizeClass(["btn small", { primary: $setup.pane === 'report' }]),
              onClick: _cache[5] || (_cache[5] = $event => ($setup.openReport()))
            }, " 📄 报告" + _toDisplayString($setup.hasReport ? '' : '（未生成）'), 3 /* TEXT, CLASS */)
          ]),
          ($setup.pane === 'report')
            ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                (!$setup.reportUrl)
                  ? (_openBlock(), _createElementBlock("div", _hoisted_11, " （缺少班级目录或批阅目录键，无法定位报告。请先在 ② 区关联班级目录后再试。） "))
                  : (_openBlock(), _createElementBlock("iframe", {
                      key: $setup.reportNonce,
                      src: $setup.reportUrl,
                      class: "report-frame",
                      title: "批阅报告预览"
                    }, null, 8 /* PROPS */, _hoisted_12)),
                _cache[18] || (_cache[18] = _createElementVNode("p", {
                  class: "hint",
                  style: {"margin-top":"4px"}
                }, " 这里预览的就是要发给学生/上传平台的报告（含转写原文、评分与扣分依据）。 若显示\"尚未生成报告\"，先点下方「📄 一键生成批阅报告」。 ", -1 /* CACHED */))
              ], 64 /* STABLE_FRAGMENT */))
            : (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                _createCommentVNode(" D126：AI 转写（便于对照原图，确认 AI 识别是否准确） "),
                _createElementVNode("h4", _hoisted_13, [
                  _cache[19] || (_cache[19] = _createTextVNode(" AI 转写 ", -1 /* CACHED */)),
                  _cache[20] || (_cache[20] = _createElementVNode("span", {
                    class: "hint",
                    style: {"font-weight":"400"}
                  }, " （AI 从作答图识别出的文字；与左侧原图对照可发现识别偏差） ", -1 /* CACHED */)),
                  ($setup.transcriptText)
                    ? (_openBlock(), _createElementBlock("button", {
                        key: 0,
                        class: "btn small",
                        style: {"margin-left":"auto"},
                        onClick: _cache[6] || (_cache[6] = $event => ($setup.showTranscript = !$setup.showTranscript))
                      }, _toDisplayString($setup.showTranscript ? '收起' : '展开'), 1 /* TEXT */))
                    : _createCommentVNode("v-if", true)
                ]),
                ($setup.transcriptText && $setup.showTranscript)
                  ? (_openBlock(), _createElementBlock("div", {
                      key: 0,
                      ref: "transcriptEl",
                      class: "rich-box",
                      style: {"border":"1px solid var(--c-border)","border-radius":"8px","padding":"8px","max-height":"30vh","overflow":"auto","background":"var(--c-bg-soft,#f8fafc)","font-size":"13px"},
                      innerHTML: $setup.transcriptHtml
                    }, null, 8 /* PROPS */, _hoisted_14))
                  : (!$setup.transcriptText)
                    ? (_openBlock(), _createElementBlock("p", _hoisted_15, " （暂无转写内容。请按顺序排查：① 该生是否根本没参与本次转写（如「仅评阅」、 或批阅发生在 D126 之前，那时不保存转写）——重跑「① 仅转录」即可；② 多数学生转录 失败时，勾选「有学生转录失败时仍继续」再看；③ 若「仅转录」提示完成、文件夹里也有 transcripts/*.json，但这里仍为空 → 属于**目录口径不一致**（草稿与转写不在同一 grading 目录），请把该作业的 grading 目录名反馈给开发者。） "))
                    : _createCommentVNode("v-if", true),
                _createCommentVNode(" ===== D175：一份批语 + 一个分数 = 你要发给学生的东西 =====\n               保存一定会同时写批语与分数；\"另存修订版\"与\"人工分数\"不再各走各的。 "),
                _createElementVNode("h4", _hoisted_16, [
                  _cache[21] || (_cache[21] = _createTextVNode(" ✍ 最终批语 ", -1 /* CACHED */)),
                  _createElementVNode("span", _hoisted_17, _toDisplayString($setup.commentHint), 1 /* TEXT */),
                  _cache[22] || (_cache[22] = _createElementVNode("span", { style: {"flex":"1"} }, null, -1 /* CACHED */)),
                  (!$setup.editingComment)
                    ? (_openBlock(), _createElementBlock("button", {
                        key: 0,
                        class: "btn small",
                        onClick: $setup.startEditComment
                      }, _toDisplayString(($setup.savedRevision || $setup.commentChanged) ? '✏ 继续修改' : '✏ 在 AI 批语基础上修改'), 1 /* TEXT */))
                    : _createCommentVNode("v-if", true),
                  ($setup.finalComment !== $setup.aiOriginal || $setup.savedRevision)
                    ? (_openBlock(), _createElementBlock("button", {
                        key: 1,
                        class: "btn small",
                        onClick: $setup.useAiOriginal,
                        title: "丢弃你的修改，恢复 AI 原文"
                      }, "↩ 恢复 AI 原文"))
                    : _createCommentVNode("v-if", true)
                ]),
                _createCommentVNode(" 只读：**当前最终批语**（含本地已应用的修改）；AI 原文另折叠对照 "),
                (!$setup.editingComment)
                  ? (_openBlock(), _createElementBlock("div", _hoisted_18, [
                      ($setup.finalCommentHtml)
                        ? (_openBlock(), _createElementBlock("div", {
                            key: 0,
                            ref: "aiCommentEl",
                            class: "rich-box",
                            innerHTML: $setup.finalCommentHtml
                          }, null, 8 /* PROPS */, _hoisted_19))
                        : (_openBlock(), _createElementBlock("span", _hoisted_20, "（无批语：该生可能只有本地旧草稿分数，或尚未跑 AI 批阅）"))
                    ]))
                  : _createCommentVNode("v-if", true),
                (!$setup.editingComment && $setup.commentChanged)
                  ? (_openBlock(), _createElementBlock("details", _hoisted_21, [
                      _createElementVNode("summary", _hoisted_22, "对照 AI 原文（" + _toDisplayString($setup.aiOriginal.length) + " 字，只读）", 1 /* TEXT */),
                      _createElementVNode("div", _hoisted_23, _toDisplayString($setup.aiOriginal), 1 /* TEXT */)
                    ]))
                  : _createCommentVNode("v-if", true),
                _createCommentVNode(" 编辑态：这就是\"要发出去的批语\" "),
                ($setup.editingComment)
                  ? (_openBlock(), _createElementBlock("div", _hoisted_24, [
                      _withDirectives(_createElementVNode("textarea", {
                        "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => (($setup.revDraft) = $event)),
                        rows: "8",
                        style: {"width":"100%","font-family":"inherit"},
                        placeholder: "在此修改批语（支持 LaTeX $...$）。保存后报告中你的改动会按行标红。"
                      }, null, 512 /* NEED_PATCH */), [
                        [_vModelText, $setup.revDraft]
                      ]),
                      _createElementVNode("p", _hoisted_25, [
                        _createElementVNode("button", {
                          class: "btn small primary",
                          onClick: $setup.applyEditComment
                        }, "✓ 应用到批语"),
                        _createElementVNode("button", {
                          class: "btn small",
                          onClick: $setup.cancelEditComment
                        }, "取消"),
                        _createElementVNode("button", {
                          class: "btn small",
                          disabled: $setup.savingRev,
                          onClick: $setup.saveRevisionOnly,
                          title: "只把修订版写进草稿，不动分数（高级用法）"
                        }, _toDisplayString($setup.savingRev ? '保存中…' : '仅存修订版'), 9 /* TEXT, PROPS */, _hoisted_26),
                        _cache[23] || (_cache[23] = _createElementVNode("span", { class: "hint" }, [
                          _createTextVNode("「应用到批语」后还需点下面 "),
                          _createElementVNode("b", null, "💾 保存"),
                          _createTextVNode(" 才写入草稿")
                        ], -1 /* CACHED */))
                      ])
                    ]))
                  : _createCommentVNode("v-if", true),
                _createCommentVNode(" ===== 分数 ===== "),
                _cache[27] || (_cache[27] = _createElementVNode("h4", { style: {"margin-top":"12px"} }, "分数", -1 /* CACHED */)),
                _createElementVNode("p", _hoisted_27, [
                  _createElementVNode("label", _hoisted_28, [
                    _cache[24] || (_cache[24] = _createTextVNode("最终分数 ", -1 /* CACHED */)),
                    _withDirectives(_createElementVNode("input", {
                      "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => (($setup.finalScore) = $event)),
                      type: "number",
                      min: "0",
                      max: "100",
                      style: {"width":"88px"},
                      onInput: _cache[9] || (_cache[9] = $event => {$setup.dirty = true; $setup.previewMd = ''})
                    }, null, 544 /* NEED_HYDRATION, NEED_PATCH */), [
                      [_vModelText, $setup.finalScore]
                    ])
                  ]),
                  _createElementVNode("span", _hoisted_29, _toDisplayString($setup.scoreHint), 1 /* TEXT */)
                ]),
                _createCommentVNode(" ===== 与 AI 的关系（三选一） ===== "),
                _cache[28] || (_cache[28] = _createElementVNode("h4", { style: {"margin-top":"12px"} }, "批语与 AI 的关系", -1 /* CACHED */)),
                _createElementVNode("p", _hoisted_30, [
                  _createElementVNode("button", {
                    class: _normalizeClass(["btn small", { primary: $setup.commentMode === 'keep' }]),
                    onClick: _cache[10] || (_cache[10] = $event => ($setup.setCommentMode('keep'))),
                    title: "保留 AI 原文，你的改动按行标红（默认）"
                  }, "✏ 修订 AI（标红改动）", 2 /* CLASS */),
                  _createElementVNode("button", {
                    class: _normalizeClass(["btn small", { primary: $setup.commentMode === 'append' }]),
                    onClick: _cache[11] || (_cache[11] = $event => ($setup.setCommentMode('append'))),
                    title: "AI 原文在前 + 你的补充批语在后"
                  }, "➕ 追加到 AI 之后", 2 /* CLASS */),
                  _createElementVNode("button", {
                    class: _normalizeClass(["btn small", { primary: $setup.commentMode === 'replace' }]),
                    onClick: _cache[12] || (_cache[12] = $event => ($setup.setCommentMode('replace'))),
                    title: "纯人工批语，报告里不出现 AI 原文"
                  }, "↩ 完全替代 AI", 2 /* CLASS */)
                ]),
                ($setup.commentMode !== 'keep')
                  ? _withDirectives((_openBlock(), _createElementBlock("textarea", {
                      key: 5,
                      "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => (($setup.comment) = $event)),
                      rows: "5",
                      style: {"width":"100%","font-family":"inherit","margin-top":"6px"},
                      placeholder: $setup.commentMode === 'append'
                      ? '教师补充批语（追加在 AI 原文之后，支持 LaTeX）'
                      : '纯人工批语（替代 AI 原文，支持 LaTeX）',
                      onInput: _cache[14] || (_cache[14] = $event => {$setup.dirty = true; $setup.previewMd = ''})
                    }, null, 40 /* PROPS, NEED_HYDRATION */, _hoisted_31)), [
                      [_vModelText, $setup.comment]
                    ])
                  : _createCommentVNode("v-if", true),
                ($setup.commentMode !== 'keep')
                  ? (_openBlock(), _createElementBlock("p", _hoisted_32, [
                      _createTextVNode(_toDisplayString($setup.commentMode === 'append'
              ? '报告 = AI 原文 + 【教师补充批语】+ 你的分数'
              : '报告 = 纯人工批语 + 你的分数（不出现 AI 原文）') + " 　", 1 /* TEXT */),
                      _createElementVNode("button", {
                        class: "btn small",
                        onClick: $setup.startEditComment
                      }, "✏ 在编辑框里写这份批语")
                    ]))
                  : _createCommentVNode("v-if", true),
                _createCommentVNode(" ===== 保存 / 预览 ===== "),
                _createElementVNode("p", _hoisted_33, [
                  _createElementVNode("button", {
                    class: "btn primary",
                    disabled: $setup.saving,
                    onClick: $setup.save
                  }, _toDisplayString($setup.saving ? '保存中…' : '💾 保存（批语 + 分数一起）'), 9 /* TEXT, PROPS */, _hoisted_34),
                  _createElementVNode("button", {
                    class: "btn small",
                    disabled: $setup.previewBusy,
                    onClick: $setup.doPreview
                  }, _toDisplayString($setup.previewBusy ? '生成中…' : '👁 预览将发出的报告'), 9 /* TEXT, PROPS */, _hoisted_35),
                  ($setup.dirty)
                    ? (_openBlock(), _createElementBlock("span", _hoisted_36, "● 有未保存改动"))
                    : ($setup.msg)
                      ? (_openBlock(), _createElementBlock("span", _hoisted_37, _toDisplayString($setup.msg), 1 /* TEXT */))
                      : _createCommentVNode("v-if", true)
                ]),
                ($setup.dirty && $setup.msg)
                  ? (_openBlock(), _createElementBlock("p", _hoisted_38, _toDisplayString($setup.msg), 1 /* TEXT */))
                  : _createCommentVNode("v-if", true),
                ($setup.showPreview)
                  ? (_openBlock(), _createElementBlock("div", _hoisted_39, [
                      _createElementVNode("p", _hoisted_40, [
                        _cache[25] || (_cache[25] = _createTextVNode(" 这是", -1 /* CACHED */)),
                        _cache[26] || (_cache[26] = _createElementVNode("b", null, "保存后要发出去的报告", -1 /* CACHED */)),
                        _createTextVNode("（" + _toDisplayString($setup.previewKind) + "）。确认无误再点「💾 保存」。 ", 1 /* TEXT */)
                      ]),
                      _createElementVNode("pre", _hoisted_41, _toDisplayString($setup.previewMd), 1 /* TEXT */)
                    ]))
                  : _createCommentVNode("v-if", true)
              ], 64 /* STABLE_FRAGMENT */))
        ], 4 /* STYLE */)
      ], 4 /* STYLE */)
    ])
  ]))
}
__sfc_main.render = render
export default __sfc_main

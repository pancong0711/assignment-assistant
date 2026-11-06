import { defineComponent as _defineComponent } from 'vue'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { saveXxtGradeDraft, xxtReviewFileUrl, xxtGradeReportUrl } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/engineClient'
import { renderRich } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/richdoc'
import { renderMathIn, KATEX_DONE_ATTR } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/katexRender'


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
/** D170-T10：修订版是否**已写入引擎草稿库**（区别于"正在编辑、还没保存"）。 */
const revisionSavedInStore = computed(() => Boolean(revisionText.value))

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
const aiCommentHtml = computed<string>(() => {
  const t = String(aiSet.value.comment || '')
  return t ? renderRich(t) : ''
})

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

// 内容或当前学生变化 → 重渲染公式（v-html 更新后 DOM 已替换，必须重新跑 KaTeX）
watch([transcriptHtml, aiCommentHtml, showTranscript], () => { void renderFormulas() },
  { flush: 'post' })
onMounted(() => { void renderFormulas() })

/* 人工批阅编辑态 */
const score = ref(''); const comment = ref(''); const humanMode = ref('none')
const revising = ref(false); const revDraft = ref('')
const savingRev = ref(false)

/** D170-T4：保存后**不要**用旧草稿覆盖教师刚输入的值。
 *
 *  此前：保存成功 → emit('saved') → 父组件重拉草稿 → props.drafts 变 →
 *  这个 watch 立刻把 `score` 回填成**旧的** human/ai 值 →
 *  教师看到"分数没变"，以为没生效而反复点（数据其实已保存）。
 *
 *  现在：保存成功后置 `justSaved=true`；下一次 watch 只更新**非编辑态**，
 *  并且在下一次切换学生（idx 变）时清除标记。
 */
let justSaved = false
watch([idx, () => props.drafts], ([newIdx], [oldIdx]) => {
  // 切换学生 → 一定要回填（这是正确行为）
  if (newIdx !== oldIdx) justSaved = false
  if (justSaved) return          // 刚保存过：保留教师的输入，不覆盖
  const d = props.drafts[cur.value?.key || ''] || {}
  score.value = d?.human?.score !== undefined && d?.human?.score !== null
    ? String(d.human.score) : (d?.ai?.score !== undefined && d?.ai?.score !== null ? String(d.ai.score) : '100')
  comment.value = String(d?.human?.comment || '')
  humanMode.value = String(d?.humanMode || (d?.human?.used ? 'replace' : 'none'))
  revDraft.value = String((d?.revision || {}).text || '')
  revising.value = false
}, { immediate: true })

function prev() { if (idx.value > 0) idx.value-- }
function next() { if (idx.value < props.students.length - 1) idx.value++ }
function imgUrl(f: string) { return xxtReviewFileUrl(props.engineAddr, props.token, props.classId, props.workId, f) }

function startRevise() { revising.value = true; revDraft.value = revisionText.value || String(aiSet.value.comment || '') }

/** D171-T5：**只保存修订版**（不改人工批阅）。
 *
 *  此前修订框在上方，唯一的保存键在下方"人工批阅"区，且那个键同时写
 *  human + revision + humanMode → 教师分不清"我保存的是修订还是人工批阅"。
 */
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
      justSaved = true
      msg.value = '✅ 修订版已保存（AI 原文不受影响；导出报告时按行标红）'
      revising.value = false
      emit('saved')
    } else msg.value = r?.error || '保存修订版失败'
  } finally { savingRev.value = false }
}

async function save() {
  const c = cur.value
  if (!c) return
  const n = score.value.trim() === '' ? null : Number(score.value)
  const payload: any = {
    classId: props.classId, workId: props.workId, key: c.key, student: c.name,
    human_mode: humanMode.value,
    taskId: props.taskId, classDir: props.classDir,
  }
  if (humanMode.value !== 'none') {
    payload.human = { score: Number.isFinite(n as number) ? n : null, comment: comment.value, used: true }
  }
  if (revising.value && revDraft.value.trim()) {
    payload.revision = { text: revDraft.value }
  }
  const r = await saveXxtGradeDraft(props.engineAddr, props.token, payload)
  if (r?.ok) {
    justSaved = true             // D170-T4：阻止 watch 覆盖刚输入的值
    msg.value = `✅ 已保存（模式 ${humanMode.value}${humanMode.value === 'none' ? '，仅用 AI 批语' : ''}）`
    emit('notify', `已保存 ${c.name} 的审核（模式 ${humanMode.value}）`)
    emit('saved')
  } else msg.value = r?.error || '保存失败'
}

const __returned__ = { props, emit, idx, rotate, showTranscript, pane, reportNonce, reportUrl, hasReport, openReport, showReportTab, layout, msg, cur, draft, aiSet, revisionText, revisionSavedInStore, answerImages, transcriptText, transcriptHtml, aiCommentHtml, transcriptEl, aiCommentEl, renderFormulas, score, comment, humanMode, revising, revDraft, savingRev, get justSaved() { return justSaved }, set justSaved(v) { justSaved = v }, prev, next, imgUrl, startRevise, saveRevisionOnly, save }
Object.defineProperty(__returned__, '__isScriptSetup', { enumerable: false, value: true })
return __returned__
}

})
import { toDisplayString as _toDisplayString, createElementVNode as _createElementVNode, createTextVNode as _createTextVNode, createCommentVNode as _createCommentVNode, renderList as _renderList, Fragment as _Fragment, openBlock as _openBlock, createElementBlock as _createElementBlock, normalizeStyle as _normalizeStyle, normalizeClass as _normalizeClass, vModelText as _vModelText, withDirectives as _withDirectives, vModelSelect as _vModelSelect, withModifiers as _withModifiers } from "vue"

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
const _hoisted_16 = { style: {"margin-top":"10px"} }
const _hoisted_17 = {
  class: "hint",
  style: {"font-weight":"400"}
}
const _hoisted_18 = { style: {"border":"1px solid var(--c-border)","border-radius":"8px","padding":"8px","min-height":"80px","background":"var(--c-bg-soft,#f8fafc)"} }
const _hoisted_19 = { key: 0 }
const _hoisted_20 = ["innerHTML"]
const _hoisted_21 = { key: 2 }
const _hoisted_22 = { style: {"margin":"6px 0"} }
const _hoisted_23 = {
  key: 2,
  class: "hint",
  style: {"margin":"0 0 6px","color":"#0369a1"}
}
const _hoisted_24 = {
  key: 4,
  style: {"margin":"4px 0"}
}
const _hoisted_25 = ["disabled"]
const _hoisted_26 = ["disabled"]
const _hoisted_27 = { style: {"display":"flex","gap":"8px","align-items":"center","flex-wrap":"wrap","margin":"0 0 6px"} }
const _hoisted_28 = { class: "field" }
const _hoisted_29 = { class: "field" }
const _hoisted_30 = { style: {"margin":"8px 0 0","display":"flex","gap":"8px","align-items":"center","flex-wrap":"wrap"} }
const _hoisted_31 = { style: {"margin":"8px 0 0","display":"flex","gap":"8px","align-items":"center"} }
const _hoisted_32 = {
  key: 0,
  class: "hint"
}

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
                _createElementVNode("h4", _hoisted_16, [
                  _cache[21] || (_cache[21] = _createTextVNode("AI 批语 ", -1 /* CACHED */)),
                  _createElementVNode("span", _hoisted_17, "（只读基线" + _toDisplayString($setup.aiSet.score != null ? ` · 评分 ${$setup.aiSet.score}` : '') + "）", 1 /* TEXT */)
                ]),
                _createElementVNode("div", _hoisted_18, [
                  ($setup.revisionText)
                    ? (_openBlock(), _createElementBlock("span", _hoisted_19, "（已另存修订版，见下）"))
                    : ($setup.aiCommentHtml)
                      ? (_openBlock(), _createElementBlock("div", {
                          key: 1,
                          ref: "aiCommentEl",
                          class: "rich-box",
                          innerHTML: $setup.aiCommentHtml
                        }, null, 8 /* PROPS */, _hoisted_20))
                      : (_openBlock(), _createElementBlock("span", _hoisted_21, "（无 AI 批语：该生可能只有本地旧草稿分数，或尚未跑 AI 批阅）"))
                ]),
                _createElementVNode("p", _hoisted_22, [
                  _createElementVNode("button", {
                    class: "btn small",
                    onClick: $setup.startRevise
                  }, _toDisplayString($setup.revisionText ? '编辑修订版' : '另存修订版…'), 1 /* TEXT */),
                  _cache[22] || (_cache[22] = _createElementVNode("span", {
                    class: "hint",
                    style: {"margin-left":"8px"}
                  }, " 修订 = 在 AI 批语基础上改；报告将按行**标红**改动，AI 原文不被覆盖。 ", -1 /* CACHED */))
                ]),
                _createCommentVNode(" D170-T10：修订版存在哪、在哪能看到（教师反馈\"保存后找不到\"） "),
                ($setup.revisionText)
                  ? (_openBlock(), _createElementBlock("p", _hoisted_23, [
                      _cache[23] || (_cache[23] = _createTextVNode(" 修订版已保存在", -1 /* CACHED */)),
                      _cache[24] || (_cache[24] = _createElementVNode("b", null, "引擎草稿库", -1 /* CACHED */)),
                      _cache[25] || (_cache[25] = _createTextVNode("（", -1 /* CACHED */)),
                      _cache[26] || (_cache[26] = _createElementVNode("code", null, "grade-drafts", -1 /* CACHED */)),
                      _cache[27] || (_cache[27] = _createTextVNode("，不是本机文件）： 它会在", -1 /* CACHED */)),
                      _cache[28] || (_cache[28] = _createElementVNode("b", null, "导出报告", -1 /* CACHED */)),
                      _cache[29] || (_cache[29] = _createTextVNode("时按行标红体现，也可返回本行重新「编辑修订版」。 想看全文：点上方「编辑修订版」即可展开当前修订内容。 ", -1 /* CACHED */)),
                      _cache[30] || (_cache[30] = _createElementVNode("br", null, null, -1 /* CACHED */)),
                      _createTextVNode("状态：已修订（" + _toDisplayString($setup.revisionText.length) + " 字） ", 1 /* TEXT */),
                      (!$setup.revisionSavedInStore)
                        ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                            _createTextVNode("· ⚠ 本页尚未保存，点下方「💾 保存到本地」才会写入引擎")
                          ], 64 /* STABLE_FRAGMENT */))
                        : _createCommentVNode("v-if", true)
                    ]))
                  : _createCommentVNode("v-if", true),
                ($setup.revising)
                  ? _withDirectives((_openBlock(), _createElementBlock("textarea", {
                      key: 3,
                      "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => (($setup.revDraft) = $event)),
                      rows: "5",
                      style: {"width":"100%","font-family":"inherit"},
                      placeholder: "AI 批语的人工修订版（支持 LaTeX $...$）"
                    }, null, 512 /* NEED_PATCH */)), [
                      [_vModelText, $setup.revDraft]
                    ])
                  : _createCommentVNode("v-if", true),
                ($setup.revising)
                  ? (_openBlock(), _createElementBlock("p", _hoisted_24, [
                      _createElementVNode("button", {
                        class: "btn small primary",
                        disabled: $setup.savingRev,
                        onClick: $setup.saveRevisionOnly
                      }, _toDisplayString($setup.savingRev ? '保存中…' : '💾 保存修订版'), 9 /* TEXT, PROPS */, _hoisted_25),
                      _createElementVNode("button", {
                        class: "btn small",
                        disabled: $setup.savingRev,
                        onClick: _cache[8] || (_cache[8] = $event => ($setup.revising = false))
                      }, "取消", 8 /* PROPS */, _hoisted_26),
                      _cache[31] || (_cache[31] = _createElementVNode("span", {
                        class: "hint",
                        style: {"margin-left":"8px"}
                      }, [
                        _createTextVNode("只保存修订版，"),
                        _createElementVNode("b", null, "不改"),
                        _createTextVNode("人工批阅")
                      ], -1 /* CACHED */))
                    ]))
                  : _createCommentVNode("v-if", true),
                _cache[35] || (_cache[35] = _createElementVNode("h4", { style: {"margin-top":"10px"} }, "人工批阅（可选）", -1 /* CACHED */)),
                _createElementVNode("p", _hoisted_27, [
                  _createElementVNode("label", _hoisted_28, [
                    _cache[33] || (_cache[33] = _createTextVNode("模式 ", -1 /* CACHED */)),
                    _withDirectives(_createElementVNode("select", {
                      "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => (($setup.humanMode) = $event))
                    }, [...(_cache[32] || (_cache[32] = [
                      _createElementVNode("option", { value: "none" }, "仅 AI（默认）", -1 /* CACHED */),
                      _createElementVNode("option", { value: "replace" }, "人工替代 AI（报告=纯人工）", -1 /* CACHED */),
                      _createElementVNode("option", { value: "append" }, "追加到 AI 之后（报告=AI + 教师补充）", -1 /* CACHED */),
                      _createElementVNode("option", { value: "revise" }, "修订 AI（报告=AI报告·人工修订·标红）", -1 /* CACHED */)
                    ]))], 512 /* NEED_PATCH */), [
                      [_vModelSelect, $setup.humanMode]
                    ])
                  ]),
                  _createElementVNode("label", _hoisted_29, [
                    _cache[34] || (_cache[34] = _createTextVNode("分数 ", -1 /* CACHED */)),
                    _withDirectives(_createElementVNode("input", {
                      "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => (($setup.score) = $event)),
                      type: "number",
                      min: "0",
                      max: "100",
                      style: {"width":"80px"}
                    }, null, 512 /* NEED_PATCH */), [
                      [_vModelText, $setup.score]
                    ])
                  ])
                ]),
                _withDirectives(_createElementVNode("textarea", {
                  "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => (($setup.comment) = $event)),
                  rows: "4",
                  style: {"width":"100%","font-family":"inherit"},
                  placeholder: "人工批语（支持 LaTeX；模式=none/revise 时可留空）"
                }, null, 512 /* NEED_PATCH */), [
                  [_vModelText, $setup.comment]
                ]),
                _createElementVNode("p", _hoisted_30, [
                  _createElementVNode("button", {
                    class: _normalizeClass(["btn small", { primary: $setup.humanMode === 'none' }]),
                    onClick: _cache[12] || (_cache[12] = $event => ($setup.humanMode = 'none')),
                    title: "报告只用 AI 批语（默认）"
                  }, "↩ 仅 AI", 2 /* CLASS */),
                  _createElementVNode("button", {
                    class: _normalizeClass(["btn small", { primary: $setup.humanMode === 'replace' }]),
                    onClick: _cache[13] || (_cache[13] = $event => ($setup.humanMode = 'replace')),
                    title: "人工批语替代 AI 批语 → 报告为纯人工批阅报告"
                  }, "✏ 人工替代 AI", 2 /* CLASS */),
                  _createElementVNode("button", {
                    class: _normalizeClass(["btn small", { primary: $setup.humanMode === 'append' }]),
                    onClick: _cache[14] || (_cache[14] = $event => ($setup.humanMode = 'append')),
                    title: "AI 批语在前 + 人工批语在后"
                  }, "➕ 追加到 AI 之后", 2 /* CLASS */)
                ]),
                _createElementVNode("p", _hoisted_31, [
                  _createElementVNode("button", {
                    class: "btn primary",
                    onClick: $setup.save
                  }, "💾 保存到本地（不覆盖 AI 原文）"),
                  ($setup.msg)
                    ? (_openBlock(), _createElementBlock("span", _hoisted_32, _toDisplayString($setup.msg), 1 /* TEXT */))
                    : _createCommentVNode("v-if", true)
                ])
              ], 64 /* STABLE_FRAGMENT */))
        ], 4 /* STYLE */)
      ], 4 /* STYLE */)
    ])
  ]))
}
__sfc_main.render = render
export default __sfc_main

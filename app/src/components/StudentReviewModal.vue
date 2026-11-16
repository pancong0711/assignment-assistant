<script setup lang="ts">
/** D92-R4：逐生审核弹窗（左右两栏；与「作业预览-学习通」的只读逐生预览不同——
 *  右上=AI 批语（只读，可"另存修订版"）；右下=人工批阅 + 模式（不批阅/覆盖/人工在前+附件AI/修订AI）。
 *  左=学生作答图（可上/下一位、旋转）。保存写回双套草稿（不覆盖 AI 原文）。 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { saveXxtGradeDraft, previewXxtGradeDraft, xxtReviewFileUrl, xxtGradeReportUrl } from '../lib/engineClient'
import { renderRich } from '../lib/richdoc'
import { renderMathIn, KATEX_DONE_ATTR } from '../lib/katexRender'

const props = defineProps<{
  engineAddr: string; token?: string
  classId: string; workId: string
  /** D119：草稿按作业纸归属（不同作业批次不互相覆盖） */
  taskId?: string; classDir?: string
  /** D130-T12：`altKeys` 用于同一学生的备用草稿键（引擎给的 key 与历史键可能不同） */
  students: { name: string; key: string; tag?: string; images?: string[]
              altKeys?: string[] }[]
  drafts: Record<string, any>
  startIndex?: number
}>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'saved'): void; (e: 'notify', m: string): void }>()

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
defineExpose({ showReportTab })
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

/** D175c：分数统一按**字符串**处理再解析。
 *  此前直接 `finalScore.value.trim()` —— 一旦教师手动改过分数（v-model 变成 number）
 *  就抛 `TypeError: finalScore.value.trim is not a function`，保存键"点了没反应"。 */
function rawScore(): string {
  return String(finalScore.value ?? '').trim()
}
/** 解析最终分数：空 → null（不改分）；非法 → NaN。 */
function parseScore(): number | null {
  const s = rawScore()
  if (!s) return null
  const n = Number(s)
  return Number.isFinite(n) ? n : NaN
}
function onScoreInput(v: string) {
  finalScore.value = v            // 始终保持字符串
  dirty.value = true
  previewMd.value = ''
}

/** 组装保存/预览用的请求体（两者**同一份**，保证"看到的就是会发出的"）。 */
function buildPayload() {
  const c = cur.value
  if (!c) return null
  const n = parseScore()
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
  } catch (e) {
    msg.value = `预览失败：${String((e as Error).message || e)}`
  } finally { previewBusy.value = false }
}

/** D175：**保存** = 批语 + 分数一起写（此前 mode=none 时分数被丢弃）。 */
async function save() {
  const c = cur.value
  if (!c) return
  const n = parseScore()
  if (n !== null && (!Number.isFinite(n) || n < 0 || n > 100)) {
    msg.value = '分数必须是 0~100 的数字'; return
  }
  saving.value = true
  try {
    const payload = buildPayload()
    if (!payload) { msg.value = '无法组装保存内容（缺少学生）'; return }
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
  } catch (e) {
    // 此前异常直接冒泡 → 按钮"点了没反应"，且仍显示"有未保存改动"
    msg.value = `保存失败：${String((e as Error).message || e)}`
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
</script>

<template>
  <div class="backdrop" @click.self="emit('close')">
    <div class="modal" style="max-width:min(1200px,96vw); width:96vw; max-height:92vh; overflow:auto">
      <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap">
        <h3 style="margin:0">逐生审核：{{ cur?.name || '—' }}
          <span class="hint" style="font-weight:400">（第 {{ idx + 1 }} / {{ students.length }} 位 · tag {{ cur?.tag || '—' }}）</span>
        </h3>
        <span style="flex:1"></span>
        <button class="btn" :disabled="idx <= 0" @click="prev">← 上一位</button>
        <button class="btn" :disabled="idx >= students.length - 1" @click="next">下一位 →</button>
        <button class="btn" @click="rotate = (rotate - 90 + 360) % 360">↺ 左旋</button>
        <button class="btn" @click="rotate = (rotate + 90) % 360">↻ 右旋</button>
        <button class="btn" @click="layout = layout === 'cols' ? 'rows' : 'cols'">
          {{ layout === 'cols' ? '⇵ 上下布局' : '⇋ 左右布局' }}
        </button>
        <button class="btn" @click="emit('close')">关闭</button>
      </div>

      <div style="display:flex; gap:14px; align-items:flex-start; flex-wrap:wrap; margin-top:10px"
           :style="{ flexDirection: layout === 'rows' ? 'column' : 'row' }">
        <!-- 左栏：学生作答 -->
        <div :style="{ flex: layout === 'rows' ? 'none' : '1', minWidth: '280px', width: layout === 'rows' ? '100%' : 'auto' }">
          <h4>学生作答</h4>
          <div style="border:1px solid var(--c-border); border-radius:8px; padding:6px; max-height:62vh; overflow:auto;
                      display:flex; flex-direction:column; gap:8px">
            <img v-for="f in answerImages" :key="f" :src="imgUrl(f)" :alt="f"
                 :style="{ width:'100%', height:'auto', objectFit:'contain', transform:`rotate(${rotate}deg)`, borderRadius:'6px' }" />
            <span v-if="!answerImages.length" class="hint">
              （该生没有已下载的作答图；请先到「作业预览-学习通」对该作业点「⬇ 下载作答/批语」。）
            </span>
          </div>
        </div>

        <!-- 右栏：AI 批语（上）/ 人工批阅（下） -->
        <div :style="{ flex: layout === 'rows' ? 'none' : '1.1', minWidth: '300px', width: layout === 'rows' ? '100%' : 'auto' }">
          <!-- D130-T10：页签 —— 批阅 / 报告（报告复用 reports/<学生>.html，iframe 预览） -->
          <div class="pane-tabs">
            <button class="btn small" :class="{ primary: pane === 'review' }"
                    @click="pane = 'review'">✏ 批阅</button>
            <button class="btn small" :class="{ primary: pane === 'report' }" @click="openReport()">
              📄 报告{{ hasReport ? '' : '（未生成）' }}
            </button>
          </div>

          <template v-if="pane === 'report'">
            <div v-if="!reportUrl" class="hint" style="margin-top:8px">
              （缺少班级目录或批阅目录键，无法定位报告。请先在 ② 区关联班级目录后再试。）
            </div>
            <iframe v-else :key="reportNonce" :src="reportUrl" class="report-frame"
                    title="批阅报告预览"></iframe>
            <p class="hint" style="margin-top:4px">
              这里预览的就是要发给学生/上传平台的报告（含转写原文、评分与扣分依据）。
              若显示"尚未生成报告"，先点下方「📄 一键生成批阅报告」。
            </p>
          </template>

          <template v-else>
          <!-- D126：AI 转写（便于对照原图，确认 AI 识别是否准确） -->
          <h4 style="display:flex; align-items:center; gap:6px">
            AI 转写
            <span class="hint" style="font-weight:400">
              （AI 从作答图识别出的文字；与左侧原图对照可发现识别偏差）
            </span>
            <button v-if="transcriptText" class="btn small" style="margin-left:auto"
                    @click="showTranscript = !showTranscript">
              {{ showTranscript ? '收起' : '展开' }}
            </button>
          </h4>
          <div v-if="transcriptText && showTranscript" ref="transcriptEl" class="rich-box"
               style="border:1px solid var(--c-border); border-radius:8px; padding:8px;
                      max-height:30vh; overflow:auto;
                      background:var(--c-bg-soft,#f8fafc); font-size:13px"
               v-html="transcriptHtml"></div>
          <p v-else-if="!transcriptText" class="hint" style="margin:2px 0 8px">
            （暂无转写内容。请按顺序排查：① 该生是否根本没参与本次转写（如「仅评阅」、
            或批阅发生在 D126 之前，那时不保存转写）——重跑「① 仅转录」即可；② 多数学生转录
            失败时，勾选「有学生转录失败时仍继续」再看；③ 若「仅转录」提示完成、文件夹里也有
            transcripts/*.json，但这里仍为空 → 属于**目录口径不一致**（草稿与转写不在同一
            grading 目录），请把该作业的 grading 目录名反馈给开发者。）
          </p>

          <!-- ===== D175：一份批语 + 一个分数 = 你要发给学生的东西 =====
               保存一定会同时写批语与分数；"另存修订版"与"人工分数"不再各走各的。 -->
          <h4 style="margin-top:12px; display:flex; align-items:center; gap:6px; flex-wrap:wrap">
            ✍ 最终批语
            <span class="hint" style="font-weight:400">{{ commentHint }}</span>
            <span style="flex:1"></span>
            <button class="btn small" v-if="!editingComment" @click="startEditComment">
              {{ (savedRevision || commentChanged) ? '✏ 继续修改' : '✏ 在 AI 批语基础上修改' }}
            </button>
            <button class="btn small" v-if="finalComment !== aiOriginal || savedRevision"
                    @click="useAiOriginal" title="丢弃你的修改，恢复 AI 原文">↩ 恢复 AI 原文</button>
          </h4>

          <!-- 只读：**当前最终批语**（含本地已应用的修改）；AI 原文另折叠对照 -->
          <div v-if="!editingComment" style="border:1px solid var(--c-border); border-radius:8px;
                      padding:8px; min-height:80px; max-height:34vh; overflow:auto;
                      background:var(--c-bg-soft,#f8fafc)">
            <div v-if="finalCommentHtml" ref="aiCommentEl" class="rich-box" v-html="finalCommentHtml"></div>
            <span v-else>（无批语：该生可能只有本地旧草稿分数，或尚未跑 AI 批阅）</span>
          </div>
          <details v-if="!editingComment && commentChanged" style="margin:4px 0 0">
            <summary class="hint" style="cursor:pointer">对照 AI 原文（{{ aiOriginal.length }} 字，只读）</summary>
            <div class="rich-box" style="border:1px dashed var(--c-border); border-radius:8px; padding:8px;
                        margin-top:4px; max-height:30vh; overflow:auto; white-space:pre-wrap">{{ aiOriginal }}</div>
          </details>

          <!-- 编辑态：这就是"要发出去的批语" -->
          <div v-if="editingComment">
            <textarea v-model="revDraft" rows="8" style="width:100%; font-family:inherit"
                      placeholder="在此修改批语（支持 LaTeX $...$）。保存后报告中你的改动会按行标红。"></textarea>
            <p style="margin:4px 0; display:flex; gap:8px; align-items:center; flex-wrap:wrap">
              <button class="btn small primary" @click="applyEditComment">✓ 应用到批语</button>
              <button class="btn small" @click="cancelEditComment">取消</button>
              <button class="btn small" :disabled="savingRev" @click="saveRevisionOnly"
                      title="只把修订版写进草稿，不动分数（高级用法）">
                {{ savingRev ? '保存中…' : '仅存修订版' }}</button>
              <span class="hint">「应用到批语」后还需点下面 <b>💾 保存</b> 才写入草稿</span>
            </p>
          </div>

          <!-- ===== 分数 ===== -->
          <h4 style="margin-top:12px">分数</h4>
          <p style="display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin:0 0 6px">
            <label class="field">最终分数
              <!-- D175c：**不要**用 v-model（Vue3 对 type=number 会自动转成 number，
                   而下面按字符串做 trim/校验 → 手动改分后保存抛 TypeError、静默无反应）。
                   这里显式保存原始字符串，解析统一交给 parseScore()。 -->
              <input :value="finalScore" type="number" min="0" max="100" style="width:88px"
                     @input="onScoreInput(($event.target as HTMLInputElement).value)" /></label>
            <span class="hint">{{ scoreHint }}</span>
          </p>

          <!-- ===== 与 AI 的关系（三选一） ===== -->
          <h4 style="margin-top:12px">批语与 AI 的关系</h4>
          <p style="margin:4px 0; display:flex; gap:6px; flex-wrap:wrap">
            <button class="btn small" :class="{ primary: commentMode === 'keep' }"
                    @click="setCommentMode('keep')"
                    title="保留 AI 原文，你的改动按行标红（默认）">✏ 修订 AI（标红改动）</button>
            <button class="btn small" :class="{ primary: commentMode === 'append' }"
                    @click="setCommentMode('append')"
                    title="AI 原文在前 + 你的补充批语在后">➕ 追加到 AI 之后</button>
            <button class="btn small" :class="{ primary: commentMode === 'replace' }"
                    @click="setCommentMode('replace')"
                    title="纯人工批语，报告里不出现 AI 原文">↩ 完全替代 AI</button>
          </p>
          <textarea v-if="commentMode !== 'keep'" v-model="comment" rows="5"
                    style="width:100%; font-family:inherit; margin-top:6px"
                    :placeholder="commentMode === 'append'
                      ? '教师补充批语（追加在 AI 原文之后，支持 LaTeX）'
                      : '纯人工批语（替代 AI 原文，支持 LaTeX）'"
                    @input="dirty = true; previewMd = ''"></textarea>
          <p v-if="commentMode !== 'keep'" class="hint" style="margin:2px 0 0">
            {{ commentMode === 'append'
              ? '报告 = AI 原文 + 【教师补充批语】+ 你的分数'
              : '报告 = 纯人工批语 + 你的分数（不出现 AI 原文）' }}
            　<button class="btn small" @click="startEditComment">✏ 在编辑框里写这份批语</button>
          </p>

          <!-- ===== 保存 / 预览 ===== -->
          <p style="margin:10px 0 0; display:flex; gap:8px; align-items:center; flex-wrap:wrap">
            <button class="btn primary" :disabled="saving" @click="save">
              {{ saving ? '保存中…' : '💾 保存（批语 + 分数一起）' }}</button>
            <button class="btn small" :disabled="previewBusy" @click="doPreview">
              {{ previewBusy ? '生成中…' : '👁 预览将发出的报告' }}</button>
            <span class="hint" v-if="dirty" style="color:#b45309">● 有未保存改动</span>
            <span class="hint" v-else-if="msg">{{ msg }}</span>
          </p>
          <p v-if="dirty && msg" class="hint" style="margin:2px 0; color:#b45309">{{ msg }}</p>

          <div v-if="showPreview" style="margin-top:8px; border:1px solid #0369a1; border-radius:8px;
                      padding:8px; max-height:38vh; overflow:auto; background:#fff">
            <p class="hint" style="margin:0 0 6px">
              这是<b>保存后要发出去的报告</b>（{{ previewKind }}）。确认无误再点「💾 保存」。
            </p>
            <pre style="white-space:pre-wrap; font-family:inherit; margin:0">{{ previewMd }}</pre>
          </div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pane-tabs { display: flex; gap: 6px; margin-bottom: 8px; }
.report-frame { width: 100%; height: 62vh; border: 1px solid var(--c-border); border-radius: 8px;
               background: #fff; }
</style>

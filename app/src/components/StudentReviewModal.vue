<script setup lang="ts">
/** D92-R4：逐生审核弹窗（左右两栏；与「作业预览-学习通」的只读逐生预览不同——
 *  右上=AI 批语（只读，可"另存修订版"）；右下=人工批阅 + 模式（不批阅/覆盖/人工在前+附件AI/修订AI）。
 *  左=学生作答图（可上/下一位、旋转）。保存写回双套草稿（不覆盖 AI 原文）。 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { saveXxtGradeDraft, xxtReviewFileUrl, xxtGradeReportUrl } from '../lib/engineClient'
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

          <h4 style="margin-top:10px">AI 批语 <span class="hint" style="font-weight:400">（只读基线{{ aiSet.score != null ? ` · 评分 ${aiSet.score}` : '' }}）</span></h4>
          <div style="border:1px solid var(--c-border); border-radius:8px; padding:8px; min-height:80px;
                      background:var(--c-bg-soft,#f8fafc)">
            <span v-if="revisionText">（已另存修订版，见下）</span>
            <div v-else-if="aiCommentHtml" ref="aiCommentEl" class="rich-box"
                 v-html="aiCommentHtml"></div>
            <span v-else>（无 AI 批语：该生可能只有本地旧草稿分数，或尚未跑 AI 批阅）</span>
          </div>
          <p style="margin:6px 0">
            <button class="btn small" @click="startRevise">{{ revisionText ? '编辑修订版' : '另存修订版…' }}</button>
            <span class="hint" style="margin-left:8px">
              修订 = 在 AI 批语基础上改；报告将按行**标红**改动，AI 原文不被覆盖。
            </span>
          </p>
          <!-- D170-T10：修订版存在哪、在哪能看到（教师反馈"保存后找不到"） -->
          <p v-if="revisionText" class="hint" style="margin:0 0 6px; color:#0369a1">
            修订版已保存在<b>引擎草稿库</b>（<code>grade-drafts</code>，不是本机文件）：
            它会在<b>导出报告</b>时按行标红体现，也可返回本行重新「编辑修订版」。
            想看全文：点上方「编辑修订版」即可展开当前修订内容。
            <br />状态：已修订（{{ revisionText.length }} 字）
            <template v-if="!revisionSavedInStore">· ⚠ 本页尚未保存，点下方「💾 保存到本地」才会写入引擎</template>
          </p>
          <textarea v-if="revising" v-model="revDraft" rows="5" style="width:100%; font-family:inherit"
                    placeholder="AI 批语的人工修订版（支持 LaTeX $...$）"></textarea>

          <h4 style="margin-top:10px">人工批阅（可选）</h4>
          <p style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin:0 0 6px">
            <label class="field">模式
              <select v-model="humanMode">
                <option value="none">仅 AI（默认）</option>
                <option value="replace">人工替代 AI（报告=纯人工）</option>
                <option value="append">追加到 AI 之后（报告=AI + 教师补充）</option>
                <option value="revise">修订 AI（报告=AI报告·人工修订·标红）</option>
              </select>
            </label>
            <label class="field">分数 <input v-model="score" type="number" min="0" max="100" style="width:80px" /></label>
          </p>
          <textarea v-model="comment" rows="4" style="width:100%; font-family:inherit"
                    placeholder="人工批语（支持 LaTeX；模式=none/revise 时可留空）"></textarea>
          <p style="margin:8px 0 0; display:flex; gap:8px; align-items:center; flex-wrap:wrap">
            <button class="btn small" :class="{ primary: humanMode === 'none' }"
                    @click="humanMode = 'none'" title="报告只用 AI 批语（默认）">↩ 仅 AI</button>
            <button class="btn small" :class="{ primary: humanMode === 'replace' }"
                    @click="humanMode = 'replace'"
                    title="人工批语替代 AI 批语 → 报告为纯人工批阅报告">✏ 人工替代 AI</button>
            <button class="btn small" :class="{ primary: humanMode === 'append' }"
                    @click="humanMode = 'append'"
                    title="AI 批语在前 + 人工批语在后">➕ 追加到 AI 之后</button>
          </p>
          <p style="margin:8px 0 0; display:flex; gap:8px; align-items:center">
            <button class="btn primary" @click="save">💾 保存到本地（不覆盖 AI 原文）</button>
            <span class="hint" v-if="msg">{{ msg }}</span>
          </p>
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

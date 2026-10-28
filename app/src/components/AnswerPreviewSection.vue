<script setup lang="ts">
/** AnswerPreviewSection.vue — D113：参考答案预览（独立功能区 · 竖版单列）
 *
 *  与「作业纸预览」是**两个功能区**（用户 Q1 拍板）：
 *  - 作业纸预览 = 给学生设计用（不含答案）；
 *  - 本区 = 给教师看答案/要点（原生带答案，无"显示答案"开关）。
 *
 *  版式（Q7/Q9）：只有竖版单列；一题排完 → 新题另起一页；超高题自然跨页但不与其它题交错。
 *  入口（Q11）：① 当前作业纸 ② 当前作业包内全部作业纸（按作业纸分节，D1/D2=A）。
 *  打印（Q8/D4）：独立按钮，与作业纸打印互不影响。
 */
import { computed, nextTick, ref, watch } from 'vue'
import { useKbStore } from '../stores/kb'
import { useTaskpadStore } from '../stores/taskpad'
import { usePackStore } from '../stores/packs'
import { expandPadItems, fetchSelfContainedKatex } from '../lib/sheetHtml'
import { parseTaskpad, type Taskpad } from '../lib/taskpad'
import type { KbKind } from '../lib/kb'
import { buildAnswerHtml, answerItemsOf, type AnswerSection, type AnswerItem,
  type AnswerHtmlOptions } from '../lib/answerHtml'
import SheetHtmlPreviewModal from './SheetHtmlPreviewModal.vue'
import { downloadData } from '../lib/fsAccess'

const emit = defineEmits<{ (e: 'notify', msg: string): void }>()

const kb = useKbStore()
const pad = useTaskpadStore()
const packStore = usePackStore()

const scope = ref<'current' | 'pack'>('current')
const includeContent = ref(true)
const includeNo = ref(true)
/** D113-R3：一题一页起步（默认 true；关掉则连排）。 */
const onePagePerQuestion = ref(true)
const status = ref('')

/** 单张作业纸 → 参考答案条目。 */
function itemsOf(p: Taskpad): AnswerItem[] {
  const htmlItems = expandPadItems(p, (kind) => kb.book(kind as KbKind), kb.effectiveSolution)
  return answerItemsOf(htmlItems)
}

/** 当前视图的 sections（当前作业纸 / 包内全部作业纸）。 */
const sections = computed<AnswerSection[]>(() => {
  void kb.solutionsRev
  if (scope.value === 'current') {
    return [{ items: itemsOf(pad.current) }]
  }
  // D1/D2=A：按作业纸分节（节标题含 id + 目标 tag），只取**当前作业包内**的作业纸
  if (!packStore.currentId) return []
  const allow = new Set(packStore.currentPadRefs.map((r) => r.padId))
  const out: AnswerSection[] = []
  for (const s of pad.saved) {
    if (!allow.has(s.id)) continue
    try {
      const p = parseTaskpad(JSON.parse(s.json))
      const tag = String(p.target_tag || '')
      out.push({ title: `作业纸：${s.id}${tag ? ` · tag=${tag}` : ''}`, items: itemsOf(p) })
    } catch { /* 跳过损坏记录 */ }
  }
  return out
})

const docTitle = computed(() =>
  scope.value === 'current'
    ? `参考答案 · ${pad.current.id}`
    : `参考答案 · 作业包 ${packStore.currentId || '（未选择）'}（全部作业纸）`)

const empty = computed(() => sections.value.every((s) => s.items.length === 0))

function html(opts: { katex?: 'relative' | 'raw'; katexRaw?: AnswerHtmlOptions['katexRaw'] } = {}): string {
  return buildAnswerHtml(sections.value, {
    includeContent: includeContent.value,
    includeNo: includeNo.value,
    onePagePerQuestion: onePagePerQuestion.value,
    docTitle: docTitle.value,
    ...opts,
  })
}

const liveHtml = computed(() => html())

/* ---------- 打印 / 下载（Q8/D4：独立按钮） ---------- */
const printFrame = ref<HTMLIFrameElement | null>(null)
function printAnswers(): void {
  const w = printFrame.value?.contentWindow
  if (!w) return
  try { w.focus(); w.print() } catch { emit('notify', '浏览器拒绝打印：可改用「下载参考答案 HTML」后打印') }
}

async function downloadAnswers(): Promise<void> {
  try {
    // 复用 sheetHtml 的自包含 KaTeX 拉取（内联 css + katex.min.js + auto-render，字体 dataURL）
    const assets = await fetchSelfContainedKatex()
    const out = html({ katex: 'raw', katexRaw: assets })
    downloadData(out, `answers-${new Date().toISOString().slice(0, 10)}.html`, 'text/html')
    emit('notify', `已下载参考答案 HTML（自包含 KaTeX，离线可开）：${sections.value.reduce((n, s) => n + s.items.length, 0)} 题`)
  } catch (e) {
    emit('notify', `下载失败：${String((e as Error).message || e)}`)
  }
}

/* ---------- 弹窗细看 ---------- */
const overlayOpen = ref(false)
const overlayHtml = ref('')
const overlayTitle = ref('')
async function openOverlay(): Promise<void> {
  await nextTick()
  overlayHtml.value = liveHtml.value
  overlayTitle.value = docTitle.value
  overlayOpen.value = true
}
function downloadOverlay(): void { void downloadAnswers() }

const frameKey = computed(() =>
  JSON.stringify([sections.value, includeContent.value, includeNo.value,
                  onePagePerQuestion.value, docTitle.value]))
watch(frameKey, () => { status.value = '' }, { immediate: true })
</script>

<template>
  <div class="card" id="answer-preview" style="width:100%; min-width:0">
    <h2>④ 参考答案预览 <small style="font-weight:400;color:var(--c-muted)">教师查看答案/要点 · 竖版单列 · 一题一页</small></h2>
    <p class="hint">
      本区与上方「作业纸预览」是<b>两个独立功能区</b>：作业纸预览给学生设计用（不含答案），
      本区给教师核对答案/要点用（原生带答案，无需勾选）。版式为<b>竖版单列</b>：
      一题答案排完后<b>新题另起一页</b>；单题超过一整页时自然跨页，但<b>绝不与其它题答案交错</b>。
    </p>
    <p style="display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin:6px 0">
      <label class="field" title="当前 = 只出正在编辑的这张作业纸；作业包 = 包内全部作业纸，按作业纸分节">
        范围：
        <select v-model="scope" style="min-width:150px">
          <option value="current">当前作业纸</option>
          <option value="pack">当前作业包（全部）</option>
        </select>
      </label>
      <label class="field"><input type="checkbox" v-model="includeContent" /> 显示题干</label>
      <label class="field"><input type="checkbox" v-model="includeNo" /> 显示题号</label>
      <label class="field" title="默认：一题答案排完后，新题另起一页（避免与前题答案混在一起）；关掉=连排省纸">
        <input type="checkbox" v-model="onePagePerQuestion" /> 一题一页
      </label>
      <button class="btn" @click="printAnswers">🖨 打印参考答案</button>
      <button class="btn" @click="downloadAnswers">⬇ 下载参考答案 HTML</button>
      <button class="btn" @click="openOverlay">🔍 弹窗细看</button>
    </p>
    <p class="hint" style="margin:2px 0 6px">
      预览 = 打印产物同源（同一模板/CSS）；公式用 PWA 同源 KaTeX 渲染，离线也正确显示。
      行内公式保持行内，行间公式独立成行并突出显示。
    </p>
    <iframe
      v-if="!empty"
      ref="printFrame"
      class="answer-frame"
      :srcdoc="liveHtml"
      title="参考答案预览"
      aria-label="参考答案预览：Tab 聚焦后可用方向键滚动"
      tabindex="0"
    ></iframe>
    <p class="hint" v-else>尚未选题（items 为空）：参考答案预览为空。到②段选题后回来看。</p>
    <p class="hint" v-if="status">{{ status }}</p>

    <SheetHtmlPreviewModal
      v-if="overlayOpen"
      :html="overlayHtml"
      :title="overlayTitle"
      @close="overlayOpen = false"
      @download="downloadOverlay"
    />
  </div>
</template>

<style scoped>
/* Q4：固定 560px，与作业纸预览一致；超出滚动 */
.answer-frame {
  width: 100%; height: 560px; border: 1px solid var(--c-border);
  border-radius: 8px; background: #e8ecf3;
}
</style>

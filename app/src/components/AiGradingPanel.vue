<script setup lang="ts">
/** D86 §6 / D88 §4：AI 辅助批阅面板（提炼自 XxetongView 临时面板）。
 *  六区：① LLM 设置（provider + 两段式）② 班级↔作业纸目录映射 ③ 任务（AI 批阅）
 *        ④ 逐生审核（本地草稿：改分/批语/保存/演练/上传）⑤ 一键生成批阅报告 ⑥ 一键上传全部
 *  说明：完整"逐生预览（作答图+批语两栏）"仍在「作业预览-学习通 → 批阅图片 → 逐生预览」，
 *  与本面板的"报告风格审核"并存（用户拍板的两种风格）。
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useTaskpadStore } from '../stores/taskpad'
import { useKbStore } from '../stores/kb'
import {
  extractJobError, fetchLlmConfig, fetchXxtClassMap, fetchXxtGradeDrafts, fetchXxtLoginJob,
  fetchXxtReviewIndex, fetchXxtReviewStudents, postLlmProvider, postXxtClassMap,
  startXxtGradeAi, startXxtGradeUpload,
  startKbAiSolve, fetchKbCatalog, renderReportsFromDrafts,
  fetchPromptTemplates, mutatePromptTemplate, testLlmStages, type PromptTemplate,
} from '../lib/engineClient'
import { normalizePromptId, suggestPromptId, PROMPT_ID_HINT } from '../lib/promptId'

const props = defineProps<{ engineAddr: string; token?: string }>()
const taskpadStore = useTaskpadStore()
const kbStore = useKbStore()
import { usePackStore } from '../stores/packs'
import { useRosterStore } from '../stores/roster'
import PlaygroundPanel from './PlaygroundPanel.vue'
import StudentReviewModal from './StudentReviewModal.vue'
import GradingRulesCard from './GradingRulesCard.vue'
import TeacherReportCard from './TeacherReportCard.vue'
import TrendCard from './TrendCard.vue'
const packStore = usePackStore()
const rosterStore = useRosterStore()

const msg = ref('')
/* D106：转录图片发送模式 + SVG 重绘（默认关） */
const imageMode = ref<'auto' | 'original'>('auto')
const svgRedraw = ref(false)
/** D125/D126：转录有学生失败时是否仍继续（默认关 = 中止，避免残缺数据进评阅）。
 *  引擎与 PWA 此前都已支持（`--allow-partial` / `allowPartial`），但界面没有入口，
 *  `allowPartial` 参数形同虚设 —— 用户遇到个别学生限流/读图失败时无路可走。 */
const allowPartial = ref(false)
const busy = ref(false)
const progress = ref('')
let pollTimer: number | undefined

/* ⑦ 题库 AI 作答（D89-N5/D92-R3）：对题库题目生成参考答案，不覆盖、可多版本 */
const kbCatalog = ref<{ kinds?: any[] }>({ kinds: [] })
const kbKind = ref(''); const kbChap = ref(''); const kbIdsSel = ref<string[]>([]); const kbModel = ref('')
const kbCustomModel = ref(false)
const kbKinds = computed<string[]>(() => (kbCatalog.value.kinds || []).map((k: any) => k.kind))
const kbChapters = computed<string[]>(() => {
  const k = (kbCatalog.value.kinds || []).find((x: any) => x.kind === kbKind.value)
  return (k?.chapters || []).map((c: any) => c.chap)
})
const kbIdList = computed<{ id: string; content?: string }[]>(() => {
  const k = (kbCatalog.value.kinds || []).find((x: any) => x.kind === kbKind.value)
  const c = (k?.chapters || []).find((x: any) => x.chap === kbChap.value)
  return c?.ids || []
})
/** 所选题号的内容预览（单行拼接，可横向滚动）。 */
const kbPreview = computed(() => {
  const want = new Set(kbIdsSel.value)
  const picked = kbIdList.value.filter((i) => !want.size || want.has(i.id))
  return picked.map((i) => `${i.id}: ${i.content ?? ''}`).join('   ｜   ')
})
async function loadKbCatalog() {
  const r = await fetchKbCatalog(props.engineAddr, props.token)
  kbCatalog.value = { kinds: r.kinds || [] }
  if (!kbKind.value && kbKinds.value.length) kbKind.value = kbKinds.value.includes('problems') ? 'problems' : kbKinds.value[0]
}
// 切换题库/章节时清空已选题号
watch(kbKind, () => { kbChap.value = ''; kbIdsSel.value = [] })
watch(kbChap, () => { kbIdsSel.value = [] })
// D100-T3/T8：AI 作答默认置顶（生效答案）；取消勾选 = 只追加版本不抢原答案
const kbPin = ref(true); const kbApply = ref(false)
/* D133：同时生成「评阅要点 + 知识点」。
 * 勾选后**默认不置顶**（要点未经教师确认不该抢生效答案，D130 验收 5），
 * 教师可再显式勾「同时置顶」；不勾则只生成解答，行为与旧版一致。 */
const kbWithRubric = ref(false); const kbPinRubric = ref(false)
// D104：教师额外作答要求（可选）—— 例如「请画出示意图」「输出为 HTML 文档」
const kbRequirement = ref('')
/* D108：提示词模板库（保存/默认/删除；存储于 <ws>/prompts/ai-solve/，CLI 可复用） */
const promptTemplates = ref<PromptTemplate[]>([])
const promptSel = ref('')
const promptBusy = ref(false)
const promptMsg = ref('')
const promptIsBuiltin = computed(() =>
  !!promptTemplates.value.find((t) => t.id === promptSel.value)?.builtin)
const promptIsDefault = computed(() =>
  !!promptTemplates.value.find((t) => t.id === promptSel.value)?.default)

async function loadPromptTemplates(autoPickDefault = true) {
  const r = await fetchPromptTemplates(props.engineAddr, props.token)
  promptTemplates.value = r.items || []
  if (!promptTemplates.value.length) {
    // 引擎离线时列表为空：明确提示，否则用户以为"没有模板可选"
    promptMsg.value = '模板库读取失败（引擎离线或未启动？）'
    return
  }
  if (autoPickDefault) {
    const def = r.default || promptTemplates.value.find((t) => t.default)?.id || ''
    if (def) {
      promptSel.value = def
      const t = promptTemplates.value.find((x) => x.id === def)
      if (t) kbRequirement.value = t.text
    }
  }
}
/** 切换模板 → 把模板文本载入文本框（可继续临时修改）。 */
function pickPromptTemplate() {
  const t = promptTemplates.value.find((x) => x.id === promptSel.value)
  if (t) {
    kbRequirement.value = t.text
    promptMsg.value = `已载入「${t.name}」${t.builtin ? '（内置）' : ''}`
  }
}
/* D108-FIX：模板 id 归一化/建议值逻辑见 lib/promptId.ts（与引擎 _ID_RE 一致，可单测）。 */
/** 弹窗询问新模板 id：预填建议值，归一化后校验；返回 null 表示取消。 */
function askPromptId(name: string): string | null {
  const raw = window.prompt(
    `新模板 id（${PROMPT_ID_HINT}）\n同时用作文件名，保存后不可改。`,
    suggestPromptId(name, promptTemplates.value.map((t) => t.id)),
  )
  if (raw === null) return null
  const id = normalizePromptId(raw)
  if (!id) {
    promptMsg.value = `模板 id 不合法：${raw.trim() || '（空）'}（${PROMPT_ID_HINT}）`
    return null
  }
  return id
}

/** 保存：覆盖当前模板（内置也可改内容）；无选中则新建。 */
async function savePromptTemplate() {
  const text = kbRequirement.value.trim()
  if (!text) { promptMsg.value = '内容为空，未保存'; return }
  const cur = promptTemplates.value.find((x) => x.id === promptSel.value)
  const isNew = !cur
  if (isNew) {
    const name = window.prompt('模板名称', '我的作答要求')
    if (name === null) return
    const id = askPromptId(name)
    if (!id) return
    await doSavePrompt(id, name.trim() || id, text, true)
    return
  }
  const id = cur!.id
  const name = cur!.name
  await doSavePrompt(id, name, text, false)
}

/** 统一的保存动作：写库 → 刷新列表 → 选中该模板。 */
async function doSavePrompt(id: string, name: string, text: string, isNew: boolean) {
  promptBusy.value = true
  try {
    const r = await mutatePromptTemplate(props.engineAddr, props.token, {
      action: 'save', id, name, text,
    })
    if (!r.ok) { promptMsg.value = r.error || '保存失败（引擎离线？）'; return }
    promptTemplates.value = r.items || []
    promptSel.value = id
    promptMsg.value = isNew ? `已新建模板「${name}」` : `已保存「${name}」`
  } catch (e) {
    promptMsg.value = `保存失败：${String((e as Error).message || e)}`
  } finally {
    promptBusy.value = false
  }
}
/** 另存为新模板（内置模板编辑后想保留原版时用）。 */
async function savePromptAsNew() {
  const text = kbRequirement.value.trim()
  if (!text) { promptMsg.value = '内容为空，未保存'; return }
  const curName = promptTemplates.value.find((x) => x.id === promptSel.value)?.name || ''
  const name = window.prompt('新模板名称', curName ? `${curName}（副本）` : '')
  if (name === null) return
  const id = askPromptId(name)
  if (!id) return
  // 另存为不应静默覆盖已有模板（save 是 upsert 语义）
  if (promptTemplates.value.some((t) => t.id === id)) {
    promptMsg.value = `模板 id「${id}」已存在，请换一个（另存为不会覆盖已有模板）`
    return
  }
  promptBusy.value = true
  try {
    const r = await mutatePromptTemplate(props.engineAddr, props.token,
      { action: 'save', id, name: name.trim() || id, text })
    if (!r.ok) { promptMsg.value = r.error || '保存失败'; return }
    promptTemplates.value = r.items || []
    promptSel.value = id
    promptMsg.value = `已另存为新模板「${name.trim() || id}」`
  } catch (e) {
    promptMsg.value = `另存失败：${String((e as Error).message || e)}`
  } finally {
    promptBusy.value = false
  }
}
async function deletePromptTemplate() {
  if (!promptSel.value) return
  if (promptIsBuiltin.value) { promptMsg.value = '内置模板不可删除（可「另存为新模板」后编辑）'; return }
  if (!window.confirm(`删除模板「${promptSel.value}」？`)) return
  promptBusy.value = true
  const r = await mutatePromptTemplate(props.engineAddr, props.token,
    { action: 'delete', id: promptSel.value })
  promptBusy.value = false
  if (!r.ok) { promptMsg.value = r.error || '删除失败'; return }
  promptTemplates.value = r.items || []
  promptSel.value = r.default || ''
  const t = promptTemplates.value.find((x) => x.id === promptSel.value)
  kbRequirement.value = t ? t.text : ''
  promptMsg.value = '已删除'
}
async function setPromptDefault() {
  if (!promptSel.value) return
  promptBusy.value = true
  const r = await mutatePromptTemplate(props.engineAddr, props.token,
    { action: 'set_default', id: promptSel.value })
  promptBusy.value = false
  if (!r.ok) { promptMsg.value = r.error || '设置默认失败'; return }
  promptTemplates.value = r.items || []
  promptMsg.value = `已把「${promptSel.value}」设为默认模板`
}
const kbSolveMsg = ref('')
const kbSolving = ref(false)
async function solveByKb() {
  const ids = [...kbIdsSel.value]
  // D110：空选择不再被静默当成"整章/整库"。范围越界必须先显式确认，
  // 否则用户以为只答一两题，实际把整库参考答案都刷新了（且是置顶生效答案）。
  if (!ids.length) {
    if (!kbChap.value) {
      if (!window.confirm(
        `未选择章节，也未勾选题号 → 将对 **整个「${kbKind.value}」题库** 作答`
        + (kbApply.value ? '（并写回/置顶生效答案）' : '（dry-run 预览）') + '。\n'
        + '题量可能很大且耗时长。确定继续？',
      )) return
    } else {
      const n = kbIdList.value.length
      if (!window.confirm(
        `未勾选题号 → 将对整章「${kbChap.value}」（${n} 题）作答`
        + (kbApply.value ? '（并写回/置顶生效答案）' : '（dry-run 预览）') + '。\n确定继续？',
      )) return
    }
  }
  kbSolving.value = true; kbSolveMsg.value = '正在启动题库 AI 作答……'
  try {
    const jobId = await startKbAiSolve(props.engineAddr, props.token, {
      kb: kbKind.value, chap: kbChap.value, ids, model: kbModel.value,
      pin: kbPin.value, apply: kbApply.value,
      withRubric: kbWithRubric.value,
      pinRubric: kbWithRubric.value && kbPinRubric.value,
      // 真正的"整库"仅在显式确认后下发
      all: !ids.length && !kbChap.value,
      requirement: kbRequirement.value.trim(),
      requirementTemplate: promptSel.value,   // D108：模板优先于单次输入
    })
    const tick = async () => {
      try {
        const job = await fetchXxtLoginJob(props.engineAddr, props.token, jobId)
        const lines = job.lines || []
        kbSolveMsg.value = (lines.slice(-1)[0] || '进行中…').slice(-220)
        if (job.status === 'running') { window.setTimeout(tick, 2000); return }
        // D139：先看**失败条数**——此前无论成败都显示"作答并写回完成"，
        // 失败原因又被 `slice(-2)` 截掉，教师只能看到 "failed": 1，无从排查。
        const tail = lines.slice(-6).join('\n')
        const failedN = /"failed"\s*:\s*(\d+)/.exec(tail)?.[1]
        const errs = [...tail.matchAll(/"error"\s*:\s*"([^"]{1,300})"/g)]
          .map((m) => m[1]).filter(Boolean)
        if (kbApply.value) {
          // D100-T8：作答写回版本库 → 刷新生效答案索引（题库表格/作业纸预览立即跟随）
          await kbStore.bumpSolutions()
          const pinDesc = kbWithRubric.value
            ? (kbPinRubric.value ? '已置顶（含要点）' : '未置顶（要点待你确认后再置顶）')
            : (kbPin.value ? '已置顶为生效答案' : '未置顶，仅追加版本')
          if (failedN && failedN !== '0') {
            kbSolveMsg.value = `❌ 有 ${failedN} 题作答失败（未写回）`
              + (errs.length ? `：${[...new Set(errs)].slice(0, 3).join('；')}` : '')
              + '　—— 已成功的题已写回；失败题可重试或换模型'
            return
          }
          kbSolveMsg.value = `✅ 作答并写回完成（${pinDesc}）：`
            + (lines.slice(-2).join(' ') || '')
          return
        }
        kbSolveMsg.value = 'dry-run 预览完成：' + (lines.slice(-2).join(' ') || '')
      } catch (e) { kbSolveMsg.value = extractJobError(String(e)) || String(e) }
    }
    tick()
  } catch (e) {
    kbSolveMsg.value = String((e as Error).message || e)
  } finally {
    kbSolving.value = false
  }
}

/* ① LLM 设置 */
const llmConfig = ref<{ providers?: any[]; stages?: Record<string, any>; default_base_url?: string }>({})

/* D137：provider 高级请求头（只有 provider 明确要求时才填，如 opencode-go 的
   x-opencode-session）。保存前必须二次确认并列出实际内容。 */
const pHdrText = ref('')          // 其他自定义头（多行 name=value）
const pUserAgent = ref('')
const showAdv = ref(false)
/* D145：会话头改为**勾选式**（引擎本就自动生成 session id，
   教师不需要、也不应该手写 `{session}` 占位符）。 */
const pSessionHdr = ref(false)
const pSessionHdrName = ref('x-opencode-session')
const DEFAULT_UA = 'assignment-assistant/<版本>'   // 仅用于展示默认值文案
const pendingProvider = ref<{ name: string; base_url: string; headers: Record<string, string>
                              user_agent: string } | null>(null)

/** 解析 `name=value` 多行文本 → 对象（不合法直接报错，不静默丢弃）。 */
function parseHeaders(text: string): Record<string, string> | { error: string } {
  const out: Record<string, string> = {}
  for (const raw of String(text || '').split('\n')) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const i = line.indexOf('=')
    if (i <= 0) return { error: `请求头格式应为 name=value，收到：${line}` }
    out[line.slice(0, i).trim()] = line.slice(i + 1).trim()
  }
  return out
}
const pName = ref(''); const pBase = ref(''); const pKey = ref(''); const pBatch = ref(false)
const stProvider = ref<Record<string, string>>({ transcription: '', evaluation: '' })
const stModel = ref<Record<string, string>>({ transcription: '', evaluation: '' })
const stBatch = ref(false)
const stCustom = ref<Record<string, boolean>>({ transcription: false, evaluation: false })
/** 该段所选 provider 的候选模型（与 Playground 共享同一份 providers[].models[]）。 */
function modelsForStage(s: string): string[] {
  const p = (llmConfig.value.providers || []).find((x: any) => x.name === stProvider.value[s])
  return (p?.models || []) as string[]
}

/* ② 班级映射 */
const classMap = ref<Record<string, string>>({})
const classDir = ref<Record<string, string>>({})

/* ③ 任务 */
const works = ref<Array<{ key: string; courseId: string; classId: string; cpi: string; workId: string; label: string }>>([])
const workKey = ref(''); const padId = ref(''); const packId = ref(''); const mode = ref<'optimized' | 'brute'>('optimized')
const tagsSel = ref<string[]>([]); const limit = ref(0)
const reviewOpen = ref(false); const reviewIndex = ref(0)
function openReview(i: number) { reviewIndex.value = i; reviewOpen.value = true }
/* D130-T10：生成报告后自动切到「📄 报告」页（验收 8）。
 *  点「一键生成批阅报告」时若逐生审核**已打开**，直接让弹窗切页；
 *  未打开则记住意图，等他打开**第一位**学生时再切（不擅自弹窗打断教师）。 */
const reviewModal = ref<{ showReportTab?: () => void } | null>(null)
/** D130-FIX2：本次实际读取草稿用的批阅目录（刷新后由引擎反查得到） */
const resolvedScope = ref('')
const autoReportPending = ref(false)
/** D126-B：自增即让教师总结报告重新汇总（生成/重生成报告后调用）。 */
const reportReloadKey = ref(0)
function onReviewOpen(i: number) {
  openReview(i)
  if (autoReportPending.value) {
    autoReportPending.value = false
    void nextTick(() => reviewModal.value?.showReportTab?.())
  }
}
/** D116：tags 下拉的可选项 = 本地 roster 里学生已打的 tag ∪ 当前作业包内各作业纸的 target_tag。
 *
 *  旧实现从 `students`（学习通批阅列表）里找 `tag`，但学习通**不提供**分层 tag
 *  （`xxt/preview.py`、`xxt/review.py` 里根本没有 tag 的概念）→ 下拉恒为空。
 *  分层是本机维护的信息：学生在「班级与标签」打 tag，作业纸用 `target_tag` 绑定分层。
 */
const rosterTags = computed<string[]>(() => {
  const dir = curWorkDir.value
  const out: string[] = []
  const push = (t: string) => { const v = String(t || '').trim(); if (v && !out.includes(v)) out.push(v) }
  if (!dir) {
    // 未建立 classId→classDir 映射时，退回"所有班级"的 tag（只用于展示可选值）
    for (const cid of rosterStore.classOrder || []) {
      for (const stu of rosterStore.classes[cid]?.students || []) push(stu.tag)
    }
    return out
  }
  // classDir 形如 "classes/classA"；roster 班级的 id 是内部 id、name 是显示名。
  // 依次尝试：整体相等 → 目录最后一段与 name/id 相等 → 名称互相包含。
  const tail = dir.split('/').filter(Boolean).pop() || dir
  const list = rosterStore.classList || []
  const cls = list.find((c) => c.id === dir || c.name === dir)
    || list.find((c) => c.id === tail || c.name === tail)
    || list.find((c) => dir.includes(c.name) || c.name.includes(tail))
  for (const stu of (cls ? rosterStore.classes[cls.id]?.students : []) || []) push(stu.tag)
  return out
})

/** 当前作业包（或单张作业纸）绑定的 target_tag。 */
const padTags = computed<string[]>(() => {
  const out: string[] = []
  const push = (t: string) => { const v = String(t || '').trim(); if (v && !out.includes(v)) out.push(v) }
  const list = packId.value ? packPads.value : pads.value.filter((p) => p.id === padId.value)
  for (const p of list) push((p as { tag?: string }).tag || '')
  return out
})

const tagOptions = computed<string[]>(() => {
  const out: string[] = []
  for (const t of rosterTags.value) if (!out.includes(t)) out.push(t)
  for (const t of padTags.value) if (!out.includes(t)) out.push(t)
  return out
})

/** D116-C：tags 为空时的可操作提示（而不是静默空着）。 */
const tagHint = computed<string>(() => {
  if (tagOptions.value.length) return ''
  if (!rosterStudentsTagged.value) {
    return '未找到任何分层 tag：请先到「班级与标签」给学生打 tag'
      + (curWorkDir.value ? `（当前班级目录：${curWorkDir.value}）` : '（或先在设置里关联学习通班级 → 本地班级目录）')
      + '；不选 tag = 批阅全部学生，但未打 tag 的学生不会关联到题目。'
  }
  return ''
})

/** roster 里当前班级是否至少有一个学生打了 tag。 */
const rosterStudentsTagged = computed<boolean>(() => rosterTags.value.length > 0)

/** 学习通作业 → 本地班级目录（classMap / 手动关联）。 */
const curWorkDir = computed<string>(() => {
  const w = curWork.value
  if (!w) return ''
  return classMap.value[`${w.courseId}:${w.classId}`] || classDir.value[`${w.courseId}:${w.classId}`] || ''
})

/* ④ 逐生审核 */

/* D148：**逐生补批** —— 只对一名学生跑 转写 / 批阅 / 完整。
 *  背景：`--limit N` 只批前 N 名（现在=前 N 名**有作答**的），
 *  漏掉的学生此前只能整批重跑（已批过的要重转写/重评阅，浪费额度）。
 *  这里传 `students:[姓名]`，引擎只处理这一人。 */
const rowBusy = ref('')
/* D154：行内状态（此前进度写在页面顶部 msg，滚在下面的教师根本看不到） */
const rowMsg = ref<Record<string, string>>({})
async function runOne(s: any, mode: 'transcribe' | 'evaluate' | 'full') {
  const w = curWork.value
  if (!w) {
    // D154：写在**行内**，而不是页面顶部的 msg（教师看不到）
    rowMsg.value = { ...rowMsg.value, [s.name]: '⚠ 请先在 ③ 区选择作业（含作业包/作业纸）' }
    return
  }
  const steps = mode === 'full' ? ['transcribe', 'evaluate']
    : mode === 'transcribe' ? ['transcribe'] : ['evaluate']
  const label = mode === 'full' ? '完整批阅' : mode === 'transcribe' ? '转写' : '批阅'
  rowBusy.value = s.name
  rowMsg.value = { ...rowMsg.value, [s.name]: `⏳ ${label}中…` }
  try {
    // 与「③ 任务」区**同一套装配逻辑**（避免两处口径漂移）
    const packPadList = packPads.value.map((p2) => {
      try { return JSON.parse(p2.json) } catch { return null }
    }).filter(Boolean)
    let taskpad: any = null
    let padsPayload: any[] | undefined
    if (packId.value && packPadList.length) {
      padsPayload = packPadList
      taskpad = packPadList[0]
    } else {
      const raw = pads.value.find((p2) => p2.id === padId.value)?.json || ''
      try { taskpad = raw ? JSON.parse(raw) : null } catch { taskpad = null }
    }
    if (!taskpad) { msg.value = '请先选择作业包（或单张作业纸）'; return }
    const jobId = await startXxtGradeAi(props.engineAddr, props.token, {
      courseId: w.courseId, classId: w.classId, cpi: w.cpi, workId: w.workId,
      ...(packId.value ? { packId: packId.value } : {}),
      taskpad,
      ...(padsPayload && padsPayload.length > 1 ? { pads: padsPayload } : {}),
      mode: 'optimized',
      // D156：**不再传 tags**——`students` 已精确到人；若同时传 tags，
      // plan 装配会把该 tag 下所有学生都装进来（曾导致"批张紫涵却报张松"）。
      students: [s.name],
      // D157：逐生补批**强制重跑**（否则会因已有转写/评阅而跳过，表现为"结果没变"）
      force: true,
      steps,
      imageMode: imageMode.value, svgRedraw: svgRedraw.value,
      allowPartial: true,
    })
    await pollJob(jobId, `「${s.name}」${label}`, s.name)
    await loadStudents()
  } catch (e) {
    rowMsg.value = { ...rowMsg.value,
      [s.name]: `❌ ${label}失败：${String((e as Error).message || e)}` }
  } finally {
    rowBusy.value = ''
  }
}

/** 轮询 job 直到结束（逐生补批共用；D154：结果写**行内**）。 */
async function pollJob(jobId: string, label: string, rowName = '') {
  for (let i = 0; i < 600; i++) {
    await new Promise((r) => window.setTimeout(r, 2000))
    const job = await fetchXxtLoginJob(props.engineAddr, props.token, jobId)
    const line = (job.lines || []).slice(-1)[0] || ''
    const text = `${label}：${line.slice(-160)}`
    if (rowName) rowMsg.value = { ...rowMsg.value, [rowName]: text }
    else msg.value = text
    if (job.status !== 'running') {
      const done = job.status === 'done'
      const final = done ? `✅ ${label}完成`
        : `❌ ${label}失败：${(job.lines || []).slice(-2).join(' ')}`
      if (rowName) rowMsg.value = { ...rowMsg.value, [rowName]: final }
      else msg.value = final
      return
    }
  }
  const to = `⚠️ ${label}超时（仍在后台执行）`
  if (rowName) rowMsg.value = { ...rowMsg.value, [rowName]: to }
  else msg.value = to
}

const students = ref<Array<{ name: string; key: string; tag?: string; images?: string[] }>>([])
/** D117：学生清单加载中（供逐生审核空态提示） */
const studentsLoading = ref(false)
const drafts = ref<Record<string, any>>({})

// D89：优先按"作业包"选择（一次分层作业的全部作业纸）；包内每张按 tag 自动匹配学生
const packPads = computed(() => {
  const cur = packStore.packs.find((p) => p.id === packId.value)
  const ids = new Set((cur?.pads ?? []).map((r: any) => r.padId))
  return (taskpadStore.saved || [])
    .filter((x: any) => ids.has(String(x.id)))
    .map((x: any) => {
      let tp: any = null
      try { tp = JSON.parse(x.json) } catch { tp = null }
      return { id: String(x.id), tag: String(tp?.target_tag || ''), json: x.json || '' }
    })
})
const pads = computed(() => (taskpadStore.saved || []).map((x: any) => ({
  id: String(x.id || ''), tag: String(x.target_tag || ''), json: x.json || '',
})))
const curWork = computed(() => works.value.find(w => w.key === workKey.value))
const ungraded = computed(() => students.value.filter(s => !drafts.value[s.key]).map(s => s.name))

async function loadConfig() {
  try {
    const cfg = await fetchLlmConfig(props.engineAddr, props.token)
    llmConfig.value = cfg as any
    const st = (cfg.stages || {}) as Record<string, any>
    for (const s of ['transcription', 'evaluation']) {
      stProvider.value = { ...stProvider.value, [s]: String((st[s] || {}).provider || '') }
      stModel.value = { ...stModel.value, [s]: String((st[s] || {}).model || '') }
    }
    stBatch.value = !!((st.evaluation || {}).batch)
    const cm = await fetchXxtClassMap(props.engineAddr, props.token)
    classMap.value = cm.map || {}
  } catch (e) { msg.value = `读取配置失败：${String(e)}` }
}
async function loadWorks() {
  try {
    const r = await fetchXxtReviewIndex(props.engineAddr, props.token)
    works.value = (r.works || []).map((it: any) => ({
      key: `${it.classId}:${it.workId}`, courseId: String(it.courseId || ''),
      classId: String(it.classId), cpi: String(it.cpi || '0'), workId: String(it.workId),
      label: `${it.className || it.classId} · ${it.workName || it.workId}`,
    }))
    if (!workKey.value && works.value.length) workKey.value = works.value[0].key
  } catch { /* 引擎离线 */ }
}
async function loadStudents() {
  const w = curWork.value
  if (!w) { students.value = []; drafts.value = {}; return }
  studentsLoading.value = true
  try {
    // D130-T12：作业包（packId）优先；兼容回落作业纸 id（历史上目录键漂移过）
    const scope = { taskId: packId.value || padId.value, classDir: curWorkDir.value,
                    altTaskId: packId.value ? padId.value : '' }
    const [st, dr0] = await Promise.all([
      // 把 scope 一并传给**学生清单**：引擎据此解析 `students[].key`（表与弹窗同源）
      fetchXxtReviewStudents(props.engineAddr, props.token, w.classId, w.workId,
                             undefined, scope),
      fetchXxtGradeDrafts(props.engineAddr, props.token, w.classId, w.workId, scope),
    ])
    let dr = dr0
    // D130-FIX2：刷新后 packId/padId 为空 → 上面读不到草稿。
    // 引擎会在学生清单里带回 `draftScopes`（从磁盘反查的批阅目录），用它再读一次，
    // 这样**不需要教师先手选作业包**也能看到 AI 状态。
    const scopes = (st as any)?.draftScopes as string[] | undefined
    if (!Object.keys((dr0?.drafts || {})).length && scopes?.length) {
      const t = scopes[0]!
      dr = await fetchXxtGradeDrafts(props.engineAddr, props.token, w.classId, w.workId,
                                     { ...scope, taskId: t,
                                       altTaskId: scopes.slice(1).join(',') })
      resolvedScope.value = t
    } else if (scopes?.length && !(packId.value || padId.value)) {
      resolvedScope.value = (dr0 as any)?.resolvedTaskId || scopes[0] || ''
    }
    drafts.value = (dr.drafts || {}) as Record<string, any>
    students.value = (st.students || []).map((s: any) => ({
      // D130-T12：**优先用引擎给的 key**（它知道草稿实际写在哪个键下）；
      // 旧引擎/离线回落 `workAnswerId || name`，与历史口径一致。
      name: String(s.name || ''),
      key: String(s.key || s.workAnswerId || s.name || ''),
      tag: String(s.tag || ''),
      /** 用于「同一学生两种键」兜底取值（见 draftOf） */
      altKeys: [String(s.workAnswerId || ''), String(s.name || '')].filter(Boolean),
      // D126：带上作答原件文件名（逐生审核要显示原图）
      images: Array.isArray(s.images) ? s.images.map(String) : [],
    }))
    // D116：tag 选项来自本地 roster + 作业纸 target_tag，可能晚于本函数就绪；
    // 由下面的 watch(tagOptions) 负责"首次就绪时默认全选"。
  } catch (e) { msg.value = `读取学生/草稿失败：${String(e)}` }
  finally { studentsLoading.value = false }
}
function classDirFor(w: { courseId: string; classId: string }): string {
  return classMap.value[`${w.courseId}:${w.classId}`] || classDir.value[`${w.courseId}:${w.classId}`] || ''
}
/** D123：本机真实存在的班级目录（`classes/<班级>`），供下拉选择。
 *  此前是自由输入框，教师很容易漏掉 `classes/` 前缀（实测存成 `化工25`），
 *  导致解析时找不到目录、批阅报"目录已不存在"。 */
const classDirOptions = computed<string[]>(() => {
  const out: string[] = []
  for (const cid of rosterStore.classOrder || []) {
    const c = rosterStore.classes[cid]
    if (!c) continue
    // D124：只用**班级名**（与写盘 saveToDir 同口径）；名字为空时**不列**，
    // 避免退化成 id 造出与写盘不一致的目录（那正是两套目录的成因）。
    const name = String(c.name || '').trim()
    if (!name) continue
    const dir = `classes/${name}`
    if (!out.includes(dir)) out.push(dir)
  }
  return out.sort()
})

function suggestDir() {
  const w = curWork.value; if (!w) return
  // 优先用按名称匹配的候选；匹配不到就选第一个真实班级，避免留空/手输
  const guess = classDirFor(w) || classDirOptions.value[0] || ''
  classDir.value = { ...classDir.value, [`${w.courseId}:${w.classId}`]: guess }
}
async function saveDir() {
  const w = curWork.value; if (!w) return
  const k = `${w.courseId}:${w.classId}`
  // D123：自动补 `classes/` 前缀（与引擎 normalize_class_dir 同口径）
  let v = String(classDir.value[k] || '').trim().replace(/^\/+|\/+$/g, '')
  if (v && !v.startsWith('classes/')) v = `classes/${v}`
  classDir.value = { ...classDir.value, [k]: v }
  const rep = await postXxtClassMap(props.engineAddr, props.token,
    { courseId: w.courseId, classId: w.classId, classDir: v })
  if (rep?.ok) {
    msg.value = `已关联 ${w.classId} → ${(rep as { map?: Record<string, string> }).map?.[k] || v}`
  } else {
    const cands = (rep as { candidates?: string[] })?.candidates || []
    msg.value = `保存失败：${rep?.error || ''}`
      + (cands.length ? `（可选：${cands.join('、')}）` : '')
  }
  await loadConfig()
}
/** 把「勾选式会话头」与「其他自定义头」合并成最终 headers。 */
function collectHeaders(): Record<string, string> | { error: string } {
  const parsed = parseHeaders(pHdrText.value)
  if ('error' in parsed) return parsed
  const out: Record<string, string> = { ...parsed }
  if (pSessionHdr.value) {
    const name = (pSessionHdrName.value || '').trim() || 'x-opencode-session'
    if (!/^x-[\w-]+$/i.test(name)) {
      return { error: `会话头的头名必须是 x-开头的合法头名，收到：${name}` }
    }
    // 占位符由前端代填（引擎运行时会替换成自动生成的会话 id）
    out[name] = '{session}'
  }
  return out
}

async function saveProvider() {
  if (!pName.value.trim()) { msg.value = '请填 provider 名称'; return }
  const merged = collectHeaders()
  if ('error' in merged) { msg.value = merged.error; return }
  const hasHdr = Object.keys(merged).length > 0 || pUserAgent.value.trim() !== ''
  if (hasHdr) {
    // D137：请求头会随**每次调用**发到该 provider → 保存前让教师看清实际内容
    pendingProvider.value = { name: pName.value.trim(), base_url: pBase.value.trim(),
                              headers: merged, user_agent: pUserAgent.value.trim() }
    return
  }
  await doSaveProvider(merged, '')
}

async function doSaveProvider(headers: Record<string, string>, ua: string) {
  const savedName = pName.value.trim()
  const rep = await postLlmProvider(props.engineAddr, props.token, {
    action: 'set', name: savedName, base_url: pBase.value.trim(),
    api_key: pKey.value ? pKey.value : undefined, batch_support: pBatch.value,
    headers, user_agent: ua,
  })
  if (rep?.ok) {
    const n = Object.keys(headers).length
    await loadConfig()
    // D145：明确告诉教师"存了什么"以及"是否真的会生效"
    const stages = usedByStage(savedName)
    const parts = [`provider「${savedName}」已保存（key 只掩码显示）`]
    if (n || ua) {
      const hdrNames = Object.keys(headers).join('、') || '无'
      parts.push(`请求头 ${n} 项${n ? `（${hdrNames}）` : ''}${ua ? ' + 自定义 UA' : ''}`)
    }
    if (n || ua) {
      parts.push(stages.length
        ? `✅ 已分配到 ${stages.map(stageName).join('、')} → 会真正生效`
        : '⚠️ 但还没分配到「转写段 / 评阅段」——**现在不会生效**，'
          + '请在下方两段式里选上它')
    }
    msg.value = parts.join('；')
    // D142：保存后清空表单，避免污染下一个 provider
    resetProviderForm()
  } else {
    msg.value = `保存失败：${rep?.error || ''}`
  }
  pKey.value = ''
  await loadConfig()
}

/** 清空 provider 表单（含请求头/UA），避免把上一个 provider 的配置带到下一个。 */
function resetProviderForm() {
  pName.value = ''
  pBase.value = ''
  pKey.value = ''
  pBatch.value = false
  pHdrText.value = ''
  pUserAgent.value = ''
  pSessionHdr.value = false
  pSessionHdrName.value = 'x-opencode-session'
  showAdv.value = false
}

/** 该 provider 是否被两段中的某一段引用（= 请求头是否真的会被用到）。 */
function usedByStage(name: string): string[] {
  const st = (llmConfig.value.stages || {}) as Record<string, any>
  return ['transcription', 'evaluation']
    .filter((k) => String(st[k]?.provider || '') === name)
}

async function confirmSaveProvider() {
  const p = pendingProvider.value
  pendingProvider.value = null
  if (!p) return
  await doSaveProvider(p.headers, p.user_agent)
}

/** 点「编辑」时把该 provider 已存的请求头回填到输入框。 */
function editProvider(p: any) {
  pName.value = p.name
  pBase.value = p.base_url
  pBatch.value = !!p.batch_support
  const hdrs = (p.headers || {}) as Record<string, string>
  // D145：把"会话头"从普通头里拆出来 → 回填成勾选状态（教师看到的是勾选，不是占位符）
  const sess = Object.entries(hdrs).find(([, v]) => String(v).includes('{session}'))
  pSessionHdr.value = !!sess
  pSessionHdrName.value = sess ? sess[0] : 'x-opencode-session'
  pHdrText.value = Object.entries(hdrs)
    .filter(([k]) => !sess || k !== sess[0])
    .map(([k, v]) => `${k}=${v}`).join('\n')
  pUserAgent.value = String(p.user_agent || '')
  showAdv.value = Object.keys(hdrs).length > 0 || !!p.user_agent
}

/** 段名 → 中文（提示文案用）。 */
function stageName(s: string): string {
  return s === 'transcription' ? '转写段' : s === 'evaluation' ? '评阅段' : s
}
async function delProvider(name: string) {
  if (!window.confirm(`删除 provider「${name}」及其本地 key？`)) return
  await postLlmProvider(props.engineAddr, props.token, { action: 'delete', name })
  await loadConfig()
}
async function saveStage(stage: 'transcription' | 'evaluation') {
  const p = stProvider.value[stage]
  if (!p) { msg.value = `请先为「${stage}」勾选 provider`; return }
  const rep = await postLlmProvider(props.engineAddr, props.token, {
    action: 'stage', stage, provider: p, model: stModel.value[stage] || '',
    batch: stage === 'evaluation' ? stBatch.value : undefined,
  })
  msg.value = rep?.ok ? `已保存「${stage}」：${p} / ${stModel.value[stage] || '（未填模型）'}` : `保存失败：${rep?.error || ''}`
  await loadConfig()
}
function stopPoll() { if (pollTimer !== undefined) { window.clearTimeout(pollTimer); pollTimer = undefined } }
/** D125：分步批阅 —— steps 为空 = 完整流程（transcribe,evaluate,report）。 */
async function startAi(steps?: string[]) {
  const w = curWork.value
  if (!w) { msg.value = '请选择作业（需先在「作业预览-学习通」下载作答/批语）'; return }
  // D127：前置产物缺失时给**明确提示**（而不是把按钮置灰——灰按钮不告诉原因）
  const st = (steps && steps.length) ? steps : ['transcribe', 'evaluate']
  if (st.length === 1 && st[0] === 'evaluate') {
    const n = students.value.length
    const done = students.value.filter((x) => !!drafts.value[x.key]?.ai?.transcript).length
    if (n && done === 0) {
      msg.value = '还没有任何转写：请先点「① 仅转写」（评阅必须建立在转写之上）'
      return
    }
  }
  // D89：优先用作业包（多张作业纸，按 tag 匹配）；否则退回单张作业纸
  const packPadList = packPads.value.map((p) => { try { return JSON.parse(p.json) } catch { return null } })
    .filter(Boolean)
  let taskpad: any = null
  let padsPayload: any[] | undefined
  if (packId.value && packPadList.length) {
    padsPayload = packPadList
    taskpad = packPadList[0]
  } else {
    const raw = pads.value.find(p => p.id === padId.value)?.json || ''
    try { taskpad = raw ? JSON.parse(raw) : null } catch { taskpad = null }
  }
  if (!taskpad) { msg.value = '请选择作业包（或单张作业纸）'; return }
  // D126：按 steps 显示对应文案（此前一律写「AI 批阅」，点"仅转录"时误导）
  const onlyTranscribe = st.length === 1 && st[0] === 'transcribe'
  const onlyEvaluate = st.length === 1 && st[0] === 'evaluate'
  const jobName = onlyTranscribe ? 'AI 转写' : (onlyEvaluate ? 'AI 评阅' : 'AI 批阅')
  busy.value = true
  progress.value = `正在装配任务清单并启动${jobName}……`
  try {
    const jobId = await startXxtGradeAi(props.engineAddr, props.token, {
      courseId: w.courseId, classId: w.classId, cpi: w.cpi, workId: w.workId, taskpad,
      // D127：作业包模式显式传 packId 作为批阅作用域键（与下方读草稿同口径）
      ...(packId.value ? { packId: packId.value } : {}),
      ...(padsPayload && padsPayload.length > 1 ? { pads: padsPayload } : {}),
      mode: mode.value, tags: [...tagsSel.value],
      limit: Number(limit.value) || 0,
      imageMode: imageMode.value,      // D106
      svgRedraw: svgRedraw.value,      // D106
      ...(steps && steps.length ? { steps } : {}),   // D125：分步批阅
      ...(allowPartial.value ? { allowPartial: true } : {}),   // D126-FIX：部分失败仍继续
    })
    stopPoll()
    const tick = async () => {
      try {
        const job = await fetchXxtLoginJob(props.engineAddr, props.token, jobId)
        const lines = job.lines || []
        if (job.status === 'running') {
          progress.value = `${jobName}中：${(lines.slice(-1)[0] || '').slice(-140)}`
          pollTimer = window.setTimeout(tick, 2000); return
        }
        busy.value = false
        progress.value = (job.returncode ?? 0) === 0
          ? (onlyTranscribe
            ? '✅ AI 转写完成（转写内容已写入批阅草稿，可在下方逐生审核查看）'
            : onlyEvaluate
              ? '✅ AI 评阅完成（结果已写入本地批阅草稿，可在下方逐生审核）'
              : '✅ 批阅完成（转写+评阅）。请在下方逐生审核，审完后点「📄 一键生成批阅报告」')
          : `❌ ${jobName}失败：${extractJobError(lines.join('\n'))}`
        await loadStudents()
      } catch (e) { busy.value = false; progress.value = `状态查询失败：${String(e)}` }
    }
    void tick()
  } catch (e) { busy.value = false; progress.value = `启动失败：${String(e)}` }
}
/** D125：按段测试 LLM 配置（能在正式批阅前发现 base_url/key/model 错配）。 */
async function testLlm() {
  busy.value = true; progress.value = '正在按段测试 LLM 配置（转录=多模态 / 评阅=纯文本）……'
  try {
    const r = await testLlmStages(props.engineAddr, props.token, 'both')
    // D127：失败时**逐段展示** provider/base_url/model/ms/error 原文
    // （此前 serve 用 HTTP 400 表达失败，前端只剩一句 "HTTP 400"，看不到原因）
    const lines = (r.results || []).map((x: any) => {
      const tag = x.stage === 'transcription' ? '转录段' : '评阅段'
      const head = `${tag}：${x.provider || '-'} / ${x.model || '-'} @ ${x.base_url || '-'}`
      return x.ok
        ? `✅ ${head}（${x.ms}ms，回复：${String(x.reply || '').slice(0, 30)}）`
        : `❌ ${head}\n    原因：${String(x.error || '未知错误').slice(0, 500)}`
    })
    const summary = r.ok ? '' : `\n\n${r.error || '（失败原因见上）'}`
    progress.value = (lines.join('\n') || '（无结果）') + summary
  } catch (e) {
    progress.value = `测试请求失败：${String((e as Error).message || e)}`
  } finally { busy.value = false }
}

/** D130-T12：**学生 → 草稿**的唯一取数入口。
 *
 *  历史缺陷：表格用 `drafts[s.key]`，而 `s.key` 固定取 `workAnswerId || name`；
 *  可草稿可能写在另一个键下（按姓名写 / 按 workAnswerId 写）→ 表格显示"未跑"，
 *  点开弹窗却因为兜底而能看到内容，形成"表与弹窗不一致"。
 *  现在表格与弹窗**都**走本函数：先按引擎给的 key，再按其它候选键兜底，
 *  两边同源，不可能再各说各话。
 */
function draftOf(s: { key?: string; name?: string; altKeys?: string[] }): Record<string, any> {
  const keys = [s.key, ...(s.altKeys || []), s.name].filter(Boolean) as string[]
  for (const k of keys) {
    const d = drafts.value[k]
    if (d && Object.keys(d).length) return d
  }
  return {}
}
/** D127：AI 状态 —— 让"跑过什么"在表上可见（此前只有 AI 分，跑完转写也看不出变化）。 */
function aiState(s: { key: string; name?: string; altKeys?: string[] }): { label: string; color: string } {
  const d = draftOf(s)
  const ai = d.ai || {}
  if ((d.human?.reportImages?.length || 0) > 0) return { label: '有报告', color: '#14532d' }
  if (ai.comment && (ai.score !== undefined && ai.score !== null)) return { label: '已评阅', color: '#1d4ed8' }
  if (ai.transcript) return { label: '已转写', color: '#a16207' }
  return { label: '未跑', color: '#9ca3af' }
}
/** D127：报告模式（未人工介入时显示 auto(AI)，不再是一串 "—"）。 */
function reportMode(s: { key: string; name?: string; altKeys?: string[] }): string {
  const d = draftOf(s)
  const hm = String(d.humanMode || 'none')
  if (hm === 'replace') return '人工替代'
  if (hm === 'append') return 'AI+人工'
  if (hm === 'revise') return 'AI·修订'
  return d.human?.used ? 'auto(人工)' : 'auto(AI)'
}

async function renderReports() {
  const w = curWork.value
  if (!w) { msg.value = '请选择作业'; return }
  busy.value = true
  progress.value = '正在按草稿逐生生成报告（人工在前 + 【附件】AI + 修订标红）……'
  try {
    const r = await renderReportsFromDrafts(props.engineAddr, props.token, {
      classId: w.classId, workId: w.workId, taskId: packId.value || padId.value,
    })
    busy.value = false
    if (r?.ok) {
      const n = r.count ?? (r.reports || []).length
      const types = Array.from(new Set((r.reports || []).map((x) => x.kind))).join('/')
      progress.value = `✅ 已生成 ${n} 份报告（类型：${types || '自动'}）；写入本地草稿（含报告图）`
      await loadStudents()
      // D126-B：让教师总结报告跟着刷新（评阅结果没变也会重算，成本很低：纯统计）
      reportReloadKey.value += 1
      // D130-T10：生成后自动切到报告页（弹窗已开则立即切，否则等下次打开）
      if (reviewOpen.value) {
        await nextTick()
        reviewModal.value?.showReportTab?.()
      } else {
        autoReportPending.value = true
      }
    } else {
      progress.value = `❌ 生成失败：${r?.error || '未知错误'}`
    }
  } catch (e) { busy.value = false; progress.value = `启动失败：${String(e)}` }
}
async function uploadAll(force: boolean) {
  const w = curWork.value
  if (!w) return
  const n = Object.keys(drafts.value).length
  if (!n) { msg.value = '还没有本地草稿：先跑 AI 批阅或逐生填写后保存'; return }
  if (force && !window.confirm(`强制覆盖：将上传 ${n} 份本地草稿（含打分）并覆盖平台已批阅内容？`)) return
  try {
    const jobId = await startXxtGradeUpload(props.engineAddr, props.token, {
      courseId: w.courseId, classId: w.classId, cpi: w.cpi, workId: w.workId,
      send: true, force,
    })
    busy.value = true; progress.value = `正在上传全部草稿（${force ? '强制覆盖' : '跳过已批阅'}）……`
    stopPoll()
    const tick = async () => {
      try {
        const job = await fetchXxtLoginJob(props.engineAddr, props.token, jobId)
        const lines = job.lines || []
        if (job.status === 'running') {
          progress.value = `上传中：${(lines.slice(-1)[0] || '').slice(-140)}`
          pollTimer = window.setTimeout(tick, 1500); return
        }
        busy.value = false
        progress.value = (job.returncode ?? 0) === 0
          ? '✅ 全部草稿上传完成'
          : `❌ 上传失败：${extractJobError(lines.join('\n'))}`
        await loadStudents()
      } catch (e) { busy.value = false; progress.value = `状态查询失败：${String(e)}` }
    }
    void tick()
  } catch (e) { busy.value = false; msg.value = `启动失败：${String(e)}` }
}

/** D116：tagOptions 就绪后**默认全选**（用户手动清空过则尊重其选择）。
 *  注意必须放在所有相关 computed（curWork/packPads/tagOptions）**定义之后**：
 *  `immediate: true` 会立刻求值，放前面会触发 TDZ（Cannot access before initialization）。 */
let tagAutoSelectDone = false
watch(tagOptions, (opts) => {
  if (tagAutoSelectDone || !opts.length) return
  tagAutoSelectDone = true
  if (!tagsSel.value.length) tagsSel.value = [...opts]
}, { immediate: true })
/** 切换作业/作业包时允许重新自动全选一次。 */
watch([workKey, packId, padId], () => { tagAutoSelectDone = false }, { flush: 'post' })

/** D117：作业选择变化就加载学生清单 + 草稿。
 *  旧实现只有下拉 `@change="loadStudents()"`，而 `loadWorks()` 是**代码自动赋值** workKey，
 *  不会触发 change 事件 → 进页面/批阅完成后「逐生审核」永远显示"无学生清单"、没有「审核」按钮。 */
watch(workKey, (k) => { if (k) void loadStudents(); else { students.value = []; drafts.value = {} } }, { flush: 'post' })

onMounted(async () => {
  await loadConfig()
  await loadWorks()
  // D117：自动选中的作业同样要拉学生/草稿（否则「逐生审核」空白）
  if (workKey.value) void loadStudents()
  loadKbCatalog()
  void loadPromptTemplates()
})
</script>

<template>
  <div class="card">
    <h2>AI 辅助批阅</h2>
    <p v-if="msg" class="hint" style="color:#7a5c00">{{ msg }}</p>
    <p class="hint">
      两段式：转写（多模态）→ 评阅（可 batch）｜结果为<b>本地批阅草稿</b>，审核后一键上传（未批阅不上传）。
      <template v-if="ungraded.length">尚余 <b>{{ ungraded.length }}</b> 名学生未完成批阅（{{ ungraded.slice(0, 8).join('、') }}<template v-if="ungraded.length > 8"> 等</template>）。</template>
    </p>

    <h3>① LLM 设置（provider 统一管理 + 两段式勾选）</h3>
    <table style="width:100%; border-collapse:collapse">
      <thead><tr><th style="text-align:left">provider</th><th style="text-align:left">base_url</th>
        <th>batch</th><th>key</th><th>请求头</th><th></th></tr></thead>
      <tbody>
        <tr v-for="p in (llmConfig.providers || [])" :key="p.name">
          <td>{{ p.name }}</td>
          <td class="hint">{{ p.base_url }}</td>
          <td style="text-align:center">{{ p.batch_support ? '✓' : '' }}</td>
          <td style="text-align:center">{{ p.api_key || '（未设置）' }}</td>
          <td style="text-align:center" class="hint">
            <template v-if="Object.keys(p.headers || {}).length || p.user_agent">
              <a href="javascript:;" @click="editProvider(p); showAdv = true">查看</a>
              （{{ Object.keys(p.headers || {}).length }} 项<template v-if="p.user_agent"> · UA</template>）
              <div v-if="usedByStage(p.name).length" style="color:#16a34a">
                已生效（{{ usedByStage(p.name).map((x) => x === 'transcription' ? '转写' : '评阅').join('、') }}段）
              </div>
              <div v-else style="color:#b45309">未分配段 → 不会用到</div>
            </template>
            <template v-else>—</template>
          </td>
          <td style="text-align:center">
            <a href="javascript:;" @click="editProvider(p)">编辑</a>
            ｜<a href="javascript:;" @click="delProvider(p.name)">删除</a>
          </td>
        </tr>
      </tbody>
    </table>
    <div style="margin-top:6px; display:flex; gap:8px; flex-wrap:wrap; align-items:center">
      <label class="field">名称 <input v-model="pName" placeholder="Aliyun" style="width:110px" /></label>
      <label class="field">base_url <input v-model="pBase" :placeholder="llmConfig.default_base_url || 'https://…/compatible-mode/v1'" style="width:330px" /></label>
      <label class="field">api_key <input v-model="pKey" type="password" placeholder="留空=不修改（只存掩码）" style="width:200px" /></label>
      <label class="field"><input type="checkbox" v-model="pBatch" /> 支持 batch</label>

    </div>

    <!-- D145：高级设置（在保存键**上方**——先设好再保存） -->
    <details :open="showAdv" style="margin:8px 0 6px"
             @toggle="showAdv = ($event.target as HTMLDetailsElement).open">
      <summary class="hint" style="cursor:pointer">
        ⚙️ 高级：请求头（只有 provider 明确要求时才需要设置）
      </summary>
      <div class="adv-box">
        <label class="adv-row">
          <input v-model="pSessionHdr" type="checkbox" />
          <span>
            <b>需要会话头</b>
            <span class="hint">（自动生成会话 id；如 opencode-go 的 /go 路由要求）</span>
          </span>
        </label>
        <label v-if="pSessionHdr" class="field" style="margin-left:22px">
          头名
          <input v-model="pSessionHdrName" placeholder="x-opencode-session" style="width:220px" />
          <span class="hint">会话 id 由引擎自动生成并填入，<b>无需你填写</b></span>
        </label>

        <label class="field" style="align-items:flex-start; margin-top:6px">
          其他自定义头（每行 name=value）
          <textarea v-model="pHdrText" rows="2" style="width:420px; font-family:monospace"
                    placeholder="（留空 = 不发送任何自定义头）"></textarea>
        </label>

        <label class="field" style="margin-top:4px">
          user-agent
          <input v-model="pUserAgent" :placeholder="`留空 = 使用默认值`" style="width:260px" />
          <span class="hint">默认：<code>{{ DEFAULT_UA }}</code></span>
        </label>

        <p class="hint" style="margin:4px 0 0">
          只允许 <code>x-*</code> 自定义头与 <code>user-agent</code>；
          <code>Authorization</code> / <code>Host</code> / <code>Cookie</code> 等会被引擎拒绝。
        </p>
      </div>
    </details>

    <div style="margin-top:8px; display:flex; gap:8px; align-items:center">
      <button class="btn primary" @click="saveProvider">保存 provider</button>
      <button class="btn" @click="resetProviderForm">清空表单</button>
    </div>


    <!-- 二次确认：请求头会随每次调用发送 -->
    <div v-if="pendingProvider" class="mask">
      <div class="dlg">
        <h3 style="margin:0 0 8px">确认保存这些请求头？</h3>
        <p class="hint" style="margin:0 0 6px">
          以下请求头将随**每次调用**发送到 provider「{{ pendingProvider.name }}」
          （{{ pendingProvider.base_url || '未填 base_url' }}）：
        </p>
        <pre class="hdrs">{{ Object.entries(pendingProvider.headers)
          .map(([k, v]) => `${k}: ${v}`).join('\n') || '（无自定义头）' }}</pre>
        <p v-if="pendingProvider.user_agent" class="hint" style="margin:0 0 6px">
          user-agent：<code>{{ pendingProvider.user_agent }}</code>
        </p>
        <div style="display:flex; gap:8px; justify-content:flex-end">
          <button class="btn" @click="pendingProvider = null">取消</button>
          <button class="btn primary" @click="confirmSaveProvider">我确认保存</button>
        </div>
      </div>
    </div>
    <div style="margin-top:8px">
      <div v-for="s in ['transcription', 'evaluation']" :key="s"
           style="display:flex; gap:8px; align-items:center; margin-top:4px; flex-wrap:wrap">
        <b style="width:80px">{{ s === 'transcription' ? '转写段' : '评阅段' }}</b>
        <select v-model="stProvider[s]" style="min-width:150px">
          <option value="">（选择 provider）</option>
          <option v-for="p in (llmConfig.providers || [])" :key="p.name" :value="p.name">{{ p.name }}</option>
        </select>
        <template v-if="modelsForStage(s).length && !stCustom[s]">
          <select v-model="stModel[s]" style="min-width:180px">
            <option value="">（默认）</option>
            <option v-for="m in modelsForStage(s)" :key="m" :value="m">{{ m }}</option>
          </select>
        </template>
        <input v-else v-model="stModel[s]" placeholder="模型名（填写即记录）" style="width:200px" />
        <button class="btn small" @click="stCustom[s] = !stCustom[s]" :title="modelsForStage(s).length ? '切换自定义/下拉' : '该 provider 暂无候选'">{{ stCustom[s] ? '用下拉' : '自定义' }}</button>
        <label v-if="s === 'evaluation'" class="field"><input type="checkbox" v-model="stBatch" /> 走 batch</label>
        <button class="btn" @click="saveStage(s as 'transcription' | 'evaluation')">保存</button>
      </div>
    </div>

    <h3 style="margin-top:14px">② 班级 ↔ 作业纸目录（class_map，按文件名建议）</h3>
    <div v-if="curWork" style="display:flex; gap:8px; align-items:center; flex-wrap:wrap">
      <span class="hint" style="width:240px">{{ curWork.label }}</span>
      <!-- D123：改为下拉选择真实班级目录，避免手输漏 `classes/` 前缀 -->
      <select v-model="classDir[`${curWork.courseId}:${curWork.classId}`]" style="min-width:230px">
        <option value="">（未关联）</option>
        <option v-for="d in classDirOptions" :key="d" :value="d">{{ d }}</option>
        <option
          v-if="classDir[`${curWork.courseId}:${curWork.classId}`]
            && !classDirOptions.includes(classDir[`${curWork.courseId}:${curWork.classId}`])"
          :value="classDir[`${curWork.courseId}:${curWork.classId}`]">
          {{ classDir[`${curWork.courseId}:${curWork.classId}`] }}（当前映射，目录可能不存在）
        </option>
      </select>
      <button class="btn" @click="suggestDir">填当前映射</button>
      <button class="btn" @click="saveDir">保存映射</button>
    </div>
    <p v-else class="hint">先选作业（③ 的下拉）。</p>

    <h3 style="margin-top:14px">③ 任务</h3>
    <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap">
      <select v-model="workKey" style="min-width:240px" @change="loadStudents()">
        <option value="">（选择已下载的作业）</option>
        <option v-for="w in works" :key="w.key" :value="w.key">{{ w.label }}</option>
      </select>
      <select v-model="packId" style="min-width:220px" @change="padId = ''">
        <option value="">（选择作业包：含多张按 tag 的作业纸）</option>
        <option v-for="pk in packStore.packs" :key="pk.id" :value="pk.id">
          {{ pk.id }}（{{ (pk.pads ?? []).length }} 张）
        </option>
      </select>
      <span class="hint" style="margin:0">或单张作业纸：</span>
      <select v-model="padId" style="min-width:200px" @change="packId = ''">
        <option value="">（单张作业纸）</option>
        <option v-for="p in pads" :key="p.id" :value="p.id">{{ p.id }}{{ p.tag ? ' · tag ' + p.tag : '' }}</option>
      </select>
      <label class="field">模式
        <select v-model="mode">
          <option value="optimized">优化（给题目/答案）</option>
          <option value="brute">brute-force（先自己作答再比对）</option>
        </select>
      </label>
      <label class="field" title="分层 tag 多选：来自「班级与标签」里学生打的 tag + 当前作业纸绑定的 target_tag。不选 = 批阅全部学生">
        tags
        <select v-model="tagsSel" multiple style="min-width:150px; min-height:56px">
          <option v-for="t in tagOptions" :key="t" :value="t">{{ t }}</option>
        </select>
        <button class="btn small" type="button" @click="tagsSel = [...tagOptions]">全选</button>
        <button class="btn small" type="button" :disabled="!tagsSel.length" @click="tagsSel = []">清空</button>
      </label>
      <label class="field">限前 <input v-model.number="limit" type="number" min="0" style="width:70px" /> 名</label>
      <!-- D116-C：tags 为空时给出可操作提示（不再静默空着） -->
      <p class="hint" v-if="tagHint" style="margin:4px 0 0; color:#7a5c00">
        ⚠ {{ tagHint }}
      </p>
      <p class="hint" v-else-if="!tagsSel.length" style="margin:4px 0 0">
        未选 tag = <b>批阅全部学生</b>；但只有打了 tag 的学生才能关联到对应作业纸的题目。
      </p>
      <p class="hint" v-else style="margin:4px 0 0">
        将只批阅 tag ∈ <code>{{ tagsSel.join('、') }}</code> 的学生。
      </p>
    <!-- D106：转录设置（图片压缩 / SVG 重绘） -->
    <div class="card" style="margin:8px 0; padding:8px 10px; border-left:3px solid var(--c-border)">
      <div style="font-weight:600; margin-bottom:4px; font-size:13px">转录设置</div>
      <label class="field" style="display:block; margin:2px 0">
        图片发送方式：
        <select v-model="imageMode" style="min-width:190px">
          <option value="auto">自动压缩（推荐，节省 token/时间）</option>
          <option value="original">原图直发（不计流量，用于对比转录效果）</option>
        </select>
      </label>
      <p class="hint" style="margin:2px 0 6px">
        自动压缩按体积分档：≤2MB 且长边≤2000px 原样发送；更大时缩到长边 2000/1600px 并转 JPEG。
        <b>原始图片始终保留在本地</b>，压缩只作用于送去模型的副本。
      </p>
      <label class="field" style="display:block; margin:2px 0">
        <input type="checkbox" v-model="svgRedraw" /> 让 AI 用 SVG 重绘学生手绘图（默认关）
      </label>
      <p class="hint" style="margin:2px 0 0">
        <b>SVG 重绘含义</b>：转录时让 AI 把学生画在纸上的示意图/受力图/电路图，
        用内联 <code>&lt;svg&gt;</code>（黑白线稿、最多 20 个图元）重新画出来，
        这样批阅报告里能看到"矢量图"而不是文字描述。
        仅建议几何/受力/电路类题目开启：会增加耗时与输出 token，且 AI 可能画得不准确，请人工核对。
      </p>
    </div>
      <!-- D125：分步批阅 —— 转录最慢最贵，先单独跑通再往下 -->
      <button class="btn small" :disabled="busy" title="按段测试 LLM 配置（能立刻发现 base_url/key/model 错配）"
              @click="testLlm">🔍 测试配置</button>
      <button class="btn small" :disabled="busy" title="只跑转录（发送作答图 → 得到文字转录）"
              @click="startAi(['transcribe'])">① 仅转录</button>
      <button class="btn small" :disabled="busy" title="只跑评阅（要求已有转录产物）"
              @click="startAi(['evaluate'])">② 仅评阅</button>
      <button class="btn" :disabled="busy"
              title="完整批阅：转录 → 评阅（不含报告；审核后再用下方「📄 一键生成批阅报告」）"
              @click="startAi(['transcribe', 'evaluate'])">▶ ③ 完整批阅</button>
      <label class="hint" style="display:inline-flex; align-items:center; gap:4px; margin-left:8px">
        <input type="checkbox" v-model="allowPartial" />
        有学生转录失败时仍继续（默认中止）
      </label>
    </div>
    <p v-if="progress" class="hint" style="margin-top:6px">{{ progress }}</p>

    <h3 style="margin-top:14px">④ 逐生审核（左右两栏弹窗）</h3>
    <p class="hint" style="margin:0 0 6px">
      点「审核」打开弹窗：左=作答图；右上=AI 批语（可另存修订版）；右下=人工批阅（可选，AI 原文不被覆盖）。
      保存后到 ⑤ 一键生成报告（按每生模式自动出 5 种版式之一）。
    </p>
    <!-- D127-FIX：固定高度 + 表头粘性 + 滚轮滚动（与「班级与标签」名单表同口径），
         避免几十人时整页被拉长、需要滚到页底才能看到下面的按钮。 -->
    <!-- D130-FIX2：「读取」按钮。刷新后作业包/作业纸下拉是空的，
         状态与 tag 依赖引擎反查批阅目录；给教师一个明确的"重新读取"入口，
         并显示这次实际读的是哪个批阅目录（否则空状态无从排查）。 -->
    <div v-if="curWork || students.length" class="review-tools">
      <button class="btn small" type="button" :disabled="studentsLoading" @click="loadStudents()">
        🔄 读取状态
      </button>
      <span class="hint" style="margin:0">
        <template v-if="studentsLoading">正在读取…</template>
        <template v-else>
          已读取 {{ students.length }} 名学生
          <template v-if="resolvedScope">（批阅目录：<code>{{ resolvedScope }}</code>）</template>
          <template v-else-if="students.length">（未指定作业包/作业纸）</template>
        </template>
      </span>
      <span v-if="!packId && !padId && students.length" class="hint" style="margin:0;color:#b45309">
        · 未选作业包/作业纸：tag 与 AI 状态按<b>引擎自动识别的批阅目录</b>显示；
        如需指定具体批次，请在 ③ 区选择。
      </span>
    </div>

    <div v-if="students.length" class="review-list-scroll">
      <table class="review-list-table">
        <thead>
          <tr>
            <th style="text-align:left">学生</th><th>tag</th><th>AI 状态</th>
            <th>AI 分</th><th>人工</th><th>报告模式</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(s, i) in students" :key="s.key">
            <td>{{ s.name }}</td>
            <td class="c">{{ s.tag || '—' }}</td>
            <td class="c">
              <b :style="{ color: aiState(s).color }">{{ aiState(s).label }}</b>
              <div v-if="draftOf(s).ai?.at" class="hint" style="font-size:11px">
                {{ draftOf(s).ai.at }}
              </div>
            </td>
            <td class="c">{{ draftOf(s).ai?.score ?? draftOf(s).score ?? '—' }}</td>
            <td class="c">{{ draftOf(s).human?.used ? (draftOf(s).human.score ?? '✓') : '—' }}</td>
            <td class="c">{{ reportMode(s) }}</td>
            <td class="c" style="white-space:nowrap">
              <button class="btn small" :disabled="rowBusy !== '' || !curWork"
                      :title="curWork ? '只转写这一名学生' : '请先在 ③ 区选择作业'"
                      @click="runOne(s, 'transcribe')">转写</button>
              <button class="btn small" :disabled="rowBusy !== '' || !curWork"
                      :title="curWork ? '用已有转写评阅这一名学生' : '请先在 ③ 区选择作业'"
                      @click="runOne(s, 'evaluate')">批阅</button>
              <button class="btn small" :disabled="rowBusy !== '' || !curWork"
                      :title="curWork ? '转写+评阅这一名学生' : '请先在 ③ 区选择作业'"
                      @click="runOne(s, 'full')">
                {{ rowBusy === s.name ? '…' : '完整' }}
              </button>
              ｜<button class="btn small" @click="onReviewOpen(i)">审核</button>
              <div v-if="rowMsg[s.name]" class="hint" style="margin-top:2px; white-space:normal">
                {{ rowMsg[s.name] }}
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else class="hint">
      <template v-if="!curWork">未选择作业：先在 ③ 区选「作业」。</template>
      <template v-else-if="studentsLoading">正在读取学生清单…</template>
      <template v-else>该作业暂无学生清单（引擎可能离线，或该作业还没在「作业预览-学习通」下载作答）。
        <button class="btn small" type="button" style="margin-left:6px" @click="loadStudents()">重新读取</button>
      </template>
    </p>

    <h3 style="margin-top:14px">⑤ 报告 / ⑥ 上传全部</h3>
    <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap">
      <span class="hint" style="margin:0">
        报告类型**自动**由逐生审核决定（AI批阅报告 / 人工批阅报告 / 人工在前+【附件】AI / …（人工修订））
      </span>
      <button class="btn" :disabled="busy" @click="renderReports">📄 一键生成批阅报告</button>
      <span style="flex:1"></span>
      <button class="btn" :disabled="busy" @click="uploadAll(false)">⬆⬆ 上传全部批阅（含打分）</button>
      <button class="btn" :disabled="busy" @click="uploadAll(true)">⬆⬆ 强制覆盖上传全部</button>
    </div>
    <p class="hint" style="margin-top:6px">
      完整逐生预览（作答图 + 两栏批语 + 旋转/上下位）仍在「作业预览-学习通 → 批阅图片 → 逐生预览」。
    </p>

    <!-- D130-T9：评阅规则卡（教师可见/可改评分口径；此前完全硬编码） -->
    <GradingRulesCard :engine-addr="props.engineAddr" :token="props.token"
                      @notify="(m) => { progress = m }" />

    <!-- D126-B：教师总结报告（易错知识点 + 共现矩阵 + 得分率；只给教师） -->
    <TeacherReportCard :engine-addr="props.engineAddr" :token="props.token"
                       :class-dir="curWorkDir" :task-id="packId || padId"
                       :reload-key="reportReloadKey" />

    <!-- D135：跨作业知识点趋势（同一知识点是否反复出错；只给教师） -->
    <TrendCard :engine-addr="props.engineAddr" :token="props.token"
               :class-dir="curWorkDir" :reload-key="reportReloadKey" />

    <!-- D140：Atopia 已独立为顶层选项卡，这里只留指路提示（避免双入口） -->
    <p class="hint" style="margin-top:12px">
      🤖 想让 AI 用本项目工具（多轮对话 / 读题库 / 抽知识点 / 写回）？
      请到顶部 <b>Atopia</b> 选项卡 —— 每次调用都会经过安全 Gate。
    </p>
  </div>

    <h3 style="margin-top:14px">⑦ 题库 AI 作答（对题目生成参考答案；不覆盖、可多版本）</h3>
    <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap">
      <span class="hint" style="margin:0">题库：</span>
      <select v-model="kbKind" style="min-width:120px">
        <option value="">（选择题库）</option>
        <option v-for="k in kbKinds" :key="k" :value="k">{{ k }}</option>
      </select>
      <span class="hint" style="margin:0">章节：</span>
      <select v-model="kbChap" style="min-width:130px">
        <option value="">（整库）</option>
        <option v-for="c in kbChapters" :key="c" :value="c">{{ c }}</option>
      </select>
      <span class="hint" style="margin:0">题号：</span>
      <select v-model="kbIdsSel" multiple style="min-width:200px; min-height:64px" title="多选；不选=整章">
        <option v-for="i in kbIdList" :key="i.id" :value="i.id">{{ i.id }}</option>
      </select>
      <span class="hint" style="margin:0">模型：</span>
      <template v-if="modelsForStage('evaluation').length && !kbCustomModel">
        <select v-model="kbModel" style="min-width:160px">
          <option value="">（评阅段配置）</option>
          <option v-for="m in modelsForStage('evaluation')" :key="m" :value="m">{{ m }}</option>
        </select>
        <button class="btn small" @click="kbCustomModel = true">自定义</button>
      </template>
      <template v-else>
        <input v-model="kbModel" placeholder="模型名（空=评阅段配置）" style="width:180px" />
        <button class="btn small" @click="kbCustomModel = false">用下拉</button>
      </template>
      <label class="field" title="默认勾选：AI 作答即成为生效答案（旧版仍在版本库，可一键 pin 回）">
        <input type="checkbox" v-model="kbPin" /> 作答后置顶（默认）
      </label>
      <label class="field" title="不勾=仅 dry-run 预览将作答哪些题；勾=真正调 LLM 并写回 kb/solutions/">
        <input type="checkbox" v-model="kbApply" /> 真正作答并写回
      </label>
      <label class="field"
             title="一次产出「参考解答 + 评阅要点 + 知识点」（带该题型规则摘要），写入同一版本">
        <input type="checkbox" v-model="kbWithRubric" /> 同时生成评阅要点
      </label>
      <label v-if="kbWithRubric" class="field"
             title="默认不置顶：AI 要点未经教师确认，不该抢生效答案（D130 验收 5）">
        <input type="checkbox" v-model="kbPinRubric" /> 同时置顶（跳过确认）
      </label>
    </div>
    <p v-if="kbWithRubric" class="hint" style="margin:2px 0 0">
      ⓘ 要点与解答**同一次生成**（口径一致）。默认<b>不置顶</b>：先在题库表格里核对要点，
      确认无误再「置顶」为生效答案；`copy`/`summary` 按口径不生成 AI 要点。
    </p>
    <div style="margin:6px 0">
      <!-- D108：提示词模板库 -->
      <div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap; margin-bottom:4px">
        <label class="hint" style="margin:0">提示词模板：</label>
        <select v-model="promptSel" @change="pickPromptTemplate" style="min-width:220px">
          <option value="">（不使用模板 / 单次输入）</option>
          <option v-for="t in promptTemplates" :key="t.id" :value="t.id">
            {{ t.default ? '★ ' : '' }}{{ t.name }}{{ t.builtin ? '（内置）' : '' }}
          </option>
        </select>
        <button class="btn small" :disabled="promptBusy || !promptSel || promptIsDefault"
                title="下次打开面板自动载入该模板" @click="setPromptDefault">设为默认</button>
        <button class="btn small" :disabled="promptBusy || !kbRequirement.trim()"
                title="保存到当前模板（覆盖其内容）" @click="savePromptTemplate">💾 保存</button>
        <button class="btn small" :disabled="promptBusy || !kbRequirement.trim()"
                title="另存为一个新模板（内置模板改完想留原版时用这个）" @click="savePromptAsNew">＋ 另存为</button>
        <button class="btn small" :disabled="promptBusy || !promptSel || promptIsBuiltin"
                title="内置模板不可删除" @click="deletePromptTemplate">🗑 删除</button>
      </div>
      <label class="hint" style="display:block; margin:0 0 4px">
        作答要求（会作为「优先满足」附加到每题 prompt；选中模板会载入其内容，可再临时修改，直接点「AI 作答」即生效）：
      </label>
      <textarea v-model="kbRequirement" rows="3"
        placeholder="例：请画出示意图；用 LaTeX 公式完整推导；输出为 HTML 文档；按「已知/求/解/答」结构写；计算题保留 3 位有效数字……"
        style="width:100%; max-width:760px; font-family:inherit; font-size:13px; padding:6px 8px;
               border:1px solid var(--c-border); border-radius:6px; resize:vertical"></textarea>
      <div class="hint" style="margin:2px 0 0">
        留空 = 使用系统默认作答风格（规范完整解答，公式用 $..$ / $$..$$）。
        模板保存在 <code>&lt;workspace&gt;/prompts/ai-solve/</code>，<b>CLI/AI 同样可用</b>
        （<code>assist prompt list</code> / <code>kb ai-solve --requirement-template &lt;id&gt;</code>）。
        <span v-if="promptMsg" style="color:var(--c-primary)">｜{{ promptMsg }}</span>
      </div>
      <button class="btn" :disabled="kbSolving" @click="solveByKb">▶ {{ kbApply ? 'AI 作答并写回' : 'AI 作答（dry-run）' }}</button>
    </div>
    <div class="hint" style="margin:4px 0 0">题目预览：
      <code v-if="kbPreview" style="display:inline-block; max-width:100%; overflow-x:auto; white-space:nowrap; vertical-align:bottom">{{ kbPreview }}</code>
      <span v-else>（未选题号：将按整章/整库作答）</span>
    </div>
    <p class="hint" style="margin:6px 0 0">
      AI 作答**不覆盖**原答案：每次新增一版（含模型名 + 时间戳），默认**置顶为生效答案**
      （可在「题库编辑器 → solution 🔍 预览」里改选/置顶旧版）；作业纸预览、作业包与批阅统一**实时读取生效版**
      （置顶版 → 最新版 → 题库 solution 列）。索引状态：{{ kbStore.solutionsMsg || '（未刷新）' }}
    </p>
    <p class="hint" v-if="kbSolveMsg">{{ kbSolveMsg }}</p>


    <StudentReviewModal
      v-if="reviewOpen"
      ref="reviewModal"
      :engine-addr="props.engineAddr" :token="props.token"
      :class-id="curWork?.classId || ''" :work-id="curWork?.workId || ''"
      :task-id="padId || packId" :class-dir="curWorkDir"
      :students="students" :drafts="drafts" :start-index="reviewIndex"
      @close="reviewOpen = false"
      @saved="loadStudents"
      @notify="(m) => { progress = String(m) }"
    />

    <PlaygroundPanel :engine-addr="props.engineAddr" :token="props.token" />

</template>

<style scoped>
/* D145：高级设置区 */
.adv-box { display: flex; flex-direction: column; gap: 4px; border: 1px solid #e5e7eb;
           border-radius: 8px; padding: 8px 10px; background: #fafafa; }
.adv-row { display: flex; gap: 6px; align-items: baseline; font-size: 13px; }

/* D137：provider 请求头二次确认弹窗 */
.mask { position: fixed; inset: 0; background: rgba(15, 23, 42, .45); z-index: 60;
        display: flex; align-items: center; justify-content: center; }
.dlg { background: #fff; border-radius: 10px; padding: 16px 18px; width: min(560px, 92vw);
       box-shadow: 0 12px 40px rgba(0, 0, 0, .25); }
.hdrs { background: #f9fafb; border: 1px solid var(--c-border); border-radius: 6px;
        padding: 8px; font-size: 12px; white-space: pre-wrap; margin: 0 0 8px; }

/* D127-FIX：逐生审核名单 —— 固定高度 + 滚轮 + 粘性表头（与「班级与标签」名单表同口径）。 */
.review-tools { display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
                margin: 8px 0 4px; }
.review-list-scroll {
  max-height: 420px;
  overflow: auto;
  border: 1px solid var(--c-border);
  border-radius: 8px;
}
.review-list-table { width: 100%; border-collapse: collapse; }
.review-list-table th {
  position: sticky; top: 0; z-index: 1;
  background: var(--c-primary-soft, #eef2ff);
  border-bottom: 1px solid var(--c-border);
  padding: 6px 8px; font-size: 13px; white-space: nowrap;
}
.review-list-table td {
  padding: 5px 8px; border-bottom: 1px solid var(--c-border);
  font-size: 13px;
}
.review-list-table tbody tr:hover { background: var(--c-bg-soft, #f8fafc); }
.review-list-table td.c { text-align: center; }
</style>

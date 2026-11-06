import { defineComponent as _defineComponent } from 'vue'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useTaskpadStore } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/stores/taskpad'
import {
  extractJobError, fetchLlmConfig, fetchXxtClassMap, fetchXxtGradeDrafts, fetchXxtLoginJob,
  fetchXxtReviewIndex, fetchXxtReviewStudents, postLlmProvider, postXxtClassMap,
  startXxtGradeAi, startXxtGradeUpload, renderReportsFromDrafts, testLlmStages,
} from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/engineClient'

import { usePackStore } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/stores/packs'
import { useRosterStore } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/stores/roster'

import PlaygroundPanel from '/home/bot2603/Projects/2609-assignment-assistant/app/tests/PlaygroundPanel.compiled-eclg4l.ts'
import StudentReviewModal from '/home/bot2603/Projects/2609-assignment-assistant/app/tests/StudentReviewModal.compiled-cvlewi.ts'
import GradingRulesCard from '/home/bot2603/Projects/2609-assignment-assistant/app/tests/GradingRulesCard.compiled-8bm5fr.ts'
const DEFAULT_UA = 'assignment-assistant/<版本>'   // 仅用于展示默认值文案

const __sfc_main = /*@__PURE__*/_defineComponent({
  __name: 'AiGradingPanel',
  props: {
    engineAddr: { type: String, required: true },
    token: { type: String, required: false }
  },
  setup(__props: any, { expose: __expose }) {
  __expose();

/** D86 §6 / D88 §4：AI 辅助批阅面板（提炼自 XxetongView 临时面板）。
 *  六区：① LLM 设置（provider + 两段式）② 班级↔作业纸目录映射 ③ 任务（AI 批阅）
 *        ④ 逐生审核（本地草稿：改分/批语/保存/演练/上传）⑤ 一键生成批阅报告 ⑥ 一键上传全部
 *  说明：完整"逐生预览（作答图+批语两栏）"仍在「作业预览-学习通 → 批阅图片 → 逐生预览」，
 *  与本面板的"报告风格审核"并存（用户拍板的两种风格）。
 */
const props = __props
const taskpadStore = useTaskpadStore()
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
/** D171-T1：强制重做（覆盖已有转写/评阅产物，会重新花额度） */
const forceRedo = ref(false)
const busy = ref(false)
const progress = ref('')
let pollTimer: number | undefined

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
  // D171-T1：与上方三键同口径，去掉「完整」这个不准确的叫法
  const label = mode === 'full' ? '转写+批阅' : mode === 'transcribe' ? '转写' : '批阅'
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
/** D171-T8: name -> tag, from roster/snapshot; used to tell "new" from "unassigned". */
const rosterTagByName = ref<Record<string, string> | null>(null)

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
    // D171-T8：建立"姓名 → tag"映射用于诊断（引擎回的 students 已带 tag；
    // 缺失时用 null 表示"无法判断"，避免误报"新增"）
    try {
      const m: Record<string, string> = {}
      for (const x of (st.students || []) as any[]) {
        const nm = String(x.name || '')
        if (nm) m[nm] = String(x.tag || '')
      }
      rosterTagByName.value = m
    } catch { rosterTagByName.value = null }
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
  const jobName = onlyTranscribe ? 'AI 转写' : (onlyEvaluate ? 'AI 评阅' : 'AI 转写+批阅')
  // D171-T1：强制重做 → 覆盖已有产物并重新调用模型（此前「转写+批阅」不传 force，
  // 会被后端"跳过已有结果"静默吞掉，教师以为跑完了其实只做了转写）。
  const doForce = forceRedo.value === true
  const nStu = students.value.length
  if (doForce && nStu) {
    const what = onlyTranscribe ? '转写' : (onlyEvaluate ? '评阅' : '转写与评阅')
    if (!window.confirm(
      `已勾选「强制重做」：将对 ${nStu} 名学生**重新调用大模型做${what}**，`
      + `并覆盖已有${what}结果。\n这会重新消耗额度，确定继续？`)) return
  }
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
      ...(doForce ? { force: true } : {}),           // D171-T1：强制重做
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
/** D171-T8：学生 tag 诊断标记。 */
function tagMark(s: { key?: string; name?: string; tag?: string }): { text: string; color: string; why: string } {
  const t = String(s.tag || '').trim()
  if (t) return { text: t, color: 'inherit', why: '' }
  const map = rosterTagByName.value
  const inRoster = map ? Object.prototype.hasOwnProperty.call(map, String(s.name || '')) : true
  if (!inRoster) {
    return { text: '新增', color: '#b45309',
             why: '该生不在本作业名单（可能是生成作业后才加入班级）：需单独制作作业纸并单独批阅' }
  }
  return { text: '(未分配)', color: '#b45309',
           why: '该生在名单里但没有 tag：请到「班级与标签」为其打 tag 后再批阅' }
}

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
})

const __returned__ = { props, taskpadStore, packStore, rosterStore, msg, imageMode, svgRedraw, allowPartial, forceRedo, busy, progress, get pollTimer() { return pollTimer }, set pollTimer(v) { pollTimer = v }, llmConfig, pHdrText, pUserAgent, showAdv, pSessionHdr, pSessionHdrName, DEFAULT_UA, pendingProvider, parseHeaders, pName, pBase, pKey, pBatch, stProvider, stModel, stBatch, stCustom, modelsForStage, classMap, classDir, works, workKey, padId, packId, mode, tagsSel, limit, reviewOpen, reviewIndex, openReview, reviewModal, resolvedScope, autoReportPending, reportReloadKey, onReviewOpen, rosterTags, padTags, tagOptions, tagHint, rosterStudentsTagged, curWorkDir, rowBusy, rowMsg, runOne, pollJob, students, studentsLoading, drafts, rosterTagByName, packPads, pads, curWork, ungraded, loadConfig, loadWorks, loadStudents, classDirFor, classDirOptions, suggestDir, saveDir, collectHeaders, saveProvider, doSaveProvider, resetProviderForm, usedByStage, confirmSaveProvider, editProvider, stageName, delProvider, saveStage, stopPoll, startAi, testLlm, draftOf, tagMark, aiState, reportMode, renderReports, uploadAll, get tagAutoSelectDone() { return tagAutoSelectDone }, set tagAutoSelectDone(v) { tagAutoSelectDone = v }, PlaygroundPanel, StudentReviewModal, GradingRulesCard }
Object.defineProperty(__returned__, '__isScriptSetup', { enumerable: false, value: true })
return __returned__
}

})
import { createElementVNode as _createElementVNode, toDisplayString as _toDisplayString, openBlock as _openBlock, createElementBlock as _createElementBlock, createCommentVNode as _createCommentVNode, createTextVNode as _createTextVNode, Fragment as _Fragment, renderList as _renderList, vModelText as _vModelText, withDirectives as _withDirectives, vModelCheckbox as _vModelCheckbox, vModelSelect as _vModelSelect, normalizeStyle as _normalizeStyle, createVNode as _createVNode, createBlock as _createBlock } from "vue"

const _hoisted_1 = { class: "card" }
const _hoisted_2 = {
  key: 0,
  class: "hint",
  style: {"color":"#7a5c00"}
}
const _hoisted_3 = { class: "hint" }
const _hoisted_4 = { style: {"width":"100%","border-collapse":"collapse"} }
const _hoisted_5 = { class: "hint" }
const _hoisted_6 = { style: {"text-align":"center"} }
const _hoisted_7 = { style: {"text-align":"center"} }
const _hoisted_8 = {
  style: {"text-align":"center"},
  class: "hint"
}
const _hoisted_9 = ["onClick"]
const _hoisted_10 = {
  key: 1,
  style: {"color":"#16a34a"}
}
const _hoisted_11 = {
  key: 2,
  style: {"color":"#b45309"}
}
const _hoisted_12 = { style: {"text-align":"center"} }
const _hoisted_13 = ["onClick"]
const _hoisted_14 = ["onClick"]
const _hoisted_15 = { style: {"margin-top":"6px","display":"flex","gap":"8px","flex-wrap":"wrap","align-items":"center"} }
const _hoisted_16 = { class: "field" }
const _hoisted_17 = { class: "field" }
const _hoisted_18 = ["placeholder"]
const _hoisted_19 = { class: "field" }
const _hoisted_20 = { class: "field" }
const _hoisted_21 = ["open"]
const _hoisted_22 = { class: "adv-box" }
const _hoisted_23 = { class: "adv-row" }
const _hoisted_24 = {
  key: 0,
  class: "field",
  style: {"margin-left":"22px"}
}
const _hoisted_25 = {
  class: "field",
  style: {"align-items":"flex-start","margin-top":"6px"}
}
const _hoisted_26 = {
  class: "field",
  style: {"margin-top":"4px"}
}
const _hoisted_27 = {
  key: 1,
  class: "mask"
}
const _hoisted_28 = { class: "dlg" }
const _hoisted_29 = {
  class: "hint",
  style: {"margin":"0 0 6px"}
}
const _hoisted_30 = { class: "hdrs" }
const _hoisted_31 = {
  key: 0,
  class: "hint",
  style: {"margin":"0 0 6px"}
}
const _hoisted_32 = { style: {"display":"flex","gap":"8px","justify-content":"flex-end"} }
const _hoisted_33 = { style: {"margin-top":"8px"} }
const _hoisted_34 = { style: {"width":"80px"} }
const _hoisted_35 = ["onUpdate:modelValue"]
const _hoisted_36 = ["value"]
const _hoisted_37 = ["onUpdate:modelValue"]
const _hoisted_38 = ["value"]
const _hoisted_39 = ["onUpdate:modelValue"]
const _hoisted_40 = ["onClick", "title"]
const _hoisted_41 = {
  key: 2,
  class: "field"
}
const _hoisted_42 = ["onClick"]
const _hoisted_43 = {
  key: 2,
  style: {"display":"flex","gap":"8px","align-items":"center","flex-wrap":"wrap"}
}
const _hoisted_44 = {
  class: "hint",
  style: {"width":"240px"}
}
const _hoisted_45 = ["value"]
const _hoisted_46 = ["value"]
const _hoisted_47 = {
  key: 3,
  class: "hint"
}
const _hoisted_48 = { style: {"display":"flex","gap":"8px","align-items":"center","flex-wrap":"wrap"} }
const _hoisted_49 = ["value"]
const _hoisted_50 = ["value"]
const _hoisted_51 = ["value"]
const _hoisted_52 = { class: "field" }
const _hoisted_53 = {
  class: "field",
  title: "分层 tag 多选：来自「班级与标签」里学生打的 tag + 当前作业纸绑定的 target_tag。不选 = 批阅全部学生"
}
const _hoisted_54 = ["value"]
const _hoisted_55 = ["disabled"]
const _hoisted_56 = { class: "field" }
const _hoisted_57 = {
  key: 0,
  class: "hint",
  style: {"margin":"4px 0 0","color":"#7a5c00"}
}
const _hoisted_58 = {
  key: 1,
  class: "hint",
  style: {"margin":"4px 0 0"}
}
const _hoisted_59 = {
  key: 2,
  class: "hint",
  style: {"margin":"4px 0 0"}
}
const _hoisted_60 = {
  class: "card",
  style: {"margin":"8px 0","padding":"8px 10px","border-left":"3px solid var(--c-border)"}
}
const _hoisted_61 = {
  class: "field",
  style: {"display":"block","margin":"2px 0"}
}
const _hoisted_62 = {
  class: "field",
  style: {"display":"block","margin":"2px 0"}
}
const _hoisted_63 = ["disabled"]
const _hoisted_64 = ["disabled"]
const _hoisted_65 = ["disabled"]
const _hoisted_66 = ["disabled"]
const _hoisted_67 = {
  class: "hint",
  style: {"display":"inline-flex","align-items":"center","gap":"4px","margin-left":"8px"},
  title: "勾选后：三个键都会**重新调用大模型并覆盖**已有产物（会重新花额度）"
}
const _hoisted_68 = {
  class: "hint",
  style: {"display":"inline-flex","align-items":"center","gap":"4px","margin-left":"8px"}
}
const _hoisted_69 = {
  key: 4,
  class: "hint",
  style: {"margin-top":"6px"}
}
const _hoisted_70 = {
  key: 5,
  class: "review-tools"
}
const _hoisted_71 = ["disabled"]
const _hoisted_72 = {
  class: "hint",
  style: {"margin":"0"}
}
const _hoisted_73 = {
  key: 0,
  class: "hint",
  style: {"margin":"0","color":"#b45309"}
}
const _hoisted_74 = {
  key: 6,
  class: "review-list-scroll"
}
const _hoisted_75 = { class: "review-list-table" }
const _hoisted_76 = ["title"]
const _hoisted_77 = { class: "c" }
const _hoisted_78 = {
  key: 0,
  class: "hint",
  style: {"font-size":"11px"}
}
const _hoisted_79 = { class: "c" }
const _hoisted_80 = { class: "c" }
const _hoisted_81 = { class: "c" }
const _hoisted_82 = {
  class: "c",
  style: {"white-space":"nowrap"}
}
const _hoisted_83 = ["disabled", "title", "onClick"]
const _hoisted_84 = ["disabled", "title", "onClick"]
const _hoisted_85 = ["disabled", "title", "onClick"]
const _hoisted_86 = ["onClick"]
const _hoisted_87 = {
  key: 0,
  class: "hint",
  style: {"margin-top":"2px","white-space":"normal"}
}
const _hoisted_88 = {
  key: 7,
  class: "hint"
}
const _hoisted_89 = { style: {"display":"flex","gap":"8px","align-items":"center","flex-wrap":"wrap"} }
const _hoisted_90 = ["disabled"]
const _hoisted_91 = ["disabled"]
const _hoisted_92 = ["disabled"]

export function render(_ctx, _cache, $props, $setup, $data, $options) {
  return (_openBlock(), _createElementBlock(_Fragment, null, [
    _createElementVNode("div", _hoisted_1, [
      _cache[91] || (_cache[91] = _createElementVNode("h2", null, "AI 辅助批阅", -1 /* CACHED */)),
      ($setup.msg)
        ? (_openBlock(), _createElementBlock("p", _hoisted_2, _toDisplayString($setup.msg), 1 /* TEXT */))
        : _createCommentVNode("v-if", true),
      _createElementVNode("p", _hoisted_3, [
        _cache[39] || (_cache[39] = _createTextVNode(" 两段式：转写（多模态）→ 评阅（可 batch）｜结果为", -1 /* CACHED */)),
        _cache[40] || (_cache[40] = _createElementVNode("b", null, "本地批阅草稿", -1 /* CACHED */)),
        _cache[41] || (_cache[41] = _createTextVNode("，审核后一键上传（未批阅不上传）。 ", -1 /* CACHED */)),
        ($setup.ungraded.length)
          ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
              _cache[37] || (_cache[37] = _createTextVNode("尚余 ", -1 /* CACHED */)),
              _createElementVNode("b", null, _toDisplayString($setup.ungraded.length), 1 /* TEXT */),
              _createTextVNode(" 名学生未完成批阅（" + _toDisplayString($setup.ungraded.slice(0, 8).join('、')), 1 /* TEXT */),
              ($setup.ungraded.length > 8)
                ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                    _createTextVNode(" 等")
                  ], 64 /* STABLE_FRAGMENT */))
                : _createCommentVNode("v-if", true),
              _cache[38] || (_cache[38] = _createTextVNode("）。", -1 /* CACHED */))
            ], 64 /* STABLE_FRAGMENT */))
          : _createCommentVNode("v-if", true)
      ]),
      _cache[92] || (_cache[92] = _createElementVNode("h3", null, "① LLM 设置（provider 统一管理 + 两段式勾选）", -1 /* CACHED */)),
      _createElementVNode("table", _hoisted_4, [
        _cache[44] || (_cache[44] = _createElementVNode("thead", null, [
          _createElementVNode("tr", null, [
            _createElementVNode("th", { style: {"text-align":"left"} }, "provider"),
            _createElementVNode("th", { style: {"text-align":"left"} }, "base_url"),
            _createElementVNode("th", null, "batch"),
            _createElementVNode("th", null, "key"),
            _createElementVNode("th", null, "请求头"),
            _createElementVNode("th")
          ])
        ], -1 /* CACHED */)),
        _createElementVNode("tbody", null, [
          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(($setup.llmConfig.providers || []), (p) => {
            return (_openBlock(), _createElementBlock("tr", {
              key: p.name
            }, [
              _createElementVNode("td", null, _toDisplayString(p.name), 1 /* TEXT */),
              _createElementVNode("td", _hoisted_5, _toDisplayString(p.base_url), 1 /* TEXT */),
              _createElementVNode("td", _hoisted_6, _toDisplayString(p.batch_support ? '✓' : ''), 1 /* TEXT */),
              _createElementVNode("td", _hoisted_7, _toDisplayString(p.api_key || '（未设置）'), 1 /* TEXT */),
              _createElementVNode("td", _hoisted_8, [
                (Object.keys(p.headers || {}).length || p.user_agent)
                  ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                      _createElementVNode("a", {
                        href: "javascript:;",
                        onClick: $event => {$setup.editProvider(p); $setup.showAdv = true}
                      }, "查看", 8 /* PROPS */, _hoisted_9),
                      _createTextVNode(" （" + _toDisplayString(Object.keys(p.headers || {}).length) + " 项", 1 /* TEXT */),
                      (p.user_agent)
                        ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                            _createTextVNode(" · UA")
                          ], 64 /* STABLE_FRAGMENT */))
                        : _createCommentVNode("v-if", true),
                      _cache[42] || (_cache[42] = _createTextVNode("） ", -1 /* CACHED */)),
                      ($setup.usedByStage(p.name).length)
                        ? (_openBlock(), _createElementBlock("div", _hoisted_10, " 已生效（" + _toDisplayString($setup.usedByStage(p.name).map((x) => x === 'transcription' ? '转写' : '评阅').join('、')) + "段） ", 1 /* TEXT */))
                        : (_openBlock(), _createElementBlock("div", _hoisted_11, "未分配段 → 不会用到"))
                    ], 64 /* STABLE_FRAGMENT */))
                  : (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                      _createTextVNode("—")
                    ], 64 /* STABLE_FRAGMENT */))
              ]),
              _createElementVNode("td", _hoisted_12, [
                _createElementVNode("a", {
                  href: "javascript:;",
                  onClick: $event => ($setup.editProvider(p))
                }, "编辑", 8 /* PROPS */, _hoisted_13),
                _cache[43] || (_cache[43] = _createTextVNode(" ｜", -1 /* CACHED */)),
                _createElementVNode("a", {
                  href: "javascript:;",
                  onClick: $event => ($setup.delProvider(p.name))
                }, "删除", 8 /* PROPS */, _hoisted_14)
              ])
            ]))
          }), 128 /* KEYED_FRAGMENT */))
        ])
      ]),
      _createElementVNode("div", _hoisted_15, [
        _createElementVNode("label", _hoisted_16, [
          _cache[45] || (_cache[45] = _createTextVNode("名称 ", -1 /* CACHED */)),
          _withDirectives(_createElementVNode("input", {
            "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => (($setup.pName) = $event)),
            placeholder: "Aliyun",
            style: {"width":"110px"}
          }, null, 512 /* NEED_PATCH */), [
            [_vModelText, $setup.pName]
          ])
        ]),
        _createElementVNode("label", _hoisted_17, [
          _cache[46] || (_cache[46] = _createTextVNode("base_url ", -1 /* CACHED */)),
          _withDirectives(_createElementVNode("input", {
            "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => (($setup.pBase) = $event)),
            placeholder: $setup.llmConfig.default_base_url || 'https://…/compatible-mode/v1',
            style: {"width":"330px"}
          }, null, 8 /* PROPS */, _hoisted_18), [
            [_vModelText, $setup.pBase]
          ])
        ]),
        _createElementVNode("label", _hoisted_19, [
          _cache[47] || (_cache[47] = _createTextVNode("api_key ", -1 /* CACHED */)),
          _withDirectives(_createElementVNode("input", {
            "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => (($setup.pKey) = $event)),
            type: "password",
            placeholder: "留空=不修改（只存掩码）",
            style: {"width":"200px"}
          }, null, 512 /* NEED_PATCH */), [
            [_vModelText, $setup.pKey]
          ])
        ]),
        _createElementVNode("label", _hoisted_20, [
          _withDirectives(_createElementVNode("input", {
            type: "checkbox",
            "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => (($setup.pBatch) = $event))
          }, null, 512 /* NEED_PATCH */), [
            [_vModelCheckbox, $setup.pBatch]
          ]),
          _cache[48] || (_cache[48] = _createTextVNode(" 支持 batch", -1 /* CACHED */))
        ])
      ]),
      _createCommentVNode(" D145：高级设置（在保存键**上方**——先设好再保存） "),
      _createElementVNode("details", {
        open: $setup.showAdv,
        style: {"margin":"8px 0 6px"},
        onToggle: _cache[8] || (_cache[8] = $event => ($setup.showAdv = ($event.target as HTMLDetailsElement).open))
      }, [
        _cache[56] || (_cache[56] = _createElementVNode("summary", {
          class: "hint",
          style: {"cursor":"pointer"}
        }, " ⚙️ 高级：请求头（只有 provider 明确要求时才需要设置） ", -1 /* CACHED */)),
        _createElementVNode("div", _hoisted_22, [
          _createElementVNode("label", _hoisted_23, [
            _withDirectives(_createElementVNode("input", {
              "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => (($setup.pSessionHdr) = $event)),
              type: "checkbox"
            }, null, 512 /* NEED_PATCH */), [
              [_vModelCheckbox, $setup.pSessionHdr]
            ]),
            _cache[49] || (_cache[49] = _createElementVNode("span", null, [
              _createElementVNode("b", null, "需要会话头"),
              _createElementVNode("span", { class: "hint" }, "（自动生成会话 id；如 opencode-go 的 /go 路由要求）")
            ], -1 /* CACHED */))
          ]),
          ($setup.pSessionHdr)
            ? (_openBlock(), _createElementBlock("label", _hoisted_24, [
                _cache[50] || (_cache[50] = _createTextVNode(" 头名 ", -1 /* CACHED */)),
                _withDirectives(_createElementVNode("input", {
                  "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => (($setup.pSessionHdrName) = $event)),
                  placeholder: "x-opencode-session",
                  style: {"width":"220px"}
                }, null, 512 /* NEED_PATCH */), [
                  [_vModelText, $setup.pSessionHdrName]
                ]),
                _cache[51] || (_cache[51] = _createElementVNode("span", { class: "hint" }, [
                  _createTextVNode("会话 id 由引擎自动生成并填入，"),
                  _createElementVNode("b", null, "无需你填写")
                ], -1 /* CACHED */))
              ]))
            : _createCommentVNode("v-if", true),
          _createElementVNode("label", _hoisted_25, [
            _cache[52] || (_cache[52] = _createTextVNode(" 其他自定义头（每行 name=value） ", -1 /* CACHED */)),
            _withDirectives(_createElementVNode("textarea", {
              "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => (($setup.pHdrText) = $event)),
              rows: "2",
              style: {"width":"420px","font-family":"monospace"},
              placeholder: "（留空 = 不发送任何自定义头）"
            }, null, 512 /* NEED_PATCH */), [
              [_vModelText, $setup.pHdrText]
            ])
          ]),
          _createElementVNode("label", _hoisted_26, [
            _cache[54] || (_cache[54] = _createTextVNode(" user-agent ", -1 /* CACHED */)),
            _withDirectives(_createElementVNode("input", {
              "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => (($setup.pUserAgent) = $event)),
              placeholder: `留空 = 使用默认值`,
              style: {"width":"260px"}
            }, null, 512 /* NEED_PATCH */), [
              [_vModelText, $setup.pUserAgent]
            ]),
            _createElementVNode("span", { class: "hint" }, [
              _cache[53] || (_cache[53] = _createTextVNode("默认：", -1 /* CACHED */)),
              _createElementVNode("code", null, _toDisplayString($setup.DEFAULT_UA))
            ])
          ]),
          _cache[55] || (_cache[55] = _createElementVNode("p", {
            class: "hint",
            style: {"margin":"4px 0 0"}
          }, [
            _createTextVNode(" 只允许 "),
            _createElementVNode("code", null, "x-*"),
            _createTextVNode(" 自定义头与 "),
            _createElementVNode("code", null, "user-agent"),
            _createTextVNode("； "),
            _createElementVNode("code", null, "Authorization"),
            _createTextVNode(" / "),
            _createElementVNode("code", null, "Host"),
            _createTextVNode(" / "),
            _createElementVNode("code", null, "Cookie"),
            _createTextVNode(" 等会被引擎拒绝。 ")
          ], -1 /* CACHED */))
        ])
      ], 40 /* PROPS, NEED_HYDRATION */, _hoisted_21),
      _createElementVNode("div", { style: {"margin-top":"8px","display":"flex","gap":"8px","align-items":"center"} }, [
        _createElementVNode("button", {
          class: "btn primary",
          onClick: $setup.saveProvider
        }, "保存 provider"),
        _createElementVNode("button", {
          class: "btn",
          onClick: $setup.resetProviderForm
        }, "清空表单")
      ]),
      _createCommentVNode(" 二次确认：请求头会随每次调用发送 "),
      ($setup.pendingProvider)
        ? (_openBlock(), _createElementBlock("div", _hoisted_27, [
            _createElementVNode("div", _hoisted_28, [
              _cache[58] || (_cache[58] = _createElementVNode("h3", { style: {"margin":"0 0 8px"} }, "确认保存这些请求头？", -1 /* CACHED */)),
              _createElementVNode("p", _hoisted_29, " 以下请求头将随**每次调用**发送到 provider「" + _toDisplayString($setup.pendingProvider.name) + "」 （" + _toDisplayString($setup.pendingProvider.base_url || '未填 base_url') + "）： ", 1 /* TEXT */),
              _createElementVNode("pre", _hoisted_30, _toDisplayString(Object.entries($setup.pendingProvider.headers)
          .map(([k, v]) => `${k}: ${v}`).join('\n') || '（无自定义头）'), 1 /* TEXT */),
              ($setup.pendingProvider.user_agent)
                ? (_openBlock(), _createElementBlock("p", _hoisted_31, [
                    _cache[57] || (_cache[57] = _createTextVNode(" user-agent：", -1 /* CACHED */)),
                    _createElementVNode("code", null, _toDisplayString($setup.pendingProvider.user_agent), 1 /* TEXT */)
                  ]))
                : _createCommentVNode("v-if", true),
              _createElementVNode("div", _hoisted_32, [
                _createElementVNode("button", {
                  class: "btn",
                  onClick: _cache[9] || (_cache[9] = $event => ($setup.pendingProvider = null))
                }, "取消"),
                _createElementVNode("button", {
                  class: "btn primary",
                  onClick: $setup.confirmSaveProvider
                }, "我确认保存")
              ])
            ])
          ]))
        : _createCommentVNode("v-if", true),
      _createElementVNode("div", _hoisted_33, [
        (_openBlock(), _createElementBlock(_Fragment, null, _renderList(['transcription', 'evaluation'], (s) => {
          return _createElementVNode("div", {
            key: s,
            style: {"display":"flex","gap":"8px","align-items":"center","margin-top":"4px","flex-wrap":"wrap"}
          }, [
            _createElementVNode("b", _hoisted_34, _toDisplayString(s === 'transcription' ? '转写段' : '评阅段'), 1 /* TEXT */),
            _withDirectives(_createElementVNode("select", {
              "onUpdate:modelValue": $event => (($setup.stProvider[s]) = $event),
              style: {"min-width":"150px"}
            }, [
              _cache[59] || (_cache[59] = _createElementVNode("option", { value: "" }, "（选择 provider）", -1 /* CACHED */)),
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(($setup.llmConfig.providers || []), (p) => {
                return (_openBlock(), _createElementBlock("option", {
                  key: p.name,
                  value: p.name
                }, _toDisplayString(p.name), 9 /* TEXT, PROPS */, _hoisted_36))
              }), 128 /* KEYED_FRAGMENT */))
            ], 8 /* PROPS */, _hoisted_35), [
              [_vModelSelect, $setup.stProvider[s]]
            ]),
            ($setup.modelsForStage(s).length && !$setup.stCustom[s])
              ? _withDirectives((_openBlock(), _createElementBlock("select", {
                  key: 0,
                  "onUpdate:modelValue": $event => (($setup.stModel[s]) = $event),
                  style: {"min-width":"180px"}
                }, [
                  _cache[60] || (_cache[60] = _createElementVNode("option", { value: "" }, "（默认）", -1 /* CACHED */)),
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.modelsForStage(s), (m) => {
                    return (_openBlock(), _createElementBlock("option", {
                      key: m,
                      value: m
                    }, _toDisplayString(m), 9 /* TEXT, PROPS */, _hoisted_38))
                  }), 128 /* KEYED_FRAGMENT */))
                ], 8 /* PROPS */, _hoisted_37)), [
                  [_vModelSelect, $setup.stModel[s]]
                ])
              : _withDirectives((_openBlock(), _createElementBlock("input", {
                  key: 1,
                  "onUpdate:modelValue": $event => (($setup.stModel[s]) = $event),
                  placeholder: "模型名（填写即记录）",
                  style: {"width":"200px"}
                }, null, 8 /* PROPS */, _hoisted_39)), [
                  [_vModelText, $setup.stModel[s]]
                ]),
            _createElementVNode("button", {
              class: "btn small",
              onClick: $event => ($setup.stCustom[s] = !$setup.stCustom[s]),
              title: $setup.modelsForStage(s).length ? '切换自定义/下拉' : '该 provider 暂无候选'
            }, _toDisplayString($setup.stCustom[s] ? '用下拉' : '自定义'), 9 /* TEXT, PROPS */, _hoisted_40),
            (s === 'evaluation')
              ? (_openBlock(), _createElementBlock("label", _hoisted_41, [
                  _withDirectives(_createElementVNode("input", {
                    type: "checkbox",
                    "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => (($setup.stBatch) = $event))
                  }, null, 512 /* NEED_PATCH */), [
                    [_vModelCheckbox, $setup.stBatch]
                  ]),
                  _cache[61] || (_cache[61] = _createTextVNode(" 走 batch", -1 /* CACHED */))
                ]))
              : _createCommentVNode("v-if", true),
            _createElementVNode("button", {
              class: "btn",
              onClick: $event => ($setup.saveStage(s as 'transcription' | 'evaluation'))
            }, "保存", 8 /* PROPS */, _hoisted_42)
          ])
        }), 64 /* STABLE_FRAGMENT */))
      ]),
      _cache[93] || (_cache[93] = _createElementVNode("h3", { style: {"margin-top":"14px"} }, "② 班级 ↔ 作业纸目录（class_map，按文件名建议）", -1 /* CACHED */)),
      ($setup.curWork)
        ? (_openBlock(), _createElementBlock("div", _hoisted_43, [
            _createElementVNode("span", _hoisted_44, _toDisplayString($setup.curWork.label), 1 /* TEXT */),
            _createCommentVNode(" D123：改为下拉选择真实班级目录，避免手输漏 `classes/` 前缀 "),
            _withDirectives(_createElementVNode("select", {
              "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => (($setup.classDir[`${$setup.curWork.courseId}:${$setup.curWork.classId}`]) = $event)),
              style: {"min-width":"230px"}
            }, [
              _cache[62] || (_cache[62] = _createElementVNode("option", { value: "" }, "（未关联）", -1 /* CACHED */)),
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.classDirOptions, (d) => {
                return (_openBlock(), _createElementBlock("option", {
                  key: d,
                  value: d
                }, _toDisplayString(d), 9 /* TEXT, PROPS */, _hoisted_45))
              }), 128 /* KEYED_FRAGMENT */)),
              ($setup.classDir[`${$setup.curWork.courseId}:${$setup.curWork.classId}`]
            && !$setup.classDirOptions.includes($setup.classDir[`${$setup.curWork.courseId}:${$setup.curWork.classId}`]))
                ? (_openBlock(), _createElementBlock("option", {
                    key: 0,
                    value: $setup.classDir[`${$setup.curWork.courseId}:${$setup.curWork.classId}`]
                  }, _toDisplayString($setup.classDir[`${$setup.curWork.courseId}:${$setup.curWork.classId}`]) + "（当前映射，目录可能不存在） ", 9 /* TEXT, PROPS */, _hoisted_46))
                : _createCommentVNode("v-if", true)
            ], 512 /* NEED_PATCH */), [
              [_vModelSelect, $setup.classDir[`${$setup.curWork.courseId}:${$setup.curWork.classId}`]]
            ]),
            _createElementVNode("button", {
              class: "btn",
              onClick: $setup.suggestDir
            }, "填当前映射"),
            _createElementVNode("button", {
              class: "btn",
              onClick: $setup.saveDir
            }, "保存映射")
          ]))
        : (_openBlock(), _createElementBlock("p", _hoisted_47, "先选作业（③ 的下拉）。")),
      _cache[94] || (_cache[94] = _createElementVNode("h3", { style: {"margin-top":"14px"} }, "③ 任务", -1 /* CACHED */)),
      _createElementVNode("div", _hoisted_48, [
        _withDirectives(_createElementVNode("select", {
          "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => (($setup.workKey) = $event)),
          style: {"min-width":"240px"},
          onChange: _cache[13] || (_cache[13] = $event => ($setup.loadStudents()))
        }, [
          _cache[63] || (_cache[63] = _createElementVNode("option", { value: "" }, "（选择已下载的作业）", -1 /* CACHED */)),
          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.works, (w) => {
            return (_openBlock(), _createElementBlock("option", {
              key: w.key,
              value: w.key
            }, _toDisplayString(w.label), 9 /* TEXT, PROPS */, _hoisted_49))
          }), 128 /* KEYED_FRAGMENT */))
        ], 544 /* NEED_HYDRATION, NEED_PATCH */), [
          [_vModelSelect, $setup.workKey]
        ]),
        _withDirectives(_createElementVNode("select", {
          "onUpdate:modelValue": _cache[14] || (_cache[14] = $event => (($setup.packId) = $event)),
          style: {"min-width":"220px"},
          onChange: _cache[15] || (_cache[15] = $event => ($setup.padId = ''))
        }, [
          _cache[64] || (_cache[64] = _createElementVNode("option", { value: "" }, "（选择作业包：含多张按 tag 的作业纸）", -1 /* CACHED */)),
          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.packStore.packs, (pk) => {
            return (_openBlock(), _createElementBlock("option", {
              key: pk.id,
              value: pk.id
            }, _toDisplayString(pk.id) + "（" + _toDisplayString((pk.pads ?? []).length) + " 张） ", 9 /* TEXT, PROPS */, _hoisted_50))
          }), 128 /* KEYED_FRAGMENT */))
        ], 544 /* NEED_HYDRATION, NEED_PATCH */), [
          [_vModelSelect, $setup.packId]
        ]),
        _cache[82] || (_cache[82] = _createElementVNode("span", {
          class: "hint",
          style: {"margin":"0"}
        }, "或单张作业纸：", -1 /* CACHED */)),
        _withDirectives(_createElementVNode("select", {
          "onUpdate:modelValue": _cache[16] || (_cache[16] = $event => (($setup.padId) = $event)),
          style: {"min-width":"200px"},
          onChange: _cache[17] || (_cache[17] = $event => ($setup.packId = ''))
        }, [
          _cache[65] || (_cache[65] = _createElementVNode("option", { value: "" }, "（单张作业纸）", -1 /* CACHED */)),
          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.pads, (p) => {
            return (_openBlock(), _createElementBlock("option", {
              key: p.id,
              value: p.id
            }, _toDisplayString(p.id) + _toDisplayString(p.tag ? ' · tag ' + p.tag : ''), 9 /* TEXT, PROPS */, _hoisted_51))
          }), 128 /* KEYED_FRAGMENT */))
        ], 544 /* NEED_HYDRATION, NEED_PATCH */), [
          [_vModelSelect, $setup.padId]
        ]),
        _createElementVNode("label", _hoisted_52, [
          _cache[67] || (_cache[67] = _createTextVNode("模式 ", -1 /* CACHED */)),
          _withDirectives(_createElementVNode("select", {
            "onUpdate:modelValue": _cache[18] || (_cache[18] = $event => (($setup.mode) = $event))
          }, [...(_cache[66] || (_cache[66] = [
            _createElementVNode("option", { value: "optimized" }, "优化（给题目/答案）", -1 /* CACHED */),
            _createElementVNode("option", { value: "brute" }, "brute-force（先自己作答再比对）", -1 /* CACHED */)
          ]))], 512 /* NEED_PATCH */), [
            [_vModelSelect, $setup.mode]
          ])
        ]),
        _createElementVNode("label", _hoisted_53, [
          _cache[68] || (_cache[68] = _createTextVNode(" tags ", -1 /* CACHED */)),
          _withDirectives(_createElementVNode("select", {
            "onUpdate:modelValue": _cache[19] || (_cache[19] = $event => (($setup.tagsSel) = $event)),
            multiple: "",
            style: {"min-width":"150px","min-height":"56px"}
          }, [
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.tagOptions, (t) => {
              return (_openBlock(), _createElementBlock("option", {
                key: t,
                value: t
              }, _toDisplayString(t), 9 /* TEXT, PROPS */, _hoisted_54))
            }), 128 /* KEYED_FRAGMENT */))
          ], 512 /* NEED_PATCH */), [
            [_vModelSelect, $setup.tagsSel]
          ]),
          _createElementVNode("button", {
            class: "btn small",
            type: "button",
            onClick: _cache[20] || (_cache[20] = $event => ($setup.tagsSel = [...$setup.tagOptions]))
          }, "全选"),
          _createElementVNode("button", {
            class: "btn small",
            type: "button",
            disabled: !$setup.tagsSel.length,
            onClick: _cache[21] || (_cache[21] = $event => ($setup.tagsSel = []))
          }, "清空", 8 /* PROPS */, _hoisted_55)
        ]),
        _createElementVNode("label", _hoisted_56, [
          _cache[69] || (_cache[69] = _createTextVNode("限前 ", -1 /* CACHED */)),
          _withDirectives(_createElementVNode("input", {
            "onUpdate:modelValue": _cache[22] || (_cache[22] = $event => (($setup.limit) = $event)),
            type: "number",
            min: "0",
            style: {"width":"70px"}
          }, null, 512 /* NEED_PATCH */), [
            [
              _vModelText,
              $setup.limit,
              void 0,
              { number: true }
            ]
          ]),
          _cache[70] || (_cache[70] = _createTextVNode(" 名", -1 /* CACHED */))
        ]),
        _createCommentVNode(" D116-C：tags 为空时给出可操作提示（不再静默空着） "),
        ($setup.tagHint)
          ? (_openBlock(), _createElementBlock("p", _hoisted_57, " ⚠ " + _toDisplayString($setup.tagHint), 1 /* TEXT */))
          : (!$setup.tagsSel.length)
            ? (_openBlock(), _createElementBlock("p", _hoisted_58, [...(_cache[71] || (_cache[71] = [
                _createTextVNode(" 未选 tag = ", -1 /* CACHED */),
                _createElementVNode("b", null, "批阅全部学生", -1 /* CACHED */),
                _createTextVNode("；但只有打了 tag 的学生才能关联到对应作业纸的题目。 ", -1 /* CACHED */)
              ]))]))
            : (_openBlock(), _createElementBlock("p", _hoisted_59, [
                _cache[72] || (_cache[72] = _createTextVNode(" 将只批阅 tag ∈ ", -1 /* CACHED */)),
                _createElementVNode("code", null, _toDisplayString($setup.tagsSel.join('、')), 1 /* TEXT */),
                _cache[73] || (_cache[73] = _createTextVNode(" 的学生。 ", -1 /* CACHED */))
              ])),
        _createCommentVNode(" D106：转录设置（图片压缩 / SVG 重绘） "),
        _createElementVNode("div", _hoisted_60, [
          _cache[77] || (_cache[77] = _createElementVNode("div", { style: {"font-weight":"600","margin-bottom":"4px","font-size":"13px"} }, "转录设置", -1 /* CACHED */)),
          _createElementVNode("label", _hoisted_61, [
            _cache[75] || (_cache[75] = _createTextVNode(" 图片发送方式： ", -1 /* CACHED */)),
            _withDirectives(_createElementVNode("select", {
              "onUpdate:modelValue": _cache[23] || (_cache[23] = $event => (($setup.imageMode) = $event)),
              style: {"min-width":"190px"}
            }, [...(_cache[74] || (_cache[74] = [
              _createElementVNode("option", { value: "auto" }, "自动压缩（推荐，节省 token/时间）", -1 /* CACHED */),
              _createElementVNode("option", { value: "original" }, "原图直发（不计流量，用于对比转录效果）", -1 /* CACHED */)
            ]))], 512 /* NEED_PATCH */), [
              [_vModelSelect, $setup.imageMode]
            ])
          ]),
          _cache[78] || (_cache[78] = _createElementVNode("p", {
            class: "hint",
            style: {"margin":"2px 0 6px"}
          }, [
            _createTextVNode(" 自动压缩按体积分档：≤2MB 且长边≤2000px 原样发送；更大时缩到长边 2000/1600px 并转 JPEG。 "),
            _createElementVNode("b", null, "原始图片始终保留在本地"),
            _createTextVNode("，压缩只作用于送去模型的副本。 ")
          ], -1 /* CACHED */)),
          _createElementVNode("label", _hoisted_62, [
            _withDirectives(_createElementVNode("input", {
              type: "checkbox",
              "onUpdate:modelValue": _cache[24] || (_cache[24] = $event => (($setup.svgRedraw) = $event))
            }, null, 512 /* NEED_PATCH */), [
              [_vModelCheckbox, $setup.svgRedraw]
            ]),
            _cache[76] || (_cache[76] = _createTextVNode(" 让 AI 用 SVG 重绘学生手绘图（默认关） ", -1 /* CACHED */))
          ]),
          _cache[79] || (_cache[79] = _createElementVNode("p", {
            class: "hint",
            style: {"margin":"2px 0 0"}
          }, [
            _createElementVNode("b", null, "SVG 重绘含义"),
            _createTextVNode("：转录时让 AI 把学生画在纸上的示意图/受力图/电路图， 用内联 "),
            _createElementVNode("code", null, "<svg>"),
            _createTextVNode("（黑白线稿、最多 20 个图元）重新画出来， 这样批阅报告里能看到\"矢量图\"而不是文字描述。 仅建议几何/受力/电路类题目开启：会增加耗时与输出 token，且 AI 可能画得不准确，请人工核对。 ")
          ], -1 /* CACHED */))
        ]),
        _createCommentVNode(" D125：分步批阅 —— 转录最慢最贵，先单独跑通再往下 "),
        _createElementVNode("button", {
          class: "btn small",
          disabled: $setup.busy,
          title: "按段测试 LLM 配置（能立刻发现 base_url/key/model 错配）",
          onClick: $setup.testLlm
        }, "🔍 测试配置", 8 /* PROPS */, _hoisted_63),
        _createElementVNode("button", {
          class: "btn small",
          disabled: $setup.busy,
          title: "只跑转录（发送作答图 → 得到文字转录）",
          onClick: _cache[25] || (_cache[25] = $event => ($setup.startAi(['transcribe'])))
        }, "① 仅转录", 8 /* PROPS */, _hoisted_64),
        _createElementVNode("button", {
          class: "btn small",
          disabled: $setup.busy,
          title: "只跑评阅（要求已有转录产物）",
          onClick: _cache[26] || (_cache[26] = $event => ($setup.startAi(['evaluate'])))
        }, "② 批阅", 8 /* PROPS */, _hoisted_65),
        _createElementVNode("button", {
          class: "btn",
          disabled: $setup.busy,
          title: "转写 + 批阅：两件事一起做（不含报告；审核后再用下方「📄 一键生成批阅报告」）",
          onClick: _cache[27] || (_cache[27] = $event => ($setup.startAi(['transcribe', 'evaluate'])))
        }, "▶ ③ 转写+批阅", 8 /* PROPS */, _hoisted_66),
        _createElementVNode("label", _hoisted_67, [
          _withDirectives(_createElementVNode("input", {
            type: "checkbox",
            "onUpdate:modelValue": _cache[28] || (_cache[28] = $event => (($setup.forceRedo) = $event))
          }, null, 512 /* NEED_PATCH */), [
            [_vModelCheckbox, $setup.forceRedo]
          ]),
          _cache[80] || (_cache[80] = _createTextVNode(" ☑ 强制重做（覆盖已有结果，会重新花额度） ", -1 /* CACHED */))
        ]),
        _createElementVNode("label", _hoisted_68, [
          _withDirectives(_createElementVNode("input", {
            type: "checkbox",
            "onUpdate:modelValue": _cache[29] || (_cache[29] = $event => (($setup.allowPartial) = $event))
          }, null, 512 /* NEED_PATCH */), [
            [_vModelCheckbox, $setup.allowPartial]
          ]),
          _cache[81] || (_cache[81] = _createTextVNode(" 有学生转录失败时仍继续（默认中止） ", -1 /* CACHED */))
        ])
      ]),
      ($setup.progress)
        ? (_openBlock(), _createElementBlock("p", _hoisted_69, _toDisplayString($setup.progress), 1 /* TEXT */))
        : _createCommentVNode("v-if", true),
      _cache[95] || (_cache[95] = _createElementVNode("h3", { style: {"margin-top":"14px"} }, "④ 逐生审核（左右两栏弹窗）", -1 /* CACHED */)),
      _cache[96] || (_cache[96] = _createElementVNode("p", {
        class: "hint",
        style: {"margin":"0 0 6px"}
      }, " 点「审核」打开弹窗：左=作答图；右上=AI 批语（可另存修订版）；右下=人工批阅（可选，AI 原文不被覆盖）。 保存后到 ⑤ 一键生成报告（按每生模式自动出 5 种版式之一）。 ", -1 /* CACHED */)),
      _createCommentVNode(" D127-FIX：固定高度 + 表头粘性 + 滚轮滚动（与「班级与标签」名单表同口径），\n         避免几十人时整页被拉长、需要滚到页底才能看到下面的按钮。 "),
      _createCommentVNode(" D130-FIX2：「读取」按钮。刷新后作业包/作业纸下拉是空的，\n         状态与 tag 依赖引擎反查批阅目录；给教师一个明确的\"重新读取\"入口，\n         并显示这次实际读的是哪个批阅目录（否则空状态无从排查）。 "),
      ($setup.curWork || $setup.students.length)
        ? (_openBlock(), _createElementBlock("div", _hoisted_70, [
            _createElementVNode("button", {
              class: "btn small",
              type: "button",
              disabled: $setup.studentsLoading,
              onClick: _cache[30] || (_cache[30] = $event => ($setup.loadStudents()))
            }, " 🔄 读取状态 ", 8 /* PROPS */, _hoisted_71),
            _createElementVNode("span", _hoisted_72, [
              ($setup.studentsLoading)
                ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                    _createTextVNode("正在读取…")
                  ], 64 /* STABLE_FRAGMENT */))
                : (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                    _createTextVNode(" 已读取 " + _toDisplayString($setup.students.length) + " 名学生 ", 1 /* TEXT */),
                    ($setup.resolvedScope)
                      ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                          _cache[83] || (_cache[83] = _createTextVNode("（批阅目录：", -1 /* CACHED */)),
                          _createElementVNode("code", null, _toDisplayString($setup.resolvedScope), 1 /* TEXT */),
                          _cache[84] || (_cache[84] = _createTextVNode("）", -1 /* CACHED */))
                        ], 64 /* STABLE_FRAGMENT */))
                      : ($setup.students.length)
                        ? (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                            _createTextVNode("（未指定作业包/作业纸）")
                          ], 64 /* STABLE_FRAGMENT */))
                        : _createCommentVNode("v-if", true)
                  ], 64 /* STABLE_FRAGMENT */))
            ]),
            (!$setup.packId && !$setup.padId && $setup.students.length)
              ? (_openBlock(), _createElementBlock("span", _hoisted_73, [...(_cache[85] || (_cache[85] = [
                  _createTextVNode(" · 未选作业包/作业纸：tag 与 AI 状态按", -1 /* CACHED */),
                  _createElementVNode("b", null, "引擎自动识别的批阅目录", -1 /* CACHED */),
                  _createTextVNode("显示； 如需指定具体批次，请在 ③ 区选择。 ", -1 /* CACHED */)
                ]))]))
              : _createCommentVNode("v-if", true)
          ]))
        : _createCommentVNode("v-if", true),
      ($setup.students.length)
        ? (_openBlock(), _createElementBlock("div", _hoisted_74, [
            _createElementVNode("table", _hoisted_75, [
              _cache[87] || (_cache[87] = _createElementVNode("thead", null, [
                _createElementVNode("tr", null, [
                  _createElementVNode("th", { style: {"text-align":"left"} }, "学生"),
                  _createElementVNode("th", null, "tag"),
                  _createElementVNode("th", null, "AI 状态"),
                  _createElementVNode("th", null, "AI 分"),
                  _createElementVNode("th", null, "人工"),
                  _createElementVNode("th", null, "报告模式"),
                  _createElementVNode("th", null, "操作")
                ])
              ], -1 /* CACHED */)),
              _createElementVNode("tbody", null, [
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.students, (s, i) => {
                  return (_openBlock(), _createElementBlock("tr", {
                    key: s.key
                  }, [
                    _createElementVNode("td", null, _toDisplayString(s.name), 1 /* TEXT */),
                    _createElementVNode("td", {
                      class: "c",
                      title: $setup.tagMark(s).why
                    }, [
                      _createElementVNode("span", {
                        style: _normalizeStyle({ color: $setup.tagMark(s).color })
                      }, _toDisplayString($setup.tagMark(s).text || '—'), 5 /* TEXT, STYLE */)
                    ], 8 /* PROPS */, _hoisted_76),
                    _createElementVNode("td", _hoisted_77, [
                      _createElementVNode("b", {
                        style: _normalizeStyle({ color: $setup.aiState(s).color })
                      }, _toDisplayString($setup.aiState(s).label), 5 /* TEXT, STYLE */),
                      ($setup.draftOf(s).ai?.at)
                        ? (_openBlock(), _createElementBlock("div", _hoisted_78, _toDisplayString($setup.draftOf(s).ai.at), 1 /* TEXT */))
                        : _createCommentVNode("v-if", true)
                    ]),
                    _createElementVNode("td", _hoisted_79, _toDisplayString($setup.draftOf(s).ai?.score ?? $setup.draftOf(s).score ?? '—'), 1 /* TEXT */),
                    _createElementVNode("td", _hoisted_80, _toDisplayString($setup.draftOf(s).human?.used ? ($setup.draftOf(s).human.score ?? '✓') : '—'), 1 /* TEXT */),
                    _createElementVNode("td", _hoisted_81, _toDisplayString($setup.reportMode(s)), 1 /* TEXT */),
                    _createElementVNode("td", _hoisted_82, [
                      _createElementVNode("button", {
                        class: "btn small",
                        disabled: $setup.rowBusy !== '' || !$setup.curWork,
                        title: $setup.curWork ? '只转写这一名学生' : '请先在 ③ 区选择作业',
                        onClick: $event => ($setup.runOne(s, 'transcribe'))
                      }, "转写", 8 /* PROPS */, _hoisted_83),
                      _createElementVNode("button", {
                        class: "btn small",
                        disabled: $setup.rowBusy !== '' || !$setup.curWork,
                        title: $setup.curWork ? '用已有转写评阅这一名学生' : '请先在 ③ 区选择作业',
                        onClick: $event => ($setup.runOne(s, 'evaluate'))
                      }, "批阅", 8 /* PROPS */, _hoisted_84),
                      _createElementVNode("button", {
                        class: "btn small",
                        disabled: $setup.rowBusy !== '' || !$setup.curWork,
                        title: $setup.curWork ? '转写+评阅这一名学生' : '请先在 ③ 区选择作业',
                        onClick: $event => ($setup.runOne(s, 'full'))
                      }, _toDisplayString($setup.rowBusy === s.name ? '…' : '完整'), 9 /* TEXT, PROPS */, _hoisted_85),
                      _cache[86] || (_cache[86] = _createTextVNode(" ｜", -1 /* CACHED */)),
                      _createElementVNode("button", {
                        class: "btn small",
                        onClick: $event => ($setup.onReviewOpen(i))
                      }, "审核", 8 /* PROPS */, _hoisted_86),
                      ($setup.rowMsg[s.name])
                        ? (_openBlock(), _createElementBlock("div", _hoisted_87, _toDisplayString($setup.rowMsg[s.name]), 1 /* TEXT */))
                        : _createCommentVNode("v-if", true)
                    ])
                  ]))
                }), 128 /* KEYED_FRAGMENT */))
              ])
            ])
          ]))
        : (_openBlock(), _createElementBlock("p", _hoisted_88, [
            (!$setup.curWork)
              ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                  _createTextVNode("未选择作业：先在 ③ 区选「作业」。")
                ], 64 /* STABLE_FRAGMENT */))
              : ($setup.studentsLoading)
                ? (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                    _createTextVNode("正在读取学生清单…")
                  ], 64 /* STABLE_FRAGMENT */))
                : (_openBlock(), _createElementBlock(_Fragment, { key: 2 }, [
                    _cache[88] || (_cache[88] = _createTextVNode("该作业暂无学生清单（引擎可能离线，或该作业还没在「作业预览-学习通」下载作答）。 ", -1 /* CACHED */)),
                    _createElementVNode("button", {
                      class: "btn small",
                      type: "button",
                      style: {"margin-left":"6px"},
                      onClick: _cache[31] || (_cache[31] = $event => ($setup.loadStudents()))
                    }, "重新读取")
                  ], 64 /* STABLE_FRAGMENT */))
          ])),
      _cache[97] || (_cache[97] = _createElementVNode("h3", { style: {"margin-top":"14px"} }, "⑤ 报告 / ⑥ 上传全部", -1 /* CACHED */)),
      _createElementVNode("div", _hoisted_89, [
        _cache[89] || (_cache[89] = _createElementVNode("span", {
          class: "hint",
          style: {"margin":"0"}
        }, " 报告类型**自动**由逐生审核决定（AI批阅报告 / 人工批阅报告 / 人工在前+【附件】AI / …（人工修订）） ", -1 /* CACHED */)),
        _createElementVNode("button", {
          class: "btn",
          disabled: $setup.busy,
          onClick: $setup.renderReports
        }, "📄 一键生成批阅报告", 8 /* PROPS */, _hoisted_90),
        _cache[90] || (_cache[90] = _createElementVNode("span", { style: {"flex":"1"} }, null, -1 /* CACHED */)),
        _createElementVNode("button", {
          class: "btn",
          disabled: $setup.busy,
          onClick: _cache[32] || (_cache[32] = $event => ($setup.uploadAll(false)))
        }, "⬆⬆ 上传全部批阅（含打分）", 8 /* PROPS */, _hoisted_91),
        _createElementVNode("button", {
          class: "btn",
          disabled: $setup.busy,
          onClick: _cache[33] || (_cache[33] = $event => ($setup.uploadAll(true)))
        }, "⬆⬆ 强制覆盖上传全部", 8 /* PROPS */, _hoisted_92)
      ]),
      _cache[98] || (_cache[98] = _createElementVNode("p", {
        class: "hint",
        style: {"margin-top":"6px"}
      }, " 完整逐生预览（作答图 + 两栏批语 + 旋转/上下位）仍在「作业预览-学习通 → 批阅图片 → 逐生预览」。 ", -1 /* CACHED */)),
      _createCommentVNode(" D130-T9：评阅规则卡（教师可见/可改评分口径；此前完全硬编码） "),
      _createVNode($setup["GradingRulesCard"], {
        "engine-addr": $setup.props.engineAddr,
        token: $setup.props.token,
        onNotify: _cache[34] || (_cache[34] = (m) => { $setup.progress = m })
      }, null, 8 /* PROPS */, ["engine-addr", "token"]),
      _createCommentVNode(" D153：教师总结报告 + 跨作业趋势已搬到「题库AI+」选项卡（支持多选班级/作业包/tag） "),
      _cache[99] || (_cache[99] = _createElementVNode("p", {
        class: "hint",
        style: {"margin-top":"12px"}
      }, [
        _createTextVNode(" 📊 教师总结报告与知识点趋势已移至顶部 "),
        _createElementVNode("b", null, "「题库AI+」"),
        _createTextVNode(" 选项卡 —— 那里可以"),
        _createElementVNode("b", null, "多选班级 / 作业包 / tag"),
        _createTextVNode("，看更宏观的情况。 ")
      ], -1 /* CACHED */)),
      _createCommentVNode(" D140：Atopia 已独立为顶层选项卡，这里只留指路提示（避免双入口） "),
      _cache[100] || (_cache[100] = _createElementVNode("p", {
        class: "hint",
        style: {"margin-top":"12px"}
      }, [
        _createTextVNode(" 🤖 想让 AI 用本项目工具（多轮对话 / 读题库 / 抽知识点 / 写回）？ 请到顶部 "),
        _createElementVNode("b", null, "Atopia"),
        _createTextVNode(" 选项卡 —— 每次调用都会经过安全 Gate。 ")
      ], -1 /* CACHED */))
    ]),
    _createCommentVNode(" D152：⑦ 区已整体搬到「题库AI+」选项卡（避免双入口） "),
    _cache[101] || (_cache[101] = _createElementVNode("h3", { style: {"margin-top":"14px"} }, "⑦ 题库 AI 作答", -1 /* CACHED */)),
    _cache[102] || (_cache[102] = _createElementVNode("p", { class: "hint" }, [
      _createTextVNode(" 🤖 题库 AI 作答（参考解答 / 评阅要点 / 知识点标注）已移至顶部 "),
      _createElementVNode("b", null, "「题库AI+」"),
      _createTextVNode(" 选项卡 —— 那里能力更全（题号多选 / 模型 / 模板 / 一次性完成三件事）。 ")
    ], -1 /* CACHED */)),
    ($setup.reviewOpen)
      ? (_openBlock(), _createBlock($setup["StudentReviewModal"], {
          key: 0,
          ref: "reviewModal",
          "engine-addr": $setup.props.engineAddr,
          token: $setup.props.token,
          "class-id": $setup.curWork?.classId || '',
          "work-id": $setup.curWork?.workId || '',
          "task-id": $setup.padId || $setup.packId,
          "class-dir": $setup.curWorkDir,
          students: $setup.students,
          drafts: $setup.drafts,
          "start-index": $setup.reviewIndex,
          onClose: _cache[35] || (_cache[35] = $event => ($setup.reviewOpen = false)),
          onSaved: $setup.loadStudents,
          onNotify: _cache[36] || (_cache[36] = (m) => { $setup.progress = String(m) })
        }, null, 8 /* PROPS */, ["engine-addr", "token", "class-id", "work-id", "task-id", "class-dir", "students", "drafts", "start-index"]))
      : _createCommentVNode("v-if", true),
    _createVNode($setup["PlaygroundPanel"], {
      "engine-addr": $setup.props.engineAddr,
      token: $setup.props.token
    }, null, 8 /* PROPS */, ["engine-addr", "token"])
  ], 64 /* STABLE_FRAGMENT */))
}
__sfc_main.render = render
export default __sfc_main

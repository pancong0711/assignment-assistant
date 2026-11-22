<script setup lang="ts">
/** D86 §6 / D88 §4：AI 辅助批阅面板（提炼自 XxetongView 临时面板）。
 *  六区：① LLM 设置（provider + 两段式）② 班级↔作业纸目录映射 ③ 任务（AI 批阅）
 *        ④ 逐生审核（本地草稿：改分/批语/保存/演练/上传）⑤ 一键生成批阅报告 ⑥ 一键上传全部
 *  说明：完整"逐生预览（作答图+批语两栏）"仍在「作业预览-学习通 → 批阅图片 → 逐生预览」，
 *  与本面板的"报告风格审核"并存（用户拍板的两种风格）。
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useTaskpadStore } from '../stores/taskpad'
import {
  extractJobError, fetchLlmConfig, fetchXxtClassMap, fetchXxtGradeDrafts, fetchXxtLoginJob,
  fetchXxtReviewIndex, fetchXxtReviewStudents, postLlmProvider, postXxtClassMap,
  startXxtGradeAi, startXxtGradeUpload, renderReportsFromDrafts, testLlmStages,
  fetchXxtUploadPreview, fetchXxtReportVersions, fetchReportProgress,
  cleanupXxtReports, compactXxtReportVersions,
  applyTagAudit, fetchTagAudit, fetchTagAuditHistory, runTagAudit, undoTagAudit,
  undoStudentTagApi,
} from '../lib/engineClient'

import { usePackStore } from '../stores/packs'
import { useRosterStore } from '../stores/roster'

const props = defineProps<{ engineAddr: string; token?: string }>()
const taskpadStore = useTaskpadStore()
import PlaygroundPanel from './PlaygroundPanel.vue'
import StudentReviewModal from './StudentReviewModal.vue'
import GradingRulesCard from './GradingRulesCard.vue'
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
/* D193：上传前对照表（只读）——未批阅/一致/冲突 三态，教师确认后才覆盖。 */
interface UploadPreviewRow {
  student: string; localScore?: number | null; localCommentLength?: number
  reportVersion?: string; reportTag?: string
  platformStatus?: string; platformScore?: number | null
  platformCommentLength?: number | null
  decision?: string; reason?: string; needsConfirm?: boolean
  /* D196/D200：平台是否已提交 + 上传就绪分类（ready/no-report/no-draft/not-submitted）。 */
  submitted?: boolean; readyState?: string; readyReason?: string
  /* D200：报告图 / 批语文本 / 分数 三要素（决定上传什么）。 */
  hasImage?: boolean; hasComment?: boolean; hasScore?: boolean
  imageCount?: number; uploadMode?: 'report-only' | 'text'
  /* D211：平台分数读取状态 */
  platformScoreUnknown?: boolean; platformReadError?: string
}
const previewOpen = ref(false)
const previewBusy = ref(false)
const previewRows = ref<UploadPreviewRow[]>([])
const previewSummary = ref<Record<string, number>>({})
const previewCheckedPlatform = ref(false)
/* D210：平台状态缓存信息（命中缓存时秒开，点“重新读取平台状态”才刷新）。 */
const previewCache = ref<{ hit?: boolean; ageSec?: number; maxAgeSec?: number
  fetchedAt?: string; stale?: boolean; hint?: string } | null>(null)
/* D196：上传就绪分类（只传已提交且批语齐全）；逐生上传进度。 */
const previewReadiness = ref<{ ready?: string[]; noReport?: string[]; noComment?: string[]
  emptyComment?: string[]; noDraft?: string[]; notSubmitted?: string[]
  summary?: Record<string, number>; hint?: string } | null>(null)
/* D200：只上传“报告图 + 分数”（不重复上传原始批语文本）——教师的标准工作流。 */
const uploadReportOnly = ref(true)
const oneUploadBusy = ref('')
const oneUploadResult = ref<Record<string, string>>({})
/* D197：清理结果（明确显示“完成/试运行”，并展示索引同步清理条数）。 */
const cleanupResult = ref<{ ok?: boolean; dryRun?: boolean; error?: string
  count?: number; indexRemoved?: number; indexAfter?: number; indexBefore?: number
  removed?: { name?: string; reason?: string }[]; kept?: string[]
  stats?: { totalRecords?: number; studentCount?: number; avgVersions?: number
    historyRecords?: number; orphanRecords?: number }
  hint?: string } | null>(null)
/* D193：报告版本历史（只读；便于与上传清单/报告页脚对照）。 */
const versionsOpen = ref(false)
const versionsBusy = ref(false)
const versionsRows = ref<{ student?: string; version?: string; tag?: string; at?: string
  kind?: string; score?: number | null; files?: string[]; reason?: string }[]>([])
/* D199：以逐生审核名单为基准的报告状态（含“未生成”）。 */
const versionRoster = ref<{ student?: string; versionCount?: number; hasReport?: boolean
  version?: string; tag?: string; at?: string; kind?: string; score?: number | null }[]>([])
/** D199：版本表统一为“逐生”形状（有名单用名单，没名单才回退索引记录）。 */
const versionTableRows = computed(() => {
  if (versionRoster.value.length) return versionRoster.value
  return versionsRows.value.map((v) => ({
    student: v.student, hasReport: true, version: v.version, tag: v.tag,
    at: v.at, kind: v.kind, score: v.score, versionCount: 1,
  }))
})
const versionMeta = ref<{ rosterCount?: number; reportedCount?: number
  missingReport?: string[]; unmatched?: string[]; totalInIndex?: number
  historyRecords?: number; studentCount?: number; avgVersions?: number } | null>(null)
/* D194：上次报告生成进度（中断后显示“已生成 X/Y”，可续做/只补失败学生）。 */
/* D195：生成前范围核对（谁会有报告 / 平台有行但无草稿 / 重复键）。 */
const scopeCheck = ref<{ studentCount?: number; draftCount?: number
  missingDraft?: string[]; notInList?: string[]
  duplicateKeys?: Record<string, string[]>; hint?: string } | null>(null)
const reportProgress = ref<{ exists?: boolean; state?: string; total?: number
  done?: string[]; failed?: { student?: string; error?: string }[]
  skipped?: { student?: string }[]; finishedAt?: string; updatedAt?: string } | null>(null)
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

/* D148：**逐生补批** —— 只对一名学生跑 转写 / 批阅 / 转写+批阅（D174 与上方三键统一语义）。
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
  // D171-T1 / D174：与上方三键同口径 ——「批阅」= 出批语+打分，「③」= 转写+批阅。
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

const students = ref<Array<{ name: string; key: string; studentId?: string; tag?: string; images?: string[] }>>([])
/** D117：学生清单加载中（供逐生审核空态提示） */
const studentsLoading = ref(false)
const drafts = ref<Record<string, any>>({})
/** D171-T8: name -> tag, from roster/snapshot; used to tell "new" from "unassigned". */
const rosterTagByName = ref<Record<string, string> | null>(null)

/* ---------------- D172：tag 审计（纯 Python，不调模型） ----------------
 * 「审计 tag」= 从**学生转写里的题干**反推他实际做的是包内哪张作业纸 → 实际 tag；
 * 与 roster 关联的 tag 比对，不一致的行**高亮**，教师确认后可逐人/批量应用。
 * 审计是**独立工序**：不阻断批阅、不自动重批、不改任何东西（除教师点「应用」）。 */
const auditBusy = ref(false)
const auditMsg = ref('')
const auditRow = ref<Record<string, any>>({})   // name -> audit row
const auditDetail = ref<any>(null)               // 当前打开明细的学生
const auditChecked = ref<Record<string, boolean>>({})  // 批量应用勾选
const auditMeta = ref<{ generatedAt?: string; engine?: string; rosterTagSource?: string
  skipped?: Array<{ name: string; reason: string }> } | null>(null)

/** 审计候选集 = **当前作业包内**的作业纸（教师 D2：不跨包）。
 *
 * ⚠️ D172 修复：**必须传 taskpad 原样**，不能自己拼 `questions`。
 * `taskpad.items[]` 只有 `{kb, chap, ids, tag}`，**没有题干**——题干在题库里，
 * 由引擎用 `paper.task.resolve_items_with_ids` 从 `kb/` 解析（此前前端误把
 * taskpad 当题目传，导致全班审计结果恒为 unknown）。 */
function auditTaskpads() {
  const list = packId.value ? packPads.value : pads.value.filter((p) => p.id === padId.value)
  const out: any[] = []
  for (const p of list) {
    let tp: any = null
    try { tp = JSON.parse((p as any).json || '') } catch { tp = null }
    if (!tp || !Array.isArray(tp.items) || !tp.items.length) continue
    out.push({ ...tp, id: String((p as any).id || tp.id || '') })
  }
  return out
}

async function loadAudit() {
  const w = curWork.value
  // D173：与 loadStudents 同口径——未选作业包时用引擎反查出的批阅目录，
  // 否则刷新页面后（packId 为空）审计列会一直是空的。
  const pid = packId.value || padId.value || resolvedScope.value
  if (!w || !pid || !curWorkDir.value) { auditRow.value = {}; return }
  try {
    const r = await fetchTagAudit(props.engineAddr, props.token,
                                  { classDir: curWorkDir.value, packId: pid })
    if (r?.missing || !r?.ok) { auditRow.value = {}; auditMeta.value = null; return }
    const m: Record<string, any> = {}
    for (const s of r.students || []) m[s.name] = s
    auditRow.value = m
    auditMeta.value = { generatedAt: r.generatedAt, engine: r.engine,
                        rosterTagSource: r.rosterTagSource,
                        skipped: r.skippedNotTranscribed }
  } catch { auditRow.value = {} }
}

async function runAuditNow() {
  const w = curWork.value
  const pid = packId.value || padId.value
  if (!w) { auditMsg.value = '⚠ 请先在 ③ 区选择作业（作业包/作业纸）'; return }
  if (!curWorkDir.value) { auditMsg.value = '⚠ 请先关联本地班级目录'; return }
  const tps = auditTaskpads()
  if (!tps.length) { auditMsg.value = '⚠ 当前作业包没有可用作业纸（无法比对）'; return }
  if (!confirm(`将审计「${pid}」内的作答与作业纸题目比对（纯本地计算，**不调用模型**）。\n\n只比对当前作业包内的 ${tps.length} 张作业纸；未转写的学生会被跳过。继续？`)) return
  auditBusy.value = true; auditMsg.value = '⏳ 审计中…'
  try {
    const r = await runTagAudit(props.engineAddr, props.token,
                                { classDir: curWorkDir.value, packId: pid, taskpads: tps })
    if (r?.ok === false) { auditMsg.value = `❌ 审计失败：${r.error || '未知错误'}`; return }
    await loadAudit()
    const sum = r.summary || { match: 0, mismatch: 0, unknown: 0 }
    const skip = (r.skippedNotTranscribed || []).length
    auditMsg.value = `✅ 审计完成：一致 ${sum.match} · 不一致 ${sum.mismatch} · 无法判定 ${sum.unknown}`
      + (skip ? ` · 未转写跳过 ${skip}` : '')
      + ((r as any).hint ? ` —— ${(r as any).hint}` : '')
  } catch (e) {
    auditMsg.value = `❌ 审计失败：${String((e as Error).message || e)}`
  } finally { auditBusy.value = false }
}

function auditOf(s: { name?: string }): any { return auditRow.value[String(s.name || '')] || null }

/** 审计单元格展示（与 tag 列并列的「检查」列）。 */
function auditCell(s: { name?: string }): { text: string; color: string; cls: string; why: string } {
  const a = auditOf(s)
  if (!a) {
    const sk = auditMeta.value?.skipped?.find((x) => x.name === s.name)
    if (sk) return { text: '未转写', color: '#9ca3af', cls: 'aud-notrans', why: sk.reason }
    return { text: '—', color: '#9ca3af', cls: '', why: '尚未审计：点列头「运行审计」' }
  }
  if (a.linkMissing?.length && a.verdict === 'unknown') {
    return { text: '?', color: '#6b7280', cls: 'aud-unknown', why: a.reason || '题干缺失' }
  }
  if (a.verdict === 'mismatch') {
    return { text: `${a.auditTag ?? '?'} ⚠️`, color: '#b91c1c', cls: 'aud-bad', why: a.reason || '' }
  }
  if (a.verdict === 'match') {
    return { text: `✓ ${a.auditTag ?? ''}`, color: '#15803d', cls: 'aud-ok', why: a.reason || '' }
  }
  return { text: `? ${a.auditTag || ''}`.trim(), color: '#6b7280', cls: 'aud-unknown', why: a.reason || '' }
}

/** 不一致行整行高亮（教师要求：方便检查）。 */
function auditRowClass(s: { name?: string }): string {
  const a = auditOf(s)
  if (!a) return ''
  return a.verdict === 'mismatch' ? 'row-audit-bad' : ''
}

/* ---------------- D173：过滤 / 批量 / 详情 ---------------- */

/** 列头统计（每项可点做过滤）。 */
const auditStats = computed(() => {
  const st = { all: students.value.length, match: 0, differs: 0, unknown: 0, notrans: 0 }
  for (const s of students.value) {
    const a = auditOf(s)
    if (!a) {
      if (auditMeta.value?.skipped?.some((x) => x.name === s.name)) st.notrans += 1
      continue
    }
    if (a.tagDiffers) st.differs += 1
    else if (a.verdict === 'match') st.match += 1
    else st.unknown += 1
  }
  return st
})

/** 过滤：默认全部；**「只看 tag 不同的」按 `tagDiffers`**（不是 verdict）。
 *  修复 D172 的 bug：置信不足时 verdict=unknown，但 tag 确实不同，
 *  按 verdict 过滤会把这些学生全漏掉（教师实测：勾了之后列表空）。 */
const auditFilter = ref<'all' | 'differs' | 'unknown' | 'match' | 'notrans'>('all')
const auditRows = computed(() => {
  if (auditFilter.value === 'all') return students.value
  return students.value.filter((s) => {
    const a = auditOf(s)
    if (auditFilter.value === 'notrans') {
      return !a && !!auditMeta.value?.skipped?.some((x) => x.name === s.name)
    }
    if (!a) return false
    if (auditFilter.value === 'differs') return !!a.tagDiffers
    if (auditFilter.value === 'match') return a.verdict === 'match' && !a.tagDiffers
    return a.verdict === 'unknown' && !a.tagDiffers
  })
})

/** 批量改 tag：下拉可选本包内全部 tag + 清空。 */
const bulkTag = ref('')
const auditTagOptions = computed<string[]>(() => {
  const out: string[] = []
  for (const p of (packId.value ? packPads.value : pads.value)) {
    const t = String((p as any).tag || '').trim()
    if (t && !out.includes(t)) out.push(t)
  }
  for (const a of Object.values(auditRow.value)) {
    const t = String((a as any)?.auditTag || '').trim()
    if (t && !out.includes(t)) out.push(t)
  }
  return out
})
const auditSelectedNames = computed(() => students.value
  .filter((s) => auditChecked.value[String(s.name || '')])
  .map((s) => String(s.name || '')))

async function applyBulkTag() {
  const names = auditSelectedNames.value
  if (!names.length) { auditMsg.value = '⚠ 请先勾选学生'; return }
  if (bulkTag.value === '') { auditMsg.value = '⚠ 请先选择要改成的 tag'; return }
  await applyAuditChanges(
    students.value
      .filter((s) => auditChecked.value[String(s.name || '')])
      .map((s) => ({ name: String(s.name || ''), tag: bulkTag.value, number: String(s.studentId || '') })),
    'manual-batch')
}

/** 一键采纳「审计 tag」：勾选行 → 各自改成自己的审计 tag。 */
async function applyAuditChecked() {
  const changes = students.value
    .filter((s) => auditChecked.value[String(s.name || '')])
    .map((s) => ({ name: String(s.name || ''), tag: String(auditOf(s)?.auditTag || ''), number: String(s.studentId || '') }))
    .filter((c) => c.tag)
  if (!changes.length) { auditMsg.value = '⚠ 没有勾选（或勾选的学生没有审计 tag）'; return }
  await applyAuditChanges(changes, 'audit-apply')
}

async function applyAuditOne(s: { name?: string; studentId?: string }, tag?: string) {
  const a = auditOf(s)
  const to = String(tag || a?.auditTag || '')
  if (!to) return
  // D184：详情弹窗调用可能只传 name，这里从当前下载名单补 studentId。
  const stu = students.value.find((x) => String(x.name) === String(s.name || ''))
  await applyAuditChanges([{ name: String(s.name || ''), tag: to,
                             number: String(s.studentId || stu?.studentId || '') }],
                          'manual-detail')
}

async function applyAuditChanges(changes: Array<{ name: string; tag: string; number?: string }>,
                                reason = 'manual-detail') {
  const w = curWork.value
  // D181：刷新后作业包/作业纸下拉可能为空，但引擎已从磁盘反查出批阅目录，
  // 改 tag 必须用这个作用域，否则 silently no-op。
  const pid = packId.value || padId.value || resolvedScope.value
  if (!w) { auditMsg.value = '⚠ 请先选择作业'; return }
  if (!pid) { auditMsg.value = '⚠ 请先选择作业包/作业纸（或先读取一次学生清单）'; return }
  if (!curWorkDir.value) { auditMsg.value = '⚠ 请先关联本地班级目录'; return }
  const desc = changes.map((c) => {
    const cur = auditOf({ name: c.name })?.rosterTag
      ?? students.value.find((s) => s.name === c.name)?.tag ?? '?'
    return `${c.name}：${cur || '（空）'} → ${c.tag || '（清空）'}`
  }).join('\n')
  if (!confirm(`将修改 ${changes.length} 名学生的 tag（**这是改历史**，会自动保存可撤销的历史副本）：\n\n${desc}\n\n`
    + `· 已批阅结果**不会**自动重算；\n· 需要重批请在行内点「转写+批阅」。继续？`)) return
  auditBusy.value = true; auditMsg.value = '⏳ 正在应用…'
  try {
    const r = await applyTagAudit(props.engineAddr, props.token,
                                  { classDir: curWorkDir.value, packId: pid, changes, reason })
    if (r?.ok === false) { auditMsg.value = `❌ 应用失败：${r.error || '未知错误'}`; return }
    const applied = r.applied || []
    const missing = r.missing || []
    const unchanged = r.unchanged || []
    let msg = ''
    if (applied.length) {
      msg = `✅ 已改 ${applied.length} 人；已记录 tag 变更历史（可撤销）。建议对这些学生重新「转写+批阅」。`
    }
    if (missing.length) {
      // D184：missing 必须红色错误提示，不能显示「没有变化」。
      msg += (msg ? '\n' : '') + `❌ 以下学生未找到，未写入：${missing.join('、')}`
    }
    if (!applied.length && !missing.length && unchanged.length) {
      msg = 'ℹ️ 没有变化（值与现状相同，未写盘）'
    }
    auditMsg.value = msg || 'ℹ️ 没有变化'
    await loadStudents(); await loadAudit()
    // 详情页同步刷新（若开着）
    if (auditDetail.value) {
      auditDetail.value = auditOf({ name: auditDetail.value.name }) || auditDetail.value
    }
  } catch (e) {
    auditMsg.value = `❌ 应用失败：${String((e as Error).message || e)}`
  } finally { auditBusy.value = false }
}

/** D173：按学生撤销他最近一次 tag 变更（追加记录，不删历史）。 */
async function undoStudentTag(name: string) {
  const pid = packId.value || padId.value
  if (!pid || !curWorkDir.value) return
  if (!confirm(`撤销「${name}」最近一次 tag 变更？\n\n（会追加一条新记录，不删除已有历史）`)) return
  auditBusy.value = true
  try {
    const r = await undoStudentTagApi(props.engineAddr, props.token,
                                      { classDir: curWorkDir.value, packId: pid, name })
    if (r?.ok === false) { auditMsg.value = `❌ 撤销失败：${r.error}`; return }
    auditMsg.value = r.written
      ? `✅ 已撤销「${name}」：${r.from} → ${r.to}`
      : `ℹ️ ${r.note || '无需撤销'}`
    await loadStudents(); await loadAudit()
    if (auditDetail.value) {
      auditDetail.value = auditOf({ name }) || auditDetail.value
    }
  } catch (e) { auditMsg.value = `❌ 撤销失败：${String((e as Error).message || e)}` }
  finally { auditBusy.value = false }
}

/** 详情页里当前编辑的 tag（打开详情时自动同步为 roster tag）。 */
const auditEditTag = ref('')
watch(auditDetail, (v) => {
  auditEditTag.value = String((v as any)?.rosterTag || '')
}, { immediate: true })

async function saveManualTag() {
  const d = auditDetail.value
  if (!d) return
  const stu = students.value.find((s) => String(s.name) === String(d.name || ''))
  await applyAuditChanges([{ name: String(d.name), tag: String(auditEditTag.value || ''),
                             number: String(stu?.studentId || '') }],
                          'manual-detail')
}

/** 详情页：上一位 / 下一位（教师逐个核对时不用关窗重点）。 */
const auditDetailIdx = computed(() =>
  students.value.findIndex((s) => String(s.name) === String(auditDetail.value?.name || '')))
function auditDetailStep(delta: number) {
  const n = students.value.length
  if (!n) return
  const i = auditDetailIdx.value
  const j = (i + delta + n) % n
  auditDetail.value = auditOf(students.value[j]!) || { name: students.value[j]!.name, pending: true }
}

async function undoAudit() {
  const pid = packId.value || padId.value
  if (!curWork.value || !pid || !curWorkDir.value) return
  try {
    const h = await fetchTagAuditHistory(props.engineAddr, props.token,
                                         { classDir: curWorkDir.value, packId: pid })
    const list = h.history || []
    if (!list.length) { auditMsg.value = 'ℹ️ 没有可撤销的历史副本'; return }
    const pick = list[0]!
    const label = `${pick.at}（${pick.snapshotSource || pick.reason}）`
    if (!confirm(`撤销到最近一次修改**之前**的状态？\n\n副本：${label}\n\n`
      + `撤销前会自动保存当前状态，所以撤销本身也可再撤销。继续？`)) return
    const r = await undoTagAudit(props.engineAddr, props.token,
                                 { classDir: curWorkDir.value, packId: pid, file: pick.file })
    if (r?.ok === false) { auditMsg.value = `❌ 撤销失败：${r.error}`; return }
    auditMsg.value = `✅ 已撤销（从 ${pick.file} 恢复，共 ${r.count ?? '?'} 人）`
    await loadStudents(); await loadAudit()
  } catch (e) { auditMsg.value = `❌ 撤销失败：${String((e as Error).message || e)}` }
}

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
      // D184：保留下载名单里的学号/编号，apply 时作为 number 传给引擎 UPSERT。
      studentId: String(s.studentId || ''),
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
  // D172：随学生清单一起刷新审计结果（没有审计文件时静默为空）
  await loadAudit()
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
/** D175：**最终分**（= 上传/报告实际会用的分）。此前表格只显示 AI 分，
 *  教师在审核里改了分数，回到列表仍是 AI 分 → "改了分数没有变化"。 */
function finalScoreOf(s: { key?: string; name?: string; altKeys?: string[] }): string | number {
  const d = draftOf(s)
  const h = d.human || {}
  const hm = String(d.humanMode || 'none')
  if (["replace", "human", "append", "revise"].includes(hm) && h.score !== undefined && h.score !== null) return h.score
  if (h.score !== undefined && h.score !== null) return h.score
  const a = d.ai?.score
  return a !== undefined && a !== null ? a : (d.score ?? '—')
}
/** 最终分是否被人工改过（非 AI 基线）。 */
function scoreOverridden(s: { key?: string; name?: string; altKeys?: string[] }): boolean {
  const d = draftOf(s)
  const h = d.human || {}
  const a = d.ai?.score
  return h.score !== undefined && h.score !== null && (a === undefined || a === null || Number(h.score) !== Number(a))
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
/** D216：程序对齐结论 → 可读标签（数据来自草稿 ai.align）。 */
function alignCell(s: { key?: string; name?: string; altKeys?: string[] }):
  { text: string; color: string; why: string } {
  const a = (draftOf(s).ai || {}).align || {}
  const v = String(a.verdict || '')
  if (!v) return { text: '未对齐', color: '#9ca3af',
                   why: '该生评阅结果里没有对齐信息（旧数据）；重新批阅后显示' }
  if (v === 'match') return { text: '匹配', color: '#15803d', why: String(a.reason || '') }
  if (v === 'mismatch') {
    return { text: '疑似错卷', color: '#b45309;font-weight:600',
             why: `${a.reason || ''}（建议 tag：${a.bestTag || '—'}）` }
  }
  return { text: '未确定', color: '#6b7280', why: String(a.reason || '') }
}
/** D216：全表对齐汇总（用于列表上方提示）。 */
const alignSummary = computed(() => {
  let match = 0, mismatch = 0, unknown = 0, none = 0
  for (const s of students.value) {
    const v = String(((draftOf(s).ai || {}).align || {}).verdict || '')
    if (v === 'match') match++
    else if (v === 'mismatch') mismatch++
    else if (v === 'unknown') unknown++
    else none++
  }
  return { match, mismatch, unknown, none, total: students.value.length }
})

/** D127：报告模式（未人工介入时显示 auto(AI)，不再是一串 "—"）。 */
function reportMode(s: { key: string; name?: string; altKeys?: string[] }): string {
  const d = draftOf(s)
  const hm = String(d.humanMode || 'none')
  if (hm === 'replace') return '人工替代'
  if (hm === 'append') return 'AI+人工'
  if (hm === 'revise') return 'AI·修订'
  return d.human?.used ? 'auto(人工)' : 'auto(AI)'
}

async function renderReports(opts?: { resume?: boolean; only?: string[] }) {
  const w = curWork.value
  if (!w) { msg.value = '请选择作业'; return }
  const taskId = packId.value || padId.value || resolvedScope.value
  if (!taskId) { msg.value = '⚠ 请先选择作业包/作业纸，或先读取一次学生清单'; return }
  if (!curWorkDir.value) { msg.value = '⚠ 请先关联本地班级目录'; return }
  busy.value = true
  // D195：先做一次**只读**范围核对——避免“以为全班都出了报告，其实只有有草稿的出了”。
  try {
    scopeCheck.value = await renderReportsFromDrafts(props.engineAddr, props.token, {
      classId: w.classId, workId: w.workId, taskId,
      classDir: curWorkDir.value, scopeOnly: true,
      students: students.value.map((x) => x.name).filter(Boolean),
    })
  } catch { scopeCheck.value = null }
  progress.value = opts?.resume
    ? '正在续做报告（已有报告的学生会跳过，内容未变不产生新版本）……'
    : opts?.only?.length
      ? `正在为 ${opts.only.length} 名学生重做报告……`
      : '正在按草稿逐生生成报告（人工在前 + 【附件】AI + 修订标红）……'
  try {
    const r = await renderReportsFromDrafts(props.engineAddr, props.token, {
      classId: w.classId, workId: w.workId, taskId,
      // D187：必须带 classDir；否则后端会落到 classes/<学习通数字 classId>，
      // 与真实 classes/<中文班级目录>/grading/<taskId>/drafts 不一致。
      classDir: curWorkDir.value,
      resume: opts?.resume === true,
      only: opts?.only,
      reason: opts?.resume ? 'pwa-resume' : (opts?.only ? 'pwa-only' : 'pwa-render'),
    })
    busy.value = false
    await refreshReportProgress()
    if (r?.busy) {
      progress.value = `⚠ ${r.error || '该作业正在生成报告，请稍候'}`
      return
    }
    if (r?.ok || r?.partial) {
      const n = r.count ?? (r.reports || []).length
      const types = Array.from(new Set((r.reports || []).map((x) => x.kind))).join('/')
      const vers = Array.from(new Set((r.reports || [])
        .map((x) => x.tag || x.version).filter(Boolean)))
      const failed = r.failed || []
      const skippedN = (r.skipped || []).length
      progress.value = `${r.partial ? '⚠ 部分完成' : '✅ 已生成'} ${n} 份报告`
        + `（类型：${types || '自动'}）`
        + (vers.length ? `；版本 ${vers.slice(0, 3).join('、')}${vers.length > 3 ? ' …' : ''}` : '')
        + '；写入本地草稿（含报告图）'
        + (skippedN ? `；续做跳过 ${skippedN} 人` : '')
        + ((r.reports || []).some((x) => x.changed === false)
          ? '；部分学生内容未变（版本号不变，不重复产生历史）' : '')
        + (failed.length ? `；失败 ${failed.length} 人：${failed.map((x) => x.student).join('、')}` : '')
      const miss = scopeCheck.value?.missingDraft || []
      if (miss.length) {
        progress.value += `\n⚠ 另有 ${miss.length} 名学生（表格里有行）**没有本地草稿**，`
          + `因此不会生成报告、也没有分数：${miss.slice(0, 8).join('、')}${miss.length > 8 ? ' …' : ''}`
          + '。请先对他们跑「转写+评阅」或在逐生审核里保存批阅后再生成。'
      }
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
/** D193：打开上传对照表。`platform=true` 会读取平台已批阅内容（较慢但更准）。 */
async function openUploadPreview(platform: boolean, opts?: { force?: boolean }) {
  const force = opts?.force === true
  const w = curWork.value
  if (!w) { msg.value = '请选择作业'; return }
  const taskId = packId.value || padId.value || resolvedScope.value
  if (!curWorkDir.value) { msg.value = '⚠ 请先关联本地班级目录'; return }
  previewOpen.value = true
  previewBusy.value = true
  previewRows.value = []
  previewSummary.value = {}
  previewCheckedPlatform.value = platform
  progress.value = platform
    ? (force ? '正在重新读取平台批阅状态（只读）……'
             : '正在读取上传前对照（优先用本地缓存）……')
    : '正在整理本地分数/批语/报告版本……'
  try {
    const r = await fetchXxtUploadPreview(props.engineAddr, props.token, {
      courseId: w.courseId, classId: w.classId, cpi: w.cpi, workId: w.workId,
      classDir: curWorkDir.value, taskId: taskId || undefined, platform,
      force,
    })
    if (!r?.ok) { progress.value = `❌ 对照表生成失败：${r?.error || '未知错误'}`; return }
    previewRows.value = r.rows || []
    previewSummary.value = (r.summary?.counts || {}) as Record<string, number>
    previewReadiness.value = (r.readiness || null) as any
    previewCache.value = (r.cache || null) as any
    if (!platform && (r.needComment?.length || r.noReport?.length)) {
      // 仅本地核对时也能提醒“批语为空/无报告”
      previewReadiness.value = {
        ...(previewReadiness.value || {}),
        noComment: r.needComment || [], ready: [],
        hint: `本地有 ${r.needComment?.length ?? 0} 名学生批语为空、`
          + `${r.noReport?.length ?? 0} 名未生成报告；请先批阅/AI 批阅与生成报告`,
      }
    }
    const c = previewSummary.value
    const rd = previewReadiness.value?.summary || {}
    const emptyTxt = (previewReadiness.value?.emptyComment || []).length
    progress.value = `✅ 对照表就绪：可上传 ${rd.ready ?? c.new ?? 0} 人`
      + (emptyTxt ? `（其中 ${emptyTxt} 人走“报告图+分数”，不上传批语文本）` : '')
      + ` · 无报告图/批语/分数 ${rd['no-report'] ?? 0} 人`
      + ` · 无本地草稿 ${rd['no-draft'] ?? 0} 人`
      + ` · 未提交（不上传）${rd['not-submitted'] ?? 0} 人`
      + (platform
        ? (previewCache.value?.hit
          ? `；平台状态：本地缓存（${previewCache.value.fetchedAt || ''}，`
            + `${Math.round((previewCache.value.ageSec ?? 0) / 60)} 分钟前）`
            + (previewCache.value.stale ? ' ⚠ 本地内容已变化，建议「重新读取平台状态」' : '')
          : '；平台状态：刚刚实时读取')
        : '（未读取平台状态：点「读取平台状态」更准确）')
  } catch (e) {
    progress.value = `对照表失败：${String((e as Error)?.message || e)}`
  } finally { previewBusy.value = false }
}

/** D195：**重新生成**全部报告（覆盖旧版；内容未变不产生新版本）。 */
async function regenerateAllReports() {
  if (!window.confirm('将按当前草稿**重新生成**全部报告（覆盖“最新”报告文件；'
    + '内容未变不会产生新版本，历史保留在 .versions）。继续？')) return
  await renderReports()
}

/** D195/D197：清理“不在本次名单”的报告文件 + **同步清理版本索引**。
 *
 * 现场问题：清理后“报告版本”仍显示 106 条（索引从未按名单核对）。
 * 现在流程：先用 dryRun 统计（不删）→ 教师确认 → 真删 → 刷新版本/进度。
 */
async function cleanupDuplicateReports() {
  const taskId = packId.value || padId.value || resolvedScope.value
  if (!curWorkDir.value || !taskId) { msg.value = '⚠ 请先关联班级目录并选择作业包'; return }
  const names = students.value.map((x) => x.name).filter(Boolean)
  if (!names.length) {
    msg.value = '⚠ 还没有当前作业的学生清单：请先在「逐生审核」读取学生状态，再清理'
      + '（空名单会误删，已被引擎拒绝）'
    return
  }
  cleanupResult.value = null
  try {
    // ① 试运行：只统计，不删除
    const preview = await cleanupXxtReports(props.engineAddr, props.token, {
      classDir: curWorkDir.value, taskId, students: names, dryRun: true,
    })
    if (!preview?.ok) {
      cleanupResult.value = preview || { ok: false, error: '试运行失败' }
      msg.value = `❌ 清理前核对失败：${preview?.error || '未知错误'}`
      return
    }
    const nFiles = preview.count ?? preview.removed?.length ?? 0
    const nIndex = preview.indexRemoved ?? 0
    if (!nFiles && !nIndex) {
      const st = preview.stats || {}
      cleanupResult.value = { ...preview, dryRun: true, count: 0, indexRemoved: 0 }
      const detail = st.totalRecords
        ? `名单内 ${st.studentCount ?? names.length} 名学生共 ${st.totalRecords} 条版本记录`
          + (st.historyRecords ? `（其中 ${st.historyRecords} 条为历史版本，不是多余学生）` : '')
        : `名单内 ${names.length} 人`
      msg.value = `✅ 核对完成：没有“多余学生”的报告或记录 —— ${detail}。`
        + (preview.hint ? ` ${preview.hint}` : '')
      return
    }
    const ok = window.confirm(
      `将清理不在本次名单（${names.length} 人）里的报告残留：\n\n`
      + `· 报告文件：${nFiles} 个\n`
      + `· 版本索引记录：${nIndex} 条（${preview.indexBefore ?? 0} → ${preview.indexAfter ?? 0}）\n\n`
      + `只删 reports/ 下的报告与历史版本＋索引记录，**不动草稿/分数/批语**。\n`
      + `确认执行？`)
    if (!ok) { msg.value = '已取消清理（未删除任何文件）'; return }
    // ② 真删
    const r = await cleanupXxtReports(props.engineAddr, props.token, {
      classDir: curWorkDir.value, taskId, students: names, dryRun: false,
    })
    cleanupResult.value = r || null
    if (!r?.ok) {
      msg.value = `❌ 清理失败：${r?.error || '未知错误'}`
      return
    }
    msg.value = `✅ 清理完成：删除报告文件 ${r.count ?? 0} 个，`
      + `版本索引 ${r.indexBefore ?? '?'} → ${r.indexAfter ?? '?'} 条（清理 ${r.indexRemoved ?? 0} 条）`
    // ③ 刷新版本列表与进度，避免界面继续显示旧记录
    await refreshReportProgress()
    if (versionsOpen.value) await loadReportVersions()
  } catch (e) {
    msg.value = `清理失败：${String((e as Error)?.message || e)}`
  }
}

/** D198：压缩版本历史（每生保留最新 1 版）——用于“记录数太多但其实没有多余学生”。 */
async function compactReportVersions() {
  const taskId = packId.value || padId.value || resolvedScope.value
  if (!curWorkDir.value || !taskId) { msg.value = '⚠ 请先关联班级目录并选择作业包'; return }
  const names = students.value.map((x) => x.name).filter(Boolean)
  try {
    // 先 dry-run
    const preview = await compactXxtReportVersions(props.engineAddr, props.token, {
      classDir: curWorkDir.value, taskId, keepLatest: 1,
      students: names.length ? names : undefined, dryRun: true,
    })
    if (!preview?.ok) { msg.value = `❌ 核对失败：${preview?.error || '未知错误'}`; return }
    if (!preview.removed) {
      cleanupResult.value = { ok: true, dryRun: true, count: 0, indexRemoved: 0,
        stats: { totalRecords: preview.before, studentCount: preview.students,
                 historyRecords: 0 },
        hint: '每名学生都只有 1 条版本记录，无需压缩。' }
      msg.value = `✅ 核对完成：共 ${preview.before ?? 0} 条记录，每生都只有最新 1 版，无需压缩`
      return
    }
    const ok = window.confirm(
      `将把版本历史压缩为“每生只保留最新 1 版”：\n\n`
      + `· 记录：${preview.before} → ${preview.after}（删除 ${preview.removed} 条索引）\n`
      + `· 涉及学生：${preview.students ?? '?'} 名\n`
      + `· 历史 .versions 文件：**保留**（只压缩索引，不删文件）\n\n`
      + `草稿里的 AI 批语/人工修改/报告图副本都不受影响。确认？`)
    if (!ok) { msg.value = '已取消压缩'; return }
    const r = await compactXxtReportVersions(props.engineAddr, props.token, {
      classDir: curWorkDir.value, taskId, keepLatest: 1,
      students: names.length ? names : undefined, dryRun: false,
    })
    cleanupResult.value = { ok: r?.ok, count: 0,
      indexRemoved: r?.removed, indexBefore: r?.before, indexAfter: r?.after,
      stats: { totalRecords: r?.after, studentCount: r?.students },
      hint: r?.ok ? `已压缩版本历史：${r.before} → ${r.after} 条（历史文件保留）` : r?.error }
    msg.value = r?.ok
      ? `✅ 压缩完成：版本记录 ${r.before} → ${r.after} 条（每生保留最新 1 版，历史文件仍保留）`
      : `❌ 压缩失败：${r?.error || '未知错误'}`
    await refreshReportProgress()
    if (versionsOpen.value) await loadReportVersions()
  } catch (e) {
    msg.value = `压缩失败：${String((e as Error)?.message || e)}`
  }
}

/** D194：读取上次报告生成进度（只读；用于显示“已生成 X/Y”和续做入口）。 */
async function refreshReportProgress() {
  const w = curWork.value
  const taskId = packId.value || padId.value || resolvedScope.value
  if (!w || !curWorkDir.value || !taskId) { reportProgress.value = null; return }
  try {
    reportProgress.value = await fetchReportProgress(props.engineAddr, props.token, {
      classId: w.classId, workId: w.workId, taskId, classDir: curWorkDir.value,
    })
  } catch { reportProgress.value = null }
}

/** D194：续做——已完成（有报告的）学生跳过；零成本重复点也安全。 */
async function resumeReports() {
  await renderReports({ resume: true })
}

/** D194：只补做上次失败的学生。 */
async function retryFailedReports() {
  const names = (reportProgress.value?.failed || []).map((x) => x.student || '')
    .filter(Boolean)
  if (!names.length) { msg.value = '没有失败记录'; return }
  await renderReports({ only: names })
}

/** D193：查看报告版本历史（只读；同一内容不会重复产生版本）。 */
async function loadReportVersions() {
  const taskId = packId.value || padId.value || resolvedScope.value
  if (!curWorkDir.value || !taskId) { msg.value = '⚠ 请先关联班级目录并选择作业包'; return }
  versionsOpen.value = true
  versionsBusy.value = true
  versionsRows.value = []
  try {
    const names = students.value.map((x) => x.name).filter(Boolean)
    const keyToName: Record<string, string> = {}
    for (const s of students.value) {
      if (s.key && s.name) keyToName[String(s.key)] = String(s.name)
    }
    const r = await fetchXxtReportVersions(props.engineAddr, props.token, {
      classDir: curWorkDir.value, taskId, students: names.length ? names : undefined,
      keyToName,
    })
    if (!r?.ok) { progress.value = `❌ 版本读取失败：${r?.error || '未知错误'}`; return }
    versionsRows.value = r.items || []
    versionRoster.value = r.roster || []
    versionMeta.value = {
      rosterCount: r.rosterCount, reportedCount: r.reportedCount,
      missingReport: r.missingReport || [], unmatched: r.unmatched || [],
      totalInIndex: r.totalInIndex, historyRecords: r.historyRecords,
      studentCount: r.studentCount, avgVersions: r.avgVersions,
    }
    const meta = versionMeta.value || {}
    const miss = meta.missingReport || []
    progress.value = `逐生审核名单 ${meta.rosterCount ?? names.length} 人：`
      + `已生成报告 ${meta.reportedCount ?? 0} 人`
      + (miss.length ? `，**未生成 ${miss.length} 人**（${miss.slice(0, 8).join('、')}${miss.length > 8 ? ' …' : ''}）` : '')
      + `；版本记录共 ${meta.totalInIndex ?? versionsRows.value.length} 条`
      + (meta.historyRecords ? `（其中 ${meta.historyRecords} 条为历史版本）` : '')
      + ((meta.unmatched || []).length
        ? `；⚠ ${(meta.unmatched || []).length} 个索引姓名不在名单内，可点「🧹 清理多余报告」` : '')
      + `；目录 ${r.dir || ''}`
  } catch (e) {
    progress.value = `版本读取失败：${String((e as Error)?.message || e)}`
  } finally { versionsBusy.value = false }
}

/** D196：**逐生上传**（更易定位问题：某一人失败不影响其他人，也可单独重试）。 */
/** D204：逐生上传。`dryRun=true` 只填入并读回，不点提交——用于安全验证。
 *
 * 会话过期/页面不对时引擎会返回 `session-expired`/`not-mark-page`，界面直接提示重新扫码。
 */
async function uploadOneStudent(row: { student: string; readyState?: string
  decision?: string }, opts?: { dryRun?: boolean; overwrite?: boolean }) {
  const dryRun = opts?.dryRun === true
  const overwrite = opts?.overwrite === true
  const w = curWork.value
  if (!w) return
  if (row.readyState === 'not-submitted') {
    msg.value = `${row.student} 平台未提交，无需上传批阅报告`
    return
  }
  if (row.readyState === 'no-report' || row.readyState === 'no-comment'
      || row.readyState === 'no-draft') {
    msg.value = `${row.student} 没有可上传的内容（报告图/批语/分数都缺）：请先生成批阅报告或补批阅`
    return
  }
  const needForce = row.decision === 'conflict'
  if (!dryRun && overwrite
      && !window.confirm(`覆盖 ${row.student} 的原报告？\n\n`
        + '将清空平台上该生的原批语/原报告图，替换为本地报告图与分数。\n'
        + '（旧报告图会从批语中移除，分数会被覆盖）\n\n确定继续？')) return
  if (!dryRun && !overwrite && needForce
      && !window.confirm(`${row.student} 平台已批阅且内容不同，覆盖？`)) return
  oneUploadBusy.value = row.student
  oneUploadResult.value = {
    ...oneUploadResult.value,
    [row.student]: dryRun ? '演练中（只填不提交）…' : '上传中…',
  }
  try {
    const jobId = await startXxtGradeUpload(props.engineAddr, props.token, {
      courseId: w.courseId, classId: w.classId, cpi: w.cpi, workId: w.workId,
      student: row.student, send: !dryRun, force: needForce || overwrite,
      overwrite,
      reportOnly: uploadReportOnly.value,
      // D201：带上 scope，否则引擎按旧布局找草稿 → “本地无该作业的批阅草稿”
      classDir: curWorkDir.value,
      taskId: packId.value || padId.value || resolvedScope.value || undefined,
    })
    const tick = async () => {
      try {
        const job = await fetchXxtLoginJob(props.engineAddr, props.token, jobId)
        if (job.status === 'running') {
          oneUploadResult.value = { ...oneUploadResult.value, [row.student]: '上传中…' }
          window.setTimeout(tick, 1500); return
        }
        const lines = (job.lines || []).join('\n')
        const rc = job.returncode ?? 0
        // D202：成功必须是引擎“提交后核验”通过（rc=0），否则显示可读原因
        oneUploadResult.value = {
          ...oneUploadResult.value,
          [row.student]: rc === 0
            ? (dryRun ? '✅ 演练通过（已填入并读回，未提交）'
              : overwrite ? '✅ 已覆盖上传（旧报告图已清除，已核验）'
                          : '✅ 已上传（已核验平台状态）')
            : `❌ ${extractJobError(lines).slice(0, 200)}`,
        }
        oneUploadBusy.value = ''
        await loadStudents()
      } catch (e) {
        oneUploadResult.value = { ...oneUploadResult.value,
          [row.student]: `查询失败：${String((e as Error)?.message || e)}` }
        oneUploadBusy.value = ''
      }
    }
    void tick()
  } catch (e) {
    oneUploadBusy.value = ''
    oneUploadResult.value = { ...oneUploadResult.value,
      [row.student]: `启动失败：${String((e as Error)?.message || e)}` }
  }
}

/** 确认执行上传：只上传「可上传」的人；冲突需再次确认后才 force 覆盖。 */
async function confirmUploadFromPreview() {
  const w = curWork.value
  if (!w) return
  const conflicts = previewRows.value.filter(r => r.decision === 'conflict'
    && r.readyState !== 'not-submitted')
  // D196：只上传“已提交 + 批语齐全”的学生；未提交/批语空的不进入上传名单。
  const uploadable = previewRows.value.filter(r => r.readyState
    ? r.readyState === 'ready'
    : r.decision === 'new')
  const blocked = previewRows.value.filter(r => r.readyState === 'no-report'
    || r.readyState === 'no-comment' || r.readyState === 'no-draft')
  const notSub = previewRows.value.filter(r => r.readyState === 'not-submitted')
  if (!uploadable.length && !conflicts.length) {
    msg.value = `没有需要上传的学生（未提交 ${notSub.length} 人不上传；`
      + `批语缺失 ${blocked.length} 人需先批阅）`
    return
  }
  const lines: string[] = []
  lines.push(`可上传（已提交 + 批语齐全）：${uploadable.length} 人`)
  if (blocked.length) {
    lines.push(`⚠ 已提交但没有报告图/批语/分数：${blocked.length} 人（请先生成报告或补批阅）`)
    for (const b of blocked.slice(0, 8)) lines.push(`  · ${b.student}：${b.readyReason || ''}`)
  }
  if (notSub.length) lines.push(`ℹ 未提交（不上传批阅报告）：${notSub.length} 人`)
  if (conflicts.length) {
    lines.push(`已批阅且内容不同：${conflicts.length} 人 ——`)
    for (const c of conflicts.slice(0, 10)) {
      lines.push(`  · ${c.student}：平台 ${c.platformScore ?? '—'} 分 → 本地 ${c.localScore ?? '—'} 分`)
    }
    if (conflicts.length > 10) lines.push(`  …共 ${conflicts.length} 人`)
    lines.push('')
    lines.push('⚠ 这些学生平台已有批阅，继续将**覆盖**平台内容。')
  }
  if (!window.confirm(lines.join('\n') + '\n\n确定继续上传？')) return
  previewOpen.value = false
  await uploadAll(conflicts.length > 0 && previewCheckedPlatform.value, uploadable.map(r => r.student))
}

async function uploadAll(force: boolean, only?: string[]) {
  const w = curWork.value
  if (!w) return
  const n = only?.length ?? Object.keys(drafts.value).length
  if (!n) { msg.value = '还没有本地草稿：先跑 AI 批阅或逐生填写后保存'; return }
  if (force && !only && !window.confirm(`强制覆盖：将上传 ${n} 份本地草稿（含打分）并覆盖平台已批阅内容？`)) return
  try {
    const jobId = await startXxtGradeUpload(props.engineAddr, props.token, {
      courseId: w.courseId, classId: w.classId, cpi: w.cpi, workId: w.workId,
      send: true, force, reportOnly: uploadReportOnly.value,
      classDir: curWorkDir.value,
      taskId: packId.value || padId.value || resolvedScope.value || undefined,
      // D208：按对照表上传时只传确认名单（旧实现忽略 only → 实际全传）
      students: only && only.length ? only : undefined,
    })
    busy.value = true
    progress.value = only && only.length
      ? `正在上传已确认的 ${only.length} 名学生……`
      : `正在上传全部草稿（${force ? '强制覆盖' : '跳过已批阅'}）……`
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
watch(workKey, (k) => {
  if (k) { void loadStudents(); void refreshReportProgress() }
  else { students.value = []; drafts.value = {}; reportProgress.value = null }
}, { flush: 'post' })

onMounted(async () => {
  await loadConfig()
  await loadWorks()
  // D117：自动选中的作业同样要拉学生/草稿（否则「逐生审核」空白）
  if (workKey.value) void loadStudents()
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
      <button class="btn small" :disabled="busy"
              title="只跑批阅：基于已有转写出批语 + 打分（写进逐生审核草稿；要求已有转写产物）"
              @click="startAi(['evaluate'])">② 批阅</button>
      <button class="btn" :disabled="busy"
              title="转写 + 批阅：先转写再出批语+打分（= ① + ②；不含报告，审核后再用下方「📄 一键生成批阅报告」）"
              @click="startAi(['transcribe', 'evaluate'])">▶ ③ 转写+批阅</button>
      <label class="hint" style="display:inline-flex; align-items:center; gap:4px; margin-left:8px"
             title="勾选后：三个键都会**重新调用大模型并覆盖**已有产物（会重新花额度）">
        <input type="checkbox" v-model="forceRedo" />
        强制重做（覆盖已有结果，会重新花额度）
      </label>
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
      <div class="audit-bar">
        <button class="btn small" :disabled="auditBusy || !curWork || !curWorkDir"
                :title="'用转写里的题干反推实际 tag（纯本地计算，不调模型）'"
                @click="runAuditNow()">🛡 {{ auditBusy ? '审计中…' : '运行 tag 审计' }}</button>
        <button v-if="auditMeta?.generatedAt" class="btn small" :disabled="auditBusy"
                title="把整包快照恢复到上次修改之前（改前会自动再存一份当前状态）"
                @click="undoAudit()">↩ 整包撤销</button>
        <span class="hint" style="margin:0" :title="auditMeta?.engine || ''">
          <template v-if="auditMsg">{{ auditMsg }}</template>
          <template v-else-if="auditMeta?.generatedAt">
            审计于 {{ auditMeta.generatedAt }}（tag 依据：{{ auditMeta.rosterTagSource === 'snapshot' ? '包快照（已冻结）' : '当前 roster' }}）
          </template>
          <template v-else>未审计 · 审计只比对当前作业包内的作业纸题目</template>
        </span>
      </div>

      <!-- D216：程序对齐汇总（纯本地，不花 token） -->
      <p v-if="alignSummary.total" class="hint" style="margin:4px 0"
         :style="alignSummary.mismatch ? 'color:#b45309' : 'color:var(--c-muted)'">
        🧭 题目匹配：{{ alignSummary.match }} 匹配 · {{ alignSummary.mismatch }} 疑似错卷 ·
        {{ alignSummary.unknown }} 未确定<template v-if="alignSummary.none"> ·
        {{ alignSummary.none }} 未对齐（旧数据）</template>
        <span v-if="alignSummary.mismatch">
          —— 建议核对 tag 后用现有「改 tag」按钮修正，再重新批阅（仍会出分，不会被阻断）
        </span>
      </p>

      <!-- D173：列头统计，**每项可点做过滤**（替代原来单一的「只看不一致」） -->
      <div v-if="auditMeta?.generatedAt" class="audit-filters">
        <button class="audit-chip" :class="{ on: auditFilter === 'all' }"
                @click="auditFilter = 'all'">全部 {{ auditStats.all }}</button>
        <button class="audit-chip bad" :class="{ on: auditFilter === 'differs' }"
                :title="'审计 tag 与 roster tag 不同（含引擎不敢拍板的待确认）'"
                @click="auditFilter = 'differs'">⚠ tag 不同 {{ auditStats.differs }}</button>
        <button class="audit-chip warn" :class="{ on: auditFilter === 'unknown' }"
                :title="'引擎无法判定，且 tag 相同'"
                @click="auditFilter = 'unknown'">? 待确认 {{ auditStats.unknown }}</button>
        <button class="audit-chip ok" :class="{ on: auditFilter === 'match' }"
                @click="auditFilter = 'match'">✓ 一致 {{ auditStats.match }}</button>
        <button class="audit-chip" :class="{ on: auditFilter === 'notrans' }"
                :title="'未转写 → 不可审核'"
                @click="auditFilter = 'notrans'">未转写 {{ auditStats.notrans }}</button>
      </div>

      <!-- D173：批量操作（**任何行都可勾**） -->
      <div v-if="auditSelectedNames.length" class="audit-bulk">
        <b>已勾选 {{ auditSelectedNames.length }} 人</b>
        <span>批量改 tag 为</span>
        <input v-model="bulkTag" list="audit-tag-options" placeholder="选择或输入 tag"
               style="width:150px" />
        <datalist id="audit-tag-options">
          <option v-for="t in auditTagOptions" :key="t" :value="t" />
        </datalist>
        <button class="btn small primary" :disabled="auditBusy || !bulkTag"
                @click="applyBulkTag()">应用手动 tag</button>
        <button class="btn small" :disabled="auditBusy" @click="applyAuditChecked()"
                title="把勾选学生各自改成他自己的「审计 tag」">采纳审计 tag</button>
        <button class="btn small" :disabled="auditBusy"
                @click="auditChecked = {}">清空勾选</button>
      </div>

      <table class="review-list-table">
        <thead>
          <tr>
            <th style="text-align:left">学生</th><th>tag</th>
            <th title="用转写题目反推的实际 tag（与左列不一致会整行高亮）">🛡 审计 tag</th>
            <th title="程序对齐：学生作答是否就是该 tag 对应的作业纸（不花 token）">🧭 题目匹配</th>
            <th>AI 状态</th>
            <th>AI 分</th><th>人工</th><th>报告模式</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(s, i) in auditRows" :key="s.key" :class="auditRowClass(s)">
            <td>
              <input type="checkbox"
                     :checked="!!auditChecked[String(s.name || '')]"
                     :title="'勾选后可批量改 tag'"
                     @change="auditChecked[String(s.name || '')] = ($event.target as HTMLInputElement).checked" />
              <span style="cursor:pointer" @click="auditDetail = auditOf(s) || { name: s.name, pending: true }">
                {{ s.name }}
              </span>
            </td>
            <td class="c" :title="tagMark(s).why">
              <span :style="{ color: tagMark(s).color }">{{ tagMark(s).text || '—' }}</span>
            </td>
            <td class="c" :class="auditCell(s).cls" :title="auditCell(s).why">
              <span style="cursor:pointer; text-decoration:underline dotted"
                    @click="auditDetail = auditOf(s) || { name: s.name, pending: true }">
                <span :style="{ color: auditCell(s).color }">{{ auditCell(s).text }}</span>
                <span class="hint" style="font-size:11px"> 详情</span>
              </span>
            </td>
            <td class="c" :title="alignCell(s).why">
              <span :style="{ color: alignCell(s).color }">{{ alignCell(s).text }}</span>
            </td>
            <td class="c">
              <b :style="{ color: aiState(s).color }">{{ aiState(s).label }}</b>
              <div v-if="draftOf(s).ai?.at" class="hint" style="font-size:11px">
                {{ draftOf(s).ai.at }}
              </div>
            </td>
            <td class="c">
              <b :style="{ color: scoreOverridden(s) ? '#0369a1' : 'inherit' }">{{ finalScoreOf(s) }}</b>
              <div v-if="draftOf(s).ai?.score != null && scoreOverridden(s)" class="hint" style="font-size:11px">
                AI {{ draftOf(s).ai.score }}
              </div>
            </td>
            <td class="c">{{ draftOf(s).human?.used ? (draftOf(s).human.score ?? '✓') : '—' }}</td>
            <td class="c">{{ reportMode(s) }}</td>
            <td class="c" style="white-space:nowrap">
              <button class="btn small" :disabled="rowBusy !== '' || !curWork"
                      :title="curWork ? '只转写这一名学生（不批语、不打分）' : '请先在 ③ 区选择作业'"
                      @click="runOne(s, 'transcribe')">转写</button>
              <button class="btn small" :disabled="rowBusy !== '' || !curWork"
                      :title="curWork ? '用已有转写批阅这一名学生：出批语 + 打分（不改转写）' : '请先在 ③ 区选择作业'"
                      @click="runOne(s, 'evaluate')">批阅</button>
              <button class="btn small" :disabled="rowBusy !== '' || !curWork"
                      :title="curWork ? '转写 + 批阅（出批语+打分）这一名学生' : '请先在 ③ 区选择作业'"
                      @click="runOne(s, 'full')">
                {{ rowBusy === s.name ? '…' : '转写+批阅' }}
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
      <button class="btn" :disabled="busy" @click="renderReports()">📄 一键生成批阅报告</button>
      <!-- D194：中断后可续做（已有报告的跳过）；重复点也安全 -->
      <button v-if="reportProgress?.exists && (reportProgress.done?.length || 0) > 0
                    && reportProgress.state !== 'done'"
              class="btn" style="border-color:#d97706;color:#b45309"
              :disabled="busy" @click="resumeReports">
        ⏯ 续做报告（已完成 {{ reportProgress.done?.length ?? 0 }}/{{ reportProgress.total ?? '?' }}）
      </button>
      <button v-if="reportProgress?.exists && (reportProgress.failed?.length || 0) > 0"
              class="btn" style="border-color:#dc2626;color:#b91c1c"
              :disabled="busy" @click="retryFailedReports">
        ↻ 只补失败 {{ reportProgress.failed?.length }} 人
      </button>
      <button class="btn" :disabled="busy || versionsBusy" @click="loadReportVersions">
        🕘 报告版本
      </button>
      <!-- D195：明确的重生成/清理入口（避免“以为生成了全部”） -->
      <button class="btn" :disabled="busy" @click="regenerateAllReports">🔁 重新生成全部报告</button>
      <button class="btn" :disabled="busy" @click="cleanupDuplicateReports"
              title="删除不在当前名单/重复学生名的报告文件（只动 reports/，不动草稿与分数）">
        🧹 清理多余报告
      </button>
      <button class="btn" :disabled="busy" @click="compactReportVersions"
              title="每生只保留最新 1 条版本记录（只压缩索引，历史文件保留）">
        🗜 压缩版本历史
      </button>
      <span style="flex:1"></span>
      <!-- D193：上传先看对照表（未批阅/一致/冲突），再决定覆盖，避免盲传 -->
      <button class="btn primary" :disabled="busy || previewBusy"
              @click="openUploadPreview(true)"
              title="优先用本地缓存的平台状态（秒开）；需要最新状态请点右侧「重新读取平台状态」">
        🔍 上传前对照（含平台状态）
      </button>
      <button class="btn" :disabled="busy" @click="uploadAll(false)">⬆⬆ 上传全部批阅（含打分）</button>
      <button class="btn" :disabled="busy" @click="uploadAll(true)">⬆⬆ 强制覆盖上传全部</button>
    </div>
    <p v-if="scopeCheck && (scopeCheck.missingDraft?.length || scopeCheck.duplicateKeys
                           && Object.keys(scopeCheck.duplicateKeys).length)"
       class="hint" style="margin-top:6px; color:#b45309; background:#fffbeb;
                           border:1px solid #fcd34d; border-radius:8px; padding:6px 10px">
      ⚠ 范围核对：本次可用于生成报告的草稿 <b>{{ scopeCheck.studentCount ?? 0 }}</b> 人
      （草稿记录 {{ scopeCheck.draftCount ?? 0 }} 条）。
      <span v-if="scopeCheck.missingDraft?.length">
        表格里另有 <b>{{ scopeCheck.missingDraft.length }}</b> 名学生**没有本地草稿**，
        不会生成报告也不会有分数：{{ scopeCheck.missingDraft.slice(0, 8).join('、') }}
        {{ scopeCheck.missingDraft.length > 8 ? ' …' : '' }}。
        → 先对他们「转写+评阅」或逐生保存批阅后再生成。
      </span>
      <span v-if="scopeCheck.duplicateKeys && Object.keys(scopeCheck.duplicateKeys).length">
        <br>同一学生在草稿里有多个键（会已自动按姓名合并，不再出现重复报告）：
        {{ Object.keys(scopeCheck.duplicateKeys).slice(0, 6).join('、') }}
      </span>
    </p>
    <p v-if="reportProgress?.exists" class="hint" style="margin-top:6px"
       :style="reportProgress.state === 'partial' ? 'color:#b45309' : ''">
      报告生成进度：{{ reportProgress.state === 'done' ? '已完成'
        : (reportProgress.state === 'partial' ? '部分完成（有失败）'
          : (reportProgress.state === 'running' ? '上次中断/仍在进行' : '—')) }}
      · 已生成 {{ reportProgress.done?.length ?? 0 }}/{{ reportProgress.total ?? 0 }} 人
      <span v-if="reportProgress.failed?.length"> · 失败 {{ reportProgress.failed.length }} 人</span>
      <span v-if="reportProgress.skipped?.length"> · 续做跳过 {{ reportProgress.skipped.length }} 人</span>
      <span v-if="reportProgress.updatedAt"> · 更新于 {{ reportProgress.updatedAt }}</span>
      <br>
      中断后可直接再点「📄 一键生成批阅报告」：已完成的学生会**跳过**（内容未变不产生新版本），
      只补做缺失/失败的部分；同一作业重复点击不会并发渲染。
    </p>
    <p class="hint" style="margin-top:6px">
      完整逐生预览（作答图 + 两栏批语 + 旋转/上下位）仍在「作业预览-学习通 → 批阅图片 → 逐生预览」。
    </p>

    <!-- D193：上传对照表（只读；冲突项需再次确认才覆盖） -->
    <div v-if="previewOpen" class="card" style="margin-top:10px; border:1px solid #d97706">
      <h3 style="margin:0 0 6px">上传前对照
        <small style="font-weight:400;color:var(--c-muted)">
          {{ previewCheckedPlatform ? '已读取平台状态（只读）' : '仅本地信息' }}
          · 共 {{ previewRows.length }} 人
        </small>
      </h3>
      <p v-if="previewReadiness?.hint" class="hint"
         style="margin:4px 0; color:#b45309; background:#fffbeb;
                border:1px solid #fcd34d; border-radius:8px; padding:6px 10px">
        {{ previewReadiness.hint }}
        <template v-if="previewReadiness.emptyComment?.length">
          <br>批语文本为空但有报告图（将只传报告图+分数）：
          {{ previewReadiness.emptyComment.slice(0, 8).join('、') }}
          {{ previewReadiness.emptyComment.length > 8 ? ' …' : '' }}
        </template>
        <template v-if="previewReadiness.noReport?.length">
          <br>没有报告图/批语/分数：{{ previewReadiness.noReport.slice(0, 8).join('、') }}
          {{ previewReadiness.noReport.length > 8 ? ' …' : '' }} → 请先「📄 一键生成批阅报告」
        </template>
        <template v-if="previewReadiness.notSubmitted?.length">
          <br>未提交（不上传）：{{ previewReadiness.notSubmitted.slice(0, 8).join('、') }}
          {{ previewReadiness.notSubmitted.length > 8 ? ' …' : '' }}
        </template>
      </p>
      <p v-if="previewCache && previewCheckedPlatform" class="hint"
         style="margin:4px 0"
         :style="previewCache.stale ? 'color:#b45309' : 'color:var(--c-muted)'">
        <template v-if="previewCache.hit">
          📦 平台状态来自本地缓存（{{ previewCache.fetchedAt || '—' }}，
          {{ Math.round((previewCache.ageSec ?? 0) / 60) }} 分钟前；有效期
          {{ Math.round((previewCache.maxAgeSec ?? 1800) / 60) }} 分钟）。
          <span v-if="previewCache.stale">⚠ {{ previewCache.hint }}</span>
          <span v-else>如需最新状态请点「🔍 重新读取平台状态」。</span>
        </template>
        <template v-else>🌐 平台状态为刚刚实时读取，已写入本地缓存。</template>
      </p>
      <p style="margin:6px 0">
        <label class="field" style="display:inline-flex; gap:6px; align-items:center">
          <input type="checkbox" v-model="uploadReportOnly" />
          只上传<b>报告图 + 分数</b>，不再重复上传原始批语文本
          <span class="hint">（推荐：报告图里已经是排版好的批语）</span>
        </label>
      </p>
      <p v-if="(previewRows || []).some(r => r.platformReadError || r.platformScoreUnknown)"
         class="hint" style="margin:4px 0; color:#b45309">
        ⚠ 有 {{ (previewRows || []).filter(r => r.platformReadError || r.platformScoreUnknown).length }}
        名学生的平台分数未能读取（右侧显示“读取失败/未知”）。可点「🔍 重新读取平台状态」重试；
        不影响本地上传（上传时会再读一次平台状态做覆盖判断）。
      </p>
      <p class="hint" style="margin:4px 0">
        可上传 <b>{{ previewSummary.new ?? 0 }}</b> ·
        已一致（跳过）<b>{{ previewSummary.unchanged ?? 0 }}</b> ·
        冲突（需确认）<b style="color:#b45309">{{ previewSummary.conflict ?? 0 }}</b> ·
        无可传内容 <b>{{ previewSummary.skipped ?? 0 }}</b> ·
        失败 <b style="color:#b91c1c">{{ previewSummary.failed ?? 0 }}</b>
      </p>
      <div style="max-height:280px; overflow:auto; border:1px solid var(--c-border); border-radius:8px">
        <table style="width:100%; border-collapse:collapse; font-size:13px">
          <thead>
            <tr style="background:#f6f6f8">
              <th style="text-align:left; padding:4px 8px">学生</th>
              <th style="text-align:left; padding:4px 8px">报告版本</th>
              <th style="text-align:left; padding:4px 8px">本地分数</th>
              <th style="text-align:left; padding:4px 8px">平台状态</th>
              <th style="text-align:left; padding:4px 8px">平台分数</th>
              <th style="text-align:left; padding:4px 8px">提交/就绪</th>
              <th style="text-align:left; padding:4px 8px">决定</th>
              <th style="text-align:left; padding:4px 8px">逐生上传</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in previewRows" :key="r.student">
              <td style="padding:4px 8px">{{ r.student }}</td>
              <td style="padding:4px 8px">
                <code v-if="r.reportVersion">{{ r.reportTag || r.reportVersion }}</code>
                <span v-else style="color:#b45309">未生成</span>
              </td>
              <td style="padding:4px 8px">{{ r.localScore ?? '—' }}</td>
              <td style="padding:4px 8px">{{ r.platformStatus || '—' }}</td>
              <td style="padding:4px 8px" :title="r.platformReadError || ''">
                <template v-if="r.platformScore !== null && r.platformScore !== undefined">
                  {{ r.platformScore }}
                </template>
                <span v-else-if="r.platformReadError" style="color:#b45309">读取失败</span>
                <span v-else-if="r.platformScoreUnknown" style="color:#b45309">未知</span>
                <span v-else>—</span>
              </td>
              <td style="padding:4px 8px" :title="r.readyReason || ''">
                <span v-if="r.readyState==='ready'" style="color:#15803d">
                  已提交·可传<template v-if="r.hasImage">（报告图）</template>
                </span>
                <span v-else-if="r.readyState==='no-report'"
                      style="color:#b45309;font-weight:600">已提交·无报告图</span>
                <span v-else-if="r.readyState==='no-comment'"
                      style="color:#b45309;font-weight:600">已提交·无内容</span>
                <span v-else-if="r.readyState==='no-draft'"
                      style="color:#b45309;font-weight:600">已提交·无草稿</span>
                <span v-else-if="r.readyState==='not-submitted'" style="color:#6b7280">未提交</span>
                <span v-else>{{ r.platformStatus || '—' }}</span>
              </td>
              <td style="padding:4px 8px" :title="r.reason || ''">
                <span v-if="r.decision==='new'" style="color:#15803d">可上传</span>
                <span v-else-if="r.decision==='unchanged'" style="color:#6b7280">一致·跳过</span>
                <span v-else-if="r.decision==='conflict'" style="color:#b45309;font-weight:600">冲突·需确认</span>
                <span v-else-if="r.decision==='skipped'" style="color:#6b7280">无可传内容</span>
                <span v-else>{{ r.decision || '—' }}</span>
              </td>
              <td style="padding:4px 8px; white-space:nowrap">
                <button class="btn small"
                        :disabled="oneUploadBusy !== '' || busy
                          || r.readyState === 'not-submitted'
                          || r.readyState === 'no-report'
                          || r.readyState === 'no-comment'
                          || r.readyState === 'no-draft'"
                        :title="r.readyState === 'not-submitted' ? '未提交，无需上传'
                          : (r.readyState === 'no-report' || r.readyState === 'no-comment'
                             || r.readyState === 'no-draft')
                            ? '没有可上传内容，请先生成报告/补批阅'
                            : (r.hasImage ? '上传报告图 + 分数' : '上传批语 + 分数')"
                        @click="uploadOneStudent(r)">上传</button>
                <button class="btn small" style="margin-left:4px"
                        :disabled="oneUploadBusy !== '' || busy
                          || r.readyState === 'not-submitted'
                          || r.readyState === 'no-report'
                          || r.readyState === 'no-comment'
                          || r.readyState === 'no-draft'"
                        title="只填入批语/分数并读回校验，不点提交（安全验证）"
                        @click="uploadOneStudent(r, { dryRun: true })">演练</button>
                <button class="btn small" style="margin-left:4px; border-color:#b45309; color:#b45309"
                        :disabled="oneUploadBusy !== '' || busy
                          || r.readyState === 'not-submitted'
                          || r.readyState === 'no-report'
                          || r.readyState === 'no-comment'
                          || r.readyState === 'no-draft'"
                        title="清空平台上该生原批语/原报告图，替换为本地报告图与分数"
                        @click="uploadOneStudent(r, { overwrite: true })">覆盖</button>
                <span v-if="oneUploadResult[r.student]" class="hint" style="margin-left:6px">
                  {{ oneUploadResult[r.student] }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p style="margin-top:8px">
        <button class="btn primary" :disabled="previewBusy || busy" @click="confirmUploadFromPreview">
          按对照表上传
        </button>
        <button class="btn" style="margin-left:8px" :disabled="previewBusy"
                @click="openUploadPreview(false)">仅本地重算</button>
        <button class="btn" style="margin-left:8px" :disabled="previewBusy"
                @click="openUploadPreview(true, { force: true })">🔍 重新读取平台状态</button>
        <button class="btn" style="margin-left:8px" @click="previewOpen=false">关闭</button>
        <span v-if="previewBusy" class="hint" style="margin-left:8px">读取中…</span>
      </p>
    </div>

    <!-- D197：清理结果（明确“是否完成”，含索引同步清理条数） -->
    <div v-if="cleanupResult" class="card" style="margin-top:10px"
         :style="cleanupResult.ok === false ? 'border-color:#dc2626' : 'border-color:#86efac'">
      <h3 style="margin:0 0 6px">
        {{ cleanupResult.ok === false ? '清理失败'
          : (cleanupResult.dryRun ? '清理核对（未删除）' : '清理完成') }}
        <small style="font-weight:400;color:var(--c-muted)">
          {{ cleanupResult.ok === false ? ''
            : `报告文件 ${cleanupResult.count ?? 0} 个 · 版本索引 ${cleanupResult.indexBefore ?? '?'} → ${cleanupResult.indexAfter ?? '?'} 条` }}
        </small>
      </h3>
      <p v-if="cleanupResult.ok === false" style="color:#b91c1c; margin:4px 0">
        {{ cleanupResult.error }}
      </p>
      <p v-else-if="cleanupResult.hint" style="margin:4px 0">{{ cleanupResult.hint }}</p>
      <div v-else-if="(cleanupResult.removed || []).length"
           style="max-height:160px; overflow:auto; font-size:13px">
        <div v-for="(x, i) in (cleanupResult.removed || []).slice(0, 40)" :key="i">
          · {{ x.name }} <span class="hint">{{ x.reason }}</span>
        </div>
        <div v-if="(cleanupResult.removed || []).length > 40" class="hint">
          …共 {{ (cleanupResult.removed || []).length }} 项
        </div>
      </div>
      <p v-else class="hint" style="margin:4px 0">没有需要清理的内容。</p>
      <p style="margin-top:6px">
        <button class="btn" @click="cleanupResult = null">关闭</button>
        <button class="btn" style="margin-left:8px" @click="loadReportVersions">查看报告版本</button>
      </p>
    </div>

    <!-- D193：报告版本历史（内容哈希；同一内容不重复产生版本） -->
    <div v-if="versionsOpen" class="card" style="margin-top:10px">
      <h3 style="margin:0 0 6px">报告版本
        <small style="font-weight:400;color:var(--c-muted)">
          {{ versionsBusy ? '读取中…'
            : `名单 ${versionMeta?.rosterCount ?? 0} 人 / 已生成 ${versionMeta?.reportedCount ?? 0} 人`
              + ` / 未生成 ${versionMeta?.missingReport?.length ?? 0} 人`
              + ` · 版本记录 ${versionMeta?.totalInIndex ?? versionRoster.length} 条` }}
          · 版本号=报告内容哈希前 6 位
        </small>
      </h3>
      <p v-if="(versionMeta?.missingReport || []).length" class="hint"
         style="margin:4px 0; color:#b45309; background:#fffbeb;
                border:1px solid #fcd34d; border-radius:8px; padding:6px 10px">
        逐生审核名单里有 {{ (versionMeta?.missingReport || []).length }} 名学生**还没有报告**：
        {{ (versionMeta?.missingReport || []).slice(0, 10).join('、') }}
        {{ (versionMeta?.missingReport || []).length > 10 ? ' …' : '' }}
        → 点「📄 一键生成批阅报告」补生成（已有报告的会跳过）。
      </p>
      <div style="max-height:240px; overflow:auto">
        <table style="width:100%; border-collapse:collapse; font-size:13px">
          <thead>
            <tr style="background:#f6f6f8">
              <th style="text-align:left; padding:4px 8px">学生</th>
              <th style="text-align:left; padding:4px 8px">报告状态</th>
              <th style="text-align:left; padding:4px 8px">最新版本</th>
              <th style="text-align:left; padding:4px 8px">生成时间</th>
              <th style="text-align:left; padding:4px 8px">类型</th>
              <th style="text-align:left; padding:4px 8px">分数</th>
              <th style="text-align:left; padding:4px 8px">版本数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(v, i) in versionTableRows" :key="`${v.student}-${i}`">
              <td style="padding:4px 8px">{{ v.student }}</td>
              <td style="padding:4px 8px">
                <span v-if="v.hasReport !== false" style="color:#15803d">已生成</span>
                <span v-else style="color:#b45309;font-weight:600">未生成</span>
              </td>
              <td style="padding:4px 8px">
                <code v-if="v.tag || v.version">{{ v.tag || v.version }}</code>
                <span v-else style="color:#9ca3af">—</span>
              </td>
              <td style="padding:4px 8px">{{ v.at || '—' }}</td>
              <td style="padding:4px 8px">{{ v.kind || '—' }}</td>
              <td style="padding:4px 8px">{{ v.score ?? '—' }}</td>
              <td style="padding:4px 8px">{{ v.versionCount ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p style="margin-top:6px">
        <button class="btn" :disabled="versionsBusy" @click="loadReportVersions">刷新</button>
        <button class="btn" style="margin-left:8px" @click="versionsOpen=false">关闭</button>
      </p>
    </div>

    <!-- D130-T9：评阅规则卡（教师可见/可改评分口径；此前完全硬编码） -->
    <GradingRulesCard :engine-addr="props.engineAddr" :token="props.token"
                      @notify="(m) => { progress = m }" />

    <!-- D153：教师总结报告 + 跨作业趋势已搬到「题库AI+」选项卡（支持多选班级/作业包/tag） -->
    <p class="hint" style="margin-top:12px">
      📊 教师总结报告与知识点趋势已移至顶部 <b>「题库AI+」</b> 选项卡 ——
      那里可以<b>多选班级 / 作业包 / tag</b>，看更宏观的情况。
    </p>

    <!-- D140：Atopia 已独立为顶层选项卡，这里只留指路提示（避免双入口） -->
    <p class="hint" style="margin-top:12px">
      🤖 想让 AI 用本项目工具（多轮对话 / 读题库 / 抽知识点 / 写回）？
      请到顶部 <b>Atopia</b> 选项卡 —— 每次调用都会经过安全 Gate。
    </p>
  </div>

    <!-- D152：⑦ 区已整体搬到「题库AI+」选项卡（避免双入口） -->
    <h3 style="margin-top:14px">⑦ 题库 AI 作答</h3>
    <p class="hint">
      🤖 题库 AI 作答（参考解答 / 评阅要点 / 知识点标注）已移至顶部
      <b>「题库AI+」</b> 选项卡 —— 那里能力更全（题号多选 / 模型 / 模板 / 一次性完成三件事）。
    </p>


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

    <!-- D173：tag 判定详情（逐题对照 + 判据 + 人工确认 + 历史） -->
    <div v-if="auditDetail" class="mask" @click.self="auditDetail = null">
      <div class="dlg audit-dlg">
        <div class="audit-dlg-head">
          <h4 style="margin:0">🛡 {{ auditDetail.name }} —— tag 判定详情</h4>
          <div class="audit-nav">
            <button class="btn small" :disabled="auditBusy" @click="auditDetailStep(-1)">⟨ 上一位</button>
            <button class="btn small" :disabled="auditBusy" @click="auditDetailStep(1)">下一位 ⟩</button>
            <button class="btn small" @click="auditDetail = null">✕</button>
          </div>
        </div>

        <!-- 未审计 -->
        <p v-if="auditDetail.pending" class="hint">
          该学生还没有审计结果。请先点「🛡 运行 tag 审计」。
        </p>

        <template v-else>
          <!-- ① 结论 -->
          <table class="audit-three">
            <tr><th>roster tag</th><th>当前 roster</th><th>🛡 实际（审计）tag</th><th>判定</th></tr>
            <tr>
              <td>{{ auditDetail.rosterTag ?? '—' }}
                <span class="hint" style="display:block;font-size:11px">
                  {{ auditDetail.rosterTagSource === 'snapshot' ? '包快照（冻结）' : '当前 roster' }}
                </span>
              </td>
              <td>{{ auditDetail.currentRosterTag ?? '—' }}</td>
              <td :style="{ fontWeight: 600,
                            color: auditDetail.tagDiffers ? '#b91c1c' : '#15803d' }">
                {{ auditDetail.auditTag ?? '?' }}
                <span class="hint" style="display:block;font-size:11px">
                  得分 {{ auditDetail.score }} · 领先 {{ auditDetail.margin }} · 置信 {{ auditDetail.confidence }}
                </span>
              </td>
              <td>
                <b v-if="auditDetail.tagDiffers" style="color:#b91c1c">tag 不同</b>
                <b v-else-if="auditDetail.verdict === 'match'" style="color:#15803d">一致</b>
                <b v-else style="color:#6b7280">无法判定</b>
              </td>
            </tr>
          </table>
          <p class="hint" style="margin:8px 0">{{ auditDetail.reason }}</p>
          <p v-if="auditDetail.legacyFormat" class="audit-warn">
            ⚠ 这份转写是**旧格式**（只有 markdown、没有结构化 items），题干是靠正则切的，可靠性低。
            建议对该生重新「转写」后再审计。
          </p>
          <p v-if="auditDetail.linkMissing?.length" class="audit-warn">
            第 {{ auditDetail.linkMissing.join('、') }} 题没找到印刷题干（学生未抄题 / OCR 丢失），
            这几题**未计入**比对。
          </p>

          <!-- ② 怎么判的（判据） -->
          <details class="audit-why" open>
            <summary><b>怎么判的（判据）</b></summary>
            <ul class="audit-why-list">
              <li>方法：<code>{{ auditDetail.why?.method || 'ngram-v1' }}</code></li>
              <li>**只比对题干**（转写的 <code>printed_question</code>），不看作答对错</li>
              <li>逐题与每张作业纸的每一题做**最优配对**，再取平均</li>
              <li>相似度 = {{ auditDetail.why?.bigramWeight }} × 字面(2/3-gram Dice)
                  + {{ auditDetail.why?.numberWeight }} × 数值常量重合</li>
              <li>高置信需：得分 ≥ {{ auditDetail.why?.minScore }} 且领先次优 ≥ {{ auditDetail.why?.marginMin }}</li>
              <li>低于 minScore 或领先不足 → 一律「无法判定」（**宁可标问号，也不误标红**）</li>
            </ul>
            <table v-if="auditDetail.why?.perPaperTotals?.length" class="audit-pairs">
              <thead><tr><th>作业纸</th><th>tag</th><th>合计得分</th><th>题数</th></tr></thead>
              <tbody>
                <tr v-for="(t, k) in auditDetail.why.perPaperTotals" :key="k">
                  <td><code>{{ t.padId }}</code></td><td>{{ t.tag }}</td>
                  <td :style="{ color: t.tag === auditDetail.auditTag ? '#15803d' : 'inherit',
                                fontWeight: t.tag === auditDetail.auditTag ? 600 : 400 }">
                    {{ (t.score * 100).toFixed(1) }}%
                  </td>
                  <td>{{ t.questionCount ?? '—' }}</td>
                </tr>
              </tbody>
            </table>
          </details>

          <!-- ③ 逐题对照（一题一行） -->
          <h5 style="margin:14px 0 6px">逐题对照（{{ auditDetail.pairs?.length || 0 }} 题）</h5>
          <div v-if="!auditDetail.pairs?.length" class="hint">没有可对照的题目。</div>
          <div v-for="(p, k) in auditDetail.pairs" :key="k" class="audit-q">
            <div class="audit-q-head">
              <b>学生第 {{ p.no }} 题</b>
              <span v-if="p.best?.tag" class="hint" style="margin-left:8px">
                最像：{{ p.best.tag }} 卷 第 {{ p.best.paperNo }} 题
                （{{ ((p.best.score || 0) * 100).toFixed(1) }}%）
              </span>
            </div>
            <div class="audit-stem">
              <span class="audit-stem-label">转写的题干</span>
              <span>{{ p.studentStem || '（未识别到印刷题干）' }}</span>
            </div>
            <table class="audit-pairs">
              <thead>
                <tr><th>作业纸</th><th>题号</th><th>相似度</th><th>拆解</th><th>该题题干</th></tr>
              </thead>
              <tbody>
                <tr v-for="(pp, j) in p.perPaper || []" :key="j"
                    :style="{ background: p.best?.tag === pp.tag ? '#f0fdf4' : 'transparent' }">
                  <td>{{ pp.tag }}</td>
                  <td>{{ pp.paperNo }}</td>
                  <td :style="{ color: pp.score >= 0.75 ? '#15803d'
                                : pp.score >= 0.45 ? '#a16207' : '#b91c1c', fontWeight: 600 }">
                    {{ (pp.score * 100).toFixed(1) }}%
                  </td>
                  <td class="hint" style="font-size:11px; white-space:nowrap"
                      :title="'共同数值：' + ((pp.detail?.numbersShared || []).join('、') || '无')">
                    字面 {{ ((pp.detail?.literal || 0) * 100).toFixed(0) }}%
                    · 数值 {{ ((pp.detail?.number || 0) * 100).toFixed(0) }}%
                  </td>
                  <td style="text-align:left; font-size:12px">{{ pp.paperStem }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- ④ 人工确认（手动改 tag） -->
          <h5 style="margin:14px 0 6px">人工确认</h5>
          <div class="audit-manual">
            <span>改 tag 为</span>
            <input v-model="auditEditTag" list="audit-tag-options" placeholder="选择或输入 tag"
                   style="width:150px" />
            <button class="btn small primary" :disabled="auditBusy || auditEditTag === (auditDetail.rosterTag ?? '')"
                    @click="saveManualTag()">保存并应用</button>
            <button v-if="auditDetail.auditTag && auditDetail.auditTag !== auditDetail.rosterTag"
                    class="btn small" :disabled="auditBusy"
                    @click="applyAuditOne({ name: auditDetail.name }, auditDetail.auditTag)">
              采纳审计 tag（{{ auditDetail.auditTag }}）
            </button>
            <button v-if="(auditDetail.tagHistory?.length || 0) > 0" class="btn small"
                    :disabled="auditBusy" @click="undoStudentTag(auditDetail.name)">
              ↩ 撤销此人最近一次修改
            </button>
          </div>
          <p class="hint" style="margin:4px 0 0">
            改 tag 会**立即写盘并记录历史**；已批阅结果不会自动重算。
          </p>

          <!-- ⑤ 该生的 tag 变更历史 -->
          <details v-if="(auditDetail.tagHistory?.length || 0) > 0" class="audit-why" open
                   style="margin-top:10px">
            <summary><b>tag 变更历史（{{ auditDetail.tagHistory.length }} 条）</b></summary>
            <table class="audit-pairs">
              <thead><tr><th>时间</th><th>从</th><th>到</th><th>来源</th><th>备注</th></tr></thead>
              <tbody>
                <tr v-for="(h, k) in [...auditDetail.tagHistory].reverse()" :key="k">
                  <td>{{ h.at }}</td><td>{{ h.from || '（空）' }}</td><td>{{ h.to || '（空）' }}</td>
                  <td>{{ h.reason === 'undo-student' ? '撤销' : (h.reason === 'audit-apply' ? '采纳审计'
                        : (h.reason === 'manual-batch' ? '批量手动' : '手动')) }}</td>
                  <td>{{ h.note || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </details>
        </template>

        <div class="audit-actions">
          <button class="btn small" @click="auditDetail = null">关闭</button>
        </div>
      </div>
    </div>

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

/* D172：tag 审计 */
.audit-bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
             margin: 6px 0; padding: 6px 8px; background: #f8fafc;
             border: 1px dashed var(--c-border); border-radius: 8px; }
/* 不一致行整行高亮（教师要求：方便检查） */
.review-list-table tbody tr.row-audit-bad { background: #fef2f2; }
.review-list-table tbody tr.row-audit-bad:hover { background: #fee2e2; }
.review-list-table tbody tr.row-audit-bad td:first-child {
  box-shadow: inset 3px 0 0 #dc2626;
}
.audit-dlg { width: min(720px, 94vw); max-height: 86vh; overflow: auto; }
.audit-three, .audit-pairs { width: 100%; border-collapse: collapse; margin-top: 6px; }
.audit-three th, .audit-three td, .audit-pairs th, .audit-pairs td {
  border: 1px solid var(--c-border); padding: 5px 8px; font-size: 13px; text-align: center; }
.audit-three th { background: #eef2ff; }
.audit-pairs th { background: #f1f5f9; }
.audit-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 12px; }

/* D173：过滤 chip / 批量条 / 详情页 */
.audit-filters { display: flex; gap: 6px; flex-wrap: wrap; margin: 4px 0 8px; }
.audit-chip { border: 1px solid var(--c-border); background: #fff; border-radius: 999px;
              padding: 3px 10px; font-size: 12px; cursor: pointer; }
.audit-chip.on { border-color: #4f46e5; background: #eef2ff; font-weight: 600; }
.audit-chip.bad.on { border-color: #dc2626; background: #fef2f2; color: #b91c1c; }
.audit-chip.warn.on { border-color: #d97706; background: #fffbeb; color: #a16207; }
.audit-chip.ok.on { border-color: #16a34a; background: #f0fdf4; color: #15803d; }
.audit-bulk { display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
              padding: 6px 8px; margin-bottom: 6px; background: #eef2ff;
              border: 1px solid #c7d2fe; border-radius: 8px; font-size: 13px; }
.audit-dlg-head { display: flex; justify-content: space-between; align-items: center;
                  gap: 8px; margin-bottom: 8px; }
.audit-nav { display: flex; gap: 6px; }
.audit-warn { background: #fffbeb; border: 1px solid #fde68a; border-radius: 6px;
              padding: 6px 8px; font-size: 12px; color: #92400e; margin: 6px 0; }
.audit-why { margin-top: 10px; border: 1px solid var(--c-border); border-radius: 8px;
             padding: 8px 10px; background: #fafafa; }
.audit-why summary { cursor: pointer; font-size: 13px; }
.audit-why-list { margin: 6px 0; padding-left: 20px; font-size: 12px; line-height: 1.7; }
.audit-q { border: 1px solid var(--c-border); border-radius: 8px; padding: 8px;
           margin-bottom: 8px; }
.audit-q-head { font-size: 13px; margin-bottom: 6px; }
.audit-stem { font-size: 12px; background: #f8fafc; border-radius: 6px;
              padding: 6px 8px; margin-bottom: 6px; line-height: 1.6; }
.audit-stem-label { display: inline-block; min-width: 84px; color: #6b7280; }
.audit-manual { display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
                font-size: 13px; }
</style>

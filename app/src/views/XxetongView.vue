<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import type { XxtTargetsDiff, XxtWork, XxtWorksCourse } from '../lib/engineClient'
import {
  clearXxtRuns, clearXxtTargetsHistory, deleteXxtRun, fetchXxtLoginJob, fetchXxtNoticeAttachments,
  fetchXxtFreshness, fetchXxtReviewIndex, fetchXxtReviewProbeLatest, fetchXxtReviewStudents,
  fetchXxtReviewWork, fetchXxtRun, fetchXxtRuns, fetchXxtStatus, fetchXxtStorage, fetchXxtTargets,
  fetchXxtWorks, importXxtRun, pruneXxtReview, pruneXxtRuns, startXxtDiscover,
  startXxtDiscoverWorks, startXxtExtract, startXxtExtractTargets, startXxtLogin,
  startXxtNoticeSend,
  deleteXxtReviewWork, purgeXxtReviewWork, startXxtReviewDownload, startXxtReviewProbe,
  xxtReviewFileUrl,
} from '../lib/engineClient'
import type { XxtNoticeAttachment, XxtNoticeTargetCourse, XxtReviewImageWork, XxtReviewManifestStudent, XxtReviewProbe,
  XxtReviewStudent, XxtStorageStats } from '../lib/engineClient'
import { useSettingsStore } from '../stores/settings'
import { useXxtJobsStore } from '../stores/xxtJobs'
import ProcessStreamView from '../components/ProcessStreamView.vue'

/* 学习通 tab（D63 T7/T8 实装，docs/16 §20）：
 * - 登录卡：QR 框（/xxt/qr）↔ 头像（verdict=alive 时 data-URL）；
 * - 列表：/xxt/runs 最新 run 的 全 course 分组列表，组头 sticky、每列表独立滚动；
 * - 行操作：置顶(≤10 可调)/移出/刷新/从学习通恢复（恢复=仅回放最近 run JSON，零网络）。
 * 写操作：D77 起发公告白名单开放；批阅回传仍冻结。   */

const settings = useSettingsStore()
const xxtJobs = useXxtJobsStore()
const engUrl = computed(() => settings.engineUrl)
const tok = computed(() => settings.engineToken)

/* ---------- 登录卡 ---------- */
const verdict = ref<'alive' | 'dead' | 'unknown' | string>('unknown')
const avatar = ref<string | null>(null)
const qrcode = ref<string>('')
const qrLoading = ref(false)
const loginHint = ref('')

let loginTimer: number | undefined
let loginSeq = 0
let loginJobId = ''
let qrReady = false
let qrStartedAt = 0
let loginJobCheckedAt = 0
let extractTimer: number | undefined

function stopLoginPolling() {
  if (loginTimer !== undefined) {
    window.clearTimeout(loginTimer)
    loginTimer = undefined
  }
}

async function refreshStatus() {
  try {
    const r = await fetchXxtStatus(engUrl.value, tok.value)
    verdict.value = r.verdict
    avatar.value = r.avatar_dataurl || null
    if (r.verdict === 'alive') {
      loginHint.value = `已登录（体检 ${r.info?.checked_at || ''}；storage 已回写续期）`
    } else if (r.verdict === 'dead') {
      loginHint.value = `会话失效${(r.info?.reasons || []).join('，')}——请扫码`
    } else {
      const why = (r.info?.reasons || []).join('，')
      loginHint.value = why.includes('playwright')
        ? '引擎缺 playwright——请到「设置中心 → Playwright（学习通提取）」一键联网安装'
        : '引擎未记录会话（未扫码登录），可点上方「扫码登录」'
    }
  } catch {
    verdict.value = 'unknown'
    loginHint.value = '引擎未在线（设置中心可改 engine 地址）'
  }
}

function buildQrUrl(): string {
  const base = engUrl.value.replace(/\/+$/, '') || ''
  const u = new URL('/xxt/qr', base + '/')
  if (tok.value) u.searchParams.set('token', tok.value)
  u.searchParams.set('t', String(Date.now()))
  return u.toString()
}

/** 预加载探针：只有 engine 真正返回可解码的 QR 才把 URL 交给 <img>，避免破图。 */
function probeQr(url: string): Promise<boolean> {
  return new Promise((resolve) => {
    const im = new Image()
    im.onload = () => resolve(true)
    im.onerror = () => resolve(false)
    im.src = url
  })
}

async function startScan() {
  const run = ++loginSeq
  stopLoginPolling()
  qrcode.value = ''
  qrReady = false
  qrLoading.value = true
  qrStartedAt = Date.now()
  loginJobCheckedAt = 0
  loginHint.value = '已发起扫码任务：正在生成二维码……'
  try {
    loginJobId = await startXxtLogin(engUrl.value, tok.value)
    void startQrPolling(run)
  } catch (e) {
    qrLoading.value = false
    loginHint.value = `启动失败：${String(e)}（检查引擎在线/playwright 安装项）`
  }
}

async function startQrPolling(run: number) {
  const tick = async () => {
    if (run !== loginSeq) return
    await refreshStatus()
    if (run !== loginSeq) return
    if (verdict.value === 'alive') {
      qrcode.value = ''
      qrLoading.value = false
      stopLoginPolling()
      return
    }
    // D68：二维码已显示后，若 CLI 登录任务已失败（如超时/检测异常），也要收掉破图态并给出原因。
    if (loginJobId && Date.now() - loginJobCheckedAt > 5000) {
      loginJobCheckedAt = Date.now()
      try {
        const job = await fetchXxtLoginJob(engUrl.value, tok.value, loginJobId)
        if (job.status === 'failed') {
          const line = (job.lines || []).slice(-1)[0] || `任务状态：${job.status}`
          qrcode.value = ''
          qrReady = false
          qrLoading.value = false
          loginHint.value = `扫码登录失败：${line}`
          stopLoginPolling()
          return
        }
      } catch { /* 任务状态查询失败时继续等 QR/体检 */ }
    }
    if (!qrReady) {
      const url = buildQrUrl()
      if (await probeQr(url)) {
        if (run !== loginSeq) return
        qrcode.value = url
        qrReady = true
        qrLoading.value = false
        loginHint.value = '二维码已就绪，请用学习通 App 扫描'
      } else if (loginJobId && Date.now() - qrStartedAt > 12000) {
        try {
          const job = await fetchXxtLoginJob(engUrl.value, tok.value, loginJobId)
          if (job.status !== 'running') {
            const line = (job.lines || []).slice(-1)[0] || `任务状态：${job.status}`
            qrLoading.value = false
            loginHint.value = `二维码生成失败：${line}`
            stopLoginPolling()
            return
          }
        } catch { /* 任务状态查询失败时继续重试 QR */ }
      } else {
        loginHint.value = '二维码生成中，请稍候……'
      }
    } else {
      loginHint.value = '二维码已就绪，请用学习通 App 扫描'
    }
    if (run === loginSeq) {
      loginTimer = window.setTimeout(tick, qrReady ? 3000 : 1500)
    }
  }
  await tick()
}

/* ---------- 列表（最新 run） ---------- */
interface WorkRow {
  workId: string; name: string; answer_window?: string
  pending?: number | null; submitted?: number | null; unsubmitted?: number | null
  submitted_names?: { name: string; status?: string }[]
  unsubmitted_names?: string[]; sub_not_in_roster?: string[]
  anchor?: { ok?: boolean; notes?: string[]; roster_delta?: number }
}
interface ClassRow { name: string; classId: string; status: string; works: WorkRow[]; roster?: { total?: number | null } ; notes?: string[] }
interface CourseRow { name: string; courseId: string; classes: ClassRow[] }
const runs = ref<{ run_id: string; ts_start?: string; ts_end?: string; classes?: number; works?: number; failures?: number }[]>([])
const extracting = computed(() => xxtJobs.extractJobId !== '')
const extractSubmitting = ref(false)
const curRun = ref<string | null>(null)
const courses = ref<CourseRow[]>([])
const loadSteps = ref<{ action: string; detail?: string; title?: string; url?: string; ts?: string; shot?: string }[]>([])
const loadingRun = ref(false)
const runMsg = ref('')
const filterMode = ref<'all' | 'hasWorks' | 'empty' | 'fail'>('all')  // T8
/* ---- §24 通知查看卡（只读；数据=最新 run 的 notices[]） ---- */
interface NoticeItem { text: string; href: string }
const noticeClsFilter = ref<string>('')
function noticeOf(cl: ClassRow): NoticeItem[] { return (cl as unknown as { notices?: NoticeItem[] }).notices || [] }
const noticeClasses = computed(() =>
  courses.value.flatMap(c => c.classes).filter(cl => noticeOf(cl).length > 0))
const noticeRows = computed(() => {
  const pool = noticeClasses.value.filter(cl => !noticeClsFilter.value || cl.classId === noticeClsFilter.value)
  const rows: { cls: string; title: string; when: string; read?: string; ratio?: number }[] = []
  for (const cl of pool) {
    for (const it of noticeOf(cl)) {
      const t = it.text || ''
      const wm = t.match(/(\d{2}-\d{2} \d{2}:\d{2}|\d{4}-\d{2}-\d{2})/)
      const rm = t.match(/已读：(\d+)\/(\d+)/)
      rows.push({ cls: cl.name, title: t.replace(/\s*\d{2}-\d{2} \d{2}:\d{2}.*$/, '').slice(0, 60),
                  when: wm ? wm[1] : '', read: rm ? `${rm[1]}/${rm[2]}` : undefined,
                  ratio: rm ? Number(rm[1]) / Math.max(1, Number(rm[2])) : undefined })
    }
  }
  return rows
})

/* 列表项可见性（T8） */
const pinned = ref<string[]>(JSON.parse(localStorage.getItem('xxt-pinned') || '[]') as string[])
const pinCap = ref(Number(localStorage.getItem('xxt-pinCap') || 10) || 10)
const removed = ref<string[]>(JSON.parse(localStorage.getItem('xxt-removed') || '[]') as string[])

function rowBg(cl: ClassRow, idx: number): string {
  if (isPinned(cl)) return 'var(--c-pin-bg, #fffbe8)'
  return idx % 2 === 1 ? 'var(--c-zebra, #f7f9fc)' : 'transparent'
}
function key(cl: ClassRow): string { return `${cl.classId}` }
function isPinned(cl: ClassRow): boolean { return pinned.value.includes(cl.classId) }
function isRemoved(cl: ClassRow): boolean { return removed.value.includes(key(cl)) }

function persistLocal() {
  localStorage.setItem('xxt-pinned', JSON.stringify(pinned.value))
  localStorage.setItem('xxt-removed', JSON.stringify(removed.value))
  localStorage.setItem('xxt-pinCap', String(pinCap.value))
}

function togglePin(cl: ClassRow) {
  const k = cl.classId
  if (isPinned(cl)) {
    pinned.value = pinned.value.filter(x => x !== k)
  } else {
    if (pinned.value.length >= pinCap.value) {
      runMsg.value = `置顶已达上限 ${pinCap.value}（上限可在下方调整）`
      return
    }
    pinned.value.push(k)
  }
  persistLocal()
}

function removeRow(cl: ClassRow) {
  if (!isRemoved(cl)) removed.value.push(key(cl))
  persistLocal()
}

function restoreRemoved() {
  removed.value = []          // 「从学习通恢复列表」：按 20.3 决议=仅回放最近 run JSON（零网络）
  runMsg.value = '已恢复全部行（回放最近 run）'
  persistLocal()
}

const storageStats = ref<XxtStorageStats>({})
const storageMsg = ref('')

async function loadStorageStats() {
  try { storageStats.value = await fetchXxtStorage(engUrl.value, tok.value) } catch { /* noop */ }
}
function fmtBytes(n?: number): string {
  const b = n || 0
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`
  return `${(b / 1024 / 1024).toFixed(1)} MB`
}
async function pruneRuns() {
  const maxMb = ((storageStats.value.max_bytes || 0) / 1024 / 1024).toFixed(0)
  if (!confirm(`按容量清理最旧的 run？规则：总数不超过 ${storageStats.value.max_count || 1000} 条，`
    + `总大小不超过 ${maxMb || 50} MB（先到先删）。`)) return
  try {
    const r = await pruneXxtRuns(engUrl.value, tok.value)
    storageMsg.value = `已清理 ${r.removed_count || 0} 条旧 run`
    await refreshRuns()
  } catch (e) { storageMsg.value = `清理失败：${String(e)}` }
}

async function refreshRuns() {
  loadingRun.value = true
  runMsg.value = ''
  try {
    runs.value = await fetchXxtRuns(engUrl.value, tok.value)
    void loadStorageStats()
    if (!runs.value.length) { runMsg.value = '暂无 run（引擎侧 xxt extract run 未产出）'; return }
    await loadRun(runs.value[0].run_id)
  } catch (e) {
    runMsg.value = `引擎不可达：${String(e)}`
  } finally { loadingRun.value = false }
}

/** D74-6：run JSON 防御性归一，任何缺字段的坏数据都不允许拖垮整页渲染。 */
function normalizeCourses(raw: unknown): CourseRow[] {
  if (!Array.isArray(raw)) return []
  const out: CourseRow[] = []
  for (const c of raw) {
    if (!c || typeof c !== 'object') continue
    const co = c as Record<string, unknown>
    const classes: ClassRow[] = []
    const clsRaw = Array.isArray(co['classes']) ? co['classes'] : []
    for (const cl of clsRaw) {
      if (!cl || typeof cl !== 'object') continue
      const clo = cl as Record<string, unknown>
      const clRow: ClassRow = {
        name: String(clo['name'] ?? clo['classId'] ?? '未命名班级'),
        classId: String(clo['classId'] ?? ''),
        status: String(clo['status'] ?? 'unknown'),
        works: Array.isArray(clo['works']) ? (clo['works'] as WorkRow[]) : [],
        roster: (clo['roster'] as { total?: number | null } | undefined) ?? undefined,
        notes: Array.isArray(clo['notes']) ? (clo['notes'] as string[]) : [],
      }
      ;(clRow as unknown as { notices?: unknown }).notices =
        Array.isArray(clo['notices']) ? clo['notices'] : []
      classes.push(clRow)
    }
    out.push({
      name: String(co['name'] ?? co['courseId'] ?? '未命名课程'),
      courseId: String(co['courseId'] ?? ''),
      classes,
    })
  }
  return out
}

async function loadRun(id: string) {
  loadingRun.value = true
  try {
    const raw = (await fetchXxtRun(engUrl.value, tok.value, id)) as Record<string, unknown>
    if (!raw || typeof raw !== 'object' || !Array.isArray(raw['courses'])) {
      throw new Error('该条目不是有效的 run（可能已损坏或不是 run）')
    }
    curRun.value = String(raw['run_id'] || id)
    courses.value = normalizeCourses(raw['courses'])
    loadSteps.value = ((raw['steps'] as unknown[]) || []) as typeof loadSteps.value
    runMsg.value = `run ${curRun.value} 已载入（${courses.value.reduce((a, c) => a + c.classes.length, 0)} 班）`
  } catch (e) {
    runMsg.value = `载入失败：${String(e)}`
  } finally { loadingRun.value = false }
}

function stopExtractPolling() {
  if (extractTimer !== undefined) {
    window.clearTimeout(extractTimer)
    extractTimer = undefined
  }
}

function pollExtractJob(jobId: string) {
  stopExtractPolling()
  const tick = async () => {
    // D73：job_id 可能已在别处结束/清理；旧的 tick 直接退出
    if (xxtJobs.extractJobId !== jobId) return
    try {
      const job = await fetchXxtLoginJob(engUrl.value, tok.value, jobId)
      if (job.status === 'running') {
        const line = (job.lines || []).slice(-1)[0]
        xxtJobs.setExtractMsg(line ? `提取中：${line.slice(-120)}` : '提取中……')
        runMsg.value = xxtJobs.extractMsg
        extractTimer = window.setTimeout(tick, 1500)
        return
      }
      xxtJobs.finishExtractJob()
      if (job.status === 'done' && (job.returncode ?? 0) === 0) {
        runMsg.value = '提取完成，正在刷新列表与预览索引……'
        await refreshRuns()
        await loadReviewIndex()
      } else {
        const line = (job.lines || []).slice(-1)[0] || `任务状态：${job.status}`
        runMsg.value = `提取失败：${line}`
      }
    } catch (e) {
      xxtJobs.finishExtractJob()
      runMsg.value = `提取任务状态查询失败：${String(e)}`
    }
  }
  void tick()
}

async function startExtract() {
  if (extracting.value || extractSubmitting.value) return
  stopExtractPolling()
  extractSubmitting.value = true
  runMsg.value = '已提交提取任务：扫描账户课程/班级并提取作业、通知等信息……'
  try {
    const jobId = await startXxtExtract(engUrl.value, tok.value, { skip_notices: false })
    xxtJobs.startExtractJob(jobId)
    runMsg.value = xxtJobs.extractMsg
    pollExtractJob(jobId)
  } catch (e) {
    runMsg.value = `提取启动失败：${String(e)}`
  } finally {
    extractSubmitting.value = false
  }
}

/* ---------- D72 targets 选择提取（发现→勾选→提取） ---------- */
interface TargetClass { name: string; classId: string; works?: string[] }
interface TargetCourse { name: string; courseId: string; classes: TargetClass[] }
const targets = ref<TargetCourse[]>([])
const targetsAt = ref('')
const targetsDiff = ref<XxtTargetsDiff | null>(null)
const targetsAge = ref<number | null>(null)
const targetsHistory = ref(0)
const diffAckAt = ref<string>(localStorage.getItem('xxt-targets-diff-ack') || '')
const TARGET_SEL_KEY = 'xxt-target-selected'
const COURSE_EXPANDED_KEY = 'xxt-expanded-courses'
const targetSel = ref<Record<string, boolean>>({})
const targetQuery = ref('')
function readStoredSet(key: string): Set<string> {
  try {
    const raw = JSON.parse(localStorage.getItem(key) || '[]')
    return new Set(Array.isArray(raw) ? raw.map((x) => String(x)) : [])
  } catch { return new Set() }
}
function readStoredExpanded(): Record<string, boolean> {
  try {
    const raw = JSON.parse(localStorage.getItem(COURSE_EXPANDED_KEY) || '{}')
    return raw && typeof raw === 'object' ? raw as Record<string, boolean> : {}
  } catch { return {} }
}
const expandedCourses = ref<Record<string, boolean>>(readStoredExpanded())
const targetMsg = ref('')
const discoverLoading = ref(false)
const importLoading = ref(false)
const importInput = ref<HTMLInputElement | null>(null)
let discoverTimer: number | undefined

function tkey(c: TargetCourse, k: TargetClass): string { return `${c.courseId}:${k.classId}` }
function isSel(c: TargetCourse, k: TargetClass): boolean {
  return targetSel.value[tkey(c, k)] === true
}
function persistTargetSel() {
  try {
    localStorage.setItem(TARGET_SEL_KEY, JSON.stringify(
      Object.keys(targetSel.value).filter((k) => targetSel.value[k])))
  } catch { /* noop */ }
}
function onClassToggle(c: TargetCourse, k: TargetClass, ev: Event) {
  targetSel.value[tkey(c, k)] = (ev.target as HTMLInputElement).checked
  persistTargetSel()
}
function onCourseToggle(c: TargetCourse, ev: Event) {
  const on = (ev.target as HTMLInputElement).checked
  for (const k of c.classes) targetSel.value[tkey(c, k)] = on
  persistTargetSel()
}
const visibleTargetCourses = computed<TargetCourse[]>(() => {
  const q = targetQuery.value.trim().toLowerCase()
  if (!q) return targets.value
  const out: TargetCourse[] = []
  for (const c of targets.value) {
    if (`${c.name} ${c.courseId}`.toLowerCase().includes(q)) {
      out.push(c)
      continue
    }
    const classes = c.classes.filter(k => `${k.name} ${k.classId}`.toLowerCase().includes(q))
    if (classes.length) out.push({ ...c, classes })
  }
  return out
})
function toggleAll(on: boolean) {
  for (const c of visibleTargetCourses.value) {
    for (const k of c.classes) targetSel.value[tkey(c, k)] = on
  }
  persistTargetSel()
}
function selectedTargets(): TargetCourse[] {
  return targets.value
    .map(c => ({ ...c, classes: c.classes.filter(k => isSel(c, k)) }))
    .filter(c => c.classes.length > 0)
}
function selectedCount(): number {
  return selectedTargets().reduce((a, c) => a + c.classes.length, 0)
}
function selectedClassCount(c: TargetCourse): number {
  return c.classes.filter(k => isSel(c, k)).length
}
function totalClassCount(): number {
  return targets.value.reduce((a, c) => a + c.classes.length, 0)
}
function isCourseExpanded(c: TargetCourse): boolean {
  return expandedCourses.value[c.courseId] === true
}
function persistExpanded() {
  try { localStorage.setItem(COURSE_EXPANDED_KEY, JSON.stringify(expandedCourses.value)) } catch { /* noop */ }
}
function onCourseDetailsToggle(c: TargetCourse, ev: Event) {
  const open = Boolean((ev.target as HTMLDetailsElement).open)
  expandedCourses.value = { ...expandedCourses.value, [c.courseId]: open }
  persistExpanded()
}
function expandAllCourses(on: boolean) {
  const next: Record<string, boolean> = {}
  for (const c of visibleTargetCourses.value) next[c.courseId] = on
  expandedCourses.value = next
  persistExpanded()
}
function stopDiscoverPolling() {
  if (discoverTimer !== undefined) { window.clearTimeout(discoverTimer); discoverTimer = undefined }
}
async function loadTargets() {
  const o = await fetchXxtTargets(engUrl.value, tok.value)
  const current = new Set<string>()
  for (const c of targets.value) for (const k of c.classes) if (isSel(c, k)) current.add(tkey(c, k))
  const saved = current.size ? current : readStoredSet(TARGET_SEL_KEY)
  targets.value = (o.courses || []) as TargetCourse[]
  targetsAt.value = o.discovered_at || ''
  targetsDiff.value = o.diff ?? null
  targetsAge.value = o.age_seconds ?? null
  targetsHistory.value = o.history_count ?? 0
  const sel: Record<string, boolean> = {}
  for (const c of targets.value) for (const k of c.classes) sel[tkey(c, k)] = saved.has(tkey(c, k))
  targetSel.value = sel
  persistTargetSel()
}

function fmtAge(sec: number | null): string {
  if (sec === null || sec === undefined) return '未知'
  if (sec < 3600) return `${Math.max(1, Math.round(sec / 60))} 分钟前`
  if (sec < 86400) return `${Math.round(sec / 3600)} 小时前`
  return `${Math.round(sec / 86400)} 天前`
}
function ageColor(sec: number | null): string {
  if (sec === null || sec === undefined) return 'var(--c-muted)'
  if (sec < 86400) return 'var(--c-ok, #16a34a)'
  if (sec < 7 * 86400) return '#7a5c00'
  return 'var(--c-danger, #dc2626)'
}
const diffCount = computed(() => {
  const c = targetsDiff.value?.counts || {}
  return (c.courses_added || 0) + (c.courses_removed || 0)
    + (c.classes_added || 0) + (c.classes_removed || 0) + (c.renamed || 0)
})
const showDiff = computed(() => diffCount.value > 0 && diffAckAt.value !== targetsAt.value)
function ackDiff() {
  diffAckAt.value = targetsAt.value
  try { localStorage.setItem('xxt-targets-diff-ack', diffAckAt.value) } catch { /* noop */ }
}
function isCourseAdded(c: TargetCourse): boolean {
  return !!targetsDiff.value?.courses_added?.some(x => x.courseId === c.courseId)
}
function courseRename(c: TargetCourse): string {
  const r = targetsDiff.value?.renamed?.find(x => x.courseId === c.courseId && !x.classId)
  return r ? `${r.old} → ${r.new}` : ''
}
function isClassAdded(c: TargetCourse, k: TargetClass): boolean {
  return !!targetsDiff.value?.classes_added?.some(
    x => x.courseId === c.courseId && x.classId === k.classId)
}
function classRename(c: TargetCourse, k: TargetClass): string {
  const r = targetsDiff.value?.renamed?.find(
    x => x.courseId === c.courseId && x.classId === k.classId)
  return r ? `${r.old} → ${r.new}` : ''
}
async function clearTargetsHistory() {
  if (!targetsHistory.value) return
  if (!confirm(`清理发现结果历史快照（保留当前快照）？当前 ${targetsHistory.value} 份。`)) return
  try {
    const n = await clearXxtTargetsHistory(engUrl.value, tok.value)
    targetMsg.value = `已清理 ${n} 份历史快照`
    targetsDiff.value = null
    targetsHistory.value = 0
    ackDiff()
  } catch (e) {
    targetMsg.value = `清理失败：${String(e)}`
  }
}
function pollDiscoverJob(jobId: string) {
  stopDiscoverPolling()
  const tick = async () => {
    try {
      const job = await fetchXxtLoginJob(engUrl.value, tok.value, jobId)
      if (job.status === 'running') {
        const line = (job.lines || []).slice(-1)[0]
        targetMsg.value = line ? `发现中：${line.slice(-120)}` : '发现中……'
        discoverTimer = window.setTimeout(tick, 1500)
        return
      }
      if (job.status === 'done' && (job.returncode ?? 0) === 0) {
        await loadTargets()
        targetMsg.value = `发现完成：${targets.value.length} 门课 / ${totalClassCount()} 个班（默认不选；可折叠课程或搜索后勾选）`
      } else {
        targetMsg.value = `发现失败：${(job.lines || []).slice(-1)[0] || job.status}`
      }
    } catch (e) {
      targetMsg.value = `发现状态查询失败：${String(e)}`
    } finally {
      discoverLoading.value = false
    }
  }
  void tick()
}
async function startDiscover() {
  if (discoverLoading.value) return
  discoverLoading.value = true
  targetMsg.value = '正在只读发现「我教的课」课程/班级……'
  try {
    const jobId = await startXxtDiscover(engUrl.value, tok.value)
    pollDiscoverJob(jobId)
  } catch (e) {
    targetMsg.value = `发现启动失败：${String(e)}`
    discoverLoading.value = false
  }
}
async function extractSelected() {
  if (extracting.value || extractSubmitting.value) return
  const sel = extractionTargets()
  const n = sel.reduce((a, c) => a + c.classes.length, 0)
  if (!n) {
    const selectedClassesWithWorks = selectedTargets().some(c =>
      c.classes.some(k => hasWorks(c, k)))
    targetMsg.value = selectedClassesWithWorks
      ? '所选班级已发现作业清单，但没有勾选任何作业；请在班级行内勾选要提取的作业。'
      : '请先勾选至少一个班级/作业'
    return
  }
  // D74-8：操作前置新鲜度预判（超 7 天给二次确认；不会自动开浏览器）
  try {
    const fr = await fetchXxtFreshness(engUrl.value, tok.value)
    if (fr.level === 'danger') {
      if (!confirm(`发现结果已 ${fmtAge(fr.age_seconds ?? null)} 未刷新，平台可能有新增/删除的班级/作业。\n`
        + `建议先点「刷新发现」；仍要按当前清单提取吗？`)) {
        targetMsg.value = '已取消提取；建议先刷新发现再操作。'
        return
      }
      targetMsg.value = `⚠ 使用 ${fmtAge(fr.age_seconds ?? null)} 前的发现结果提取（已确认继续）`
    } else if (fr.level === 'warn') {
      targetMsg.value = `提示：${fr.hint || '发现结果偏旧'}`
    }
  } catch { /* 引擎不可达时后续提交会报错 */ }
  stopExtractPolling()
  extractSubmitting.value = true
  targetMsg.value = `正在提取所选 ${n} 个班${selectedWorksCount() ? ` / ${selectedWorksCount()} 份作业` : ''}……`
  try {
    const jobId = await startXxtExtractTargets(engUrl.value, tok.value, sel, { skip_notices: false })
    xxtJobs.startExtractJob(jobId)
    runMsg.value = xxtJobs.extractMsg
    pollExtractJob(jobId)
  } catch (e) {
    targetMsg.value = `提取启动失败：${String(e)}`
  } finally {
    extractSubmitting.value = false
  }
}
function pickImportFile() { importInput.value?.click() }
async function onImportFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  const f = input.files?.[0]
  if (!f) return
  importLoading.value = true
  targetMsg.value = `正在导入 ${f.name}……`
  try {
    const data = JSON.parse(await f.text())
    const r = await importXxtRun(engUrl.value, tok.value, data, f.name)
    targetMsg.value = `已导入 run ${r.run_id || ''}（${r.courses ?? 0} 课 / ${r.classes ?? 0} 班 / ${r.works ?? 0} 作业）`
    await refreshRuns()
  } catch (e) {
    targetMsg.value = `导入失败：${String(e)}`
  } finally {
    importLoading.value = false
    input.value = ''
  }
}

/* ---------- D74-4：作业级惰性展开 ---------- */
const worksCourses = ref<XxtWorksCourse[]>([])
const worksAt = ref('')
const worksLoading = ref(false)
const worksMsg = ref('')
const WORKS_SEL_KEY = 'xxt-works-selected'
const worksSel = ref<Record<string, boolean>>({})
let worksTimer: number | undefined

function stopWorksPolling() {
  if (worksTimer !== undefined) { window.clearTimeout(worksTimer); worksTimer = undefined }
}
function wkey(c: TargetCourse, k: TargetClass, w: XxtWork): string {
  return `${c.courseId}:${k.classId}:${w.workId}`
}
function worksOf(c: TargetCourse, k: TargetClass): XxtWork[] {
  for (const wc of worksCourses.value) {
    if (wc.courseId !== c.courseId) continue
    for (const wcl of wc.classes || []) {
      if (wcl.classId === k.classId) return wcl.works || []
    }
  }
  return []
}
function hasWorks(c: TargetCourse, k: TargetClass): boolean {
  return worksCourses.value.some(wc => wc.courseId === c.courseId
    && (wc.classes || []).some(wcl => wcl.classId === k.classId))
}
function isWorkSel(c: TargetCourse, k: TargetClass, w: XxtWork): boolean {
  return worksSel.value[wkey(c, k, w)] === true
}
function persistWorksSel() {
  try {
    localStorage.setItem(WORKS_SEL_KEY, JSON.stringify(
      Object.keys(worksSel.value).filter((k) => worksSel.value[k])))
  } catch { /* noop */ }
}
function onWorkToggle(c: TargetCourse, k: TargetClass, w: XxtWork, ev: Event) {
  worksSel.value[wkey(c, k, w)] = (ev.target as HTMLInputElement).checked
  persistWorksSel()
}
function selectedWorksCount(): number {
  let n = 0
  for (const c of targets.value) for (const k of c.classes) {
    if (!isSel(c, k)) continue
    for (const w of worksOf(c, k)) if (isWorkSel(c, k, w)) n++
  }
  return n
}
async function loadWorks() {
  const o = await fetchXxtWorks(engUrl.value, tok.value)
  const current = new Set<string>()
  for (const wc of worksCourses.value) for (const wcl of wc.classes || []) {
    for (const w of wcl.works || []) {
      if (worksSel.value[`${wc.courseId}:${wcl.classId}:${w.workId}`] === true) {
        current.add(`${wc.courseId}:${wcl.classId}:${w.workId}`)
      }
    }
  }
  const saved = current.size ? current : readStoredSet(WORKS_SEL_KEY)
  worksCourses.value = (o.courses || []) as XxtWorksCourse[]
  worksAt.value = o.discovered_at || ''
  const sel: Record<string, boolean> = {}
  for (const wc of worksCourses.value) for (const wcl of wc.classes || []) {
    for (const w of wcl.works || []) {
      const key = `${wc.courseId}:${wcl.classId}:${w.workId}`
      sel[key] = saved.has(key)
    }
  }
  worksSel.value = sel
  persistWorksSel()
}
function pollWorksJob(jobId: string) {
  stopWorksPolling()
  const tick = async () => {
    try {
      const job = await fetchXxtLoginJob(engUrl.value, tok.value, jobId)
      if (job.status === 'running') {
        const line = (job.lines || []).slice(-1)[0]
        worksMsg.value = line ? `发现作业中：${line.slice(-120)}` : '发现作业中……'
        worksTimer = window.setTimeout(tick, 1500)
        return
      }
      if (job.status === 'done' && (job.returncode ?? 0) === 0) {
        await loadWorks()
        worksMsg.value = `作业清单已发现：${worksCourses.value.reduce((a, c) => a + (c.classes || []).length, 0)} 个班`
          + ` / 已勾选 ${selectedWorksCount()} 份作业（默认不选，请手动勾选）`
      } else {
        worksMsg.value = `发现作业失败：${(job.lines || []).slice(-1)[0] || job.status}`
      }
    } catch (e) {
      worksMsg.value = `发现作业状态查询失败：${String(e)}`
    } finally {
      worksLoading.value = false
    }
  }
  void tick()
}
async function startDiscoverWorks() {
  if (worksLoading.value) return
  const sel = selectedTargets()
  if (!sel.length) { worksMsg.value = '请先在「发现课程/班级」勾选至少一个班'; return }
  worksLoading.value = true
  worksMsg.value = '正在只读发现所选班级的作业清单……'
  try {
    const jobId = await startXxtDiscoverWorks(engUrl.value, tok.value, sel)
    pollWorksJob(jobId)
  } catch (e) {
    worksMsg.value = `发现作业启动失败：${String(e)}`
    worksLoading.value = false
  }
}
/** 提取用的 targets：班级勾选 + （已发现作业时）只带勾选的 workId。 */
function extractionTargets(): TargetCourse[] {
  const out: TargetCourse[] = []
  for (const c of targets.value) {
    const classes: TargetClass[] = []
    for (const k of c.classes) {
      if (!isSel(c, k)) continue
      if (hasWorks(c, k)) {
        const chosen = worksOf(c, k).filter(w => isWorkSel(c, k, w)).map(w => w.workId)
        if (!chosen.length) continue   // 该班一个作业都没选 → 整班跳过
        classes.push({ name: k.name, classId: k.classId, works: chosen })
      } else {
        classes.push({ name: k.name, classId: k.classId })
      }
    }
    if (classes.length) out.push({ name: c.name, courseId: c.courseId, classes })
  }
  return out
}

/* ---------- D75-1：真实批阅列表预览（本地 review 存档） ---------- */
const reviewOpen = ref(false)
const reviewTitle = ref('')
const reviewStudents = ref<XxtReviewStudent[]>([])
const reviewScored = ref(0)
const reviewLoading = ref(false)
const reviewMsg = ref('')
const reviewWorkRef = ref<XxtReviewImageWork | null>(null)

async function openReview(cl: ClassRow, w: WorkRow) {
  reviewOpen.value = true
  reviewTitle.value = `${cl.name} · ${w.name}`
  reviewStudents.value = []
  reviewScored.value = 0
  reviewLoading.value = true
  reviewMsg.value = ''
  reviewWorkRef.value = reviewIndex.value.find(
    it => it.classId === cl.classId && it.workId === w.workId) || null
  try {
    const r = await fetchXxtReviewStudents(engUrl.value, tok.value, cl.classId, w.workId,
      curRun.value || undefined)
    if (!r.ok) {
      reviewMsg.value = r.error === 'no archived review list'
        ? '本机没有该作业的 review 列表存档或已下载清单；请先执行一次「📥 提取所选」，或点该行「⬇」下载后再预览。'
        : `读取失败：${r.error || ''}`
    } else {
      reviewStudents.value = r.students || []
      reviewScored.value = r.scored || 0
      reviewMsg.value = `共 ${r.count || 0} 人，已有分数 ${r.scored || 0} 人`
        + (r.source === 'manifest' ? '（来自已下载 students.json 清单）' : '')
    }
  } catch (e) {
    reviewMsg.value = `读取失败：${String(e)}`
  } finally {
    reviewLoading.value = false
  }
}
async function openStudentPreview(idx: number) {
  if (!reviewWorkRef.value) {
    reviewMsg.value = '该作业尚未下载图片/批语：请先点该行的「⬇」下载，再逐生预览。'
    return
  }
  await openReviewWork(reviewWorkRef.value)
  reviewWorkIdx.value = idx
  reviewImgIdxReset()
}
function reviewImgIdxReset() { reviewWorkImgIdx.value = 0; reviewWorkRotate.value = 0 }

function closeReview() { reviewOpen.value = false }

/* ---------- D75-1c/d：批阅图片（按班级/作业文件夹） ---------- */
const reviewIndex = ref<XxtReviewImageWork[]>([])
const reviewIndexStats = ref<{ works?: number; images?: number; bytes?: number }>({})
const reviewDlMsg = ref('')
const reviewDlLoading = ref(false)
let reviewDlTimer: number | undefined

async function loadReviewIndex() {
  try {
    const r = await fetchXxtReviewIndex(engUrl.value, tok.value)
    reviewIndex.value = r.works || []
    reviewIndexStats.value = r.stats || {}
  } catch { /* 引擎离线时忽略 */ }
}
function reviewFileUrl(item: XxtReviewImageWork, fname: string): string {
  return xxtReviewFileUrl(engUrl.value, tok.value, item.classId, item.workId, fname)
}
function stopReviewDlPolling() {
  if (reviewDlTimer !== undefined) { window.clearTimeout(reviewDlTimer); reviewDlTimer = undefined }
}
function pollReviewDl(jobId: string) {
  stopReviewDlPolling()
  const tick = async () => {
    try {
      const job = await fetchXxtLoginJob(engUrl.value, tok.value, jobId)
      if (job.status === 'running') {
        const line = (job.lines || []).slice(-1)[0]
        reviewDlMsg.value = line ? `下载中：${line.slice(-120)}` : '下载作答图片/批语中……'
        reviewDlTimer = window.setTimeout(tick, 1500)
        return
      }
      if (job.status === 'done' && (job.returncode ?? 0) === 0) {
        reviewDlJobId.value = ''
        try { localStorage.removeItem('xxt-review-dl-job') } catch { /* noop */ }
        await loadReviewIndex()
        reviewDlMsg.value = '下载完成（见下方「批阅图片」文件夹）'
      } else {
        reviewDlJobId.value = ''
        try { localStorage.removeItem('xxt-review-dl-job') } catch { /* noop */ }
        reviewDlMsg.value = `下载失败：${(job.lines || []).slice(-1)[0] || job.status}`
      }
    } catch (e) {
      reviewDlMsg.value = `下载状态查询失败：${String(e)}`
    } finally {
      reviewDlLoading.value = false
    }
  }
  void tick()
}
async function downloadReview(c: CourseRow, cl: ClassRow, w: WorkRow) {
  if (reviewDlLoading.value) return
  reviewDlLoading.value = true
  reviewDlMsg.value = `正在下载 ${cl.name} · ${w.name} 的作答图片与批语……`
  try {
    const jobId = await startXxtReviewDownload(engUrl.value, tok.value, {
      courseId: c.courseId, classId: cl.classId, workId: w.workId,
      courseName: c.name, className: cl.name, workName: w.name,
      allowPost: allowPost.value,
    })
    reviewDlJobId.value = jobId
    try { localStorage.setItem('xxt-review-dl-job', jobId) } catch { /* noop */ }
    pollReviewDl(jobId)
  } catch (e) {
    reviewDlMsg.value = `下载启动失败：${String(e)}`
    reviewDlLoading.value = false
  }
}
async function pruneReview() {
  if (!confirm('清理 6 个月前的批阅图片/批语？（按作业文件夹时间，独立于 run 历史清理）')) return
  try {
    const n = await pruneXxtReview(engUrl.value, tok.value)
    reviewDlMsg.value = `已清理 ${n} 个旧作业目录`
    await loadReviewIndex()
  } catch (e) { reviewDlMsg.value = `清理失败：${String(e)}` }
}

/* ---------- D75-1e/4：探针 PWA 化 + 逐生两列预览 ---------- */
const allowPost = ref<string[]>(JSON.parse(localStorage.getItem('xxt-review-allow-post') || '[]') as string[])
const probeLoading = ref(false)
const probeMsg = ref('')
const probeResult = ref<XxtReviewProbe | null>(null)
const reviewDlJobId = ref<string>(localStorage.getItem('xxt-review-dl-job') || '')
const reviewWorkOpen = ref(false)
const reviewWorkTitle = ref('')
const reviewWorkItem = ref<XxtReviewImageWork | null>(null)
const reviewWorkStudents = ref<XxtReviewManifestStudent[]>([])
const reviewWorkIdx = ref(0)
const reviewWorkImgIdx = ref(0)
const reviewWorkRotate = ref(0)
const reviewWorkLoading = ref(false)
const curStudent = computed<XxtReviewManifestStudent | null>(() =>
  reviewWorkStudents.value[reviewWorkIdx.value] || null)
const curImages = computed<string[]>(() => curStudent.value?.images || [])

const reviewByClass = computed<Record<string, XxtReviewImageWork[]>>(() => {
  const out: Record<string, XxtReviewImageWork[]> = {}
  for (const it of reviewIndex.value) {
    const k = it.classId || '?'
    if (!out[k]) out[k] = []
    out[k].push(it)
  }
  return out
})
const reviewLayout = ref<'cols' | 'rows'>('cols')
const reviewSearch = ref('')
function layoutKey(it: XxtReviewImageWork): string {
  return `xxt-review-layout:${it.classId}:${it.workId}`
}
function applyLayout(it: XxtReviewImageWork) {
  try { reviewLayout.value = localStorage.getItem(layoutKey(it)) === 'rows' ? 'rows' : 'cols' } catch { reviewLayout.value = 'cols' }
}
function toggleLayout(it: XxtReviewImageWork) {
  reviewLayout.value = reviewLayout.value === 'cols' ? 'rows' : 'cols'
  try { localStorage.setItem(layoutKey(it), reviewLayout.value) } catch { /* noop */ }
}
function toggleCurrentLayout() {
  if (reviewWorkItem.value) toggleLayout(reviewWorkItem.value)
}
function searchStudent() {
  const q = reviewSearch.value.trim()
  if (!q) return
  const i = reviewWorkStudents.value.findIndex(st => (st.name || '').includes(q))
  if (i >= 0) { reviewWorkIdx.value = i; reviewWorkImgIdx.value = 0; reviewWorkRotate.value = 0 }
}
async function purgeReviewWork(it: XxtReviewImageWork) {
  const label = `${it.className || it.classId} · ${it.workName || it.workId}`
  if (!confirm(`彻底删除「${label}」？将删除图片 + students.json 清单，不可恢复。`)) return
  if (!confirm('再次确认：彻底删除该次作业的全部本地批阅数据？')) return
  try {
    await purgeXxtReviewWork(engUrl.value, tok.value, it.classId, it.workId)
    reviewDlMsg.value = `已彻底删除 ${label}`
    await loadReviewIndex()
  } catch (e) { reviewDlMsg.value = `彻底删除失败：${String(e)}` }
}

async function deleteReviewWork(it: XxtReviewImageWork) {
  if (!confirm(`删除 ${it.className || it.classId} · ${it.workName || it.workId} 的图片？`
    + `将删除作答/评语图片，保留 students.json 清单与批语文字记录。`)) return
  try {
    const r = await deleteXxtReviewWork(engUrl.value, tok.value, it.classId, it.workId)
    reviewDlMsg.value = `已删除该次作业图片（作答 ${r.deleted_answer || 0} / 评语 ${r.deleted_comment || 0}，清单保留）`
    await loadReviewIndex()
  } catch (e) { reviewDlMsg.value = `删除失败：${String(e)}` }
}

function unescapeHtml(input?: string): string {
  return (input || '')
    .replace(/&lt;/gi, '<').replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"').replace(/&#39;/g, "'")
    .replace(/&nbsp;/gi, ' ').replace(/&amp;/gi, '&')
}
function stripHtml(input?: string): string {
  const raw = unescapeHtml(input)
  return raw.replace(/<\s*br\s*\/?>/gi, '\n').replace(/<\/p\s*>/gi, '\n')
    .replace(/<[^>]+>/g, '').replace(/\n{3,}/g, '\n\n').trim()
}
function htmlHasImg(input?: string): boolean {
  return /<img\b/i.test(unescapeHtml(input))
}
const curCommentText = computed(() => {
  const st = curStudent.value
  if (!st) return ''
  return st.comment_text || stripHtml(st.comment)
})
const curCommentStale = computed(() => {
  const st = curStudent.value
  if (!st) return false
  return !st.comment_text && !!st.comment && htmlHasImg(st.comment)
    && !(st.comment_images || []).length
})
const curPQTexts = computed(() => {
  const st = curStudent.value
  if (!st) return []
  if (st.per_question_comment_texts?.length) return st.per_question_comment_texts
  return (st.per_question_comments || []).map(t => stripHtml(t))
})
function persistAllowPost() {
  try { localStorage.setItem('xxt-review-allow-post', JSON.stringify(allowPost.value)) } catch { /* noop */ }
}
function toggleAllowPost(url: string) {
  if (!url) return
  allowPost.value = allowPost.value.includes(url)
    ? allowPost.value.filter(x => x !== url) : [...allowPost.value, url]
  persistAllowPost()
}
async function startProbe(c: CourseRow, cl: ClassRow, w: WorkRow) {
  if (probeLoading.value) return
  probeLoading.value = true
  probeMsg.value = `正在只读探针：${cl.name} · ${w.name}……`
  probeResult.value = null
  try {
    const jobId = await startXxtReviewProbe(engUrl.value, tok.value,
      { courseId: c.courseId, classId: cl.classId, workId: w.workId, sample: 1 })
    const tick = async () => {
      try {
        const job = await fetchXxtLoginJob(engUrl.value, tok.value, jobId)
        if (job.status === 'running') {
          const line = (job.lines || []).slice(-1)[0]
          probeMsg.value = line ? `探针中：${line.slice(-120)}` : '探针中……'
          window.setTimeout(tick, 1500)
          return
        }
        probeResult.value = await fetchXxtReviewProbeLatest(engUrl.value, tok.value)
        probeMsg.value = `探针完成：学生 ${probeResult.value.students?.length || 0} 人，`
          + `被拦截非 GET ${probeResult.value.aborted?.length || 0} 个`
      } catch (e) {
        probeMsg.value = `探针失败：${String(e)}`
      } finally {
        probeLoading.value = false
      }
    }
    void tick()
  } catch (e) {
    probeMsg.value = `探针启动失败：${String(e)}`
    probeLoading.value = false
  }
}
async function refreshReviewIndex() {
  await loadReviewIndex()
  reviewDlMsg.value = '批阅图片目录已刷新'
}
async function openReviewWork(it: XxtReviewImageWork) {
  reviewWorkOpen.value = true
  reviewWorkItem.value = it
  reviewWorkTitle.value = `${it.className || it.classId} · ${it.workName || it.workId}`
  reviewWorkStudents.value = []
  reviewWorkIdx.value = 0
  reviewWorkImgIdx.value = 0
  reviewWorkRotate.value = 0
  reviewSearch.value = ''
  applyLayout(it)
  reviewWorkLoading.value = true
  try {
    const m = await fetchXxtReviewWork(engUrl.value, tok.value, it.classId, it.workId)
    reviewWorkStudents.value = m.students || []
  } catch (e) {
    reviewDlMsg.value = `读取批阅清单失败：${String(e)}`
  } finally {
    reviewWorkLoading.value = false
  }
}
function closeReviewWork() { reviewWorkOpen.value = false }
function prevStudent() {
  if (reviewWorkIdx.value > 0) reviewWorkIdx.value -= 1
  reviewWorkImgIdx.value = 0; reviewWorkRotate.value = 0
}
function nextStudent() {
  if (reviewWorkIdx.value < reviewWorkStudents.value.length - 1) reviewWorkIdx.value += 1
  reviewWorkImgIdx.value = 0; reviewWorkRotate.value = 0
}
function rotateImage(delta: number) {
  reviewWorkRotate.value = (reviewWorkRotate.value + delta + 360) % 360
}
function curImageUrl(f: string): string {
  return reviewWorkItem.value ? reviewFileUrl(reviewWorkItem.value, f) : ''
}

async function deleteCurrentRun() {
  if (!curRun.value) return
  const id = curRun.value
  if (!confirm(`删除历史 run ${id}？将同时删除其 JSON 与截图，不可恢复。`)) return
  try {
    await deleteXxtRun(engUrl.value, tok.value, id)
    runMsg.value = `已删除 ${id}`
    await refreshRuns()
  } catch (e) {
    runMsg.value = `删除失败：${String(e)}`
  }
}

async function removeRun(id: string) {
  if (!confirm(`删除历史 run ${id}？将同时删除其 JSON、截图与 run 级 HTML 存档，不可恢复。`)) return
  try {
    await deleteXxtRun(engUrl.value, tok.value, id)
    runMsg.value = `已删除 ${id}`
    if (curRun.value === id) { curRun.value = null; courses.value = []; loadSteps.value = [] }
    await refreshRuns()
  } catch (e) {
    runMsg.value = `删除失败：${String(e)}`
  }
}
async function clearAllRuns() {
  if (!runs.value.length) return
  if (!confirm(`清空全部 ${runs.value.length} 条历史 run？将删除 JSON、run 级截图与 HTML 存档，不可恢复。`)) return
  try {
    const n = await clearXxtRuns(engUrl.value, tok.value)
    curRun.value = null; courses.value = []; loadSteps.value = []
    runMsg.value = `已清空 ${n} 项历史工件`
    await refreshRuns()
  } catch (e) {
    runMsg.value = `清空失败：${String(e)}`
  }
}

const grouped = computed(() => courses.value.map(c => {
  const pass = (cl: ClassRow): boolean => {
    if (isRemoved(cl)) { return false }
    if (filterMode.value === 'hasWorks') { return cl.works.length > 0 }
    if (filterMode.value === 'empty') { return cl.status === 'empty_confirmed' }
    if (filterMode.value === 'fail') { return cl.status === 'not_extracted' }
    return true
  }
  const visible = c.classes.filter(pass)
  if (filterMode.value === 'hasWorks') { visible.sort((a, b) => b.works.length - a.works.length) }
  const pinnedRows = visible.filter(cl => isPinned(cl))
  const normal = visible.filter(cl => !isPinned(cl))
  return { course: c, pinnedRows, normal, total: visible.length }
}))


/* ---------- D77：课程通知发布（写操作；白名单测试） ---------- */
const NOTICE_ALLOWLIST = new Set(['217801417:40009084'])
const NOTICE_DEFAULT_TITLE = '大学物理课作业通知'
const NOTICE_DEFAULT_BODY = '作业纸见附件，请各位同学打印自己的那一张并手写完成、拍照上传到学习通作业里面。'
const noticeSel = ref<Record<string, boolean>>({})
const noticeTitle = ref(NOTICE_DEFAULT_TITLE)
const noticeBody = ref(NOTICE_DEFAULT_BODY)
const noticeAttachments = ref<XxtNoticeAttachment[]>([])
const noticeAttSel = ref<Record<string, boolean>>({})
const noticeMsg = ref('')
const noticeConfirm = ref(false)
const noticeLoading = ref(false)
let noticeTimer: number | undefined

function nkey(courseId: string, classId: string): string { return `${courseId}:${classId}` }
function noticeAllowed(courseId: string, classId: string): boolean {
  return NOTICE_ALLOWLIST.has(nkey(courseId, classId))
}
function isNoticeSel(courseId: string, classId: string): boolean {
  return noticeSel.value[nkey(courseId, classId)] === true
}
function onNoticeClassToggle(courseId: string, classId: string, ev: Event) {
  if (!noticeAllowed(courseId, classId)) return
  const checked = (ev.target as HTMLInputElement).checked
  if (checked) noticeSel.value = { ...noticeSel.value, [nkey(courseId, classId)]: true }
  else {
    const next = { ...noticeSel.value }
    delete next[nkey(courseId, classId)]
    noticeSel.value = next
  }
  applyNoticeAttachmentsToContent()
}
function selectedNoticeTargets(): XxtNoticeTargetCourse[] {
  const out: XxtNoticeTargetCourse[] = []
  for (const c of courses.value) {
    const classes = c.classes.filter(k => isNoticeSel(c.courseId, k.classId)).map(k => ({ classId: k.classId, name: k.name }))
    if (classes.length) out.push({ courseId: c.courseId, courseName: c.name, classes })
  }
  return out
}
function selectedNoticeCount(): number {
  return selectedNoticeTargets().reduce((a, c) => a + c.classes.length, 0)
}
function selectedAttachmentNames(): string[] {
  return Object.keys(noticeAttSel.value).filter(k => noticeAttSel.value[k])
    .map(p => noticeAttachments.value.find(a => a.path === p)?.name || String(p).split(/[\/]/).pop() || String(p))
}
function attachmentLine(names: string[]): string {
  return names.length ? `附件文件名：${names.join('、')}` : ''
}
function applyNoticeAttachmentsToContent() {
  const names = selectedAttachmentNames()
  const line = attachmentLine(names)
  // title suffix: only when title still starts with default or already has our suffix
  const suffix = names.length ? `（附件：${names.slice(0, 2).join('、')}${names.length > 2 ? '等' : ''}）` : ''
  let t = noticeTitle.value.trim()
  const baseTitle = t.startsWith(NOTICE_DEFAULT_TITLE) ? NOTICE_DEFAULT_TITLE : (t.includes('（附件：') ? NOTICE_DEFAULT_TITLE : t)
  const maxLen = 128
  let nt = suffix ? `${baseTitle}${suffix}` : baseTitle
  if (nt.length > maxLen) nt = nt.slice(0, maxLen)
  noticeTitle.value = nt
  // body: keep user text but replace/update the attachment filename line at the end
  let b = noticeBody.value.trim()
  if (!b) b = NOTICE_DEFAULT_BODY
  const withoutAtt = b.split('\n').filter(x => !x.startsWith('附件文件名：')).join('\n').trim()
  noticeBody.value = line ? `${withoutAtt}\n\n${line}` : withoutAtt
}
async function loadNoticeAttachments() {
  try {
    noticeAttachments.value = await fetchXxtNoticeAttachments(engUrl.value, tok.value, 200)
    // drop stale selections
    const valid = new Set(noticeAttachments.value.map(a => a.path))
    const next: Record<string, boolean> = {}
    for (const [k, v] of Object.entries(noticeAttSel.value)) if (v && valid.has(k)) next[k] = true
    noticeAttSel.value = next
  } catch (e) {
    noticeMsg.value = `附件清单读取失败：${String(e)}`
  }
}
function onNoticeAttachToggle(path: string, ev: Event) {
  const checked = (ev.target as HTMLInputElement).checked
  if (checked) noticeAttSel.value = { ...noticeAttSel.value, [path]: true }
  else {
    const next = { ...noticeAttSel.value }
    delete next[path]
    noticeAttSel.value = next
  }
  applyNoticeAttachmentsToContent()
}
function stopNoticePolling() {
  if (noticeTimer !== undefined) { window.clearTimeout(noticeTimer); noticeTimer = undefined }
}
function pollNoticeJob(jobId: string, send: boolean) {
  stopNoticePolling()
  const tick = async () => {
    try {
      const job = await fetchXxtLoginJob(engUrl.value, tok.value, jobId)
      if (job.status === 'running') {
        const line = (job.lines || []).slice(-1)[0]
        noticeMsg.value = `${send ? '发送中' : '预检中'}：${line ? line.slice(-160) : '……'}`
        noticeTimer = window.setTimeout(tick, 1500)
        return
      }
      noticeLoading.value = false
      const tail = (job.lines || []).slice(-8).join('\n')
      if (job.status === 'done' && (job.returncode ?? 0) === 0) {
        noticeMsg.value = send
          ? `发布完成。请在学习通网页查看；本地 receipt 已保存。
${tail}`
          : `预检完成（未发布）。本地 receipt/截图已保存。
${tail}`
      } else {
        noticeMsg.value = `${send ? '发布' : '预检'}失败：${tail || job.status}`
      }
    } catch (e) {
      noticeLoading.value = false
      noticeMsg.value = `任务状态查询失败：${String(e)}`
    }
  }
  void tick()
}
async function runNoticeSend(send: boolean) {
  if (noticeLoading.value) return
  const targets = selectedNoticeTargets()
  if (!targets.length) { noticeMsg.value = '请先勾选允许发布的班级'; return }
  if (!noticeTitle.value.trim()) { noticeMsg.value = '标题不能为空'; return }
  if (!noticeBody.value.trim()) { noticeMsg.value = '正文不能为空'; return }
  if (send && !noticeConfirm.value) { noticeMsg.value = '请先勾选“我已确认发送对象与内容”'; return }
  if (send) {
    const names = selectedAttachmentNames()
    const ok = window.confirm(`即将真正发布通知：
标题：${noticeTitle.value}
目标：${targets.map(c => `${c.courseName || c.courseId}/${c.classes.map(k => k.name || k.classId).join('+')}`).join('; ')}
附件：${names.join('、') || '无'}

确定发送？`)
    if (!ok) { noticeMsg.value = '已取消发布。'; return }
  }
  noticeLoading.value = true
  noticeMsg.value = send ? '正在提交发布任务……' : '正在提交预检任务……'
  try {
    const r = await startXxtNoticeSend(engUrl.value, tok.value, {
      targets,
      title: noticeTitle.value.trim(),
      bodyHtml: noticeBody.value.trim(),
      attachments: Object.keys(noticeAttSel.value).filter(k => noticeAttSel.value[k]),
      send,
    })
    pollNoticeJob(r.jobId, send)
  } catch (e) {
    noticeLoading.value = false
    noticeMsg.value = `启动失败：${String(e)}`
  }
}

onMounted(() => {
  refreshStatus()
  refreshRuns()
  loadTargets().catch(() => { /* 无历史发现结果时忽略 */ })
  loadNoticeAttachments().catch(() => { /* 引擎离线或无附件时忽略 */ })
  loadWorks().catch(() => { /* 无历史作业清单时忽略 */ })
  loadReviewIndex().catch(() => { /* 无批阅图片目录时忽略 */ })
  if (reviewDlJobId.value) { reviewDlMsg.value = '检测到未完成的下载任务，继续轮询……'; pollReviewDl(reviewDlJobId.value) }
  // D73：切换 tab 回来后恢复提取 job 轮询
  if (xxtJobs.extractJobId) {
    runMsg.value = xxtJobs.extractMsg || '提取任务进行中……'
    pollExtractJob(xxtJobs.extractJobId)
  }
})
onUnmounted(() => { loginSeq += 1; stopLoginPolling(); stopExtractPolling(); stopDiscoverPolling(); stopWorksPolling(); stopReviewDlPolling() })
</script>

<template>
  <section>
    <h2>学习通 <small style="font-weight:400;color:var(--c-muted)">登录 · 只读基本信息（D63 T7/T8；写操作维持 D62 冻结）</small></h2>

    <!-- 登录卡：QR 框 ↔ 头像 -->
    <div class="card">
      <div style="display:flex; gap:24px; align-items:flex-start; flex-wrap:wrap">
        <div style="width:168px; text-align:center">
          <div style="border:1px solid var(--c-border); border-radius:12px; padding:6px; background:#fff; min-height:156px; display:flex; align-items:center; justify-content:center">
            <img v-if="verdict==='alive' && avatar" :src="avatar" alt="登录头像"
                 style="width:140px; height:140px; border-radius:50%; object-fit:cover" />
            <div v-else-if="verdict==='alive'"
                 style="width:140px; height:140px; border-radius:50%; display:flex; align-items:center; justify-content:center; flex-direction:column; background:var(--c-bg,#f7f7f9)">
              <span style="font-size:44px">🎓</span><small>已登录</small>
            </div>
            <img v-else-if="qrcode" :src="qrcode" alt="登录二维码" style="width:150px" />
            <span v-else-if="qrLoading" class="hint" style="color:var(--c-muted)">二维码生成中…</span>
            <span v-else class="hint" style="color:var(--c-muted)">待扫码</span>
          </div>
          <div style="margin-top:6px">{{ verdict==='alive' ? `● 已登录${verdict?'':''}` : '○ 未登录/失效' }}</div>
        </div>
        <div style="flex:1; min-width:260px">
          <p class="hint">{{ loginHint || '点击「扫码登录」开始（只扫码，无账密路径）' }}</p>
          <p>
            <button class="btn primary" :disabled="verdict==='alive'" @click="startScan">📷 扫码登录（QR）</button>
            <button class="btn" style="margin-left:8px" @click="refreshStatus">🔄 刷新体检</button>
          </p>
          <p class="hint" style="color:var(--c-muted)">
            体检=三信号判活+storage 回写续期（§11）；
            dead 时头像位退回二维码态。
          </p>
        </div>
      </div>
    </div>

    <!-- §24 通知查看卡（只读；数据=最新 run notices[]） -->
    <div class="card" v-if="noticeRows.length">
      <h3>通知 <small style="font-weight:400;color:var(--c-muted)">最新 run 抓取的各班通知（只读；{{ noticeRows.length }} 条）</small></h3>
      <p>
        <label class="field">班级：
          <select v-model="noticeClsFilter" style="width:200px">
            <option value="">全部（{{ noticeClasses.length }} 班有通知）</option>
            <option v-for="cl in noticeClasses" :key="cl.classId" :value="cl.classId">{{ cl.name }}</option>
          </select>
        </label>
      </p>
      <div style="max-height:320px; overflow-y:auto; border:1px solid var(--c-border); border-radius:8px">
        <table style="width:100%; border-collapse:collapse">
          <tbody>
            <tr v-for="(r, i) in noticeRows" :key="i">
              <td style="padding:5px 8px; width:150px">{{ r.cls }}</td>
              <td style="padding:5px 8px">{{ r.title }}</td>
              <td style="padding:5px 8px; width:110px; white-space:nowrap">{{ r.when }}</td>
              <td style="padding:5px 8px; width:90px; white-space:nowrap">
                <span v-if="r.read" :style="r.ratio !== undefined && r.ratio < 0.9 ? 'color:#7a5c00' : ''">已读 {{ r.read }}</span>
                <span v-else class="hint" style="color:var(--c-muted)">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- D77 发公告向导卡：engine CLI 写操作套壳；当前白名单仅开放已真机验证班级 -->
    <div class="card">
      <h3>发公告 <small style="font-weight:400;color:var(--c-muted)">从“已提取班”中选择发布对象；当前测试白名单仅开放「大学物理知识点拾遗（by pc）/默认班级」</small>
        <span class="tag" style="background:#fff3cd; color:#7a5c00; padding:2px 8px; border-radius:6px; font-size:12px">🔒 白名单写操作</span></h3>
      <p class="hint">
        数据源=最近一次提取 run 的班级列表。未勾选或白名单外班级不可选；真正发送前会二次确认，并由 engine CLI 执行。
      </p>
      <div v-if="!courses.length" class="hint" style="color:var(--c-muted)">
        暂无已提取班级：请先在「发现课程/班级」中勾选并「提取所选」。
      </div>
      <div v-else style="max-height:220px; overflow:auto; border:1px solid var(--c-border); border-radius:8px; padding:8px; margin-bottom:8px">
        <div v-for="c in courses" :key="'notice-' + c.courseId" style="margin-bottom:8px">
          <b>{{ c.name }}</b>
          <span class="hint" style="color:var(--c-muted)">courseId {{ c.courseId }} · {{ c.classes.length }} 班</span>
          <div style="margin:4px 0 0 22px; display:flex; flex-wrap:wrap; gap:12px">
            <label v-for="k in c.classes" :key="k.classId"
                   :style="{ color: noticeAllowed(c.courseId, k.classId) ? '' : 'var(--c-muted)' }">
              <input type="checkbox" :checked="isNoticeSel(c.courseId, k.classId)"
                     :disabled="!noticeAllowed(c.courseId, k.classId)"
                     @change="onNoticeClassToggle(c.courseId, k.classId, $event)" />
              {{ k.name }}
              <span v-if="!noticeAllowed(c.courseId, k.classId)" class="hint">（白名单外）</span>
            </label>
          </div>
        </div>
      </div>
      <p><label class="field">标题（≤128 字）：
        <input v-model="noticeTitle" type="text" maxlength="128" placeholder="大学物理课作业通知" style="width:min(520px,90%)" />
      </label></p>
      <p><label class="field" style="vertical-align:top">正文：
        <textarea v-model="noticeBody" rows="4" placeholder="作业纸见附件，请各位同学打印自己的那一张并手写完成、拍照上传到学习通作业里面。" style="width:min(640px,92%); vertical-align:middle"></textarea>
      </label></p>
      <p>
        <button class="btn small" :disabled="noticeLoading" @click="loadNoticeAttachments">🔄 刷新附件清单</button>
        <span class="hint" style="margin-left:8px">共 {{ noticeAttachments.length }} 个可发布的作业纸 PDF；勾选后文件名会自动进入标题/正文。</span>
      </p>
      <div v-if="noticeAttachments.length" style="max-height:180px; overflow:auto; border:1px solid var(--c-border); border-radius:8px; padding:8px; margin-bottom:8px">
        <label v-for="a in noticeAttachments" :key="a.path" style="display:block; margin:3px 0">
          <input type="checkbox" :checked="!!noticeAttSel[a.path]" @change="onNoticeAttachToggle(a.path, $event)" />
          {{ a.name }}
          <span class="hint" style="color:var(--c-muted)">{{ a.generated_at || '' }} · {{ fmtBytes(a.size) }}</span>
        </label>
      </div>
      <p class="hint">定时发送 / 提醒渠道：本轮保持缺省关闭；附件走学习通 WebUploader（PDF/DOC/DOCX）。</p>
      <p>
        <label>
          <input v-model="noticeConfirm" type="checkbox" />
          我已确认发送对象与内容
        </label>
      </p>
      <p>
        <button class="btn" :disabled="!selectedNoticeCount() || noticeLoading" @click="runNoticeSend(false)">
          {{ noticeLoading ? '任务中…' : '🧪 预检/试运行（不发布）' }}
        </button>
        <button class="btn primary" style="margin-left:8px"
                :disabled="!selectedNoticeCount() || !noticeConfirm || noticeLoading"
                @click="runNoticeSend(true)">
          📢 发布通知（二次确认）
        </button>
        <span class="hint" style="margin-left:8px">已选 {{ selectedNoticeCount() }} 个班 / {{ selectedAttachmentNames().length }} 个附件</span>
      </p>
      <p v-if="noticeMsg" class="hint" style="white-space:pre-wrap">{{ noticeMsg }}</p>
      <p class="hint" style="color:var(--c-muted)">
        流程：PWA → POST /xxt/notice/send → assist xxt notice-send --spec → Playwright 打开新建通知页 → 注入收件人/填标题正文/上传附件 → dry-run 截图或点击发送。receipt 写入本机 xxt_home()/notice-sends/。
      </p>
    </div>

    <!-- D72 targets：只读发现 → 勾选 → 按需提取；D73-9 旧 run 导入 -->
    <div class="card">
      <h3>发现课程/班级 <small style="font-weight:400;color:var(--c-muted)">只读发现「我教的课」的课程/班级 → 勾选范围 → 提取；也可导入旧 run JSON（D73-9）</small></h3>
      <p>
        <button class="btn primary" :disabled="verdict!=='alive' || discoverLoading" @click="startDiscover">
          {{ discoverLoading ? '发现中…' : (targets.length ? '🔄 刷新发现（只读）' : '🔍 发现课程/班级（只读）') }}
        </button>
        <button class="btn" style="margin-left:8px" :disabled="!targets.length" @click="toggleAll(true)">全选</button>
        <button class="btn" style="margin-left:8px" :disabled="!targets.length" @click="toggleAll(false)">全不选</button>
        <button class="btn" style="margin-left:8px"
                :disabled="!selectedCount() || worksLoading || extracting || extractSubmitting"
                @click="startDiscoverWorks">
          {{ worksLoading ? '发现作业中…' : '📚 发现所选班级的作业（只读）' }}
        </button>
        <button class="btn primary" style="margin-left:8px"
                :disabled="!selectedCount() || extracting || extractSubmitting"
                @click="extractSelected">
          📥 提取所选（{{ selectedCount() }} 个班<template v-if="worksCourses.length"> / {{ selectedWorksCount() }} 份作业</template>）
        </button>
        <button class="btn" style="margin-left:12px" :disabled="importLoading" @click="pickImportFile">
          {{ importLoading ? '导入中…' : '📂 导入旧 run JSON' }}
        </button>
        <input ref="importInput" type="file" accept=".json,application/json" style="display:none" @change="onImportFile" />
      </p>
      <details class="hint" style="margin:6px 0">
        <summary>高级：全量提取账户数据（忽略当前勾选，自动发现全部课程/班级，较慢）</summary>
        <p style="margin:6px 0">
          <button class="btn" :disabled="verdict!=='alive' || extracting || extractSubmitting || loadingRun" @click="startExtract">
            {{ extracting || extractSubmitting ? '全量提取中…' : '📥 全量提取账户数据' }}
          </button>
          <span class="hint">等价于 CLI <code>assist xxt extract --all</code>；仅在确实需要整账户数据时使用。</span>
        </p>
      </details>
      <p v-if="targetMsg" class="hint">{{ targetMsg }}</p>
      <p v-if="targetsAt" class="hint">
        上次发现：{{ targetsAt }}
        （<b :style="{ color: ageColor(targetsAge) }">{{ fmtAge(targetsAge) }}</b>）
        · 历史快照 {{ targetsHistory }} 份
        <button class="btn" style="margin-left:8px" :disabled="!targetsHistory" @click="clearTargetsHistory">🧹 清理发现快照</button>
        <span style="color:var(--c-muted)">（清单仅存本机引擎；默认只发现你教的课）</span>
      </p>
      <p v-if="targetsAge != null && targetsAge > 86400" class="hint"
         :style="{ color: targetsAge > 7 * 86400 ? 'var(--c-danger, #dc2626)' : '#7a5c00' }">
        ⚠ 发现结果已 {{ fmtAge(targetsAge) }} 未刷新，平台上可能有新增/删除的班级；建议先点「刷新发现」。
      </p>
      <div v-if="showDiff" class="hint" style="border:1px dashed var(--c-border); border-radius:8px; padding:8px; margin:6px 0">
        <b>相比上次（{{ targetsDiff?.against_at || '—' }}）的变化：</b>
        新增 {{ targetsDiff?.counts?.courses_added || 0 }} 门课 / {{ targetsDiff?.counts?.classes_added || 0 }} 个班，
        移除 {{ targetsDiff?.counts?.courses_removed || 0 }} 门课 / {{ targetsDiff?.counts?.classes_removed || 0 }} 个班，
        改名 {{ targetsDiff?.counts?.renamed || 0 }} 处。
        <details v-if="(targetsDiff?.courses_removed?.length || targetsDiff?.classes_removed?.length)">
          <summary>查看已移除项</summary>
          <div v-for="x in targetsDiff?.courses_removed || []" :key="'cr' + x.courseId"
               style="text-decoration:line-through; color:var(--c-danger, #dc2626)">
            课程：{{ x.name }}（{{ x.courseId }}）
          </div>
          <div v-for="x in targetsDiff?.classes_removed || []" :key="'kr' + x.courseId + ':' + x.classId"
               style="text-decoration:line-through; color:var(--c-danger, #dc2626)">
            班级：{{ x.courseName || x.courseId }} / {{ x.name }}（{{ x.classId }}）
          </div>
        </details>
        <button class="btn small" style="margin-left:8px" @click="ackDiff">知道了</button>
      </div>
      <p v-if="worksMsg" class="hint">{{ worksMsg }}</p>
      <p v-if="worksAt" class="hint" style="color:var(--c-muted)">
        作业清单发现时间：{{ worksAt }}（默认不选；勾选后才会提取对应作业）
      </p>
      <div v-if="targets.length"
           style="border:1px solid var(--c-border); border-radius:8px; padding:8px">
        <div style="display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:8px">
          <input v-model.trim="targetQuery" type="search" placeholder="搜索课程 / 班级 / ID"
                 style="flex:1; min-width:180px; padding:4px 6px" />
          <button class="btn small" :disabled="!visibleTargetCourses.length" @click="expandAllCourses(true)">展开全部</button>
          <button class="btn small" :disabled="!visibleTargetCourses.length" @click="expandAllCourses(false)">折叠全部</button>
          <span class="hint" style="color:var(--c-muted)">已选 {{ selectedCount() }} / {{ totalClassCount() }} 班</span>
        </div>
        <p v-if="!visibleTargetCourses.length" class="hint" style="color:var(--c-muted)">没有匹配的课程/班级。</p>
        <div style="max-height:360px; overflow:auto">
          <details v-for="c in visibleTargetCourses" :key="c.courseId"
                   :open="isCourseExpanded(c)" @toggle="onCourseDetailsToggle(c, $event)"
                   style="margin-bottom:8px; border-bottom:1px solid var(--c-border); padding-bottom:6px">
            <summary style="font-weight:600; cursor:pointer; padding:4px 2px">
              <input type="checkbox"
                     :checked="c.classes.length > 0 && c.classes.every(k => isSel(c, k))"
                     @click.stop @change="onCourseToggle(c, $event)" />
              {{ c.name }}
              <span v-if="isCourseAdded(c)" class="tag" style="background:#dcfce7;color:#166534;padding:1px 6px;border-radius:6px;font-size:12px">新增</span>
              <span v-else-if="courseRename(c)" class="tag" style="background:#ffedd5;color:#9a3412;padding:1px 6px;border-radius:6px;font-size:12px">{{ courseRename(c) }}</span>
              <span class="hint" style="color:var(--c-muted)">
                courseId {{ c.courseId }} · {{ c.classes.length }} 班 · 已选 {{ selectedClassCount(c) }}
              </span>
            </summary>
            <div style="margin:6px 0 0 22px">
              <div v-for="(k, ki) in c.classes" :key="k.classId"
                   :style="{ marginBottom: '8px', padding: '2px 4px', borderRadius: '6px',
                             background: ki % 2 === 1 ? 'var(--c-zebra, #f7f9fc)' : 'transparent' }">
                <label>
                  <input type="checkbox" :checked="isSel(c, k)" @change="onClassToggle(c, k, $event)" />
                  {{ k.name }}
                  <span v-if="isClassAdded(c, k)" class="tag" style="background:#dcfce7;color:#166534;padding:1px 5px;border-radius:6px;font-size:11px">新增</span>
                  <span v-else-if="classRename(c, k)" class="tag" style="background:#ffedd5;color:#9a3412;padding:1px 5px;border-radius:6px;font-size:11px">{{ classRename(c, k) }}</span>
                  <span v-if="hasWorks(c, k)" class="hint" style="color:var(--c-muted)">（{{ worksOf(c, k).length }} 份作业）</span>
                </label>
                <div v-if="hasWorks(c, k)" style="margin:4px 0 0 22px; display:flex; flex-wrap:wrap; gap:12px">
                  <label v-for="w in worksOf(c, k)" :key="w.workId" class="hint">
                    <input type="checkbox" :checked="isWorkSel(c, k, w)" @change="onWorkToggle(c, k, w, $event)" />
                    {{ w.name }}
                    <span style="color:var(--c-muted)">待批 {{ w.pending ?? '-' }} / 已交 {{ w.submitted ?? '-' }} / 未交 {{ w.unsubmitted ?? '-' }}</span>
                  </label>
                  <span v-if="!worksOf(c, k).length" class="hint" style="color:var(--c-muted)">（该班未发现作业）</span>
                </div>
              </div>
              <span v-if="!c.classes.length" class="hint" style="color:var(--c-muted)">（未发现班级）</span>
            </div>
          </details>
        </div>
      </div>
      <p v-else class="hint" style="color:var(--c-muted)">
        点「发现课程/班级」后在此勾选；旧数据可点「导入旧 run JSON」后自动刷新列表。
      </p>
    </div>

    <!-- 列表卡 -->
    <div class="card">
      <h3>发现作业 <small style="font-weight:400;color:var(--c-muted)">提取后按班级/作业展示结果（数据=最近 run JSON）；预览使用同一次提取的存档，点开行看名单</small></h3>
      <p>
        <button class="btn" :disabled="loadingRun" @click="refreshRuns">⟳ 刷新列表（读取已有 run）</button>
        <button class="btn" style="margin-left:8px" @click="restoreRemoved">♻ 从学习通恢复列表（回放最近 run）</button>
        <label class="field" style="margin-left:12px">置顶上限：
          <select v-model.number="pinCap" @change="persistLocal" style="width:80px">
            <option v-for="n in [5,10,15,20]" :key="n" :value="n">{{ n }}</option>
          </select>
        </label>
        <button class="btn" style="margin-left:8px" @click="() => loadRun(curRun || '')" :disabled="!curRun">重载本 run</button>
        <button class="btn" style="margin-left:8px" @click="deleteCurrentRun" :disabled="!curRun">🗑 删除本 run</button>
        <label class="field" style="margin-left:12px">筛选：
          <select v-model="filterMode" style="width:150px">
            <option value="all">全部班级</option>
            <option value="hasWorks">有作业（多→少）</option>
            <option value="empty">确认为 0</option>
            <option value="fail">未提取（失败）</option>
          </select>
        </label>
      </p>
      <p v-if="runMsg" class="hint">{{ runMsg }}</p>
      <p v-if="runs.length" class="hint" style="color:var(--c-muted)">
        历史 run：
        <select v-model="curRun" @change="loadRun(curRun || '')" style="max-width:240px">
          <option v-for="r in runs" :key="r.run_id" :value="r.run_id">
            {{ r.run_id }}（{{ r.works || 0 }} 作业/失败 {{ r.failures || 0 }}）
          </option>
        </select>
      </p>

      <div v-if="grouped.length" style="border:1px solid var(--c-border); border-radius:8px; overflow:auto">
        <table style="width:100%; border-collapse:collapse; table-layout:fixed">
          <colgroup>
            <col style="width:22%" /><col style="width:44%" /><col style="width:12%" /><col style="width:22%" />
          </colgroup>
          <thead>
            <tr style="position:sticky; top:0; z-index:3; background:var(--c-surface,#fff)">
              <th style="text-align:left; padding:6px 8px">班级</th>
              <th style="padding:6px 8px">作业（待批 / 已交 / 未交）</th>
              <th style="padding:6px 8px">状态</th>
              <th style="padding:6px 8px">操作</th>
            </tr>
          </thead>
          <tbody v-for="g in grouped" :key="g.course.courseId">
            <tr>
              <td colspan="4" style="padding:6px 8px; background:var(--c-bg,#f7f7f9); border-top:1px solid var(--c-border)">
                <b>{{ g.course.name }}</b>
                <span class="hint" style="margin-left:8px; color:var(--c-muted)">courseId {{ g.course.courseId }} · {{ g.pinnedRows.length + g.normal.length }} 班</span>
              </td>
            </tr>
            <tr v-for="(cl, ri) in [...g.pinnedRows, ...g.normal]" :key="cl.classId"
                :style="{ background: rowBg(cl, ri) }">
              <td style="padding:6px 8px; white-space:normal; word-break:break-word">
                {{ cl.name }}{{ isPinned(cl) ? ' 📌' : '' }}
              </td>
              <td style="padding:6px 8px; white-space:normal; word-break:break-word">
                <span v-if="!cl.works.length">–</span>
                <details v-else>
                  <summary style="background:transparent">{{ cl.works.length }} 份</summary>
                  <table style="width:100%; border-collapse:collapse; margin-top:4px; background:transparent">
                    <thead>
                      <tr class="hint" style="color:var(--c-muted); font-size:12px">
                        <th style="text-align:left; padding:2px 4px">作业</th>
                        <th style="padding:2px 4px">待批</th>
                        <th style="padding:2px 4px">已交</th>
                        <th style="padding:2px 4px">未交</th>
                        <th style="padding:2px 4px">预览</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="w in cl.works" :key="w.workId">
                        <td style="padding:2px 4px; white-space:normal; word-break:break-word">{{ w.name }}</td>
                        <td style="padding:2px 4px; text-align:center">{{ w.pending ?? '-' }}</td>
                        <td style="padding:2px 4px; text-align:center">{{ w.submitted ?? '-' }}</td>
                        <td style="padding:2px 4px; text-align:center">{{ w.unsubmitted ?? '-' }}</td>
                        <td style="padding:2px 4px; text-align:center; white-space:nowrap">
                          <button class="btn" style="padding:2px 8px" @click="openReview(cl, w)">👁 预览</button>
                          <button class="btn" style="padding:2px 8px; margin-left:4px"
                                  :disabled="probeLoading" @click="startProbe(g.course, cl, w)">🧪</button>
                          <button class="btn" style="padding:2px 8px; margin-left:4px"
                                  :disabled="reviewDlLoading" @click="downloadReview(g.course, cl, w)">⬇</button>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                  <div style="margin-top:6px; background:transparent">
                    <details style="background:transparent">
                      <summary class="hint" style="background:transparent">未交名单 / 白名单（仅本机教师端可见）</summary>
                      <div v-for="w in cl.works" :key="'n' + w.workId" style="margin:4px 0; font-size:12px">
                        <b>{{ w.name }}</b>：
                        <span>未交（{{ (w.unsubmitted_names || []).length }}）：</span>
                        <span style="word-break:break-all">{{ (w.unsubmitted_names || []).join('、') || '（无差集或本班无名册基准）' }}</span>
                        <span v-if="(w.sub_not_in_roster || []).length "> ｜ 提交但不在名册（白名单）：</span>
                        <span v-if="(w.sub_not_in_roster || []).length" style="word-break:break-all">{{ (w.sub_not_in_roster || []).join('、') }}</span>
                      </div>
                    </details>
                  </div>
                </details>
              </td>
              <td style="padding:6px 8px; text-align:center">
                {{ cl.status === 'extracted' ? '✅' : (cl.status === 'empty_confirmed' ? '∅0' : '⚠ 未提取') }}
              </td>
              <td style="padding:6px 8px; text-align:center; white-space:normal">
                <button class="btn" @click="togglePin(cl)">{{ isPinned(cl) ? '取消置顶' : '📌 置顶' }}</button>
                <button class="btn" style="margin-left:4px" @click="removeRow(cl)">✕ 移出</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="hint" style="color:var(--c-muted)">
        暂无列表数据：引擎侧先运行 <code>assist xxt extract --targets …</code> 或在 .scratch 放置 run JSON。
      </p>
    </div>
    <!-- D75-1d 批阅图片：按班级/作业文件夹 + 6 个月清理 -->
    <div class="card" v-if="reviewIndex.length || reviewDlMsg">
      <h3>批阅图片 <small style="font-weight:400;color:var(--c-muted)">按班级/作业分文件夹；图片用「学生_班级+作业_pNN」命名；保留 6 个月，可手动清理</small>
        <button class="btn" style="float:right" @click="pruneReview">🧹 清理 6 个月前</button>
        <button class="btn" style="float:right; margin-right:8px" @click="refreshReviewIndex">🔄 刷新本区</button>
      </h3>
      <p class="hint">
        共 {{ reviewIndexStats.works ?? 0 }} 个作业目录 / {{ reviewIndexStats.images ?? 0 }} 张图 /
        {{ fmtBytes(reviewIndexStats.bytes) }}
        <span v-if="reviewDlMsg">｜{{ reviewDlMsg }}</span>
      </p>
      <p v-if="probeMsg" class="hint">{{ probeMsg }}</p>
      <div v-if="probeResult" class="hint"
           style="border:1px dashed var(--c-border); border-radius:8px; padding:8px; margin:6px 0">
        <b>探针结果</b>：学生 {{ probeResult.students?.length || 0 }} 人
        <div v-for="(d, i) in probeResult.details || []" :key="i">
          {{ d.name }}：图片 {{ d.images }}，作业批语 {{ d.comment_len }} 字，
          题目批语 {{ d.per_question_comments }} 栏，分数 {{ d.score || '—' }}
          <span v-if="d.error" style="color:var(--c-danger,#dc2626)">（{{ d.error }}）</span>
        </div>
        <div v-if="(probeResult.aborted || []).length" style="margin-top:6px">
          <b>被拦截的非 GET 请求（勾选=下次下载放行这些只读请求）：</b>
          <label v-for="(a, i) in probeResult.aborted" :key="i" style="display:block; margin:2px 0">
            <input type="checkbox" :checked="allowPost.includes(a.url || '')"
                   @change="toggleAllowPost(a.url || '')" />
            {{ a.method }} {{ (a.url || '').slice(0, 110) }}
          </label>
        </div>
        <div v-else style="margin-top:4px">没有非 GET 请求被拦截。</div>
      </div>
      <details v-for="(items, cid) in reviewByClass" :key="cid"
               style="border:1px solid var(--c-border); border-radius:8px; margin-bottom:8px">
        <summary style="cursor:pointer; padding:8px; font-weight:600">
          {{ items[0]?.className || cid }}
          <span class="hint" style="color:var(--c-muted)">（{{ items.length }} 次作业）</span>
        </summary>
        <div style="padding:0 8px 8px">
          <div v-for="(it, i) in items" :key="i" style="border-top:1px solid var(--c-border); padding:8px 0">
            <b>{{ it.workName || it.workId }}</b>
            <span class="hint" style="color:var(--c-muted)">
              （作答 {{ it.count }} / 评语 {{ it.comment_count || 0 }} 图 / {{ it.students }} 人 /
              {{ it.zero_image_count ?? 0 }} 人 0 作答图 / {{ fmtBytes(it.bytes) }}<template v-if="it.generated_at"> / {{ it.generated_at }}</template>）
            </span>
            <span v-if="it.images_deleted" class="tag"
                  style="background:#fee2e2;color:#991b1b;padding:1px 6px;border-radius:6px;margin-left:6px">图片已删除（保留清单）</span>
            <button class="btn" style="padding:2px 8px; margin-left:8px" @click="openReviewWork(it)">👁 打开预览</button>
            <button class="btn" style="padding:2px 8px; margin-left:4px" @click="deleteReviewWork(it)">🗑 删除图片</button>
            <button class="btn" style="padding:2px 8px; margin-left:4px" @click="purgeReviewWork(it)">🗑 彻底删除</button>
            <div v-if="!it.images_deleted && (it.zero_image_students || []).length"
                 class="hint" style="color:#7a5c00">
              0 图学生：{{ (it.zero_image_students || []).join('、') }}
            </div>
            <div v-if="!it.images_deleted" style="display:flex; flex-wrap:wrap; gap:6px; margin-top:6px">
              <img v-for="f in it.images" :key="f" :src="reviewFileUrl(it, f)" :alt="f"
                   style="width:96px; height:72px; object-fit:cover; border:1px solid var(--c-border); border-radius:4px" />
            </div>
          </div>
        </div>
      </details>
    </div>

    <!-- D73-11 历史 run 管理：时间/班级/作业/失败数 + 单删/清空（含 run 级 HTML 存档） -->
    <div class="card" v-if="runs.length">
      <h3>历史 run 管理
        <small style="font-weight:400;color:var(--c-muted)">时间 / 班级 / 作业 / 失败数；删除=JSON+截图+run 级 HTML 存档</small>
        <button class="btn" style="float:right" @click="clearAllRuns">🗑 清空全部历史（{{ runs.length }}）</button>
        <button class="btn" style="float:right; margin-right:8px" @click="pruneRuns">🧹 按容量清理</button>
      </h3>
      <p class="hint" style="color:var(--c-muted)">
        run 工件：{{ storageStats.count ?? runs.length }} 条 / {{ storageStats.max_count ?? 1000 }} 条 ·
        {{ fmtBytes(storageStats.bytes) }} / {{ fmtBytes(storageStats.max_bytes || 50 * 1024 * 1024) }}
        <span v-if="storageMsg">｜{{ storageMsg }}</span>
      </p>
      <div style="max-height:300px; overflow:auto; border:1px solid var(--c-border); border-radius:8px">
        <table style="width:100%; border-collapse:collapse">
          <thead>
            <tr style="position:sticky; top:0; background:var(--c-surface,#fff)">
              <th style="text-align:left; padding:6px 8px">run</th>
              <th style="padding:6px 8px">结束时间</th>
              <th style="padding:6px 8px">班级</th>
              <th style="padding:6px 8px">作业</th>
              <th style="padding:6px 8px">失败</th>
              <th style="padding:6px 8px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in runs" :key="r.run_id"
                :style="r.run_id === curRun ? 'background:var(--c-pin-bg,#fffbe8)' : ''">
              <td style="padding:6px 8px">{{ r.run_id }}</td>
              <td style="padding:6px 8px; text-align:center">{{ r.ts_end || r.ts_start || '—' }}</td>
              <td style="padding:6px 8px; text-align:center">{{ r.classes ?? 0 }}</td>
              <td style="padding:6px 8px; text-align:center">{{ r.works ?? 0 }}</td>
              <td style="padding:6px 8px; text-align:center">{{ r.failures ?? 0 }}</td>
              <td style="padding:6px 8px; text-align:center; white-space:nowrap">
                <button class="btn" @click="loadRun(r.run_id)">载入</button>
                <button class="btn" style="margin-left:4px" @click="removeRun(r.run_id)">🗑 删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 导航过程展示框（§20.3 方案 A 抽共享组件 D64-b） -->
    <div class="card" v-if="loadSteps.length">
      <h3>Playwright 浏览器操作历史 <small style="font-weight:400;color:var(--c-muted)">按 run 追加；每跳一张缩略图（引擎真会话所拍）</small></h3>
      <ProcessStreamView :run-id="curRun || ''" :steps="loadSteps" :engine-addr="engUrl" :token="tok" />
    </div>

    <!-- D75-1 真实批阅列表预览（本机 review 存档，只读） -->
    <div v-if="reviewOpen" @click.self="closeReview"
         style="position:fixed; inset:0; background:rgba(15,23,42,.45); z-index:80; display:flex; align-items:center; justify-content:center">
      <div style="background:var(--c-card,#fff); border-radius:12px; max-width:min(920px,94vw); max-height:88vh; overflow:auto; padding:16px">
        <h3 style="margin-top:0">批阅列表预览：{{ reviewTitle }}
          <button class="btn" style="float:right" @click="closeReview">关闭</button>
        </h3>
        <p class="hint">
          {{ reviewMsg }}
          <template v-if="reviewWorkRef">（已下载图片/批语，可点「逐生预览」查看两列内容）</template>
          <template v-else>（本机未下载该作业图片/批语；请先点该行「⬇」下载，再逐生预览）</template>
        </p>
        <div v-if="reviewLoading" class="hint">读取中…</div>
        <table v-else-if="reviewStudents.length" style="width:100%; border-collapse:collapse">
          <thead>
            <tr style="background:var(--c-bg,#f7f7f9)">
              <th style="text-align:left; padding:6px 8px">学生</th>
              <th style="padding:6px 8px">分数</th>
              <th style="padding:6px 8px">状态</th>
              <th style="padding:6px 8px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(s, i) in reviewStudents" :key="s.studentId || s.name">
              <td style="padding:5px 8px">{{ s.name }}</td>
              <td style="padding:5px 8px; text-align:center">{{ s.score || '—' }}</td>
              <td style="padding:5px 8px; text-align:center"
                  :style="{ color: s.graded ? 'var(--c-ok, #16a34a)': '#7a5c00' }">{{ s.status }}</td>
              <td style="padding:5px 8px; text-align:center">
                <button class="btn" style="padding:2px 8px" @click="openStudentPreview(i)">逐生预览</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="hint">没有可显示的学生行。</p>
      </div>
    </div>
    <!-- D75-4 逐生两列预览：作答 | 批语；旋转 / 上一位 / 下一位（只读） -->
    <div v-if="reviewWorkOpen" @click.self="closeReviewWork"
         style="position:fixed; inset:0; background:rgba(15,23,42,.5); z-index:85; display:flex; align-items:center; justify-content:center">
      <div style="background:var(--c-card,#fff); border-radius:12px; max-width:min(1100px,96vw); max-height:90vh; overflow:auto; padding:16px">
        <h3 style="margin-top:0">逐生预览：{{ reviewWorkTitle }}
          <span class="hint" style="font-weight:400">（第 {{ reviewWorkIdx + 1 }} / {{ reviewWorkStudents.length }} 位）</span>
          <button class="btn" style="float:right" @click="closeReviewWork">关闭</button>
        </h3>
        <p>
          <button class="btn" :disabled="reviewWorkIdx <= 0" @click="prevStudent">← 上一位</button>
          <button class="btn" style="margin-left:6px"
                  :disabled="reviewWorkIdx >= reviewWorkStudents.length - 1" @click="nextStudent">下一位 →</button>
          <button class="btn" style="margin-left:12px" @click="rotateImage(-90)">↺ 左旋</button>
          <button class="btn" style="margin-left:6px" @click="rotateImage(90)">↻ 右旋</button>
          <label class="field" style="margin-left:12px">搜索学生：
            <input v-model="reviewSearch" @keyup.enter="searchStudent" placeholder="姓名" style="width:120px" />
          </label>
          <button class="btn" style="margin-left:6px" @click="searchStudent">🔍</button>
          <button class="btn" style="margin-left:12px" @click="toggleCurrentLayout">
            {{ reviewLayout === 'cols' ? '⇵ 上下布局' : '⇋ 左右布局' }}
          </button>
          <span class="hint" style="margin-left:8px">
            当前学生：{{ curStudent?.name || '—' }} · 分数 {{ curStudent?.score || '—' }}
          </span>
        </p>
        <div v-if="reviewWorkLoading" class="hint">读取中…</div>
        <div v-else-if="curStudent"
             :style="{ display: 'flex', gap: '14px', alignItems: 'flex-start', flexWrap: 'wrap',
                       flexDirection: reviewLayout === 'rows' ? 'column' : 'row' }">
          <div :style="{ flex: reviewLayout === 'rows' ? 'none' : '1.2', width: reviewLayout === 'rows' ? '100%' : 'auto', minWidth: '280px' }">
            <h4>学生作答（{{ curImages.length }} 张）</h4>
            <div style="display:flex; flex-direction:column; gap:8px; overflow:auto; max-height:64vh;
                        border:1px solid var(--c-border); border-radius:8px; padding:6px">
              <img v-for="(f, i) in curImages" :key="f" :src="curImageUrl(f)" :alt="f"
                   @click="reviewWorkImgIdx = i"
                   :style="{ width: '100%', height: 'auto', objectFit: 'contain',
                             border: reviewWorkImgIdx === i ? '2px solid var(--c-primary,#1d4ed8)' : '1px solid var(--c-border)',
                             borderRadius: '6px',
                             transform: `rotate(${reviewWorkRotate}deg)`,
                             cursor: 'pointer' }" />
              <span v-if="!curImages.length" class="hint" style="color:#7a5c00">
                该生 0 作答图（补交/教师代传时评语里通常有报告图片，见右侧）
              </span>
            </div>
          </div>
          <div :style="{ flex: reviewLayout === 'rows' ? 'none' : '1', width: reviewLayout === 'rows' ? '100%' : 'auto', minWidth: '280px' }">
            <h4>批语 / 评语</h4>
            <div style="border:1px solid var(--c-border); border-radius:8px; padding:8px; min-height:180px">
              <div><b>作业批语：</b></div>
              <div style="white-space:pre-wrap; word-break:break-word">
                {{ curCommentText || '（空）' }}
              </div>
              <img v-for="f in (curStudent.comment_images || [])" :key="f" :src="curImageUrl(f)" :alt="f"
                   style="max-width:100%; margin-top:6px; border:1px solid var(--c-border); border-radius:6px" />
              <p v-if="curCommentStale" class="hint" style="color:#7a5c00">
                ⚠ 该作业是旧版下载：评语图片未本地化（当前只显示文字）。请关闭弹窗后点该行「⬇」重新下载一次。
              </p>
              <div style="margin-top:8px"><b>题目批语：</b></div>
              <div v-for="(t, i) in curPQTexts"
                   :key="i" style="white-space:pre-wrap; word-break:break-word; margin-top:4px">
                第 {{ i + 1 }} 题：{{ t || '（空）' }}
                <img v-for="f in ((curStudent.per_question_comment_images || [])[i] || [])" :key="f"
                     :src="curImageUrl(f)" :alt="f"
                     style="max-width:100%; display:block; margin-top:4px; border:1px solid var(--c-border); border-radius:6px" />
              </div>
              <div v-if="!curPQTexts.length" class="hint">（空）</div>
            </div>
            <p class="hint" style="color:var(--c-muted)">
              人工批阅（预览/覆盖/增加/取消）需写回平台，属写操作；当前冻结，先完成只读预览/审核。
            </p>
          </div>
        </div>
        <p v-else class="hint">没有学生记录。</p>
      </div>
    </div>
  </section>
</template>

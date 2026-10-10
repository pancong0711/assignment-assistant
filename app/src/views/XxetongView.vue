<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  clearXxtRuns, deleteXxtRun, fetchXxtLoginJob, fetchXxtRun, fetchXxtRuns,
  fetchXxtStatus, fetchXxtTargets, importXxtRun, startXxtDiscover, startXxtExtract,
  startXxtExtractTargets, startXxtLogin,
} from '../lib/engineClient'
import { useSettingsStore } from '../stores/settings'
import { useXxtJobsStore } from '../stores/xxtJobs'
import ProcessStreamView from '../components/ProcessStreamView.vue'

/* 学习通 tab（D63 T7/T8 实装，docs/16 §20）：
 * - 登录卡：QR 框（/xxt/qr）↔ 头像（verdict=alive 时 data-URL）；
 * - 列表：/xxt/runs 最新 run 的 全 course 分组列表，组头 sticky、每列表独立滚动；
 * - 行操作：置顶(≤10 可调)/移出/刷新/从学习通恢复（恢复=仅回放最近 run JSON，零网络）。
 * 写操作（公告发布/批阅回传）维持 D62 冻结——本页不提供任何写按钮。   */

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

async function refreshRuns() {
  loadingRun.value = true
  runMsg.value = ''
  try {
    runs.value = await fetchXxtRuns(engUrl.value, tok.value)
    if (!runs.value.length) { runMsg.value = '暂无 run（引擎侧 xxt extract run 未产出）'; return }
    await loadRun(runs.value[0].run_id)
  } catch (e) {
    runMsg.value = `引擎不可达：${String(e)}`
  } finally { loadingRun.value = false }
}

async function loadRun(id: string) {
  loadingRun.value = true
  try {
    const raw = (await fetchXxtRun(engUrl.value, tok.value, id)) as Record<string, unknown>
    curRun.value = String(raw['run_id'] || id)
    courses.value = (raw['courses'] as CourseRow[]) || []
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
        runMsg.value = '提取完成，正在刷新列表……'
        await refreshRuns()
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
interface TargetClass { name: string; classId: string }
interface TargetCourse { name: string; courseId: string; classes: TargetClass[] }
const targets = ref<TargetCourse[]>([])
const targetsAt = ref('')
const targetSel = ref<Record<string, boolean>>({})
const targetMsg = ref('')
const discoverLoading = ref(false)
const importLoading = ref(false)
const importInput = ref<HTMLInputElement | null>(null)
let discoverTimer: number | undefined

function tkey(c: TargetCourse, k: TargetClass): string { return `${c.courseId}:${k.classId}` }
function isSel(c: TargetCourse, k: TargetClass): boolean { return targetSel.value[tkey(c, k)] !== false }
function onClassToggle(c: TargetCourse, k: TargetClass, ev: Event) {
  targetSel.value[tkey(c, k)] = (ev.target as HTMLInputElement).checked
}
function onCourseToggle(c: TargetCourse, ev: Event) {
  const on = (ev.target as HTMLInputElement).checked
  for (const k of c.classes) targetSel.value[tkey(c, k)] = on
}
function toggleAll(on: boolean) {
  for (const c of targets.value) for (const k of c.classes) targetSel.value[tkey(c, k)] = on
}
function selectedTargets(): TargetCourse[] {
  return targets.value
    .map(c => ({ ...c, classes: c.classes.filter(k => isSel(c, k)) }))
    .filter(c => c.classes.length > 0)
}
function selectedCount(): number {
  return selectedTargets().reduce((a, c) => a + c.classes.length, 0)
}
function stopDiscoverPolling() {
  if (discoverTimer !== undefined) { window.clearTimeout(discoverTimer); discoverTimer = undefined }
}
async function loadTargets() {
  const o = await fetchXxtTargets(engUrl.value, tok.value)
  targets.value = (o.courses || []) as TargetCourse[]
  targetsAt.value = o.discovered_at || ''
  const sel: Record<string, boolean> = {}
  for (const c of targets.value) for (const k of c.classes) sel[tkey(c, k)] = true
  targetSel.value = sel
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
        targetMsg.value = `发现完成：${targets.value.length} 门课 / ${selectedCount()} 个班（默认全选，可取消）`
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
  const sel = selectedTargets()
  const n = sel.reduce((a, c) => a + c.classes.length, 0)
  if (!n) { targetMsg.value = '请先勾选至少一个班级'; return }
  stopExtractPolling()
  extractSubmitting.value = true
  targetMsg.value = `正在提取所选 ${n} 个班……`
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


onMounted(() => {
  refreshStatus()
  refreshRuns()
  loadTargets().catch(() => { /* 无历史发现结果时忽略 */ })
  // D73：切换 tab 回来后恢复提取 job 轮询
  if (xxtJobs.extractJobId) {
    runMsg.value = xxtJobs.extractMsg || '提取任务进行中……'
    pollExtractJob(xxtJobs.extractJobId)
  }
})
onUnmounted(() => { loginSeq += 1; stopLoginPolling(); stopExtractPolling(); stopDiscoverPolling() })
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

    <!-- §23.3 发公告向导卡（占位 disabled；T10 冻结——表单形态预览，无任何提交逻辑） -->
    <div class="card">
      <h3>发公告 <small style="font-weight:400;color:var(--c-muted)">占位（T10 冻结；表单按 §23.3 设计预置，解冻后接引擎写会话）</small>
        <span class="tag" style="background:#fff3cd; color:#7a5c00; padding:2px 8px; border-radius:6px; font-size:12px">🔒 写操作冻结</span></h3>
      <fieldset :disabled="true" style="border:none; opacity:.65">
        <p>
          <label class="field">发布班级（多选，来自已提取班）：
            <select multiple disabled style="width:260px" size="3">
              <option v-for="c in courses" :key="c.courseId" disabled>{{ c.name }}</option>
            </select>
          </label>
        </p>
        <p><label class="field">标题（≤128 字）：
          <input type="text" maxlength="128" disabled placeholder="第X章作业说明（占位）" style="width:320px" />
        </label></p>
        <p><label class="field" style="vertical-align:top">正文：
          <textarea rows="3" disabled placeholder="公告正文（占位；解冻后为富文本/纯文本）" style="width:min(480px,90%); vertical-align:middle"></textarea>
        </label></p>
        <p><label class="btn as-label btn-file" disabled title="占位：选择「输出与交付」生成的作业纸 PDF">附件（作业纸 PDF）选择器…</label>
          <span class="hint" style="margin-left:8px">尚未选择（占位）</span></p>
        <p class="hint">定时发送 / 提醒渠道：占位（缺省关闭，§23.1 侦察对应 .scheduledSend 与四渠道提醒）</p>
        <p>
          <button class="btn" disabled>👁 发送前预览（占位）</button>
          <button class="btn primary" disabled style="margin-left:8px">📢 发布（占位·双确认后启用）</button>
        </p>
      </fieldset>
      <p class="hint" style="color:var(--c-muted)">
        解冻流程（docs/16 §23.2）：教师确认测试班 → 引擎写会话（route 白名单仅公告域+上传 CDN）→
        发送前快照存档 → 二次确认 → 提交；本卡所有控件 disabled，不含任何提交逻辑。
      </p>
    </div>

    <!-- 导航过程展示框（§20.3 方案 A 抽共享组件 D64-b） -->
    <div class="card" v-if="loadSteps.length">
      <h3>Playwright 浏览器操作历史 <small style="font-weight:400;color:var(--c-muted)">按 run 追加；每跳一张缩略图（引擎真会话所拍）</small></h3>
      <ProcessStreamView :run-id="curRun || ''" :steps="loadSteps" :engine-addr="engUrl" :token="tok" />
    </div>

    <!-- D72 targets：只读发现 → 勾选 → 按需提取；D73-9 旧 run 导入 -->
    <div class="card">
      <h3>选择课程/班级提取 <small style="font-weight:400;color:var(--c-muted)">D72 targets：只读发现「我教的课」→ 勾选 → 提取；也可导入旧 run JSON（D73-9）</small></h3>
      <p>
        <button class="btn primary" :disabled="verdict!=='alive' || discoverLoading" @click="startDiscover">
          {{ discoverLoading ? '发现中…' : '🔍 发现课程/班级（只读）' }}
        </button>
        <button class="btn" style="margin-left:8px" :disabled="!targets.length" @click="toggleAll(true)">全选</button>
        <button class="btn" style="margin-left:8px" :disabled="!targets.length" @click="toggleAll(false)">全不选</button>
        <button class="btn primary" style="margin-left:8px"
                :disabled="!selectedCount() || extracting || extractSubmitting"
                @click="extractSelected">
          📥 提取所选（{{ selectedCount() }} 个班）
        </button>
        <button class="btn" style="margin-left:12px" :disabled="importLoading" @click="pickImportFile">
          {{ importLoading ? '导入中…' : '📂 导入旧 run JSON' }}
        </button>
        <input ref="importInput" type="file" accept=".json,application/json" style="display:none" @change="onImportFile" />
      </p>
      <p v-if="targetMsg" class="hint">{{ targetMsg }}</p>
      <p v-if="targetsAt" class="hint" style="color:var(--c-muted)">
        发现时间：{{ targetsAt }}（课程/班级清单仅存本机引擎；默认只发现你教的课）
      </p>
      <div v-if="targets.length" style="max-height:360px; overflow:auto; border:1px solid var(--c-border); border-radius:8px; padding:8px">
        <div v-for="c in targets" :key="c.courseId" style="margin-bottom:10px">
          <label style="font-weight:600">
            <input type="checkbox" :checked="c.classes.every(k => isSel(c, k))" @change="onCourseToggle(c, $event)" />
            {{ c.name }}
            <span class="hint" style="color:var(--c-muted)">courseId {{ c.courseId }} · {{ c.classes.length }} 班</span>
          </label>
          <div style="display:flex; flex-wrap:wrap; gap:10px; margin:6px 0 0 22px">
            <label v-for="k in c.classes" :key="k.classId">
              <input type="checkbox" :checked="isSel(c, k)" @change="onClassToggle(c, k, $event)" />
              {{ k.name }}
            </label>
            <span v-if="!c.classes.length" class="hint" style="color:var(--c-muted)">（未发现班级）</span>
          </div>
        </div>
      </div>
      <p v-else class="hint" style="color:var(--c-muted)">
        点「发现课程/班级」后在此勾选；旧数据可点「导入旧 run JSON」后自动刷新列表。
      </p>
    </div>

    <!-- D73-11 历史 run 管理：时间/班级/作业/失败数 + 单删/清空（含 run 级 HTML 存档） -->
    <div class="card" v-if="runs.length">
      <h3>历史 run 管理
        <small style="font-weight:400;color:var(--c-muted)">时间 / 班级 / 作业 / 失败数；删除=JSON+截图+run 级 HTML 存档</small>
        <button class="btn" style="float:right" @click="clearAllRuns">🗑 清空全部历史（{{ runs.length }}）</button>
      </h3>
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

    <!-- 列表卡 -->
    <div class="card">
      <h3>读提取结果 <small style="font-weight:400;color:var(--c-muted)">基于最近 run JSON（§19 schema）；点开行看名单</small></h3>
      <p>
        <button class="btn primary" :disabled="extracting || extractSubmitting || loadingRun" @click="startExtract">{{ extracting || extractSubmitting ? '提取中…' : '📥 提取账户数据' }}</button>
        <button class="btn" style="margin-left:8px" :disabled="loadingRun" @click="refreshRuns">⟳ 刷新列表（读取已有 run）</button>
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

      <div v-if="grouped.length" style="display:flex; flex-direction:column; gap:16px">
        <div v-for="g in grouped" :key="g.course.courseId" class="course-group">
          <div class="group-head" style="position:sticky; top:0; z-index:5; background:var(--c-bg,#f7f7f9); padding:6px 0; border-bottom:1px solid var(--c-border)">
            <b>{{ g.course.name }}</b>
            <span class="hint" style="margin-left:8px; color:var(--c-muted)">courseId {{ g.course.courseId }} · {{ g.pinnedRows.length + g.normal.length }} 班</span>
          </div>
          <div class="class-scroll" style="max-height:420px; overflow-y:auto; border:1px solid var(--c-border); border-radius:8px">
            <table style="width:100%; border-collapse:collapse">
              <thead>
                <tr style="position:sticky; top:32px; background:var(--c-surface,#fff)">
                  <th style="text-align:left; padding:6px 8px">班级</th>
                  <th style="padding:6px 8px">作业</th>
                  <th style="padding:6px 8px">状态</th>
                  <th style="padding:6px 8px">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="cl in [...g.pinnedRows, ...g.normal]" :key="cl.classId"
                    :style="isPinned(cl) ? 'background:var(--c-pin-bg,#fffbe8)' : ''">
                  <td style="padding:6px 8px">
                    {{ cl.name }}{{ isPinned(cl) ? ' 📌' : '' }}
                  </td>
                  <td style="padding:6px 8px; text-align:center">
                    <span v-if="!cl.works.length">–</span>
                    <details v-else>
                      <summary>{{ cl.works.length }} 份</summary>
                      <table style="border-collapse:collapse; margin-top:4px">
                        <tbody>
                          <tr v-for="w in cl.works" :key="w.workId">
                            <td style="padding:2px 6px">{{ w.name }}</td>
                            <td style="padding:2px 6px">{{ w.pending ?? '-' }}/{{ w.submitted ?? '-' }}/{{ w.unsubmitted ?? '-' }}</td>
                            <td style="padding:2px 6px">
                              <span v-if="w.anchor?.roster_delta != null && Math.abs(w.anchor?.roster_delta||0) > 2" class="hint" style="color:#7a5c00">
                                差值{{ w.anchor?.roster_delta }}（含发布人/未入班，灰注）
                              </span>
                            </td>
                          </tr>
                        </tbody>
                      </table>
                      <div style="margin-top:6px">
                        <details>
                          <summary class="hint">未交名单 / 白名单（仅本机教师端可见）</summary>
                          <div v-for="w in cl.works" :key="'n'+w.workId" style="margin:4px 0; font-size:12px">
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
                  <td style="padding:6px 8px; text-align:center; white-space:nowrap">
                    <button class="btn" @click="togglePin(cl)">{{ isPinned(cl) ? '取消置顶' : '📌 置顶' }}</button>
                    <button class="btn" style="margin-left:4px" @click="removeRow(cl)">✕ 移出</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <p v-else class="hint" style="color:var(--c-muted)">
        暂无列表数据：引擎侧先运行 <code>assist xxt extract --targets …</code> 或在 .scratch 放置 run JSON。
      </p>
    </div>
  </section>
</template>

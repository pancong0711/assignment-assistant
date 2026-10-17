<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  copyXxtWork, createXxtWorkFolder, extractJobError, fetchXxtAttachmentWhitelist, fetchXxtLoginJob, fetchXxtNoticeAttachments, fetchXxtRun, fetchXxtRuns, fetchXxtWorkDetail,
  fetchXxtTargets, fetchXxtWorkFolders, fetchXxtWorkList, fetchXxtWriteAllowlist, saveXxtAttachmentWhitelist, saveXxtWriteAllowlist,
  startXxtNoticeSend, startXxtWorkCreate, startXxtWorkPublish, uploadXxtNoticeFiles,
} from '../lib/engineClient'
import type { XxtAllowItem, XxtNoticeAttachment, XxtWorkFolder, XxtWorkLibraryItem } from '../lib/engineClient'
import { useSettingsStore } from '../stores/settings'
import { useXxtRunStore } from '../stores/xxtRun'

const settings = useSettingsStore()
const xxtRun = useXxtRunStore()
const engUrl = computed(() => settings.engineUrl)
const tok = computed(() => settings.engineToken)

interface PubClass { courseId: string; courseName: string; cpi: string; classId: string; name: string }
const classes = ref<PubClass[]>([])
const runId = ref('')
const msg = ref('')
const busy = ref(false)
const previewOpen = ref(false)
const previewTitle = ref('')
const previewLines = ref<string[]>([])
const logOpen = ref(false)
const logTitle = ref('')
const logLines = ref<string[]>([])

function key(c: { courseId: string; classId: string }): string { return `${c.courseId}:${c.classId}` }
/** D83-5.2：作业库文件夹按“班级”而非仅课程记忆（学习通文件夹按班级独立）。 */
function folderKeyOf(c: { courseId: string; classId: string }): string { return `${c.courseId}:${c.classId}` }
const allowKeys = ref<Record<string, boolean>>({})
function allowed(c: { courseId: string; classId: string }): boolean { return allowKeys.value[key(c)] === true }

/** D83-6：班级来源 = 共享「当前 run」；为空回落 runs[0]。
 *  可选合并 targets 全量发现（showAllDiscovered），使不在当前 run 的班也能加入白名单。 */
const showAllDiscovered = ref(false)
async function toggleShowAll() { await loadClasses(); await loadAllow() }

async function loadClasses() {
  try {
    const runs = await fetchXxtRuns(engUrl.value, tok.value)
    if (!runs.length) { msg.value = '暂无已提取批次；请先到「作业预览-学习通」提取班级。'; return }
    // 优先共享当前 run，其次回落最新 run；若该 run 已不存在再回落 runs[0]
    const want = xxtRun.currentRunId && runs.some(r => r.run_id === xxtRun.currentRunId)
      ? xxtRun.currentRunId : runs[0].run_id
    const r = (await fetchXxtRun(engUrl.value, tok.value, want)) as {
      run_id?: string; courses?: { courseId?: string; name?: string; cpi?: string;
      classes?: { classId?: string; name?: string }[] }[]
    }
    runId.value = String(r.run_id || want)
    xxtRun.setCurrentRun(runId.value)
    const map = new Map<string, PubClass>()
    for (const c of r.courses || []) for (const k of c.classes || []) {
      const pc: PubClass = { courseId: String(c.courseId), courseName: c.name || String(c.courseId),
        cpi: String(c.cpi || '0'), classId: String(k.classId), name: k.name || String(k.classId) }
      map.set(key(pc), pc)
    }
    if (showAllDiscovered.value) {
      for (const pc of await fetchDiscoveredClasses()) if (!map.has(key(pc))) map.set(key(pc), pc)
    }
    const out = [...map.values()]
    classes.value = out
    for (const c of out) { const fk = folderKeyOf(c); if (!(fk in folderMap.value)) folderMap.value[fk] = { directoryId: '0', name: '根目录' } }
  } catch (e) { msg.value = `读取班级失败：${String(e)}` }
}

/** D83-5.3：从 targets.json 全量发现读班级（不含 cpi → 缺省 '0'），失败静默返回空。 */
async function fetchDiscoveredClasses(): Promise<PubClass[]> {
  try {
    const t = await fetchXxtTargets(engUrl.value, tok.value)
    const out: PubClass[] = []
    for (const c of t.courses || []) for (const k of c.classes || []) out.push({
      courseId: String(c.courseId), courseName: c.name || String(c.courseId),
      cpi: String((c as { cpi?: string }).cpi || '0'), classId: String(k.classId), name: k.name || String(k.classId),
    })
    return out
  } catch { return [] }
}
async function loadAllow() {
  try {
    const items = await fetchXxtWriteAllowlist(engUrl.value, tok.value)
    const nextAllow: Record<string, boolean> = {}
    for (const x of items) nextAllow[`${x.courseId}:${x.classId}`] = true
    allowKeys.value = nextAllow
  } catch { /* noop */ }
}
async function toggleAllow(c: PubClass, ev: Event) {
  const on = (ev.target as HTMLInputElement).checked
  // D83-5.3：按 id 增量保存（当前列表 ∪ 已保存白名单），避免因 classes.value 不含某班而丢失/加不上
  const next: Record<string, PubClass> = {}
  for (const x of classes.value) if (allowKeys.value[key(x)]) next[key(x)] = x
  if (on) next[key(c)] = c; else delete next[key(c)]
  try {
    const items: XxtAllowItem[] = Object.values(next)
      .map(x => ({ courseId: x.courseId, classId: x.classId, name: x.name }))
    await saveXxtWriteAllowlist(engUrl.value, tok.value, items)
    await loadAllow()
    msg.value = on ? `已把 ${c.name} 加入写操作白名单` : `已把 ${c.name} 移出白名单`
  } catch (e) { msg.value = `白名单保存失败：${String(e)}` }
}
const allowExpanded = ref<Record<string, boolean>>({})
function allowGroups() {
  const map = new Map<string, { courseId: string; courseName: string; classes: PubClass[] }>()
  for (const c of classes.value) {
    if (!map.has(c.courseId)) map.set(c.courseId, { courseId: c.courseId, courseName: c.courseName, classes: [] })
    map.get(c.courseId)!.classes.push(c)
  }
  return [...map.values()]
}
function allowCount(g: { classes: PubClass[] }): number { return g.classes.filter(c => allowed(c)).length }

/* ---------- D95：多班勾选（只列白名单班；按课程分组） ---------- */
const noticeTargets = ref<Record<string, boolean>>({})
const workTargets = ref<Record<string, boolean>>({})
/** 只列白名单内的班（方案 A）；按课程分组。 */
const whitelistedClasses = computed<PubClass[]>(() => classes.value.filter(allowed))
const classGroups = computed(() => {
  const g: Record<string, { courseId: string; courseName: string; classes: PubClass[] }> = {}
  for (const c of whitelistedClasses.value) {
    const k = c.courseId
    g[k] = g[k] || { courseId: c.courseId, courseName: c.courseName, classes: [] }
    g[k].classes.push(c)
  }
  return Object.values(g)
})
function pickedKeys(sel: Record<string, boolean>): string[] { return Object.keys(sel).filter(k => sel[k]) }
function pickedClasses(sel: Record<string, boolean>): PubClass[] {
  const set = new Set(pickedKeys(sel))
  return whitelistedClasses.value.filter(c => set.has(key(c)))
}
function togglePickAll(sel: 'notice' | 'work', on: boolean) {
  const next: Record<string, boolean> = {}
  if (on) for (const c of whitelistedClasses.value) next[key(c)] = true
  if (sel === 'notice') noticeTargets.value = next
  else { workTargets.value = next; syncWorkBase() }
}
function toggleClassPick(sel: 'notice' | 'work', c: PubClass, on: boolean) {
  const cur = sel === 'notice' ? noticeTargets.value : workTargets.value
  const next = { ...cur }
  if (on) next[key(c)] = true; else delete next[key(c)]
  if (sel === 'notice') noticeTargets.value = next
  else { workTargets.value = next; syncWorkBase() }
}
function toggleCoursePick(sel: 'notice' | 'work', g: { classes: PubClass[] }, on: boolean) {
  const cur = sel === 'notice' ? noticeTargets.value : workTargets.value
  const next = { ...cur }
  for (const c of g.classes) { if (on) next[key(c)] = true; else delete next[key(c)] }
  if (sel === 'notice') noticeTargets.value = next
  else { workTargets.value = next; syncWorkBase() }
}
/** 作业发布：以「第一个勾选班」为基准读取作业库/文件夹（同课程）。 */
/** D96：作业来源课程（决定作业库/文件夹/作业列表的 (courseId,cpi)）。 */
const workSourceCourseId = ref('')
/** 勾选班涉及的课程（去重）。 */
const workPickedCourses = computed(() => {
  const seen: Record<string, { courseId: string; courseName: string }> = {}
  for (const c of pickedClasses(workTargets.value)) {
    seen[c.courseId] = seen[c.courseId] || { courseId: c.courseId, courseName: c.courseName }
  }
  return Object.values(seen)
})
/** 基准班：来源课程下第一个勾选班（取 cpi）。 */
const workBaseClass = computed<PubClass | undefined>(() => {
  const picks = pickedClasses(workTargets.value)
  const cid = workSourceCourseId.value || picks[0]?.courseId || ''
  return picks.find(c => c.courseId === cid)
})
function syncWorkBase() {
  const picks = pickedClasses(workTargets.value)
  // 来源课程失效（未在勾选内）→ 回到第一个勾选班的课程
  if (workSourceCourseId.value && !picks.some(c => c.courseId === workSourceCourseId.value)) {
    workSourceCourseId.value = picks[0]?.courseId || ''
  }
  if (!workSourceCourseId.value && picks.length) workSourceCourseId.value = picks[0].courseId
  workTarget.value = workBaseClass.value ? key(workBaseClass.value) : ''
  void loadWorks(true)
}
function allowExpandedState(cid: string): boolean { return allowExpanded.value[cid] !== false }
function toggleAllowExpanded(cid: string, ev: Event) { allowExpanded.value = { ...allowExpanded.value, [cid]: (ev.target as HTMLDetailsElement).open } }
function expandAllAllow(on: boolean) { const next: Record<string, boolean> = {}; for (const g of allowGroups()) next[g.courseId] = on; allowExpanded.value = next }

/* 文件库文件夹：按 courseId:classId 记忆（D83-5.2；载入时清掉 D83 前的裸 courseId 旧键） */
function loadFolderMap(): Record<string, XxtWorkFolder> {
  try {
    const raw = JSON.parse(localStorage.getItem('xxt-work-folders') || '{}') as Record<string, XxtWorkFolder>
    return Object.fromEntries(Object.entries(raw).filter(([k]) => k.includes(':')))
  } catch { return {} }
}
const folderMap = ref<Record<string, XxtWorkFolder>>(loadFolderMap())
const folderList = ref<XxtWorkFolder[]>([])
function persistFolderMap() { try { localStorage.setItem('xxt-work-folders', JSON.stringify(folderMap.value)) } catch { /* noop */ } }
const CACHE_TTL = 30 * 24 * 3600 * 1000
function cacheGet<T>(key: string): T | null {
  try {
    const raw = JSON.parse(localStorage.getItem(key) || 'null')
    if (!raw || typeof raw.at !== 'number') return null
    if (Date.now() - raw.at > CACHE_TTL) return null
    return raw.data as T
  } catch { return null }
}
function cacheSet(key: string, data: unknown) {
  try { localStorage.setItem(key, JSON.stringify({ at: Date.now(), data })) } catch { /* noop */ }
}
async function loadFolders(force = false) {
  const c = workBaseClass.value
  if (!c) { folderList.value = []; return }
  const ck = `xxt-work-folders-cache-v3:${folderKeyOf(c)}`
  if (!force) {
    const hit = cacheGet<XxtWorkFolder[]>(ck)
    if (hit) { folderList.value = hit; return }
  }
  try {
    folderList.value = await fetchXxtWorkFolders(engUrl.value, tok.value, c.courseId, c.classId, c.cpi)
    cacheSet(ck, folderList.value)
    const fk = folderKeyOf(c)
    const cur = folderMap.value[fk]
    if (!cur || !folderList.value.some(f => f.directoryId === cur.directoryId)) {
      folderMap.value[fk] = { directoryId: '0', name: '根目录' }
      persistFolderMap()
    }
  } catch (e) { msg.value = `文件夹读取失败：${String(e)}` }
}

/* 通知 */
const noticeTitle = ref('作业通知-大学物理')
const noticeBody = ref('作业纸见附件，请各位同学打印自己的那一张并手写完成、拍照上传到学习通作业里面。')
const noticeAtt = ref<XxtNoticeAttachment[]>([])
const attExts = ref<string[]>([])
const attExtOptions = ['pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png', 'webp', 'gif', 'xls', 'xlsx', 'ppt', 'pptx', 'zip', 'txt']
const attAccept = computed(() => attExts.value.map(e => '.' + e).join(','))
const noticePick = ref<Record<string, boolean>>({})
const uploadInput = ref<HTMLInputElement | null>(null)
function attAllowed(name: string): boolean { const e = (name.split('.').pop() || '').toLowerCase(); return attExts.value.includes(e) }
async function loadAttWhitelist() { try { attExts.value = await fetchXxtAttachmentWhitelist(engUrl.value, tok.value) } catch { /* noop */ } }
async function saveAttWhitelist() { try { attExts.value = await saveXxtAttachmentWhitelist(engUrl.value, tok.value, attExts.value); await loadAtt(); msg.value = '附件格式白名单已保存' } catch (e) { msg.value = `白名单保存失败：${String(e)}` } }
async function loadAtt() { try { noticeAtt.value = (await fetchXxtNoticeAttachments(engUrl.value, tok.value, 200)).filter(a => attAllowed(a.name)) } catch { /* noop */ } }
function attNames() { return Object.keys(noticePick.value).filter(k => noticePick.value[k]).map(p => noticeAtt.value.find(a => a.path === p)?.name || p.split(/[\\/]/).pop() || p) }
function applyAtt() {
  const names = attNames()
  noticeTitle.value = `作业通知-大学物理${names.length ? `（附件：${names.slice(0, 2).join('、')}${names.length > 2 ? '等' : ''}）` : ''}`.slice(0, 128)
  const base = noticeBody.value.split('\n').filter(x => !x.startsWith('附件文件名：')).join('\n').trim()
  noticeBody.value = names.length ? `${base}\n\n附件文件名：${names.join('、')}` : base
}
function toggleAtt(path: string, ev: Event) {
  const on = (ev.target as HTMLInputElement).checked
  const next = { ...noticePick.value }
  if (on) next[path] = true; else delete next[path]
  noticePick.value = next; applyAtt()
}
function pickUpload() { uploadInput.value?.click() }
async function onUpload(ev: Event) {
  const input = ev.target as HTMLInputElement
  const allFiles = Array.from(input.files || [])
  if (!allFiles.length) return
  const files = allFiles.filter(f => attAllowed(f.name))
  if (files.length < allFiles.length) msg.value = `已忽略 ${allFiles.length - files.length} 个不在白名单内的文件`
  if (!files.length) return
  const items: { name: string; data_b64: string }[] = []
  for (const f of files.slice(0, 10)) {
    const bytes = new Uint8Array(await f.arrayBuffer())
    let bin = ''; for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i])
    items.push({ name: f.name, data_b64: btoa(bin) })
  }
  try {
    const saved = await uploadXxtNoticeFiles(engUrl.value, tok.value, items)
    noticeAtt.value = [...saved, ...noticeAtt.value]
    for (const s of saved) noticePick.value = { ...noticePick.value, [s.path]: true }
    applyAtt(); msg.value = `已上传 ${saved.length} 个附件`
  } catch (e) { msg.value = `上传失败：${String(e)}` }
  input.value = ''
}

function showPreview(title: string, lines: string[]) {
  previewTitle.value = title
  previewLines.value = lines
  previewOpen.value = true
}
function previewNotice() {
  const picks = pickedClasses(noticeTargets.value)
  if (!picks.length) { msg.value = '请勾选要发布的白名单班级'; return }
  const names = attNames()
  showPreview('通知发布预览', [
    `发布班级（${picks.length}）：${picks.map(c => `${c.courseName}/${c.name}`).join('；')}`,
    `标题：${noticeTitle.value}`,
    '正文：',
    noticeBody.value,
    `附件：${names.join('、') || '无'}`,
  ])
}
function previewWork() {
  const picks = pickedClasses(workTargets.value)
  const c = workBaseClass.value
  const w = works.value.find(x => x.workLibraryId === workPick.value)
  if (!picks.length || !c || !w) { msg.value = '请勾选白名单班级并选择作业'; return }
  if (new Set(picks.map(x => x.courseId)).size > 1) { msg.value = '作业发布仅支持同课程多班。'; return }
  if (workUsed.value) { msg.value = '该作业已发布，禁止重复发布。'; return }
  showPreview('作业发布预览', [
    `发布班级（${picks.length}）：${picks.map(x => `${x.courseName}/${x.name}`).join('；')}`,
    `作业库文件夹：${folderCur.value.name}`,
    `作业：${workTitle.value || w.text || w.workLibraryId}`,
    `workLibraryId：${w.workLibraryId}`,
    '题干：',
    workStem.value || '（未读取到题干；请在学习通确认）',
    `开始时间：${startTime.value}`,
    `截止时间：${endTime.value}`,
    `允许补交：${allowLate.value ? '是' : '否'}`,
    `补交截止：${allowLate.value ? lateDeadline.value : '—'}`,
    `截止前允许重做：${redoTimes.value} 次`,
    `记住为默认：${rememberDefault.value ? '是' : '否'}`,
  ])
}

async function sendNotice(send: boolean) {
  const picks = pickedClasses(noticeTargets.value)
  if (!picks.length) { msg.value = '请勾选要发布的白名单班级'; return }
  if (send && !confirm(`确认把同一通知发布到 ${picks.length} 个班？\n${picks.map(c => `${c.courseName}/${c.name}`).join('\n')}`)) return
  // 按课程分组：courses[].classes[]
  const byCourse: Record<string, { courseId: string; classes: { classId: string; name: string }[] }> = {}
  for (const c of picks) {
    byCourse[c.courseId] = byCourse[c.courseId] || { courseId: c.courseId, classes: [] }
    byCourse[c.courseId].classes.push({ classId: c.classId, name: c.name })
  }
  busy.value = true
  startLog('发布通知')
  try {
    const r = await startXxtNoticeSend(engUrl.value, tok.value, {
      targets: Object.values(byCourse),
      title: noticeTitle.value, bodyHtml: noticeBody.value,
      attachments: Object.keys(noticePick.value).filter(k => noticePick.value[k]), send,
    })
    await poll(r.jobId)
  } catch (e) { busy.value = false; msg.value = `失败：${String(e)}` }
}

/* 作业 */
const workTarget = ref('')
const works = ref<XxtWorkLibraryItem[]>([])
const workPick = ref('')
const workTitle = ref('')
const workStem = ref('')
const workUsed = ref(false)
const draftTitle = ref('')
const draftStem = ref('请查看学习通班级消息，打印自己的那份作业纸，手写完成，签名并记录日期，拍照原图上传，纸质版于作业截止后课前提交。')

/** D83-7：新建草稿的附件（图片/pdf/doc…），随 createDraft 以 base64 一并提交，内嵌进那道简答题正文。 */
interface DraftAtt { name: string; data_b64: string; size: number }
const draftAtts = ref<DraftAtt[]>([])
const draftAttInput = ref<HTMLInputElement | null>(null)
function pickDraftAtt() { draftAttInput.value?.click() }
async function onDraftAttUpload(ev: Event) {
  const input = ev.target as HTMLInputElement
  const allFiles = Array.from(input.files || [])
  if (!allFiles.length) return
  const files = allFiles.filter(f => attAllowed(f.name))
  if (files.length < allFiles.length) msg.value = `已忽略 ${allFiles.length - files.length} 个不在白名单内的文件`
  const items: DraftAtt[] = []
  for (const f of files.slice(0, 10)) {
    const bytes = new Uint8Array(await f.arrayBuffer())
    let bin = ''; for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i])
    items.push({ name: f.name, data_b64: btoa(bin), size: f.size })
  }
  draftAtts.value = [...draftAtts.value, ...items].slice(0, 10)
  msg.value = `草稿附件 ${draftAtts.value.length} 个（将内嵌进简答题）`
  input.value = ''
}
function removeDraftAtt(i: number) { draftAtts.value.splice(i, 1) }
const startTime = ref('')
const endTime = ref('')
const allowLate = ref(true)
const lateDeadline = ref('')
const redoTimes = ref(3)
const rememberDefault = ref(true)
const timeEdited = ref(false)

function fmt(d: Date): string { const p = (n: number) => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}` }
function defaultTimes() {
  const now = new Date()
  const start = now.getHours() < 18 ? new Date(now.getFullYear(), now.getMonth(), now.getDate(), 18, 0, 0) : now
  const end = new Date(start); end.setDate(end.getDate() + 5); end.setHours(18, 0, 0, 0)
  const late = new Date(end); late.setDate(late.getDate() + 2); late.setHours(18, 0, 0, 0)
  return { start: fmt(start), end: fmt(end), late: fmt(late) }
}
function applyDefaults() { const d = defaultTimes(); startTime.value = d.start; endTime.value = d.end; lateDeadline.value = d.late; timeEdited.value = false }
function refreshStale() {
  if (!startTime.value) { applyDefaults(); return }
  if (new Date(startTime.value.replace(/-/g, '/')).getTime() < Date.now() - 60_000) {
    if (!timeEdited.value) { applyDefaults(); msg.value = '开始时间已过期，已按默认规则更新。' }
    else msg.value = '提示：开始时间已早于当前时间，发布可能被平台拒绝；可点「恢复默认时间」。'
  }
}
async function loadWorks(force = false) {
  const c = workBaseClass.value
  if (!c) { works.value = []; return }
  const dir = folderMap.value[folderKeyOf(c)]?.directoryId || '0'
  const ck = `xxt-work-list-cache-v3:${folderKeyOf(c)}:${dir}`
  if (!force) {
    const hit = cacheGet<XxtWorkLibraryItem[]>(ck)
    if (hit) {
      works.value = hit
      workPick.value = ''; workTitle.value = ''; workStem.value = ''; workUsed.value = false
      await loadFolders()
      return
    }
  }
  const r = await fetchXxtWorkList(engUrl.value, tok.value, c.courseId, c.classId, c.cpi, dir)
  works.value = r.items || []
  cacheSet(ck, works.value)
  workPick.value = ''; workTitle.value = ''; workStem.value = ''; workUsed.value = false
  await loadFolders()
}
function workPublished(w: XxtWorkLibraryItem): boolean {
  const c = workBaseClass.value
  return !!c && (w.publishedClasses || []).includes(c.classId)
}
async function loadDetail() {
  const c = workBaseClass.value
  const w = works.value.find(x => x.workLibraryId === workPick.value)
  if (!c || !w) { workTitle.value = ''; workStem.value = ''; return }
  try {
    const d = await fetchXxtWorkDetail(engUrl.value, tok.value, c.courseId, c.classId, c.cpi, w.workLibraryId)
    workTitle.value = d.title || w.text?.split('\n')[0] || w.workLibraryId
    workStem.value = (d.stemHtml || '').replace(/<[^>]+>/g, '').trim()
    workUsed.value = Boolean((d as { workUsed?: boolean }).workUsed)
  } catch { workTitle.value = w.text?.split('\n')[0] || ''; workStem.value = '' }
}
async function createDraft() {
  const c = workBaseClass.value
  if (!c || !allowed(c)) { msg.value = '请选择白名单内班级'; return }
  if (!draftTitle.value.trim() || !draftStem.value.trim()) { msg.value = '请填写作业标题与题干'; return }
  busy.value = true; msg.value = '正在新建作业草稿……'
  try {
    const jobId = await startXxtWorkCreate(engUrl.value, tok.value, {
      courseId: c.courseId, classId: c.classId, cpi: c.cpi,
      title: draftTitle.value.trim(), stemHtml: draftStem.value.trim(),
      directoryId: folderMap.value[folderKeyOf(c)]?.directoryId || '0',
      // D83-7：附件 base64（serve 端按通知扩展名白名单落盘 → CLI --attach 内嵌进简答题）
      attachments: draftAtts.value.map(a => ({ name: a.name, data_b64: a.data_b64 })),
    })
    const res = await poll(jobId)
    const all = res.lines.join('\n')
    const m = all.match(/"workLibraryId":\s*"([^"]+)"/)
    await loadWorks(true)
    if (res.ok && m) {
      workPick.value = m[1]
      await loadDetail()
      draftAtts.value = []
      msg.value = `作业草稿已创建并选中：${draftTitle.value.trim()}`
    } else {
      msg.value = res.ok ? '作业草稿已创建，请刷新作业库查看。' : `新建失败：${extractJobError(all)}`
    }
  } catch (e) { busy.value = false; msg.value = `新建失败：${String(e)}` }
}
/** D96：醒目反馈（消息 + 日志面板），避免"点了没反应"。 */
function failWork(m: string) { msg.value = `⚠ ${m}`; appendLog(`[发布作业] ${m}`); startLog('发布作业') }
async function publishWork(send: boolean) {
  const picks = pickedClasses(workTargets.value)
  const c = workBaseClass.value
  const w = works.value.find(x => x.workLibraryId === workPick.value)
  if (!picks.length) { failWork('请先勾选要发布的白名单班级'); return }
  if (!c) { failWork('请选择「作业来源课程」'); return }
  if (!w) { failWork('请先在「已有作业」中选择一个作业'); return }
  if (workPublished(w) || workUsed.value) { failWork('该作业已发布过，禁止重复发布；如需修改请先创建副本（副本+时间戳）。'); return }
  refreshStale()
  if (new Date(startTime.value.replace(/-/g, '/')).getTime() < Date.now() - 60_000) {
    failWork('开始时间早于当前时间，请点「恢复默认时间」后再发布。'); return
  }
  const courses = new Set(picks.map(x => x.courseId))
  if (courses.size > 1) {
    failWork('作业库按课程独立，**发布限同课程**；请只勾选同一课程的班级（跨课程请分别发布）。'); return
  }
  if (c.courseId !== picks[0].courseId) {
    failWork('「作业来源课程」与目标班级课程不一致：请让来源课程 = 目标班级所在课程。'); return
  }
  const classIds = picks.map(x => x.classId)
  if (send && !confirm(`确认把「${workTitle.value || w.text}」发布到 ${picks.length} 个班？\n${picks.map(x => `${x.courseName}/${x.name}`).join('\n')}`)) return
  busy.value = true
  startLog('发布作业')
  try {
    if (rememberDefault.value && send) {
      try { localStorage.setItem('xxt-work-defaults', JSON.stringify({ startTime: startTime.value, endTime: endTime.value, allowLate: allowLate.value, lateDeadline: lateDeadline.value, redoTimes: redoTimes.value })) } catch { /* noop */ }
    }
    const r = await startXxtWorkPublish(engUrl.value, tok.value, {
      courseId: c.courseId, classId: c.classId, classIds,
      workLibraryId: w.workLibraryId, cpi: c.cpi,
      startTime: startTime.value, endTime: endTime.value, allowLate: allowLate.value,
      lateDeadline: lateDeadline.value, redoTimes: redoTimes.value, send,
    })
    await poll(r.jobId)
    await loadWorks(true)
  } catch (e) { busy.value = false; msg.value = `失败：${String(e)}` }
}

function startLog(title: string) {
  logTitle.value = title
  logLines.value = []
  logOpen.value = true
}
function appendLog(line: string) {
  if (!line) return
  const lines = logLines.value
  if (lines[lines.length - 1] === line) return
  lines.push(line)
  if (lines.length > 400) lines.splice(0, lines.length - 400)
}

async function poll(jobId: string): Promise<{ ok: boolean; lines: string[] }> {
  for (let i = 0; i < 160; i++) {
    const job = await fetchXxtLoginJob(engUrl.value, tok.value, jobId)
    const lines = job.lines || []
    const last = lines.slice(-1)[0] || ''
    if (job.status === 'running') {
      appendLog(last)
      msg.value = `执行中（${i * 1.5 | 0}s）：${last.slice(-160)}`
    } else {
      for (const ln of lines.slice(-30)) appendLog(ln)
      const all = lines.join('\n')
      if (all.includes('发布成功') || all.includes('"status": true') || all.includes('"status":true')) {
        appendLog('✅ 发布成功')
        msg.value = '✅ 发布成功；可到学习通查看。'
      } else if (all.includes('"ok": true') && all.includes('"mode": "send"')) {
        appendLog('✅ 任务完成')
        msg.value = '✅ 任务完成。'
      } else if (job.returncode && job.returncode !== 0) {
        const err = extractJobError(all) || job.status
        appendLog(`❌ 任务失败：${err}`)
        msg.value = `❌ 任务失败：${err}`
      } else {
        appendLog(`任务结束：${last.slice(-220) || job.status}`)
        msg.value = `任务结束：${last.slice(-220) || job.status}`
      }
      busy.value = false
      return { ok: !(job.returncode && job.returncode !== 0), lines }
    }
    await new Promise(r => setTimeout(r, 1500))
  }
  busy.value = false
  msg.value = '任务超时，请刷新后查看。'
  return { ok: false, lines: logLines.value }
}

const folderCur = computed(() => {
  const c = workBaseClass.value
  return c ? (folderMap.value[folderKeyOf(c)] || { directoryId: '0', name: '根目录' }) : { directoryId: '0', name: '根目录' }
})
function setFolder(ev: Event) {
  const c = workBaseClass.value
  if (!c) return
  const id = (ev.target as HTMLSelectElement).value
  const f = folderList.value.find(x => x.directoryId === id) || { directoryId: '0', name: '根目录' }
  folderMap.value = { ...folderMap.value, [folderKeyOf(c)]: f }
  persistFolderMap()
  void loadWorks()
}
const newFolderName = ref('')
async function createFolder() {
  const c = workBaseClass.value
  if (!c || !allowed(c)) { msg.value = '该班未加入写操作白名单：请在页面上方「写操作白名单」勾选后再试'; return }
  if (!newFolderName.value.trim()) { msg.value = '请输入文件夹名'; return }
  busy.value = true; msg.value = '正在创建文件夹……'
  try {
    const r = await createXxtWorkFolder(engUrl.value, tok.value, {
      courseId: c.courseId, classId: c.classId, cpi: c.cpi,
      directoryId: folderMap.value[folderKeyOf(c)]?.directoryId || '0',
      title: newFolderName.value.trim(),
    })
    if (!r.ok) throw new Error(r.error || '创建失败')
    newFolderName.value = ''
    await loadFolders(true)
    msg.value = '文件夹已创建'
  } catch (e) { msg.value = `创建文件夹失败：${String(e)}` }
  busy.value = false
}
async function copySelectedWork() {
  const c = workBaseClass.value
  const w = works.value.find(x => x.workLibraryId === workPick.value)
  if (!c || !w) { msg.value = '请选择白名单班级与作业'; return }
  const stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, '')
  const base = (workTitle.value || w.text?.split('\n')[0] || w.workLibraryId).slice(0, 40)
  const title = `${base}-副本-${stamp}`
  if (!confirm(`复制为：${title}？`)) return
  busy.value = true; msg.value = '正在创建副本……'
  try {
    const r = await copyXxtWork(engUrl.value, tok.value, {
      courseId: c.courseId, classId: c.classId, cpi: c.cpi,
      directoryId: folderMap.value[folderKeyOf(c)]?.directoryId || '0',
      workLibraryId: w.workLibraryId, title,
    })
    if (!r.ok) throw new Error(r.error || '复制失败')
    await loadWorks(true)
    workPick.value = r.newWorkLibraryId || ''
    await loadDetail()
    msg.value = `副本已创建：${title}`
  } catch (e) { msg.value = `创建副本失败：${String(e)}` }
  busy.value = false
}

onMounted(async () => {
  const saved = localStorage.getItem('xxt-work-defaults')
  if (saved) { try { const d = JSON.parse(saved); startTime.value = d.startTime; endTime.value = d.endTime; allowLate.value = d.allowLate ?? true; lateDeadline.value = d.lateDeadline; redoTimes.value = d.redoTimes ?? 3 } catch { applyDefaults() } } else applyDefaults()
  await loadAttWhitelist(); await loadClasses(); await loadAllow(); await loadAtt()
  document.addEventListener('visibilitychange', refreshStale)
})
onUnmounted(() => document.removeEventListener('visibilitychange', refreshStale))
</script>

<template>
  <section>
    <div class="card">
      <h2>发布-学习通 <small>通知 / 作业发布；写操作仅对「白名单」班级开放</small></h2>
      <p v-if="msg" class="notice info" style="margin:4px 0; font-weight:600">{{ msg }}</p>
      <p class="hint">当前批次：{{ runId || '（无）' }}；已选白名单：{{ Object.keys(allowKeys).filter(k => allowKeys[k]).length }} 个班</p>
    </div>

    <div class="card">
      <h3>写操作白名单 <small>默认全部关闭；按课程折叠，勾选后该班才可发布</small></h3>
      <div v-if="classes.length" style="border:1px solid var(--c-border); border-radius:8px; padding:8px">
        <div style="display:flex; gap:8px; margin-bottom:6px; align-items:center">
          <button class="btn small" @click="expandAllAllow(true)">展开全部</button>
          <button class="btn small" @click="expandAllAllow(false)">折叠全部</button>
          <label class="hint" style="display:flex; align-items:center; gap:4px; margin-left:8px">
            <input type="checkbox" v-model="showAllDiscovered" @change="toggleShowAll" />
            显示全部已发现班级（含不在当前批次的班）
          </label>
        </div>
        <div style="max-height:280px; overflow:auto">
          <details v-for="g in allowGroups()" :key="'ag'+g.courseId" :open="allowExpandedState(g.courseId)"
                   @toggle="toggleAllowExpanded(g.courseId, $event)" style="margin-bottom:6px">
            <summary style="cursor:pointer; font-weight:600">
              {{ g.courseName }}
              <span class="hint" style="color:var(--c-muted)">courseId {{ g.courseId }} · {{ g.classes.length }} 班 · 白名单 {{ allowCount(g) }}</span>
            </summary>
            <div style="margin:4px 0 0 20px">
              <label v-for="c in g.classes" :key="'a'+key(c)" style="display:block; margin:2px 0">
                <input type="checkbox" :checked="allowed(c)" @change="toggleAllow(c, $event)" />
                {{ c.name }}
              </label>
            </div>
          </details>
        </div>
      </div>
      <p v-else class="hint">暂无已提取班级。</p>
    </div>

    <div class="card">
      <h3>发通知</h3>
      <p class="hint" style="margin:0 0 4px">目标班级（<b>多选</b>，只列白名单班；勾选后同一通知发往全部勾选班）：</p>
      <div v-if="classGroups.length" style="max-height:160px; overflow:auto; border:1px solid var(--c-border); border-radius:8px; padding:8px; margin-bottom:6px">
        <p style="margin:0 0 4px">
          <button class="btn small" @click="togglePickAll('notice', true)">全选</button>
          <button class="btn small" style="margin-left:4px" @click="togglePickAll('notice', false)">清空</button>
          <span class="hint" style="margin-left:8px">已选 {{ pickedKeys(noticeTargets).length }} 个班</span>
        </p>
        <div v-for="g in classGroups" :key="'ng'+g.courseId" style="margin-bottom:4px">
          <label style="font-weight:600">
            <input type="checkbox" :checked="g.classes.every(c => noticeTargets[key(c)])"
                   @change="toggleCoursePick('notice', g, ($event.target as HTMLInputElement).checked)" />
            {{ g.courseName }}
          </label>
          <span v-for="c in g.classes" :key="'n'+key(c)" style="margin-left:12px; white-space:nowrap">
            <label><input type="checkbox" :checked="!!noticeTargets[key(c)]"
                   @change="toggleClassPick('notice', c, ($event.target as HTMLInputElement).checked)" /> {{ c.name }}</label>
          </span>
        </div>
      </div>
      <p v-else class="hint">白名单内暂无班级：请在上方「写操作白名单」勾选要发布的班。</p>
      <p><label class="field">标题：<input v-model="noticeTitle" maxlength="128" style="width:min(560px,90%)" /></label></p>
      <p><label class="field" style="vertical-align:top">正文：<textarea v-model="noticeBody" rows="4" style="width:min(640px,92%)"></textarea></label></p>
      <p>
        <button class="btn small" @click="loadAtt">刷新附件</button>
        <button class="btn small" style="margin-left:8px" @click="pickUpload">上传图片/PDF/doc</button>
        <input ref="uploadInput" type="file" multiple :accept="attAccept" style="display:none" @change="onUpload" />
      </p>
      <div v-if="noticeAtt.length" style="max-height:160px; overflow:auto; border:1px solid var(--c-border); border-radius:8px; padding:8px">
        <label v-for="a in noticeAtt" :key="a.path" style="display:block"><input type="checkbox" :checked="!!noticePick[a.path]" @change="toggleAtt(a.path, $event)" /> {{ a.name }}</label>
      </div>
      <details class="hint" style="margin-top:8px">
        <summary>附件格式白名单（{{ attExts.join(' / ') }}）</summary>
        <div style="display:flex; flex-wrap:wrap; gap:10px; margin:6px 0">
          <label v-for="e in attExtOptions" :key="e">
            <input type="checkbox" :value="e" v-model="attExts" /> {{ e }}
          </label>
        </div>
        <button class="btn small" @click="saveAttWhitelist">保存白名单</button>
        <span class="hint" style="margin-left:8px">仅白名单内格式允许上传为通知附件。</span>
      </details>
      <p><button class="btn" :disabled="busy" @click="previewNotice">👁 检查预览</button>
         <button class="btn primary" style="margin-left:8px" :disabled="busy" @click="sendNotice(true)">📢 发布通知</button></p>
    </div>

    <div class="card">
      <h3>发布作业 <small>新建 1 道简答题草稿，或从作业库选择已有作业原样发布；同班同作业禁止重复发布</small></h3>
      <p class="hint" style="margin:0 0 4px">目标班级（<b>多选</b>，只列白名单班；<b>发布限同课程</b>）：</p>
      <div v-if="classGroups.length" style="max-height:160px; overflow:auto; border:1px solid var(--c-border); border-radius:8px; padding:8px; margin-bottom:6px">
        <p style="margin:0 0 4px">
          <button class="btn small" @click="togglePickAll('work', true)">全选</button>
          <button class="btn small" style="margin-left:4px" @click="togglePickAll('work', false)">清空</button>
          <span class="hint" style="margin-left:8px">已选 {{ pickedKeys(workTargets).length }} 个班</span>
        </p>
        <div v-for="g in classGroups" :key="'wg'+g.courseId" style="margin-bottom:4px">
          <label style="font-weight:600">
            <input type="checkbox" :checked="g.classes.every(c => workTargets[key(c)])"
                   @change="toggleCoursePick('work', g, ($event.target as HTMLInputElement).checked)" />
            {{ g.courseName }}
          </label>
          <span v-for="c in g.classes" :key="'w'+key(c)" style="margin-left:12px; white-space:nowrap">
            <label><input type="checkbox" :checked="!!workTargets[key(c)]"
                   @change="toggleClassPick('work', c, ($event.target as HTMLInputElement).checked)" /> {{ c.name }}</label>
          </span>
        </div>
      </div>
      <p v-else class="hint">白名单内暂无班级：请在上方「写操作白名单」勾选要发布的班。</p>
      <p><label class="field" title="D96：作业库按课程独立；此处选择从哪个课程的作业库取作业/文件夹">
        作业来源课程：
        <select v-model="workSourceCourseId" style="width:280px" @change="syncWorkBase">
          <option value="">（先勾选目标班级）</option>
          <option v-for="c in workPickedCourses" :key="c.courseId" :value="c.courseId">{{ c.courseName }}（{{ c.courseId }}）</option>
        </select>
        <span class="hint" style="margin-left:8px" v-if="workPickedCourses.length > 1">⚠ 已勾选跨课程多班：发布限同课程</span>
      </label></p>
      <p><label class="field">作业库文件夹：
        <select :value="folderCur.directoryId" style="width:260px" @change="setFolder($event)">
          <option value="0">根目录</option>
          <option v-for="f in folderList" :key="f.directoryId" :value="f.directoryId">{{ f.name }}</option>
        </select>
        <button class="btn small" style="margin-left:8px" @click="loadFolders(true)">🔄 刷新文件夹</button>
        <input v-model="newFolderName" placeholder="新文件夹名" style="width:140px; margin-left:8px" />
        <button class="btn small" style="margin-left:4px" :disabled="busy" @click="createFolder">＋ 新建文件夹</button>
      </label></p>
      <div style="border:1px dashed var(--c-border); border-radius:8px; padding:8px; margin:8px 0">
        <p><b>新建作业草稿（1 道简答题）</b></p>
        <p><input v-model="draftTitle" placeholder="作业标题" style="width:min(420px,90%)" /></p>
        <!-- D83-7：附件内嵌进这道简答题；格式白名单复用发布通知那套 -->
        <p class="hint">附件（{{ attExts.join('/') }}，最多 10 个）：
          <button class="btn small" @click="pickDraftAtt">＋ 选择附件</button>
          <input ref="draftAttInput" type="file" multiple :accept="attAccept" style="display:none" @change="onDraftAttUpload" />
          <span v-if="!draftAtts.length">未选择</span>
        </p>
        <p v-if="draftAtts.length" style="margin:2px 0">
          <label v-for="(a, i) in draftAtts" :key="'da'+i" style="display:inline-block; margin-right:10px; font-size:13px">
            📎 {{ a.name }}（{{ Math.round(a.size/1024) }}KB）
            <button class="btn small" @click="removeDraftAtt(i)">✕</button>
          </label>
        </p>
        <p><textarea v-model="draftStem" rows="3" placeholder="简答题干" style="width:min(640px,92%)"></textarea></p>
        <button class="btn" :disabled="busy" @click="createDraft">＋ 新建草稿到所选文件夹</button>
      </div>
      <p><label class="field">已有作业：<select v-model="workPick" style="width:min(560px,90%)" @change="loadDetail">
        <option value="">（选择作业库中的作业）</option>
        <option v-for="w in works" :key="w.workLibraryId" :value="w.workLibraryId" :disabled="workPublished(w)">
          {{ w.text || w.workLibraryId }}{{ workPublished(w) ? '（本班已发布）' : '' }}
        </option>
      </select></label>
        <button class="btn small" style="margin-left:8px" @click="loadWorks(true)">🔁 刷新作业库</button>
        <button class="btn small" style="margin-left:4px" :disabled="busy || !workPick" @click="copySelectedWork">📄 创建副本（副本+时间戳）</button>
      </p>
      <div v-if="workPick" class="hint" style="border:1px solid var(--c-border); border-radius:8px; padding:8px">
        <b>{{ workTitle || '（作业）' }}</b>
        <span v-if="workUsed" class="tag" style="background:#fee2e2;color:#991b1b;padding:1px 6px;border-radius:6px;margin-left:6px">已发布，禁止重复发布</span>
        <p style="white-space:pre-wrap">{{ workStem || '（题干未读取到；可到学习通查看）' }}</p>
      </div>
      <p><label class="field">开始：<input v-model="startTime" style="width:180px" @input="timeEdited = true" /></label>
         <label class="field" style="margin-left:12px">截止：<input v-model="endTime" style="width:180px" @input="timeEdited = true" /></label>
         <button class="btn small" style="margin-left:8px" @click="applyDefaults">↺ 恢复默认时间</button></p>
      <p><label><input v-model="allowLate" type="checkbox" /> 允许补交</label>
         <label class="field" style="margin-left:12px">补交截止：<input v-model="lateDeadline" style="width:180px" @input="timeEdited = true" /></label></p>
      <p><label class="field">截止前允许重做：<input v-model.number="redoTimes" type="number" min="0" max="100" style="width:80px" /> 次</label></p>
      <p><label><input v-model="rememberDefault" type="checkbox" /> 记住为默认</label></p>
      <p><button class="btn" :disabled="busy" @click="previewWork">👁 检查预览</button>
        <button class="btn primary" style="margin-left:8px" :disabled="busy" @click="publishWork(true)">📢 发布作业</button></p>
    </div>
    <div v-if="previewOpen" @click.self="previewOpen = false"
         style="position:fixed; inset:0; background:rgba(15,23,42,.45); z-index:100; display:flex; align-items:center; justify-content:center">
      <div style="background:var(--c-card,#fff); border-radius:12px; max-width:min(760px,94vw); max-height:86vh; overflow:auto; padding:16px">
        <h3 style="margin-top:0">{{ previewTitle }}<button class="btn" style="float:right" @click="previewOpen = false">关闭</button></h3>
        <pre style="white-space:pre-wrap; word-break:break-word; font-size:13px; line-height:1.6">{{ previewLines.join('\n') }}</pre>
      </div>
    </div>
    <div v-if="logOpen" @click.self="logOpen = false"
         style="position:fixed; inset:0; background:rgba(15,23,42,.45); z-index:101; display:flex; align-items:center; justify-content:center">
      <div style="background:var(--c-card,#fff); border-radius:12px; max-width:min(760px,94vw); max-height:86vh; display:flex; flex-direction:column; padding:16px">
        <h3 style="margin-top:0">{{ logTitle }} · CLI 输出<button class="btn" style="float:right" @click="logOpen = false">关闭</button></h3>
        <p v-if="msg" class="notice info" style="margin:4px 0; font-weight:600">{{ msg }}</p>
        <pre style="flex:1; overflow:auto; white-space:pre-wrap; word-break:break-word; font-size:12px; background:var(--c-bg,#f7f7f9); border:1px solid var(--c-border); border-radius:8px; padding:8px; max-height:56vh">{{ logLines.join('\n') }}</pre>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  copyXxtWork, createXxtWorkFolder, fetchXxtAttachmentWhitelist, fetchXxtLoginJob, fetchXxtNoticeAttachments, fetchXxtRun, fetchXxtRuns, fetchXxtWorkDetail,
  fetchXxtWorkFolders, fetchXxtWorkList, fetchXxtWriteAllowlist, saveXxtAttachmentWhitelist, saveXxtWriteAllowlist,
  startXxtNoticeSend, startXxtWorkCreate, startXxtWorkPublish, uploadXxtNoticeFiles,
} from '../lib/engineClient'
import type { XxtAllowItem, XxtNoticeAttachment, XxtWorkFolder, XxtWorkLibraryItem } from '../lib/engineClient'
import { useSettingsStore } from '../stores/settings'

const settings = useSettingsStore()
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
const allowKeys = ref<Record<string, boolean>>({})
function allowed(c: { courseId: string; classId: string }): boolean { return allowKeys.value[key(c)] === true }

async function loadClasses() {
  try {
    const runs = await fetchXxtRuns(engUrl.value, tok.value)
    if (!runs.length) { msg.value = '暂无已提取批次；请先到「作业预览-学习通」提取班级。'; return }
    const r = (await fetchXxtRun(engUrl.value, tok.value, runs[0].run_id)) as {
      run_id?: string; courses?: { courseId?: string; name?: string; cpi?: string;
      classes?: { classId?: string; name?: string }[] }[]
    }
    runId.value = String(r.run_id || runs[0].run_id)
    const out: PubClass[] = []
    for (const c of r.courses || []) for (const k of c.classes || []) out.push({
      courseId: String(c.courseId), courseName: c.name || String(c.courseId),
      cpi: String(c.cpi || '0'), classId: String(k.classId), name: k.name || String(k.classId),
    })
    classes.value = out
    for (const c of out) { if (!(c.courseId in folderMap.value)) folderMap.value[c.courseId] = { directoryId: '0', name: '根目录' } }
  } catch (e) { msg.value = `读取班级失败：${String(e)}` }
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
  const next: Record<string, boolean> = { ...allowKeys.value }
  if (on) next[key(c)] = true; else delete next[key(c)]
  try {
    const items: XxtAllowItem[] = classes.value.filter(x => next[key(x)] === true)
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
function allowExpandedState(cid: string): boolean { return allowExpanded.value[cid] !== false }
function toggleAllowExpanded(cid: string, ev: Event) { allowExpanded.value = { ...allowExpanded.value, [cid]: (ev.target as HTMLDetailsElement).open } }
function expandAllAllow(on: boolean) { const next: Record<string, boolean> = {}; for (const g of allowGroups()) next[g.courseId] = on; allowExpanded.value = next }

/* 文件库文件夹：按 courseId 记忆 */
const folderMap = ref<Record<string, XxtWorkFolder>>(JSON.parse(localStorage.getItem('xxt-work-folders') || '{}'))
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
  const c = classes.value.find(x => key(x) === workTarget.value)
  if (!c) { folderList.value = []; return }
  const ck = `xxt-work-folders-cache-v2:${c.courseId}`
  if (!force) {
    const hit = cacheGet<XxtWorkFolder[]>(ck)
    if (hit) { folderList.value = hit; return }
  }
  try {
    folderList.value = await fetchXxtWorkFolders(engUrl.value, tok.value, c.courseId, c.classId, c.cpi)
    cacheSet(ck, folderList.value)
    const cur = folderMap.value[c.courseId]
    if (!cur || !folderList.value.some(f => f.directoryId === cur.directoryId)) {
      folderMap.value[c.courseId] = { directoryId: '0', name: '根目录' }
      persistFolderMap()
    }
  } catch (e) { msg.value = `文件夹读取失败：${String(e)}` }
}

/* 通知 */
const noticeTitle = ref('作业通知-大学物理')
const noticeBody = ref('作业纸见附件，请各位同学打印自己的那一张并手写完成、拍照上传到学习通作业里面。')
const noticeTarget = ref('')
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
  const c = classes.value.find(x => key(x) === noticeTarget.value)
  if (!c || !allowed(c)) { msg.value = '请选择白名单内班级'; return }
  const names = attNames()
  showPreview('通知发布预览', [
    `发布班级：${c.courseName} / ${c.name}`,
    `标题：${noticeTitle.value}`,
    '正文：',
    noticeBody.value,
    `附件：${names.join('、') || '无'}`,
  ])
}
function previewWork() {
  const c = classes.value.find(x => key(x) === workTarget.value && allowed(x))
  const w = works.value.find(x => x.workLibraryId === workPick.value)
  if (!c || !w) { msg.value = '请选择白名单班级与作业'; return }
  if (workUsed.value) { msg.value = '该作业已发布，禁止重复发布。'; return }
  showPreview('作业发布预览', [
    `发布班级：${c.courseName} / ${c.name}`,
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
  const c = classes.value.find(x => key(x) === noticeTarget.value)
  if (!c || !allowed(c)) { msg.value = '请选择白名单内班级'; return }
  if (send && !confirm(`确认发布通知到 ${c.courseName}/${c.name}？`)) return
  busy.value = true
  startLog('发布通知')
  try {
    const r = await startXxtNoticeSend(engUrl.value, tok.value, {
      targets: [{ courseId: c.courseId, classes: [{ classId: c.classId, name: c.name }] }],
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
  const c = classes.value.find(x => key(x) === workTarget.value)
  if (!c) { works.value = []; return }
  const dir = folderMap.value[c.courseId]?.directoryId || '0'
  const ck = `xxt-work-list-cache-v2:${c.courseId}:${dir}`
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
  const c = classes.value.find(x => key(x) === workTarget.value)
  return !!c && (w.publishedClasses || []).includes(c.classId)
}
async function loadDetail() {
  const c = classes.value.find(x => key(x) === workTarget.value)
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
  const c = classes.value.find(x => key(x) === workTarget.value)
  if (!c || !allowed(c)) { msg.value = '请选择白名单内班级'; return }
  if (!draftTitle.value.trim() || !draftStem.value.trim()) { msg.value = '请填写作业标题与题干'; return }
  busy.value = true; msg.value = '正在新建作业草稿……'
  try {
    const jobId = await startXxtWorkCreate(engUrl.value, tok.value, {
      courseId: c.courseId, classId: c.classId, cpi: c.cpi,
      title: draftTitle.value.trim(), stemHtml: draftStem.value.trim(),
      directoryId: folderMap.value[c.courseId]?.directoryId || '0',
    })
    const res = await poll(jobId)
    const all = res.lines.join('\n')
    const m = all.match(/"workLibraryId":\s*"([^"]+)"/)
    await loadWorks(true)
    if (res.ok && m) {
      workPick.value = m[1]
      await loadDetail()
      msg.value = `作业草稿已创建并选中：${draftTitle.value.trim()}`
    } else {
      msg.value = res.ok ? '作业草稿已创建，请刷新作业库查看。' : `新建失败：${all.slice(-300)}`
    }
  } catch (e) { busy.value = false; msg.value = `新建失败：${String(e)}` }
}
async function publishWork(send: boolean) {
  const c = classes.value.find(x => key(x) === workTarget.value && allowed(x))
  const w = works.value.find(x => x.workLibraryId === workPick.value)
  if (!c || !w) { msg.value = '请选择白名单班级与作业'; return }
  if (workPublished(w) || workUsed.value) { msg.value = '该作业已发布过，禁止重复发布；如需修改请先创建副本（副本+时间戳）。'; return }
  refreshStale()
  if (new Date(startTime.value.replace(/-/g, '/')).getTime() < Date.now() - 60_000) {
    msg.value = '开始时间早于当前时间，请点「恢复默认时间」后再发布。'; return
  }
  if (send && !confirm(`确认把「${workTitle.value || w.text}」发布到 ${c.courseName}/${c.name}？`)) return
  busy.value = true
  startLog('发布作业')
  try {
    if (rememberDefault.value && send) {
      try { localStorage.setItem('xxt-work-defaults', JSON.stringify({ startTime: startTime.value, endTime: endTime.value, allowLate: allowLate.value, lateDeadline: lateDeadline.value, redoTimes: redoTimes.value })) } catch { /* noop */ }
    }
    const r = await startXxtWorkPublish(engUrl.value, tok.value, {
      courseId: c.courseId, classId: c.classId, workLibraryId: w.workLibraryId, cpi: c.cpi,
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
        appendLog(`❌ 任务失败：${last.slice(-220) || job.status}`)
        msg.value = `❌ 任务失败：${last.slice(-220) || job.status}`
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
  const c = classes.value.find(x => key(x) === workTarget.value)
  return c ? (folderMap.value[c.courseId] || { directoryId: '0', name: '根目录' }) : { directoryId: '0', name: '根目录' }
})
function setFolder(cid: string, ev: Event) {
  const id = (ev.target as HTMLSelectElement).value
  const f = folderList.value.find(x => x.directoryId === id) || { directoryId: '0', name: '根目录' }
  folderMap.value = { ...folderMap.value, [cid]: f }
  persistFolderMap()
  void loadWorks()
}
const newFolderName = ref('')
async function createFolder() {
  const c = classes.value.find(x => key(x) === workTarget.value)
  if (!c || !allowed(c)) { msg.value = '请选择白名单班级'; return }
  if (!newFolderName.value.trim()) { msg.value = '请输入文件夹名'; return }
  busy.value = true; msg.value = '正在创建文件夹……'
  try {
    const r = await createXxtWorkFolder(engUrl.value, tok.value, {
      courseId: c.courseId, classId: c.classId, cpi: c.cpi,
      directoryId: folderMap.value[c.courseId]?.directoryId || '0',
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
  const c = classes.value.find(x => key(x) === workTarget.value && allowed(x))
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
      directoryId: folderMap.value[c.courseId]?.directoryId || '0',
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
      <p v-if="msg" class="hint">{{ msg }}</p>
      <p class="hint">当前批次：{{ runId || '（无）' }}；已选白名单：{{ Object.keys(allowKeys).filter(k => allowKeys[k]).length }} 个班</p>
    </div>

    <div class="card">
      <h3>写操作白名单 <small>默认全部关闭；按课程折叠，勾选后该班才可发布</small></h3>
      <div v-if="classes.length" style="border:1px solid var(--c-border); border-radius:8px; padding:8px">
        <div style="display:flex; gap:8px; margin-bottom:6px">
          <button class="btn small" @click="expandAllAllow(true)">展开全部</button>
          <button class="btn small" @click="expandAllAllow(false)">折叠全部</button>
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
      <p><label class="field">班级：<select v-model="noticeTarget" style="width:320px">
        <option value="">（选择白名单班级）</option>
        <option v-for="c in classes" :key="'n'+key(c)" :value="key(c)" :disabled="!allowed(c)">{{ c.courseName }} / {{ c.name }}</option>
      </select></label></p>
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
      <p><label class="field">班级：<select v-model="workTarget" style="width:320px" @change="loadWorks()">
        <option value="">（选择白名单班级）</option>
        <option v-for="c in classes" :key="'w'+key(c)" :value="key(c)" :disabled="!allowed(c)">{{ c.courseName }} / {{ c.name }}</option>
      </select></label></p>
      <p><label class="field">作业库文件夹：
        <select :value="folderCur.directoryId" style="width:260px" @change="setFolder(classes.find(x => key(x) === workTarget)?.courseId || '', $event)">
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
        <p class="hint" style="margin:4px 0">{{ msg }}</p>
        <pre style="flex:1; overflow:auto; white-space:pre-wrap; word-break:break-word; font-size:12px; background:var(--c-bg,#f7f7f9); border:1px solid var(--c-border); border-radius:8px; padding:8px; max-height:56vh">{{ logLines.join('\n') }}</pre>
      </div>
    </div>
  </section>
</template>

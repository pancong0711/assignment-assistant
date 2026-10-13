<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  fetchXxtLoginJob, fetchXxtNoticeAttachments, fetchXxtRun, fetchXxtRuns, fetchXxtWorkList,
  startXxtNoticeSend, startXxtWorkPublish, uploadXxtNoticeFiles,
} from '../lib/engineClient'
import type { XxtNoticeAttachment, XxtWorkLibraryItem } from '../lib/engineClient'
import { useSettingsStore } from '../stores/settings'

const settings = useSettingsStore()
const engUrl = computed(() => settings.engineUrl)
const tok = computed(() => settings.engineToken)

const ALLOW = new Set(['217801417:40009084'])
const DEFAULT_TITLE = '作业通知-大学物理'
const DEFAULT_BODY = '作业纸见附件，请各位同学打印自己的那一张并手写完成、拍照上传到学习通作业里面。'

interface PubClass { courseId: string; courseName: string; cpi: string; classId: string; name: string }
const classes = ref<PubClass[]>([])
const runId = ref('')
const msg = ref('')
const busy = ref(false)

function key(c: PubClass): string { return `${c.courseId}:${c.classId}` }
function allowed(c: PubClass): boolean { return ALLOW.has(key(c)) }

async function loadClasses() {
  try {
    const runs = await fetchXxtRuns(engUrl.value, tok.value)
    if (!runs.length) { msg.value = '暂无已提取 run；请先到「作业预览-学习通」提取班级。'; return }
    const r = (await fetchXxtRun(engUrl.value, tok.value, runs[0].run_id)) as {
      run_id?: string; courses?: { courseId?: string; name?: string; cpi?: string;
      classes?: { classId?: string; name?: string }[] }[]
    }
    runId.value = String(r.run_id || runs[0].run_id)
    const out: PubClass[] = []
    for (const c of r.courses || []) {
      for (const k of c.classes || []) out.push({
        courseId: String(c.courseId), courseName: c.name || String(c.courseId),
        cpi: String(c.cpi || '0'),
        classId: String(k.classId), name: k.name || String(k.classId),
      })
    }
    classes.value = out
  } catch (e) { msg.value = `读取班级失败：${String(e)}` }
}

/* ---------- 通知发布 ---------- */
const noticeTitle = ref(DEFAULT_TITLE)
const noticeBody = ref(DEFAULT_BODY)
const noticeTarget = ref('')
const noticeAtt = ref<XxtNoticeAttachment[]>([])
const noticePick = ref<Record<string, boolean>>({})
const uploadInput = ref<HTMLInputElement | null>(null)

async function loadAtt() {
  try { noticeAtt.value = await fetchXxtNoticeAttachments(engUrl.value, tok.value, 200) } catch { /* noop */ }
}
function attNames(): string[] {
  return Object.keys(noticePick.value).filter(k => noticePick.value[k])
    .map(p => noticeAtt.value.find(a => a.path === p)?.name || p.split(/[\\/]/).pop() || p)
}
function applyAtt() {
  const names = attNames()
  const suffix = names.length ? `（附件：${names.slice(0, 2).join('、')}${names.length > 2 ? '等' : ''}）` : ''
  noticeTitle.value = `${DEFAULT_TITLE}${suffix}`.slice(0, 128)
  const base = noticeBody.value.split('\n').filter(x => !x.startsWith('附件文件名：')).join('\n').trim()
  noticeBody.value = names.length ? `${base}\n\n附件文件名：${names.join('、')}` : base
}
function toggleAtt(path: string, ev: Event) {
  const on = (ev.target as HTMLInputElement).checked
  if (on) noticePick.value = { ...noticePick.value, [path]: true }
  else { const n = { ...noticePick.value }; delete n[path]; noticePick.value = n }
  applyAtt()
}
function pickUpload() { uploadInput.value?.click() }
async function onUpload(ev: Event) {
  const input = ev.target as HTMLInputElement
  const files = Array.from(input.files || [])
  if (!files.length) return
  const items: { name: string; data_b64: string }[] = []
  for (const f of files.slice(0, 10)) {
    const buf = await f.arrayBuffer()
    let bin = ''
    const bytes = new Uint8Array(buf)
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i])
    items.push({ name: f.name, data_b64: btoa(bin) })
  }
  try {
    const saved = await uploadXxtNoticeFiles(engUrl.value, tok.value, items)
    noticeAtt.value = [...saved, ...noticeAtt.value]
    for (const s of saved) noticePick.value = { ...noticePick.value, [s.path]: true }
    applyAtt()
    msg.value = `已上传 ${saved.length} 个附件到 workspace 临时目录`
  } catch (e) { msg.value = `上传失败：${String(e)}` }
  input.value = ''
}
async function sendNotice(send: boolean) {
  const names = [noticeTarget.value].filter(Boolean)
  if (!names.length) { msg.value = '请选择发布班级'; return }
  if (send && !confirm(`确认发布通知到：${names.join('、')}？`)) return
  busy.value = true
  msg.value = send ? '正在发布通知……' : '正在预检通知……'
  try {
    const r = await startXxtNoticeSend(engUrl.value, tok.value, {
      targets: [{ courseId: noticeTarget.value.split(':')[0], classes: [{ classId: noticeTarget.value.split(':')[1] }] }],
      title: noticeTitle.value, bodyHtml: noticeBody.value,
      attachments: Object.keys(noticePick.value).filter(k => noticePick.value[k]), send,
    })
    await poll(r.jobId)
  } catch (e) { busy.value = false; msg.value = `失败：${String(e)}` }
}

/* ---------- 作业发布 ---------- */
const workTarget = ref('')
const works = ref<XxtWorkLibraryItem[]>([])
const workPick = ref('')
const startTime = ref('')
const endTime = ref('')
const allowLate = ref(true)
const lateDeadline = ref('')
const redoTimes = ref(3)
const rememberDefault = ref(true)

function fmt(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}
function applyDefaults() {
  const now = new Date()
  const start = now.getHours() < 18 ? new Date(now.getFullYear(), now.getMonth(), now.getDate(), 18, 0, 0) : now
  const end = new Date(start); end.setDate(end.getDate() + 5); end.setHours(18, 0, 0, 0)
  const late = new Date(end); late.setDate(late.getDate() + 2); late.setHours(18, 0, 0, 0)
  startTime.value = fmt(start); endTime.value = fmt(end); lateDeadline.value = fmt(late)
}
async function loadWorks() {
  const c = classes.value.find(x => key(x) === workTarget.value)
  if (!c) { works.value = []; return }
  const r = await fetchXxtWorkList(engUrl.value, tok.value, c.courseId, c.classId, c.cpi)
  works.value = r.items || []
  workPick.value = works.value[0]?.workLibraryId || ''
}
async function publishWork(send: boolean) {
  const c = classes.value.find(x => key(x) === workTarget.value && allowed(x))
  if (!c) { msg.value = '请选择白名单班级'; return }
  if (!workPick.value) { msg.value = '请选择作业'; return }
  if (send && !confirm(`确认发布作业到：${c.courseName}/${c.name}？`)) return
  busy.value = true
  msg.value = send ? '正在发布作业……' : '正在预检作业……'
  try {
    if (rememberDefault.value && send) {
      try { localStorage.setItem('xxt-work-defaults', JSON.stringify({ startTime: startTime.value, endTime: endTime.value, allowLate: allowLate.value, lateDeadline: lateDeadline.value, redoTimes: redoTimes.value })) } catch { /* noop */ }
    }
    const r = await startXxtWorkPublish(engUrl.value, tok.value, {
      courseId: c.courseId, classId: c.classId, workLibraryId: workPick.value, cpi: c.cpi,
      startTime: startTime.value, endTime: endTime.value, allowLate: allowLate.value,
      lateDeadline: lateDeadline.value, redoTimes: redoTimes.value, send,
    })
    await poll(r.jobId)
  } catch (e) { busy.value = false; msg.value = `失败：${String(e)}` }
}

async function poll(jobId: string) {
  for (let i = 0; i < 120; i++) {
    const job = await fetchXxtLoginJob(engUrl.value, tok.value, jobId)
    const last = (job.lines || []).slice(-1)[0] || ''
    msg.value = `${job.status === 'running' ? '执行中' : job.status}：${last.slice(-160)}`
    if (job.status !== 'running') { busy.value = false; return }
    await new Promise(r => setTimeout(r, 1500))
  }
  busy.value = false
}

onMounted(async () => {
  const saved = localStorage.getItem('xxt-work-defaults')
  if (saved) {
    try {
      const d = JSON.parse(saved)
      startTime.value = d.startTime || ''; endTime.value = d.endTime || ''
      allowLate.value = d.allowLate ?? true; lateDeadline.value = d.lateDeadline || ''
      redoTimes.value = d.redoTimes ?? 3
    } catch { applyDefaults() }
  } else applyDefaults()
  await loadClasses()
  await loadAtt()
})
</script>

<template>
  <section>
    <div class="card">
      <h2>发布-学习通 <small>通知 / 作业发布；当前仅白名单班级可写（数据源=最近一次提取批次）</small></h2>
      <p v-if="msg" class="hint">{{ msg }}</p>
      <p class="hint">当前批次：{{ runId || '（无）' }}</p>
    </div>

    <div class="card">
      <h3>发通知</h3>
      <p><label class="field">班级：
        <select v-model="noticeTarget" style="width:320px">
          <option value="">（选择白名单班级）</option>
          <option v-for="c in classes" :key="'n'+key(c)" :value="key(c)" :disabled="!allowed(c)">
            {{ c.courseName }} / {{ c.name }}{{ allowed(c) ? '' : '（白名单外）' }}
          </option>
        </select>
      </label></p>
      <p><label class="field">标题：
        <input v-model="noticeTitle" maxlength="128" style="width:min(560px,90%)" />
      </label></p>
      <p><label class="field" style="vertical-align:top">正文：
        <textarea v-model="noticeBody" rows="4" style="width:min(640px,92%)"></textarea>
      </label></p>
      <p>
        <button class="btn small" @click="loadAtt">刷新附件</button>
        <button class="btn small" style="margin-left:8px" @click="pickUpload">上传图片/PDF/doc</button>
        <input ref="uploadInput" type="file" multiple accept="image/*,.pdf,.doc,.docx" style="display:none" @change="onUpload" />
      </p>
      <div v-if="noticeAtt.length" style="max-height:160px; overflow:auto; border:1px solid var(--c-border); border-radius:8px; padding:8px">
        <label v-for="a in noticeAtt" :key="a.path" style="display:block">
          <input type="checkbox" :checked="!!noticePick[a.path]" @change="toggleAtt(a.path, $event)" /> {{ a.name }}
        </label>
      </div>
      <p>
        <button class="btn" :disabled="busy" @click="sendNotice(false)">🧪 预检（不发布）</button>
        <button class="btn primary" style="margin-left:8px" :disabled="busy" @click="sendNotice(true)">📢 发布通知</button>
      </p>
    </div>

    <div class="card">
      <h3>发布作业 <small>从作业库选择已有作业，原样发布；不新建、不复制</small></h3>
      <p><label class="field">班级：
        <select v-model="workTarget" style="width:320px" @change="loadWorks">
          <option value="">（选择白名单班级）</option>
          <option v-for="c in classes" :key="'w'+key(c)" :value="key(c)" :disabled="!allowed(c)">
            {{ c.courseName }} / {{ c.name }}{{ allowed(c) ? '' : '（白名单外）' }}
          </option>
        </select>
      </label></p>
      <p><label class="field">作业：
        <select v-model="workPick" style="width:min(620px,90%)">
          <option value="">（选择作业库中的作业）</option>
          <option v-for="w in works" :key="w.workLibraryId" :value="w.workLibraryId">{{ w.text || w.workLibraryId }}</option>
        </select>
      </label>
        <button class="btn small" style="margin-left:8px" @click="loadWorks">刷新作业库</button>
      </p>
      <p><label class="field">开始：<input v-model="startTime" style="width:180px" /></label>
         <label class="field" style="margin-left:12px">截止：<input v-model="endTime" style="width:180px" /></label></p>
      <p><label><input v-model="allowLate" type="checkbox" /> 允许补交</label>
         <label class="field" style="margin-left:12px">补交截止：<input v-model="lateDeadline" style="width:180px" /></label></p>
      <p><label class="field">截止前允许重做：<input v-model.number="redoTimes" type="number" min="0" max="100" style="width:80px" /> 次</label></p>
      <p><label><input v-model="rememberDefault" type="checkbox" /> 记住为默认</label></p>
      <p>
        <button class="btn" :disabled="busy" @click="publishWork(false)">🧪 预检（不发布）</button>
        <button class="btn primary" style="margin-left:8px" :disabled="busy" @click="publishWork(true)">📢 发布作业</button>
      </p>
    </div>
  </section>
</template>

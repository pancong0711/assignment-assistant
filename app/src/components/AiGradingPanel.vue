<script setup lang="ts">
/** D86 §6 / D88 §4：AI 辅助批阅面板（提炼自 XxetongView 临时面板）。
 *  六区：① LLM 设置（provider + 两段式）② 班级↔作业纸目录映射 ③ 任务（AI 批阅）
 *        ④ 逐生审核（本地草稿：改分/批语/保存/演练/上传）⑤ 一键生成批阅报告 ⑥ 一键上传全部
 *  说明：完整"逐生预览（作答图+批语两栏）"仍在「作业预览-学习通 → 批阅图片 → 逐生预览」，
 *  与本面板的"报告风格审核"并存（用户拍板的两种风格）。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useTaskpadStore } from '../stores/taskpad'
import { useKbStore } from '../stores/kb'
import {
  extractJobError, fetchLlmConfig, fetchXxtClassMap, fetchXxtGradeDrafts, fetchXxtLoginJob,
  fetchXxtReviewIndex, fetchXxtReviewStudents, postLlmProvider, postXxtClassMap,
  startXxtGradeAi, startXxtGradeUpload,
  startKbAiSolve, fetchKbCatalog, renderReportsFromDrafts,
  fetchPromptTemplates, mutatePromptTemplate, type PromptTemplate,
} from '../lib/engineClient'
import { normalizePromptId, suggestPromptId, PROMPT_ID_HINT } from '../lib/promptId'

const props = defineProps<{ engineAddr: string; token?: string }>()
const taskpadStore = useTaskpadStore()
const kbStore = useKbStore()
import { usePackStore } from '../stores/packs'
import PlaygroundPanel from './PlaygroundPanel.vue'
import StudentReviewModal from './StudentReviewModal.vue'
const packStore = usePackStore()

const msg = ref('')
/* D106：转录图片发送模式 + SVG 重绘（默认关） */
const imageMode = ref<'auto' | 'original'>('auto')
const svgRedraw = ref(false)
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
        if (kbApply.value) {
          // D100-T8：作答写回版本库 → 刷新生效答案索引（题库表格/作业纸预览立即跟随）
          await kbStore.bumpSolutions()
          kbSolveMsg.value = `作答并写回完成（${kbPin.value ? '已置顶为生效答案' : '未置顶，仅追加版本'}）：`
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
/** D92-R4：当前作业学生 tag 集合（去重，按出现顺序）。 */
const tagOptions = computed<string[]>(() => {
  const seen: string[] = []
  for (const s of students.value) { const t = (s.tag || '').trim(); if (t && !seen.includes(t)) seen.push(t) }
  return seen
})

/* ④ 逐生审核 */
const students = ref<Array<{ name: string; key: string; tag?: string }>>([])
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
  if (!w) { students.value = []; return }
  try {
    const [st, dr] = await Promise.all([
      fetchXxtReviewStudents(props.engineAddr, props.token, w.classId, w.workId),
      fetchXxtGradeDrafts(props.engineAddr, props.token, w.classId, w.workId),
    ])
    drafts.value = (dr.drafts || {}) as Record<string, any>
    students.value = (st.students || []).map((s: any) => ({
      name: String(s.name || ''), key: String(s.workAnswerId || s.name || ''),
      tag: String(s.tag || ''),
    }))
    // 默认全选当前作业的 tag 集合（新作业加载时重置）
    tagsSel.value = [...tagOptions.value]
  } catch (e) { msg.value = `读取学生/草稿失败：${String(e)}` }
}
function classDirFor(w: { courseId: string; classId: string }): string {
  return classMap.value[`${w.courseId}:${w.classId}`] || classDir.value[`${w.courseId}:${w.classId}`] || ''
}
function suggestDir() {
  const w = curWork.value; if (!w) return
  classDir.value = { ...classDir.value, [`${w.courseId}:${w.classId}`]: classDirFor(w) }
}
async function saveDir() {
  const w = curWork.value; if (!w) return
  const k = `${w.courseId}:${w.classId}`
  const rep = await postXxtClassMap(props.engineAddr, props.token,
    { courseId: w.courseId, classId: w.classId, classDir: classDir.value[k] || '' })
  msg.value = rep?.ok ? `已关联 ${w.classId} → ${classDir.value[k]}` : `保存失败：${rep?.error || ''}`
  await loadConfig()
}
async function saveProvider() {
  if (!pName.value.trim()) { msg.value = '请填 provider 名称'; return }
  const rep = await postLlmProvider(props.engineAddr, props.token, {
    action: 'set', name: pName.value.trim(), base_url: pBase.value.trim(),
    api_key: pKey.value ? pKey.value : undefined, batch_support: pBatch.value,
  })
  msg.value = rep?.ok ? `provider「${pName.value}」已保存（key 只掩码显示）` : `保存失败：${rep?.error || ''}`
  pKey.value = ''
  await loadConfig()
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
async function startAi() {
  const w = curWork.value
  if (!w) { msg.value = '请选择作业（需先在「作业预览-学习通」下载作答/批语）'; return }
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
  busy.value = true; progress.value = '正在装配任务清单并启动 AI 批阅……'
  try {
    const jobId = await startXxtGradeAi(props.engineAddr, props.token, {
      courseId: w.courseId, classId: w.classId, cpi: w.cpi, workId: w.workId, taskpad,
      ...(padsPayload && padsPayload.length > 1 ? { pads: padsPayload } : {}),
      mode: mode.value, tags: [...tagsSel.value],
      limit: Number(limit.value) || 0,
      imageMode: imageMode.value,      // D106
      svgRedraw: svgRedraw.value,      // D106
    })
    stopPoll()
    const tick = async () => {
      try {
        const job = await fetchXxtLoginJob(props.engineAddr, props.token, jobId)
        const lines = job.lines || []
        if (job.status === 'running') {
          progress.value = `AI 批阅中：${(lines.slice(-1)[0] || '').slice(-140)}`
          pollTimer = window.setTimeout(tick, 2000); return
        }
        busy.value = false
        progress.value = (job.returncode ?? 0) === 0
          ? '✅ AI 批阅完成（结果已写入本地批阅草稿，可在下方逐生审核）'
          : `❌ AI 批阅失败：${extractJobError(lines.join('\n'))}`
        await loadStudents()
      } catch (e) { busy.value = false; progress.value = `状态查询失败：${String(e)}` }
    }
    void tick()
  } catch (e) { busy.value = false; progress.value = `启动失败：${String(e)}` }
}
async function renderReports() {
  const w = curWork.value
  if (!w) { msg.value = '请选择作业'; return }
  busy.value = true
  progress.value = '正在按草稿逐生生成报告（人工在前 + 【附件】AI + 修订标红）……'
  try {
    const r = await renderReportsFromDrafts(props.engineAddr, props.token, {
      classId: w.classId, workId: w.workId, taskId: padId.value || packId.value,
    })
    busy.value = false
    if (r?.ok) {
      const n = r.count ?? (r.reports || []).length
      const types = Array.from(new Set((r.reports || []).map((x) => x.kind))).join('/')
      progress.value = `✅ 已生成 ${n} 份报告（类型：${types || '自动'}）；写入本地草稿（含报告图）`
      await loadStudents()
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

onMounted(async () => { await loadConfig(); await loadWorks(); loadKbCatalog(); void loadPromptTemplates() })
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
        <th>batch</th><th>key</th><th></th></tr></thead>
      <tbody>
        <tr v-for="p in (llmConfig.providers || [])" :key="p.name">
          <td>{{ p.name }}</td>
          <td class="hint">{{ p.base_url }}</td>
          <td style="text-align:center">{{ p.batch_support ? '✓' : '' }}</td>
          <td style="text-align:center">{{ p.api_key || '（未设置）' }}</td>
          <td style="text-align:center">
            <a href="javascript:;" @click="pName = p.name; pBase = p.base_url; pBatch = !!p.batch_support">编辑</a>
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
      <button class="btn" @click="saveProvider">保存 provider</button>
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
      <input v-model="classDir[`${curWork.courseId}:${curWork.classId}`]" placeholder="classes/xxx" style="width:230px" />
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
      <label class="field" title="按当前作业学生 tag 集合多选；默认全选">
        tags
        <select v-model="tagsSel" multiple style="min-width:150px; min-height:56px">
          <option v-for="t in tagOptions" :key="t" :value="t">{{ t }}</option>
        </select>
        <button class="btn small" type="button" @click="tagsSel = [...tagOptions]">全选</button>
      </label>
      <label class="field">限前 <input v-model.number="limit" type="number" min="0" style="width:70px" /> 名</label>
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
      <button class="btn" :disabled="busy" @click="startAi">▶ 开始 AI 批阅</button>
    </div>
    <p v-if="progress" class="hint" style="margin-top:6px">{{ progress }}</p>

    <h3 style="margin-top:14px">④ 逐生审核（左右两栏弹窗）</h3>
    <p class="hint" style="margin:0 0 6px">
      点「审核」打开弹窗：左=作答图；右上=AI 批语（可另存修订版）；右下=人工批阅（可选，AI 原文不被覆盖）。
      保存后到 ⑤ 一键生成报告（按每生模式自动出 5 种版式之一）。
    </p>
    <table v-if="students.length" style="width:100%; border-collapse:collapse">
      <thead><tr><th style="text-align:left">学生</th><th>tag</th><th>AI</th><th>人工</th><th>模式</th><th></th></tr></thead>
      <tbody>
        <tr v-for="(s, i) in students" :key="s.key">
          <td>{{ s.name }}</td>
          <td style="text-align:center">{{ s.tag || '—' }}</td>
          <td style="text-align:center">{{ drafts[s.key]?.ai ? (drafts[s.key].ai.score ?? '✓') : (drafts[s.key]?.score ?? '—') }}</td>
          <td style="text-align:center">{{ drafts[s.key]?.human?.used ? (drafts[s.key].human.score ?? '✓') : '—' }}</td>
          <td style="text-align:center">{{ drafts[s.key]?.humanMode || drafts[s.key]?.source || '—' }}</td>
          <td style="text-align:center"><button class="btn" @click="openReview(i)">审核</button></td>
        </tr>
      </tbody>
    </table>
    <p v-else class="hint">（未选作业或该作业无学生清单）</p>

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
    </div>
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
      :engine-addr="props.engineAddr" :token="props.token"
      :class-id="curWork?.classId || ''" :work-id="curWork?.workId || ''"
      :students="students" :drafts="drafts" :start-index="reviewIndex"
      @close="reviewOpen = false"
      @saved="loadStudents"
      @notify="(m) => { progress = String(m) }"
    />

    <PlaygroundPanel :engine-addr="props.engineAddr" :token="props.token" />

</template>

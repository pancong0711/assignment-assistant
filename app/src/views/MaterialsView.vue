<script setup lang="ts">
/** D131：课堂资料页（只读）。
 *
 *  设计取舍（docs/79 §10.4）：**抽取与确认刻意留在 CLI**——
 *  确认动作决定 `summary` 批阅的依据，必须教师亲自执行，
 *  不让 PWA（进而让 AI/脚本）静默改生效清单。本页只做"看清现状"。
 */
import { computed, onMounted, ref } from 'vue'
import { useSettingsStore } from '../stores/settings'
import {
  MATERIALS_UPLOAD_EXTS, fetchMaterialsFiles, fetchMaterialsKnowledge,
  confirmMaterials, copyFromAtopia, createMaterialsChap, extractMaterials,
  fetchAtopiaWork, fetchMaterialsList, fetchMaterialsSuggestPreview,
  fetchMaterialsExtractInfo, fetchMaterialsSuggestDiagnostics,
  removeMaterialsFile, restoreMaterialsFile, suggestMaterials, transcribeMaterials,
  uploadMaterialsFiles,
  fetchLlmConfig, type LlmProvider, type MaterialsExtractInfo,
  type MaterialsSuggestDiagnostics,
  type MaterialsChap, type MaterialsFile,
} from '../lib/engineClient'

const settings = useSettingsStore()
const loading = ref(false)
const chaps = ref<MaterialsChap[]>([])
const root = ref('')
const msg = ref('')
const active = ref<string>('')
const knowTerms = ref<string[]>([])
const knowMd = ref('')
/** D138：按主题分组（`{主题: 术语[]}`）；无主题时全部归「其他」 */
const knowTopics = ref<Record<string, string[]>>({})

/* D134-T3e：上传与文件管理（`_source/` 是教师原件，同名不覆盖；移除只进回收站） */
const files = ref<MaterialsFile[]>([])
const showTrash = ref(false)
const uploading = ref(false)
/* D155：资料类型（只影响 `_source/<类型>/` 子目录） */
const upKind = ref<'plan' | 'ppt' | 'textbook' | 'other'>('plan')
const UP_KINDS = [
  { v: 'plan', label: '授课计划' },
  { v: 'ppt', label: 'PPT/讲义' },
  { v: 'textbook', label: '教材' },
  { v: 'other', label: '其他' },
] as const
const fileMsg = ref('')
const pendingRemove = ref<MaterialsFile | null>(null)
const pendingRestore = ref<MaterialsFile | null>(null)

/* D228：原件多选——抽取与 AI 知识点识别都可只处理选中文件。
 * 更新一个文件时只需选它重抽（sha256 变才真正处理）；未选文件/索引保持不动。 */
const selectedSourceFiles = ref<Set<string>>(new Set())
const knownSourceFiles = ref<Set<string>>(new Set())
const selectionChapter = ref('')
const forceExtract = ref(false)
const sourceFiles = computed(() => files.value.filter((f) => f.dir === '_source' && !f.error))
const selectedFileList = computed(() => sourceFiles.value
  .filter((f) => selectedSourceFiles.value.has(f.file))
  .map((f) => f.file))
const selectedUnextracted = computed(() => sourceFiles.value
  .filter((f) => selectedSourceFiles.value.has(f.file) && !f.extracted))
const allFilesSelected = computed(() => !!sourceFiles.value.length
  && sourceFiles.value.every((f) => selectedSourceFiles.value.has(f.file)))

function toggleFile(file: string, checked: boolean) {
  const next = new Set(selectedSourceFiles.value)
  if (checked) next.add(file); else next.delete(file)
  selectedSourceFiles.value = next
}
function selectAllFiles() {
  selectedSourceFiles.value = new Set(sourceFiles.value.map((f) => f.file))
}
function clearFileSelection() {
  selectedSourceFiles.value = new Set()
}
function invertFileSelection() {
  selectedSourceFiles.value = new Set(sourceFiles.value
    .filter((f) => !selectedSourceFiles.value.has(f.file)).map((f) => f.file))
}

/** D171-T7：AI 建议知识点的 provider / 模型。
 *  默认**跟随评阅段配置**（教师建议），但可显式覆盖（存 localStorage）。 */
const suggestProviders = ref<LlmProvider[]>([])
const suggestProvider = ref('')
const suggestModel = ref('')
const suggestStages = ref<Record<string, { provider?: string; model?: string }>>({})
const LS_SUGGEST_MODEL = 'assignment-assistant.materials.suggestModel.v1'

async function loadSuggestProviders() {
  try {
    const r = await fetchLlmConfig(settings.engineUrl, settings.engineToken)
    suggestProviders.value = (r?.providers || []) as LlmProvider[]
    suggestStages.value = (r?.stages || {}) as Record<string, { provider?: string; model?: string }>
    const saved = localStorage.getItem(LS_SUGGEST_MODEL)
    if (saved) {
      try {
        const o = JSON.parse(saved)
        suggestProvider.value = String(o.provider || '')
        suggestModel.value = String(o.model || '')
      } catch { /* 忽略坏值 */ }
    }
  } catch { suggestProviders.value = [] }
}

function saveSuggestChoice() {
  localStorage.setItem(LS_SUGGEST_MODEL,
    JSON.stringify({ provider: suggestProvider.value, model: suggestModel.value }))
}

const evalStage = computed(() => suggestStages.value.evaluation || {})
const suggestProviderObj = computed(() =>
  suggestProviders.value.find((p) => p.name === suggestProvider.value) || null)
const effectiveProviderName = computed(() =>
  suggestProvider.value || String(evalStage.value.provider || '未配置'))
const effectiveModelName = computed(() => {
  if (suggestModel.value.trim()) return suggestModel.value.trim()
  if (suggestProvider.value) return String(suggestProviderObj.value?.models?.[0] || '默认模型')
  return String(evalStage.value.model || '默认模型')
})
/** 当前生效的 provider/模型描述；默认明确显示“评阅段用的是哪个 provider”。 */
const suggestModelLabel = computed(() =>
  `${effectiveProviderName.value} / ${effectiveModelName.value}`
  + (suggestProvider.value ? '（本面板显式指定）' : '（跟随评阅段 evaluation）'))
const suggestStageWarning = computed(() => {
  if (!suggestProvider.value && !evalStage.value.provider) {
    return '评阅段 provider 未配置；请先在设置中心配置 evaluation 段，或在这里显式选择 provider。'
  }
  const p = suggestProviderObj.value
  if (p && !p.has_key && (p as any).type !== 'command') {
    return `provider「${p.name}」没有可用 api_key。`
  }
  return ''
})
const transcribeStage = computed(() => suggestStages.value.transcription || {})
const transcribeModelLabel = computed(() => {
  if (suggestProvider.value) {
    return `${suggestProvider.value} / ${suggestModel.value.trim()
      || String(suggestProviderObj.value?.models?.[0] || '默认模型')}（本面板显式指定）`
  }
  return `${String(transcribeStage.value.provider || '未配置')} / `
    + `${String(transcribeStage.value.model || '默认模型')}（跟随转录段 transcription）`
})

/* D137：抽取 / AI 建议 / 确认生效 */
const stepBusy = ref<'extract' | 'transcribe' | 'suggest' | 'confirm' | ''>('')
const stepMsg = ref('')
const transcribeEngine = ref<'auto' | 'local' | 'vision'>('auto')
const transcribeForce = ref(false)
const suggestDiag = ref<MaterialsSuggestDiagnostics & { request?: Record<string, unknown> } | null>(null)
const diagBusy = ref(false)
const diagMsg = ref('')
const pendingConfirm = ref<{ preview: string; terms: string[]; hasConfirmed: boolean } | null>(null)
const confirmOverwrite = ref(false)

function diagText(): string {
  return JSON.stringify(suggestDiag.value || {}, null, 2)
}
async function copySuggestDiag() {
  try {
    await navigator.clipboard.writeText(diagText())
    diagMsg.value = '诊断信息已复制'
  } catch {
    diagMsg.value = '复制失败；可直接选中下方 JSON 手动复制'
  }
}
async function runSuggestDiagnostics() {
  if (!active.value) return
  diagBusy.value = true
  diagMsg.value = ''
  try {
    suggestDiag.value = await fetchMaterialsSuggestDiagnostics(
      settings.engineUrl, settings.engineToken, active.value,
      suggestProvider.value, suggestModel.value.trim(), selectedFileList.value)
    const s = suggestDiag.value.source
    const l = suggestDiag.value.llm
    diagMsg.value = suggestDiag.value.ok
      ? `配置与素材检查通过：${l?.provider || '—'} / ${l?.model || '—'}；`
        + `${s?.selectedCount ?? 0} 个文件，${s?.chars ?? 0} 字，${s?.imageCount ?? 0} 张图`
      : `检查发现问题：${(l?.warnings || []).concat(s?.warnings || []).join('；') || suggestDiag.value.error || '见下方详情'}`
  } catch (e) {
    diagMsg.value = `诊断请求失败：${String((e as Error).message || e)}`
  } finally {
    diagBusy.value = false
  }
}

async function doExtract() {
  if (!active.value) return
  const picked = selectedFileList.value
  if (!picked.length) {
    stepMsg.value = '请先勾选要抽取的文件（可用「全选」）。'
    return
  }
  stepBusy.value = 'extract'
  stepMsg.value = ''
  try {
    const r = await extractMaterials(settings.engineUrl, settings.engineToken,
                                     active.value, forceExtract.value, picked)
    const errs = (r as any)?.errors as Array<{ file?: string; error?: string }> | undefined
    const skipped = (r?.skipped_unchanged || []).length
    if (r?.ok) {
      stepMsg.value = `✅ 已处理选中 ${picked.length} 个文件`
        + (skipped ? `；其中 ${skipped} 个内容未变、按 sha256 增量跳过` : '')
        + '。可继续「② AI 建议知识点」。'
    } else {
      const detail = (errs || [])
        .map((e) => `${e.file || '（整体）'}：${e.error || ''}`)
        .filter(Boolean).join('；')
      stepMsg.value = `❌ ${r?.error || '抽取失败'}`
        + (detail ? `\n明细：${detail}` : '')
        + '\n常见原因：选中文件不存在、类型不支持（支持 pptx/docx/xlsx/pdf/图片/md/txt），或 PDF 缺 poppler-utils。'
    }
    await refresh()
  } catch (e) {
    stepMsg.value = `抽取失败：${String((e as Error).message || e)}`
  } finally { stepBusy.value = '' }
}

async function doTranscribe() {
  if (!active.value) return
  const picked = selectedFileList.value
  if (!picked.length) {
    stepMsg.value = '请先勾选要转写的文件（可用「全选」）。'
    return
  }
  if (selectedUnextracted.value.length) {
    stepMsg.value = `选中文件中有 ${selectedUnextracted.value.length} 个尚未抽取；请先点「① 抽取选中文件」。`
    return
  }
  const scope = picked.length === sourceFiles.value.length
    ? `全部 ${picked.length} 个文件`
    : `选中的 ${picked.length} 个文件`
  const engineLabel = transcribeEngine.value === 'local' ? '本地 OCR'
    : transcribeEngine.value === 'vision' ? 'AI 视觉转写'
    : '自动（本地 OCR 优先，失败页走视觉）'
  if (!window.confirm(
    `将对${scope}执行转写（可能调用模型并产生费用）。\n`
    + `引擎：${engineLabel}\n模型：${transcribeModelLabel.value}`)) return
  stepBusy.value = 'transcribe'
  stepMsg.value = `正在转写${scope}（${engineLabel}）…`
  try {
    const r = await transcribeMaterials(
      settings.engineUrl, settings.engineToken, active.value, picked,
      { engine: transcribeEngine.value, provider: suggestProvider.value,
        model: suggestModel.value.trim(), force: transcribeForce.value })
    if (r?.ok) {
      stepMsg.value = `✅ 转写完成：${r.transcribed || 0} 个文件`
        + `；跳过 ${r.skipped || 0} 个已有文字层的文件。`
        + (r.warning ? `\n提示：${r.warning}` : '')
    } else {
      const failures = (r?.errors || []).map((e) => `${e.file || ''}：${e.error || ''}`)
        .filter(Boolean).join('；')
      stepMsg.value = `❌ ${r?.error || r?.detail || '转写未全部完成'}`
        + (failures ? `\n明细：${failures.slice(0, 1200)}` : '')
        + '\n可只勾选失败文件重试；已成功的页会复用。'
    }
    await refresh()
  } catch (e) {
    stepMsg.value = `转写失败：${String((e as Error).message || e)}`
  } finally { stepBusy.value = '' }
}

async function doSuggest() {
  if (!active.value) return
  const picked = selectedFileList.value
  if (!picked.length) {
    stepMsg.value = '请先勾选要识别知识点的文件（可用「全选」）。'
    return
  }
  if (selectedUnextracted.value.length) {
    stepMsg.value = `选中文件中有 ${selectedUnextracted.value.length} 个尚未抽取；请先点「① 抽取选中文件」。`
    return
  }
  const scope = picked.length === sourceFiles.value.length
    ? `全部 ${picked.length} 个文件`
    : `选中的 ${picked.length} 个文件`
  if (!window.confirm(
    `「AI 建议知识点」将基于${scope}调用模型（产生费用），继续？\n`
    + `模型：${suggestModelLabel.value}`)) return
  stepBusy.value = 'suggest'
  stepMsg.value = `正在基于${scope}让 AI 识别知识点，请稍候…`
  suggestDiag.value = null
  diagMsg.value = ''
  try {
    const r = await suggestMaterials(settings.engineUrl, settings.engineToken, active.value,
                                     suggestModel.value.trim(), suggestProvider.value, picked)
    suggestDiag.value = (r?.diagnostics as any) || {
      request: { provider: suggestProvider.value, model: suggestModel.value.trim(), files: picked },
    }
    if (r?.ok) {
      const mode = r?.source?.mode === 'vision' ? '图片/多模态' : '文本'
      const nFiles = r?.source?.files ?? picked.length
      const nTerms = r?.term_count ?? 0
      stepMsg.value = `✅ 已生成 AI 建议：${nTerms} 个知识点（来源 ${nFiles} 个文件，${mode}）`
        + `；实际使用：${r?.provider || effectiveProviderName.value} / ${r?.model || effectiveModelName.value}`
        + '。尚未生效，请核对后点「③ 确认生效」。'
    } else {
      stepMsg.value = `❌ ${r?.error || '知识点识别失败'}`
        + (r?.detail ? `\n原因：${r.detail}` : '')
        + (r?.errorType ? `\n错误类型：${r.errorType}` : '')
    }
    await refresh()
  } catch (e) {
    const msg = String((e as Error).message || e)
    stepMsg.value = `知识点识别失败：${msg}`
    suggestDiag.value = {
      request: { provider: suggestProvider.value, model: suggestModel.value.trim(), files: picked },
      error: msg,
    }
  } finally { stepBusy.value = '' }
}

/** 确认前**先取全文**：必须让教师看清将生效的内容才允许点确认。 */
async function askConfirm() {
  if (!active.value) return
  stepBusy.value = 'confirm'
  stepMsg.value = ''
  try {
    const r = await fetchMaterialsSuggestPreview(settings.engineUrl, settings.engineToken,
                                                 active.value)
    if (!r?.ok || !r.hasAiSuggest) {
      stepMsg.value = `❌ ${r?.error || '没有待确认的 AI 建议（先点「AI 建议知识点」）'}`
      return
    }
    confirmOverwrite.value = false
    pendingConfirm.value = {
      preview: String(r.preview || ''), terms: r.terms || [],
      hasConfirmed: !!r.hasConfirmed,
    }
  } catch (e) {
    stepMsg.value = `读取建议失败：${String((e as Error).message || e)}`
  } finally { stepBusy.value = '' }
}

async function confirmApply() {
  const p = pendingConfirm.value
  pendingConfirm.value = null
  if (!p || !active.value) return
  if (p.hasConfirmed && !confirmOverwrite.value) {
    stepMsg.value = '已有生效清单：如需覆盖请勾选「覆盖已有清单」'
    return
  }
  stepBusy.value = 'confirm'
  try {
    const r = await confirmMaterials(settings.engineUrl, settings.engineToken, active.value,
                                     { confirm: 'teacher:pwa', force: confirmOverwrite.value })
    stepMsg.value = r?.ok
      ? '✅ 已确认生效：summary 批阅将以此为依据'
      : `❌ ${r?.error || '确认失败'}`
    await refresh()
  } catch (e) {
    stepMsg.value = `确认失败：${String((e as Error).message || e)}`
  } finally { stepBusy.value = '' }
}
const fileInput = ref<HTMLInputElement | null>(null)

const cur = computed(() => chaps.value.find((c) => c.chap === active.value) || null)

async function refresh() {
  loading.value = true
  msg.value = ''
  try {
    const r = await fetchMaterialsList(settings.engineUrl, settings.engineToken)
    if (!r?.ok) { msg.value = `读取失败：${r?.error || '未知错误'}`; return }
    chaps.value = r.chaps || []
    root.value = r.root || ''
    if (!active.value && chaps.value.length) active.value = chaps.value[0]!.chap
    if (active.value) await showKnowledge(active.value)
  } catch (e) {
    msg.value = `读取失败：${String((e as Error).message || e)}（引擎是否在线？）`
  } finally { loading.value = false }
}

async function showKnowledge(chap: string) {
  if (active.value !== chap) {
    // 切换章节：清空上一章的文件选择，loadFiles 会默认全选本章原件。
    selectedSourceFiles.value = new Set()
    knownSourceFiles.value = new Set()
    selectionChapter.value = ''
  }
  active.value = chap
  try {
    const r = await fetchMaterialsKnowledge(settings.engineUrl, settings.engineToken, chap)
    knowTerms.value = r?.terms || []
    knowMd.value = r?.markdown || ''
    knowTopics.value = r?.topics || {}
  } catch {
    knowTerms.value = []
    knowMd.value = ''
    knowTopics.value = {}
  }
  await loadFiles()
}

async function loadFiles() {
  if (!active.value) return
  try {
    const r = await fetchMaterialsFiles(settings.engineUrl, settings.engineToken,
                                        active.value, showTrash.value)
    files.value = r?.files || []
    const current = new Set(sourceFiles.value.map((f) => f.file))
    if (selectionChapter.value !== active.value) {
      // 首次进入该章：默认全选，保持旧行为「一键抽取全部」。
      selectedSourceFiles.value = new Set(current)
      selectionChapter.value = active.value
    } else {
      // 同章刷新：保留教师已勾选，只把新上传文件自动加入选择。
      const kept = new Set([...selectedSourceFiles.value].filter((x) => current.has(x)))
      for (const f of sourceFiles.value) {
        if (!knownSourceFiles.value.has(f.file)) kept.add(f.file)
      }
      selectedSourceFiles.value = kept
    }
    knownSourceFiles.value = current
  } catch {
    files.value = []
    selectedSourceFiles.value = new Set()
    knownSourceFiles.value = new Set()
  }
}

/* D229：查看单个文件到底抽取出了什么（文本预览 / 页图 / 元数据）。 */
const extractInfoOpen = ref(false)
const extractInfoBusy = ref(false)
const extractInfo = ref<MaterialsExtractInfo | null>(null)
const extractInfoName = ref('')
const extractInfoMsg = ref('')
async function openExtractInfo(f: MaterialsFile) {
  if (!active.value) return
  extractInfoOpen.value = true
  extractInfoBusy.value = true
  extractInfoMsg.value = ''
  extractInfo.value = null
  extractInfoName.value = f.name
  try {
    extractInfo.value = await fetchMaterialsExtractInfo(
      settings.engineUrl, settings.engineToken, active.value, f.file)
    if (!extractInfo.value?.ok) {
      extractInfoMsg.value = extractInfo.value?.error || '读取抽取信息失败'
    }
  } catch (e) {
    extractInfoMsg.value = `读取抽取信息失败：${String((e as Error).message || e)}`
  } finally { extractInfoBusy.value = false }
}
function closeExtractInfo() {
  extractInfoOpen.value = false
  extractInfo.value = null
  extractInfoMsg.value = ''
}

function pickFiles() { fileInput.value?.click() }

function readAsBase64(f: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const fr = new FileReader()
    fr.onerror = () => reject(new Error('读取文件失败'))
    fr.onload = () => {
      const s = String(fr.result || '')
      resolve(s.includes(',') ? s.slice(s.indexOf(',') + 1) : s)
    }
    fr.readAsDataURL(f)
  })
}

async function onFilesPicked(ev: Event) {
  const input = ev.target as HTMLInputElement
  const list = Array.from(input.files || [])
  input.value = ''
  if (!list.length || !active.value) return
  uploading.value = true
  fileMsg.value = ''
  try {
    const items: { name: string; data_b64: string }[] = []
    const rejected: string[] = []
    for (const f of list) {
      const ext = f.name.slice(f.name.lastIndexOf('.')).toLowerCase()
      if (!MATERIALS_UPLOAD_EXTS.includes(ext)) { rejected.push(f.name); continue }
      items.push({ name: f.name, data_b64: await readAsBase64(f) })
    }
    let okN = 0
    let renamed: string[] = []
    if (items.length) {
      const r = await uploadMaterialsFiles(settings.engineUrl, settings.engineToken,
                                           active.value, items, upKind.value)
      if (!r?.ok) { fileMsg.value = `上传失败：${r?.error || '未知错误'}`; return }
      okN = (r.saved || []).length
      renamed = (r.saved || []).filter((x: any) => x.renamed).map((x: any) => x.name)
      const skipped = (r.skipped || []).map((x: any) => `${x.name}（${x.reason}）`)
      fileMsg.value = `已上传 ${okN} 个`
        + (renamed.length ? `；同名已自动改名：${renamed.join('、')}` : '')
        + (rejected.length ? `；已拒绝（扩展名不允许）：${rejected.join('、')}` : '')
        + (skipped.length ? `；跳过：${skipped.join('、')}` : '')
    } else {
      fileMsg.value = `已拒绝（扩展名不允许）：${rejected.join('、')}`
    }
    await refresh()
  } catch (e) {
    fileMsg.value = `上传失败：${String((e as Error).message || e)}`
  } finally {
    uploading.value = false
  }
}

function askRemove(f: MaterialsFile) { pendingRemove.value = f }

async function confirmRemove() {
  const f = pendingRemove.value
  pendingRemove.value = null
  if (!f || !active.value) return
  try {
    // 引擎侧 `materials remove --file` 期望的是**相对 `_source/`** 的名字，
    // 而列表里的 `file` 是相对章节目录的（`_source/plan.md`）→ 这里去掉前缀。
    const rel = f.file.startsWith('_source/') ? f.file.slice('_source/'.length) : f.file
    const r = await removeMaterialsFile(settings.engineUrl, settings.engineToken,
                                        active.value, rel, 'teacher:pwa')
    if (r?.ok) {
      fileMsg.value = `已移入回收站：${f.name}（未删除，可在 _source/_trash/ 找回）`
    } else {
      fileMsg.value = `移除失败：${r?.error || '未知错误'}`
    }
    await loadFiles()
  } catch (e) {
    fileMsg.value = `移除失败：${String((e as Error).message || e)}`
  }
}

function askRestore(f: MaterialsFile) { pendingRestore.value = f }

async function confirmRestore() {
  const f = pendingRestore.value
  pendingRestore.value = null
  if (!f || !active.value) return
  try {
    // 回收站里的文件名相对 `_trash/`；引擎接受 `a.pdf` 或 `_trash/a.pdf`
    const rel = f.file.replace(/^_source\/_trash\//, '')
    const r = await restoreMaterialsFile(settings.engineUrl, settings.engineToken,
                                         active.value, rel, 'teacher:pwa')
    if (r?.ok) {
      fileMsg.value = `已从回收站恢复：${f.name}`
    } else {
      fileMsg.value = `恢复失败：${r?.error || '未知错误'}`
    }
    await loadFiles()
  } catch (e) {
    fileMsg.value = `恢复失败：${String((e as Error).message || e)}`
  }
}

function fmtBytes(n: number): string {
  if (!n) return '0'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

/** 章节状态标签：让教师一眼看出"卡在哪一步"。 */
function stateOf(c: MaterialsChap): { text: string; color: string } {
  if (c.hasConfirmed) return { text: '✅ 已生效', color: '#14532d' }
  if (c.hasAiSuggest) return { text: '待确认', color: '#b45309' }
  if (c.extracted > 0) return { text: '已抽取', color: '#1d4ed8' }
  if (c.sources > 0) return { text: '待抽取', color: '#6b7280' }
  return { text: '空章节', color: '#9ca3af' }
}

/** 该章节的下一步该做什么（把 CLI 命令直接给教师，可复制）。 */
function nextStep(c: MaterialsChap): string {
  if (!c.sources) return `把 PPT/PDF 放进 ${root.value}/${c.chap}/_source/`
  if (!c.extracted) return `assist materials extract --chap ${c.chap}`
  if (!c.hasAiSuggest) return `assist materials suggest --chap ${c.chap}`
  if (!c.hasConfirmed) return `assist materials confirm --chap ${c.chap}`
  return '已完成：summary 批阅会以此为依据'
}

/* D164：从 Atopia 复制解析产物（必须预览全文 + 教师确认） */
const atopiaParsed = ref<Array<{ file: string; name: string }>>([])
const pendingAtopia = ref<{ file: string; preview: string; terms: number } | null>(null)
const atopiaBusy = ref(false)

async function askCopyFromAtopia() {
  if (!active.value) return
  atopiaBusy.value = true
  msg.value = ''
  try {
    const r = await fetchAtopiaWork(settings.engineUrl, settings.engineToken, active.value)
    const parsed = (r?.files || []).filter((f: any) => f.dir === '_parsed')
    atopiaParsed.value = parsed.map((f: any) => ({ file: f.name, name: f.name }))
    if (!parsed.length) {
      msg.value = `Atopia 工作区里没有「${active.value}」的解析产物：先到 Atopia 页 工作区页签上传并解析。`
      return
    }
    // 取第一个（通常只有一个）的全文预览
    const one = await fetchAtopiaWork(settings.engineUrl, settings.engineToken,
                                      active.value, parsed[0].name)
    const data = one?.parsed || {}
    const terms = (data.knowledge || []).filter((k: any) => k && k.term)
    pendingAtopia.value = {
      file: parsed[0].name,
      terms: terms.length,
      preview: terms.map((k: any) => `- ${k.term}${k.topic ? ' · ' + k.topic : ''}`).join('\n'),
    }
  } catch (e) {
    msg.value = `读取 Atopia 解析产物失败：${String((e as Error).message || e)}`
  } finally { atopiaBusy.value = false }
}

async function confirmCopyFromAtopia() {
  const p = pendingAtopia.value
  pendingAtopia.value = null
  if (!p || !active.value) return
  atopiaBusy.value = true
  try {
    const r = await copyFromAtopia(settings.engineUrl, settings.engineToken, {
      feature: active.value, file: p.file, confirm: 'teacher:pwa',
    })
    msg.value = r?.ok
      ? `✅ 已从 Atopia 复制：${r.terms} 个知识点 → 课堂资料「${active.value}」（存为知识点清单.json/.md）`
      : `❌ ${r?.error || '复制失败'}`
    await refresh()
  } catch (e) {
    msg.value = `复制失败：${String((e as Error).message || e)}`
  } finally { atopiaBusy.value = false }
}

/* D163：新建特征名目录（26C1 等）——此前只能手工在文件系统建 */
const newChap = ref('')
const creating = ref(false)
async function doCreateChap() {
  const name = newChap.value.trim()
  if (!name) { msg.value = '请填写特征名（如 26C1）'; return }
  creating.value = true
  msg.value = ''
  try {
    const r = await createMaterialsChap(settings.engineUrl, settings.engineToken, name)
    if (!r?.ok) { msg.value = `❌ ${r?.error || '创建失败'}`; return }
    msg.value = `✅ 已创建「${name}」（可上传授课计划 / PPT）`
    newChap.value = ''
    active.value = name
    await refresh()
  } catch (e) {
    msg.value = `创建失败：${String((e as Error).message || e)}`
  } finally { creating.value = false }
}

onMounted(() => { refresh(); loadSuggestProviders() })
defineExpose({ refresh })
</script>

<template>
  <div class="wrap">
    <h2 style="margin:0 0 6px">课堂资料（章节知识点清单）</h2>
    <p class="hint" style="margin-top:0">
      `summary` 类作业的批阅依据。资料放在
      <code>{{ root || '<workspace>/materials' }}/&lt;章节&gt;/_source/</code>，
      用 CLI 抽取与确认（本页只读，避免误改生效清单）。
    </p>

    <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin:8px 0">
      <label class="field">新建特征名
        <input v-model="newChap" placeholder="如 26C1" style="width:130px"
               @keydown.enter="doCreateChap" />
      </label>
      <button class="btn primary" :disabled="creating" @click="doCreateChap">
        {{ creating ? '创建中…' : '＋ 新建资料文件夹' }}
      </button>
      <button class="btn" :disabled="loading" @click="refresh">刷新</button>
      <span v-if="msg" class="hint" style="margin:0">{{ msg }}</span>
    </div>

    <div v-if="!loading && !chaps.length" class="empty">
      <p class="hint" style="margin:0 0 6px">
        <b>还没有任何资料文件夹。</b>
      </p>
      <p class="hint" style="margin:0">
        ① 在上方填「特征名」（如 <code>26C1</code>）→ 点「＋ 新建资料文件夹」；
        ② 选中它后，在右侧「原件」区点「⬆️ 上传附件」（先选类型：授课计划 / PPT / 教材）；
        ③ 上传完依次跑「① 抽取 → ② AI 建议知识点 → ③ 确认生效」。
      </p>
    </div>

    <div v-else class="grid">
      <table class="tbl">
        <thead>
          <tr><th>章节</th><th>原件</th><th>已抽取</th><th>字数</th><th>状态</th></tr>
        </thead>
        <tbody>
          <tr v-for="c in chaps" :key="c.chap"
              :class="{ on: c.chap === active }" @click="showKnowledge(c.chap)">
            <td><b>{{ c.chap }}</b></td>
            <td class="c">{{ c.sources }}</td>
            <td class="c">{{ c.extracted }}</td>
            <td class="c">{{ c.chars }}</td>
            <td class="c"><b :style="{ color: stateOf(c).color }">{{ stateOf(c).text }}</b></td>
          </tr>
        </tbody>
      </table>

      <div v-if="cur" class="detail">
        <!-- D134-T3e：上传与文件管理（同名不覆盖；移除只进回收站） -->
        <h4 style="margin:4px 0">原件（`_source/`）</h4>
        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin:6px 0">
          <label class="field">类型
            <select v-model="upKind" style="font-size:13px">
              <option v-for="k in UP_KINDS" :key="k.v" :value="k.v">{{ k.label }}</option>
            </select>
          </label>
          <button class="btn" :disabled="uploading" @click="pickFiles">
            {{ uploading ? '上传中…' : '⬆️ 上传附件' }}
          </button>
          <input ref="fileInput" type="file" multiple style="display:none"
                 :accept="MATERIALS_UPLOAD_EXTS.join(',')" @change="onFilesPicked" />
          <label class="hint" style="display:flex; gap:4px; align-items:center; margin:0">
            <input v-model="showTrash" type="checkbox" @change="loadFiles" /> 显示回收站
          </label>
          <span v-if="fileMsg" class="hint" style="margin:0">{{ fileMsg }}</span>
        </div>
        <p v-if="!files.length" class="hint" style="margin:0 0 6px">
          还没有原件。可上传 {{ MATERIALS_UPLOAD_EXTS.join(' / ') }}（单个 ≤20MB）。
        </p>
        <table v-else class="tbl" style="margin-bottom:8px">
          <thead>
            <tr>
              <th style="width:28px">
                <input type="checkbox" :checked="allFilesSelected"
                       title="全选原件"
                       @change="($event.target as HTMLInputElement).checked ? selectAllFiles() : clearFileSelection()" />
              </th>
              <th>文件</th><th>抽取状态</th><th>大小</th><th>修改时间</th><th>位置</th><th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="f in files" :key="f.dir + '/' + f.file">
              <td>
                <input v-if="f.dir === '_source' && !f.error" type="checkbox"
                       :checked="selectedSourceFiles.has(f.file)"
                       @change="toggleFile(f.file, ($event.target as HTMLInputElement).checked)" />
              </td>
              <td>{{ f.name }}</td>
              <td class="c">
                <template v-if="f.dir === '_source'">
                  <b v-if="f.extracted" style="color:#14532d">已抽取</b>
                  <span v-else style="color:#b45309">未抽取</span>
                  <span v-if="f.extracted" class="hint" style="margin-left:4px">
                    {{ f.extractMode || '—' }}<template v-if="f.extractChars"> · {{ f.extractChars }} 字</template>
                    <template v-if="f.extractImages"> · {{ f.extractImages }} 图</template>
                  </span>
                  <div v-if="f.extracted" class="hint" style="margin-top:2px">
                    <template v-if="f.transcribed">
                      <b style="color:#14532d">已转写</b>
                      · {{ f.transcriptPages || 0 }}/{{ f.transcriptPagesTotal || 0 }} 页
                      · {{ f.transcriptChars || 0 }} 字
                      <span v-if="f.transcriptEngine"> · {{ f.transcriptEngine }}</span>
                      <span v-if="f.transcriptFailedPages?.length" style="color:#b45309">
                        · 失败页 {{ f.transcriptFailedPages.join(',') }}
                      </span>
                    </template>
                    <span v-else-if="f.extractImages && !f.extractChars" style="color:#b45309">
                      纯页图，未转写
                    </span>
                  </div>
                </template>
                <span v-else class="hint">—</span>
              </td>
              <td class="c">{{ fmtBytes(f.bytes) }}</td>
              <td class="c">{{ f.mtime }}</td>
              <td class="c">{{ f.dir === '_source' ? '原件' : '回收站' }}</td>
              <td class="c">
                <template v-if="f.dir === '_source'">
                  <button class="btn sm" :disabled="!f.extracted" @click="openExtractInfo(f)"
                          :title="f.extracted ? '查看抽取出的文本/页图/元数据' : '尚未抽取，暂无可查看内容'">
                    🔍 抽取信息
                  </button>
                  <button class="btn sm" @click="askRemove(f)">移除</button>
                </template>
                <button v-else class="btn sm" @click="askRestore(f)">恢复</button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="sourceFiles.length" style="display:flex; gap:8px; align-items:center;
             flex-wrap:wrap; margin:0 0 8px">
          <span class="hint" style="margin:0">
            已选 <b>{{ selectedFileList.length }}</b> / {{ sourceFiles.length }} 个原件
          </span>
          <button class="btn sm" @click="selectAllFiles">全选</button>
          <button class="btn sm" @click="clearFileSelection">全不选</button>
          <button class="btn sm" @click="invertFileSelection">反选</button>
          <label class="hint" style="display:flex; gap:4px; align-items:center; margin:0">
            <input v-model="forceExtract" type="checkbox" /> 强制重抽（忽略 sha256）
          </label>
          <label class="hint" style="display:flex; gap:4px; align-items:center; margin:0">
            <input v-model="transcribeForce" type="checkbox" /> 强制重转写
          </label>
          <span class="hint" style="margin:0">
            更新文件后只需勾选该文件重抽；未勾选文件及其索引保持不变。
          </span>
        </div>

        <h4 style="margin:4px 0">下一步</h4>
        <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin:4px 0">
          <button class="btn" :disabled="stepBusy !== '' || !selectedFileList.length" @click="doExtract">
            {{ stepBusy === 'extract' ? '抽取中…'
              : (allFilesSelected ? '① 抽取全部（增量）' : `① 抽取选中 ${selectedFileList.length} 个`) }}
          </button>
          <select v-model="transcribeEngine" style="font-size:13px"
                  title="转写引擎：自动=本地 OCR 优先，失败页走视觉">
            <option value="auto">转写：自动（OCR→视觉）</option>
            <option value="local">转写：仅本地 OCR</option>
            <option value="vision">转写：仅 AI 视觉</option>
          </select>
          <button class="btn" :disabled="stepBusy !== '' || !selectedFileList.length
                    || selectedUnextracted.length > 0" @click="doTranscribe"
                  title="把选中图片型资料的页图转写为可查看文本；已成功的页可复用">
            {{ stepBusy === 'transcribe' ? '转写中…' : `📝 转写选中 ${selectedFileList.length} 个` }}
          </button>
          <label class="field" title="默认跟随评阅段配置；如需单独指定可在此选择（会记住）">
            建议用模型
            <select v-model="suggestProvider" @change="saveSuggestChoice"
                    style="font-size:13px; max-width:150px">
              <option value="">（跟随评阅配置）</option>
              <option v-for="p in suggestProviders" :key="p.name" :value="p.name">
                {{ p.name }}{{ p.has_key ? '' : '（无 key）' }}
              </option>
            </select>
            <input v-model="suggestModel" placeholder="模型名（空=默认）" style="width:150px"
                   @change="saveSuggestChoice" />
          </label>
          <button class="btn"
                  :disabled="stepBusy !== '' || !selectedFileList.length || selectedUnextracted.length > 0"
                  @click="doSuggest"
                  :title="selectedUnextracted.length
                    ? '选中文件中有未抽取项，请先抽取'
                    : '只基于当前勾选的文件识别知识点'">
            {{ stepBusy === 'suggest' ? '识别中…' : '② AI 建议知识点' }}
          </button>
          <button class="btn" :disabled="diagBusy || stepBusy !== ''"
                  @click="runSuggestDiagnostics"
                  title="不调用模型：检查实际 provider/model、key 与选中文件的抽取内容">
            {{ diagBusy ? '检查中…' : '🔎 检查识别配置' }}
          </button>
          <span class="hint" style="margin:0">知识点识别将使用：{{ suggestModelLabel }}</span>
          <span class="hint" style="margin:0">转写将使用：{{ transcribeModelLabel }}</span>
          <button class="btn primary" :disabled="stepBusy !== '' || !cur.hasAiSuggest"
                  @click="askConfirm">
            {{ stepBusy === 'confirm' ? '处理中…' : '③ 确认生效' }}
          </button>
          <button class="btn" :disabled="atopiaBusy" @click="askCopyFromAtopia"
                  title="把 Atopia 工作区里该特征名的解析产物复制进来（会先预览全文）">
            {{ atopiaBusy ? '读取中…' : '📥 从 Atopia 复制' }}
          </button>
        </div>
        <p v-if="suggestStageWarning" class="hint" style="margin:2px 0; color:#b45309">
          ⚠ {{ suggestStageWarning }}
        </p>
        <p v-if="stepMsg" class="hint" style="margin:2px 0; white-space:pre-wrap">{{ stepMsg }}</p>
        <div v-if="suggestDiag" style="margin:6px 0; padding:8px; border:1px solid var(--c-border);
             border-radius:6px; background:#fafafa">
          <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap">
            <b style="font-size:13px">识别诊断</b>
            <button class="btn sm" @click="copySuggestDiag">复制诊断信息</button>
            <span v-if="diagMsg" class="hint" style="margin:0">{{ diagMsg }}</span>
          </div>
          <pre class="md" style="max-height:280px; margin:6px 0 0; white-space:pre-wrap">{{ diagText() }}</pre>
        </div>
        <p v-if="selectedUnextracted.length" class="hint" style="margin:2px 0; color:#b45309">
          选中文件中有 {{ selectedUnextracted.length }} 个尚未抽取，需先点「① 抽取选中文件」。
        </p>
        <p v-if="suggestDiag?.source?.needsTranscription" class="hint"
           style="margin:2px 0; color:#b45309">
          当前选中资料没有文字层/转写文本，将直接走视觉模型；建议先点「📝 转写选中」。
        </p>
        <p class="hint" style="margin:2px 0">
          {{ nextStep(cur) }}
        </p>

        <h4 style="margin:12px 0 4px">生效知识点清单</h4>
        <p v-if="!knowTerms.length" class="hint">
          尚无生效清单（<code>知识点清单.md</code>）。按上面「下一步」执行后这里会显示。
        </p>
        <template v-else>
          <p class="hint" style="margin:0 0 4px">
            共 {{ knowTerms.length }} 个知识点（summary 批阅以此为核对依据）：
          </p>
          <!-- D138：按主题分组（章 → 主题 → 术语）；无主题时归「其他」 -->
          <div v-for="(ts, topic) in knowTopics" :key="topic" style="margin-bottom:6px">
            <p class="hint" style="margin:0 0 2px">
              📚 <b>{{ topic }}</b>（{{ ts.length }}）
            </p>
            <div class="terms">
              <span v-for="t in ts" :key="t" class="term">{{ t }}</span>
            </div>
          </div>
          <details style="margin-top:6px">
            <summary class="hint" style="cursor:pointer">查看清单原文</summary>
            <pre class="md">{{ knowMd }}</pre>
          </details>
        </template>
      </div>
    </div>

    <!-- D229：单文件抽取详情（文本预览 / 页图 / 元数据） -->
    <div v-if="extractInfoOpen" class="mask" @click.self="closeExtractInfo">
      <div class="dlg wide" style="max-height:86vh; overflow:auto">
        <h3 style="margin:0 0 8px">抽取信息 · {{ extractInfoName }}</h3>
        <p v-if="extractInfoBusy" class="hint">读取中…</p>
        <p v-else-if="extractInfoMsg" class="hint" style="color:#b45309">{{ extractInfoMsg }}</p>
        <template v-else-if="extractInfo?.ok">
          <table class="tbl" style="margin-bottom:8px">
            <tbody>
              <tr><th>抽取引擎</th><td>{{ extractInfo.engine || '—' }}</td>
                  <th>文本字数</th><td>{{ extractInfo.chars || 0 }}</td></tr>
              <tr><th>幻灯片</th><td>{{ extractInfo.slides || '—' }}</td>
                  <th>PDF 页数</th><td>{{ extractInfo.pages || '—' }}</td></tr>
              <tr><th>页图/图片</th><td>{{ extractInfo.imageCount || 0 }}</td>
                  <th>源文件</th><td>{{ extractInfo.kind || '—' }}</td></tr>
              <tr v-if="extractInfo.textFile"><th>文本缓存</th>
                  <td colspan="3"><code>{{ extractInfo.textFile }}</code></td></tr>
            </tbody>
          </table>
          <h4 style="margin:8px 0 4px">抽取文本预览</h4>
          <pre class="md" style="max-height:320px; white-space:pre-wrap">{{ extractInfo.textPreview || '（无文本；可能是图片/扫描件，将走多模态页图识别）' }}</pre>
          <p v-if="extractInfo.textTruncated" class="hint">
            仅显示前 {{ extractInfo.textPreview?.length || 0 }} 字（全文 {{ extractInfo.textCharsTotal || 0 }} 字）。
          </p>
          <template v-if="extractInfo.transcript">
            <h4 style="margin:10px 0 4px">转写文本</h4>
            <p class="hint" style="margin:0 0 4px">
              引擎 {{ extractInfo.transcript.engine || '—' }} ·
              {{ extractInfo.transcript.pages || 0 }}/{{ extractInfo.transcript.pagesTotal || 0 }} 页 ·
              {{ extractInfo.transcript.chars || 0 }} 字
              <span v-if="extractInfo.transcript.failedPages?.length" style="color:#b45309">
                · 失败页 {{ extractInfo.transcript.failedPages.join(',') }}
              </span>
              <span v-if="extractInfo.transcript.provider || extractInfo.transcript.model">
                · {{ extractInfo.transcript.provider }} / {{ extractInfo.transcript.model }}
              </span>
            </p>
            <pre class="md" style="max-height:360px; white-space:pre-wrap">{{ extractInfo.transcriptPreview || '（转写文本为空）' }}</pre>
            <p v-if="extractInfo.transcriptTruncated" class="hint">转写文本仅显示预览。</p>
          </template>
          <template v-if="extractInfo.images?.length">
            <h4 style="margin:8px 0 4px">页图/图片清单（{{ extractInfo.images.length }}）</h4>
            <div class="hint" style="max-height:160px; overflow:auto">
              <div v-for="img in extractInfo.images" :key="img.name">
                {{ img.exists ? '✓' : '✗' }} {{ img.name }}
              </div>
            </div>
          </template>
        </template>
        <div style="display:flex; justify-content:flex-end; margin-top:8px">
          <button class="btn" @click="closeExtractInfo">关闭</button>
        </div>
      </div>
    </div>

    <!-- D164：从 Atopia 复制的确认弹窗（同样展示全文） -->
    <div v-if="pendingAtopia" class="mask">
      <div class="dlg wide">
        <h3 style="margin:0 0 8px">把 Atopia 的解析结果复制到课堂资料？</h3>
        <p class="hint" style="margin:0 0 6px">
          文件 <code>{{ pendingAtopia.file }}</code>，共
          <b>{{ pendingAtopia.terms }}</b> 个知识点。
          复制后会写成 <code>知识点清单.json</code> + <code>知识点清单.md</code>，
          <b>summary 批阅将以它为依据</b>。
        </p>
        <pre class="md" style="max-height:280px">{{ pendingAtopia.preview }}</pre>
        <div style="display:flex; gap:8px; justify-content:flex-end; margin-top:6px">
          <button class="btn" @click="pendingAtopia = null">取消</button>
          <button class="btn primary" @click="confirmCopyFromAtopia">我确认复制</button>
        </div>
      </div>
    </div>

    <!-- D137：确认生效 —— **必须展示全文**，教师看清后才点 -->
    <div v-if="pendingConfirm" class="mask">
      <div class="dlg wide">
        <h3 style="margin:0 0 8px">确认让这份清单成为批阅依据？</h3>
        <p class="hint" style="margin:0 0 6px">
          确认后 <code>summary</code> 类作业会**以此清单核对**学生是否讲到这些知识点。
          共 {{ pendingConfirm.terms.length }} 个知识点：
        </p>
        <pre class="md" style="max-height:300px">{{ pendingConfirm.preview }}</pre>
        <label v-if="pendingConfirm.hasConfirmed" style="display:flex; gap:6px;
               align-items:center; font-size:13px; margin:6px 0">
          <input v-model="confirmOverwrite" type="checkbox" />
          覆盖已有生效清单（<code>知识点清单.md</code>）
        </label>
        <div style="display:flex; gap:8px; justify-content:flex-end; margin-top:6px">
          <button class="btn" @click="pendingConfirm = null">取消</button>
          <button class="btn primary" @click="confirmApply">我确认生效</button>
        </div>
      </div>
    </div>

    <!-- L2 二次确认：恢复 -->
    <div v-if="pendingRestore" class="mask">
      <div class="dlg">
        <h3 style="margin:0 0 8px">确认恢复到原件目录？</h3>
        <p class="hint" style="margin:0 0 8px">
          将把 <b>{{ pendingRestore.name }}</b> 从 <code>_source/_trash/</code>
          移回 <code>_source/</code>（同名会自动改名，不覆盖现有文件）。
        </p>
        <div style="display:flex; gap:8px; justify-content:flex-end">
          <button class="btn" @click="pendingRestore = null">取消</button>
          <button class="btn" @click="confirmRestore">我确认恢复</button>
        </div>
      </div>
    </div>

    <!-- L2 二次确认：把动作原样给教师看，默认不执行 -->
    <div v-if="pendingRemove" class="mask">
      <div class="dlg">
        <h3 style="margin:0 0 8px">确认移除原件？</h3>
        <p class="hint" style="margin:0 0 8px">
          将把 <b>{{ pendingRemove.name }}</b> 移入
          <code>_source/_trash/</code>（<b>不删除</b>，可人工找回）。
          此操作需要你确认后才会执行。
        </p>
        <div style="display:flex; gap:8px; justify-content:flex-end">
          <button class="btn" @click="pendingRemove = null">取消</button>
          <button class="btn danger" @click="confirmRemove">我确认移除</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wrap { padding: 12px 14px; }
.grid { display: grid; grid-template-columns: minmax(320px, 1fr) minmax(320px, 1.2fr);
        gap: 14px; align-items: start; }
.tbl { border-collapse: collapse; font-size: 13px; width: 100%; }
.tbl th, .tbl td { border: 1px solid #e5e7eb; padding: 4px 8px; }
.tbl th { background: #f9fafb; }
.tbl td.c { text-align: center; }
.tbl tbody tr { cursor: pointer; }
.tbl tbody tr:hover { background: #f8fafc; }
.tbl tbody tr.on { background: #eff6ff; outline: 1px solid #bfdbfe; }
.detail { border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px 12px; }
.cmd { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px; padding: 6px 8px;
       font-size: 12px; white-space: pre-wrap; margin: 0; }
.terms { display: flex; gap: 6px; flex-wrap: wrap; }
.term { background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 999px;
        padding: 2px 10px; font-size: 12px; }
.md { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px; padding: 8px;
      font-size: 12px; max-height: 320px; overflow: auto; white-space: pre-wrap; }
.hint { color: #6b7280; font-size: 12px; }
.empty { border: 1px dashed #d1d5db; border-radius: 10px; padding: 14px 16px;
         background: #fafafa; }
.btn.sm { padding: 1px 8px; font-size: 12px; }
.btn.danger { background: #fee2e2; border-color: #fca5a5; color: #991b1b; }
.mask { position: fixed; inset: 0; background: rgba(15, 23, 42, .45);
        display: flex; align-items: center; justify-content: center; z-index: 50; }
.dlg.wide { width: min(720px, 94vw); }
.dlg { background: #fff; border-radius: 10px; padding: 16px 18px; width: min(520px, 92vw);
       box-shadow: 0 12px 40px rgba(0, 0, 0, .25); }
</style>

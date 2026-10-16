<script setup lang="ts">
/** D90 Playground —— 单次调用大模型做试验（无多轮上下文）。
 *  提问（文本 + 图片/文档附件）+ provider/模型选择 → 一次调用 → 呈现回复；
 *  支持批量发送；问题/答案本地留档（<ws>/playground/records/）+ 文件夹管理/勾选查看/移动/删除。
 *  与 D86 provider/key 安全同口径（key 只在引擎侧，绝不下发/入日志）。 */
import { computed, onMounted, ref, watch } from 'vue'
import {
  fetchLlmConfig, fetchPlaygroundRecords, mutatePlaygroundFolder, mutatePlaygroundRecord,
  playgroundAsk, playgroundBatch, postLlmProvider, uploadPlaygroundAttachment, type PlaygroundRecord,
} from '../lib/engineClient'

const props = defineProps<{ engineAddr: string; token?: string }>()

/* ---------- provider / 模型选择（D90 明确要求） ---------- */
const providers = ref<Array<{ name: string; models?: string[]; has_key?: boolean }>>([])
const provider = ref('')          // '' = 用 D86 评阅段配置
const model = ref('')             // 选中的模型名（或自定义输入）
const customModel = ref(false)    // 是否切到"自定义输入"
const temperature = ref<number | null>(null)
const modelsOfProvider = computed(() =>
  (providers.value.find((p) => p.name === provider.value)?.models || []))

async function loadProviders() {
  try {
    const cfg = await fetchLlmConfig(props.engineAddr, props.token)
    providers.value = (cfg?.providers || []) as any[]
  } catch { providers.value = [] }
}
/** 有候选模型才用下拉；否则提示去 ① 记录，或直接自定义输入。 */
const hasModelChoices = computed(() => modelsOfProvider.value.length > 0)

/** D91-M3：把当前模型名记录为 provider 的候选（写 models[]，与 ① 区"填写即记录"同源）。 */
async function rememberModel() {
  const name = model.value.trim()
  if (!provider.value) { msg.value = '请先选 provider（评阅段配置无法记录候选）'; return }
  if (!name) { msg.value = '请先填/选一个模型名'; return }
  const r = await postLlmProvider(props.engineAddr, props.token,
    { action: 'set', name: provider.value, model: name })
  if (r?.ok) { await loadProviders(); msg.value = `已记录候选模型「${name}」到 provider「${provider.value}」` }
  else msg.value = r?.error || '记录失败'
}
async function forgetModel(name: string) {
  if (!provider.value || !name) return
  const r = await postLlmProvider(props.engineAddr, props.token,
    { action: 'set', name: provider.value, forget_model: name })
  if (r?.ok) {
    if (model.value === name) model.value = ''
    await loadProviders()
    msg.value = `已从 provider「${provider.value}」删除候选「${name}」`
  } else msg.value = r?.error || '删除失败'
}

/* ---------- 提问 ---------- */
const question = ref('')
const attachments = ref<Array<{ name: string; path: string; kind: string }>>([])
const busy = ref(false)
const answer = ref('')
const lastModel = ref('')
const msg = ref('')
const batchMode = ref(false)
const batchText = ref('')          // 每行一个问题
const folder = ref('默认')

function onPickFiles(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  uploadFiles(files)
  input.value = ''
}
async function uploadFiles(files: File[]) {
  for (const f of files) {
    const dataUrl = await readAsDataURL(f)
    try {
      const r = await uploadPlaygroundAttachment(props.engineAddr, props.token, { name: f.name, data: dataUrl })
      if (r?.ok && r.path) attachments.value.push({ name: r.name || f.name, path: r.path, kind: r.kind || '' })
      else msg.value = r?.error || `上传失败：${f.name}`
    } catch {
      // 引擎离线：退化为仅文件名（引擎会提示附件不存在）——不阻塞提问
      attachments.value.push({ name: f.name, path: '', kind: '（未上传：引擎离线）' })
    }
  }
}
function readAsDataURL(f: File): Promise<string> {
  return new Promise((resolve) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => resolve('')
    reader.readAsDataURL(f)
  })
}
function removeAttachment(i: number) { attachments.value.splice(i, 1) }

async function doAsk() {
  if (busy.value) return
  if (!question.value.trim() && !attachments.value.length) { msg.value = '请输入问题或添加附件'; return }
  busy.value = true; msg.value = '正在调用大模型……'; answer.value = ''
  try {
    const r = await playgroundAsk(props.engineAddr, props.token, {
      question: question.value, attachments: attachments.value.map((a) => a.path).filter(Boolean),
      provider: provider.value, model: model.value, temperature: temperature.value, folder: folder.value,
    })
    if (r?.ok) { answer.value = r.answer || ''; lastModel.value = r.model || ''; msg.value = '完成（已留档）' }
    else msg.value = r?.error || '调用失败'
  } catch (e) { msg.value = String((e as Error).message || e) }
  finally { busy.value = false; loadRecords() }
}

async function doBatch() {
  if (busy.value) return
  const qs = batchText.value.split('\n').map((x) => x.trim()).filter(Boolean)
  if (!qs.length) { msg.value = '请每行填一个问题'; return }
  busy.value = true; msg.value = `批量发送 ${qs.length} 条……`; answer.value = ''
  try {
    const r = await playgroundBatch(props.engineAddr, props.token, {
      questions: qs, attachments: attachments.value.map((a) => a.path).filter(Boolean),
      provider: provider.value, model: model.value, folder: folder.value,
    })
    if (r?.ok) {
      answer.value = (r.results || []).map((x, i) =>
        `### 第 ${i + 1} 问\n\n${x.question}\n\n${x.ok ? x.answer : '（失败：' + (x.error || '') + '）'}`).join('\n\n---\n\n')
      msg.value = `完成：成功 ${r.succeeded}/${r.total}（已留档）`
    } else msg.value = r?.error || '批量失败'
  } catch (e) { msg.value = String((e as Error).message || e) }
  finally { busy.value = false; loadRecords() }
}

/* ---------- 记录管理 ---------- */
const records = ref<PlaygroundRecord[]>([])
const folders = ref<string[]>(['默认'])
const selected = ref<string[]>([])
const expanded = ref('')           // 展开查看的记录 id
const newFolder = ref('')

async function loadRecords() {
  try {
    const r = await fetchPlaygroundRecords(props.engineAddr, props.token)
    records.value = r?.records || []
    folders.value = r?.folders || ['默认']
  } catch { /* 引擎离线：保留现状 */ }
}
const grouped = computed(() => {
  const g: Record<string, PlaygroundRecord[]> = {}
  for (const f of folders.value) g[f] = []
  for (const rec of records.value) {
    const f = rec.folder && folders.value.includes(rec.folder) ? rec.folder : folders.value[0]
    ;(g[f] = g[f] || []).push(rec)
  }
  return g
})
function toggleSelect(id: string) {
  const i = selected.value.indexOf(id)
  if (i >= 0) selected.value.splice(i, 1); else selected.value.push(id)
}
async function delOne(id: string) {
  await mutatePlaygroundRecord(props.engineAddr, props.token, { action: 'delete', id })
  selected.value = selected.value.filter((x) => x !== id)
  await loadRecords()
}
async function delSelected() {
  for (const id of [...selected.value]) {
    await mutatePlaygroundRecord(props.engineAddr, props.token, { action: 'delete', id })
  }
  selected.value = []; await loadRecords()
}
async function moveSelected(target: string) {
  if (!selected.value.length) return
  await mutatePlaygroundRecord(props.engineAddr, props.token, { action: 'move', ids: selected.value, folder: target })
  selected.value = []; await loadRecords()
}
async function addFolder() {
  if (!newFolder.value.trim()) return
  await mutatePlaygroundFolder(props.engineAddr, props.token, { action: 'new', name: newFolder.value.trim() })
  newFolder.value = ''; await loadRecords()
}
async function delFolder(name: string) {
  await mutatePlaygroundFolder(props.engineAddr, props.token, { action: 'delete', name })
  await loadRecords()
}

/* ---------- 回复渲染（沙箱 iframe + 自托管 KaTeX，离线可渲染） ---------- */
const answerHtml = computed(() => {
  // 用沙箱 iframe + 自托管 KaTeX auto-render（离线可渲染）；纯文本安全回填。
  // 注意：拼接 '</scr'+'ipt>' 避免 SFC 的 <script> 被提前闭合。
  const ST = '<' + 'script'
  const SE = '</scr' + 'ipt>'
  // KaTeX auto-render 初始化（纯字符串，避免污染被转译的函数；delimiters 覆盖 $$ $ \( \) \[ \]）
  const katexInit =
    'var el=document.getElementById("c");' +
    'if(el&&window.renderMathInElement){try{renderMathInElement(el,{delimiters:[' +
    '{left:"$$",right:"$$",display:true},{left:"$",right:"$",display:false},' +
    '{left:"\\(",right:"\\)",display:false},{left:"\\[",right:"\\]",display:true}' +
    ']})}catch(e){}}'
  return [
    '<!doctype html><html><head><meta charset="utf-8">',
    '<link rel="stylesheet" href="./katex/katex.min.css">',
    '<style>body{font-family:system-ui,sans-serif;font-size:14px;line-height:1.7;padding:12px;color:#1f2937}',
    'h3{margin:.6em 0 .3em}pre{background:#f5f6f8;padding:8px;border-radius:6px;overflow:auto}',
    'code{background:#f0f1f3;padding:1px 4px;border-radius:3px}</style></head><body>',
    '<div id="c"></div>',
    ST + '>window.__ans=' + JSON.stringify(answer.value || '') + ';document.getElementById("c").textContent=window.__ans;' + SE,
    ST + ' src="./katex/katex.min.js">' + SE,
    ST + ' src="./katex/contrib/auto-render.min.js">' + SE,
    ST + '>' + katexInit + SE,
    '</body></html>',
  ].join('')
})

/* ---------- D91-M4：输入草稿自动保存（localStorage；刷新不丢，可清空） ---------- */
const DRAFT_KEY = 'assignment-assistant.playground.draft.v1'
function saveDraft() {
  try {
    localStorage.setItem(DRAFT_KEY, JSON.stringify({
      provider: provider.value, model: model.value, customModel: customModel.value,
      temperature: temperature.value, folder: folder.value, batchMode: batchMode.value,
      question: question.value, batchText: batchText.value, attachments: attachments.value,
    }))
  } catch { /* 容量/隐私降级 */ }
}
function loadDraft() {
  try {
    const d = JSON.parse(localStorage.getItem(DRAFT_KEY) ?? 'null')
    if (!d || typeof d !== 'object') return
    provider.value = String(d.provider ?? '')
    model.value = String(d.model ?? '')
    customModel.value = !!d.customModel
    temperature.value = d.temperature ?? null
    folder.value = String(d.folder ?? '默认')
    batchMode.value = !!d.batchMode
    question.value = String(d.question ?? '')
    batchText.value = String(d.batchText ?? '')
    attachments.value = Array.isArray(d.attachments) ? d.attachments : []
  } catch { /* ignore */ }
}
function clearDraft() {
  question.value = ''; batchText.value = ''; attachments.value = []
  try { localStorage.removeItem(DRAFT_KEY) } catch { /* ignore */ }
  msg.value = '已清空草稿'
}
// 任一输入变化即存（自动保存）
watch([provider, model, customModel, temperature, folder, batchMode, question, batchText, attachments],
      saveDraft, { deep: true })

onMounted(() => { loadProviders(); loadRecords(); loadDraft() })
</script>

<template>
  <div>
    <h3 style="margin-top:14px">⑧ Playground（单次调用大模型 · 无多轮上下文）</h3>
    <p class="hint" style="margin:0 0 6px">
      提问（文本 + 图片/文档附件）→ 一次调用 → 呈现回复；支持批量；问题与答案**本地留档**（<code>&lt;ws&gt;/playground/</code>）。
      文档支持 pdf/docx/txt（旧版 .doc 请转 docx/pdf）。输入内容**自动保存到本浏览器**（刷新不丢）。
    </p>

    <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:6px">
      <span class="hint" style="margin:0">provider：</span>
      <select v-model="provider" style="min-width:160px">
        <option value="">（评阅段配置）</option>
        <option v-for="p in providers" :key="p.name" :value="p.name">
          {{ p.name }}{{ p.has_key ? '' : '（无 key）' }}
        </option>
      </select>
      <span class="hint" style="margin:0">模型：</span>
      <template v-if="hasModelChoices && !customModel">
        <select v-model="model" style="min-width:160px">
          <option value="">（默认）</option>
          <option v-for="m in modelsOfProvider" :key="m" :value="m">{{ m }}</option>
        </select>
        <button class="btn small" title="删除该候选模型" v-if="model" @click="forgetModel(model)">✕</button>
      </template>
      <input v-else v-model="model" placeholder="模型名（空=默认）" style="width:180px" />
      <button class="btn small" @click="customModel = !customModel"
              :title="hasModelChoices ? '切换到自定义输入/下拉' : '该 provider 暂无候选：填模型名后可记录'">
        {{ customModel ? '用下拉' : '自定义' }}
      </button>
      <button class="btn small" title="把当前模型名记录为候选（下次可下拉选）" @click="rememberModel">＋记录候选</button>
      <label class="field">temperature：<input type="number" step="0.1" min="0" max="2" v-model.number="temperature" style="width:64px" /></label>
      <span class="hint" style="margin:0">归入文件夹：</span>
      <select v-model="folder" style="min-width:120px">
        <option v-for="f in folders" :key="f" :value="f">{{ f }}</option>
      </select>
    </div>

    <div style="display:flex; gap:8px; align-items:flex-start; flex-wrap:wrap">
      <div style="flex:1 1 360px; min-width:320px">
        <label class="field"><input type="checkbox" v-model="batchMode" /> 批量模式（每行一个问题）</label>
        <textarea v-if="!batchMode" v-model="question" rows="4" placeholder="输入问题（支持 LaTeX，如 $E=mc^2$）"
                  style="width:100%; font-family:inherit"></textarea>
        <textarea v-else v-model="batchText" rows="6" placeholder="每行一个问题"
                  style="width:100%; font-family:inherit"></textarea>
        <p style="margin:6px 0; display:flex; gap:8px; align-items:center; flex-wrap:wrap">
          <label class="btn small as-label" for="pg-file">＋ 添加附件（图片/pdf/docx/txt）</label>
          <input id="pg-file" type="file" multiple hidden @change="onPickFiles" />
          <button v-if="!batchMode" class="btn primary" :disabled="busy" @click="doAsk">▶ 提问</button>
          <button v-else class="btn primary" :disabled="busy" @click="doBatch">▶ 批量发送</button>
          <button class="btn small" title="清空输入草稿（提问/批量/附件）" @click="clearDraft">清空草稿</button>
          <span class="hint" style="margin:0" v-if="lastModel">模型：{{ lastModel }}</span>
        </p>
        <p class="hint" style="margin:0" v-for="(a, i) in attachments" :key="i">
          附件：{{ a.name }} <span class="hint">({{ a.kind }})</span>
          <button class="btn small" style="margin-left:6px" @click="removeAttachment(i)">移除</button>
        </p>
        <p class="hint" v-if="msg">{{ msg }}</p>
      </div>
      <div style="flex:1 1 360px; min-width:320px">
        <p class="hint" style="margin:0 0 4px">回复：</p>
        <iframe :srcdoc="answerHtml" title="模型回复" style="width:100%; height:340px; border:1px solid var(--c-border); border-radius:8px; background:#fff"></iframe>
      </div>
    </div>

    <h4 style="margin:16px 0 6px">记录管理（本地留档）</h4>
    <p style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin:0 0 6px">
      <input v-model="newFolder" placeholder="新建文件夹名" style="width:150px" />
      <button class="btn small" @click="addFolder">新建文件夹</button>
      <span class="hint" style="margin:0">已选 {{ selected.length }} 条：</span>
      <select @change="moveSelected(($event.target as HTMLSelectElement).value || folders[0])" :disabled="!selected.length">
        <option value="">移动到…</option>
        <option v-for="f in folders" :key="f" :value="f">{{ f }}</option>
      </select>
      <button class="btn small" :disabled="!selected.length" @click="delSelected">删除所选</button>
      <span style="flex:1"></span>
      <button class="btn small" @click="loadRecords">刷新</button>
    </p>

    <div v-for="f in folders" :key="f" style="margin-bottom:8px">
      <div style="display:flex; align-items:center; gap:8px">
        <b>📁 {{ f }}</b>
        <span class="hint" style="margin:0">（{{ (grouped[f] || []).length }} 条）</span>
        <button v-if="folders.length > 1 && f !== folders[0]" class="btn small" @click="delFolder(f)">删除文件夹</button>
      </div>
      <table v-if="(grouped[f] || []).length" class="grid" style="font-size:12px; width:100%">
        <thead><tr><th style="width:28px"></th><th>时间</th><th>provider/模型</th><th>问题</th><th style="width:120px">操作</th></tr></thead>
        <tbody>
          <template v-for="rec in grouped[f]" :key="rec.id">
            <tr>
              <td><input type="checkbox" :checked="selected.includes(rec.id)" @change="toggleSelect(rec.id)" /></td>
              <td style="white-space:nowrap">{{ rec.at }}</td>
              <td style="white-space:nowrap">{{ rec.provider }} / {{ rec.model || '—' }}</td>
              <td style="max-width:360px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap" :title="rec.question">{{ rec.question }}</td>
              <td style="white-space:nowrap">
                <button class="btn small" @click="expanded = expanded === rec.id ? '' : rec.id">
                  {{ expanded === rec.id ? '收起' : '查看' }}</button>
                <button class="btn small" style="margin-left:4px" @click="delOne(rec.id)">删除</button>
              </td>
            </tr>
            <tr v-if="expanded === rec.id">
              <td></td>
              <td colspan="4">
                <div style="border:1px solid var(--c-border); border-radius:6px; padding:6px; white-space:pre-wrap">
                  <div><b>问：</b>{{ rec.question }}</div>
                  <div v-if="(rec.attachments || []).length" class="hint">附件：{{ (rec.attachments || []).join('、') }}</div>
                  <div style="margin-top:6px"><b>答：</b>{{ rec.answer || '（无）' }}</div>
                  <div v-if="rec.error" style="color:#b91c1c">错误：{{ rec.error }}</div>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
      <p v-else class="hint" style="margin:2px 0 0">（空）</p>
    </div>
  </div>
</template>

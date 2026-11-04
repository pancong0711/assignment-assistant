<script setup lang="ts">
/** D140：Atopia 独立选项卡 —— 让 AI 用本项目工具的**唯一**入口。
 *
 *  分工（docs/89 §1）：
 *   - Playground = 单次调用测模型（**不给工具**，避免绕过 Gate 的旁路）；
 *   - Atopia    = 多轮对话 + 调工具，每一次调用都过 Gate
 *                 （L3 拒绝 / L2 教师逐次确认 / 审计 / 护栏）。
 */
import { computed, onMounted, ref } from 'vue'
import { useSettingsStore } from '../stores/settings'
import AtopiaPanel from '../components/AtopiaPanel.vue'
import {
  askAtopia, fetchAtopiaSessions, fetchAtopiaWork, fetchLlmConfig, uploadAtopiaWork,
  type AtopiaAskResult, type AtopiaStep, type LlmProvider,
} from '../lib/engineClient'

const settings = useSettingsStore()
const tab = ref<'chat' | 'tools' | 'work'>('chat')

/* ---------- D146：provider / 模型选择 ----------
   与 Playground 同源（/llm/config）；空值 = 沿用「评阅段」配置。
   选择记在 localStorage，下次打开沿用。 */
const LS_PROV = 'atopia.provider'
const LS_MODEL = 'atopia.model'
const providers = ref<LlmProvider[]>([])
const provider = ref(localStorage.getItem(LS_PROV) || '')
const model = ref(localStorage.getItem(LS_MODEL) || '')
const customModel = ref(false)

const modelsOfProvider = computed(() => {
  const p = providers.value.find((x) => x.name === provider.value)
  return (p?.models || []) as string[]
})
const hasModelChoices = computed(() => modelsOfProvider.value.length > 0)

function onProviderChange() {
  localStorage.setItem(LS_PROV, provider.value)
  // 换 provider → 旧模型名多半不适用，清空回落到该 provider 默认
  model.value = ''
  localStorage.setItem(LS_MODEL, '')
  customModel.value = false
  // 会话中途换 provider 会让上下文/缓存错位 → 明确新建会话
  if (msgs.value.length) {
    newSession()
    errMsg.value = '已切换 provider：为保证上下文与缓存正确，已开始新会话。'
  }
}

function onModelChange() {
  localStorage.setItem(LS_MODEL, model.value)
}

async function loadProviders() {
  try {
    const r = await fetchLlmConfig(settings.engineUrl, settings.engineToken)
    providers.value = r?.providers || []
  } catch { providers.value = [] }
}

/* ---------- 对话 ---------- */
interface Msg {
  role: 'user' | 'ai' | 'tool' | 'err'
  text: string
  steps?: AtopiaStep[]
  protocol?: string
  degraded?: boolean
}
const msgs = ref<Msg[]>([])
const input = ref('')
const busy = ref(false)
const sessionId = ref('')
const errMsg = ref('')
const pending = ref<{ tool?: string; args?: Record<string, any>; reason?: string } | null>(null)
/* D147：正在确认的那一次调用（工具+参数）——随请求回传，后端只放行与之一致的调用 */
const confirming = ref<{ tool: string; args: Record<string, any> } | null>(null)
const showSteps = ref(true)

function newSession() {
  sessionId.value = `chat-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
  msgs.value = []
  errMsg.value = ''
  pending.value = null
}

async function send(confirmed = false) {
  const task = input.value.trim()
  if (!task || busy.value) return
  if (!sessionId.value) newSession()
  busy.value = true
  errMsg.value = ''
  if (!confirmed) {
    msgs.value.push({ role: 'user', text: task })
    input.value = ''
  }
  try {
    const r: AtopiaAskResult = await askAtopia(settings.engineUrl, settings.engineToken, {
      task: confirmed
        ? `${task}（教师已确认执行写入操作）`
        : task,
      sessionId: sessionId.value,
      confirmed,
      confirmedBy: confirmed ? 'teacher:pwa' : undefined,
      confirmedTool: confirmed ? confirming.value?.tool : undefined,
      confirmedArgs: confirmed ? confirming.value?.args : undefined,
      provider: provider.value || undefined,
      model: model.value || undefined,
    })
    if (r?.sessionId) sessionId.value = r.sessionId
    if (r?.pendingConfirm) {
      // L2：**不自动执行**，弹窗让教师看清工具名与参数
      pending.value = r.pendingConfirm
      msgs.value.push({
        role: 'ai',
        text: `要我调用写入工具「${r.pendingConfirm.tool}」，需要你确认。`,
        steps: r.steps, protocol: r.protocol, degraded: r.degraded,
      })
      return
    }
    if (!r?.ok) {
      msgs.value.push({ role: 'err', text: r?.error || '执行失败', steps: r?.steps })
      return
    }
    msgs.value.push({
      role: 'ai', text: r.answer || '（没有文字回答）',
      steps: r.steps, protocol: r.protocol, degraded: r.degraded,
    })
  } catch (e) {
    errMsg.value = String((e as Error).message || e)
  } finally {
    busy.value = false
    if (confirmed) confirming.value = null
  }
}

async function confirmPending() {
  const p = pending.value
  pending.value = null
  if (!p) return
  // D147：记下"教师确认的正是这个工具与参数"
  confirming.value = { tool: String(p.tool || ''), args: (p.args || {}) as Record<string, any> }
  // 教师确认后**重发原始任务**（同一 task 文本），并标记 confirmed
  const last = [...msgs.value].reverse().find((m) => m.role === 'user')
  if (!last) return
  input.value = last.text
  await send(true)
}

/* ---------- D164：工作区（上传 → 解析 → 复制到课堂资料） ---------- */
const workFeatures = ref<string[]>([])
const workFeature = ref('')
const newFeature = ref('')
const workFiles = ref<{ file: string; name: string; dir: string; bytes: number
                        mtime: string }[]>([])
const workText = ref('')
const workBusy = ref(false)
const workMsg = ref('')
const workInput = ref<HTMLInputElement | null>(null)

async function loadWork() {
  try {
    const r = await fetchAtopiaWork(settings.engineUrl, settings.engineToken)
    workFeatures.value = r?.features || []
    if (!workFeature.value && workFeatures.value.length) workFeature.value = workFeatures.value[0]!
    if (workFeature.value) await loadWorkDetail()
  } catch { workFeatures.value = [] }
}

async function loadWorkDetail() {
  if (!workFeature.value) return
  try {
    const r = await fetchAtopiaWork(settings.engineUrl, settings.engineToken, workFeature.value)
    workFiles.value = r?.files || []
    workText.value = String(r?.text?.text || '')
  } catch { workFiles.value = []; workText.value = '' }
}

function pickWorkFiles() { workInput.value?.click() }

function readB64(f: File): Promise<string> {
  return new Promise((res, rej) => {
    const fr = new FileReader()
    fr.onerror = () => rej(new Error('读取失败'))
    fr.onload = () => {
      const s = String(fr.result || '')
      res(s.includes(',') ? s.slice(s.indexOf(',') + 1) : s)
    }
    fr.readAsDataURL(f)
  })
}

async function onWorkFiles(ev: Event) {
  const input = ev.target as HTMLInputElement
  const list = Array.from(input.files || [])
  input.value = ''
  if (!list.length) return
  if (!workFeature.value) { workMsg.value = '请先填写/选择特征名'; return }
  workBusy.value = true; workMsg.value = ''
  try {
    const items = []
    for (const f of list) items.push({ name: f.name, data_b64: await readB64(f) })
    const r = await uploadAtopiaWork(settings.engineUrl, settings.engineToken,
                                     workFeature.value, items)
    if (!r?.ok) { workMsg.value = `❌ ${r?.error || '上传失败'}`; return }
    const skipped = (r.skipped || []).map((x: any) => `${x.name}（${x.reason}）`)
    workMsg.value = `✅ 已上传 ${(r.saved || []).length} 个`
      + (skipped.length ? `；跳过：${skipped.join('、')}` : '')
    await loadWork(); await loadWorkDetail()
  } catch (e) {
    workMsg.value = `上传失败：${String((e as Error).message || e)}`
  } finally { workBusy.value = false }
}

async function createWorkFeature() {
  const name = newFeature.value.trim()
  if (!name) return
  workFeature.value = name
  newFeature.value = ''
  await loadWork()
}

/* ---------- 会话历史 ---------- */
const sessions = ref<{ id: string; turns: number; mtime: string }[]>([])
const history = ref<any[]>([])
async function loadSessions() {
  try {
    const r = await fetchAtopiaSessions(settings.engineUrl, settings.engineToken)
    sessions.value = r?.sessions || []
  } catch { sessions.value = [] }
}
async function openSession(id: string) {
  try {
    const r = await fetchAtopiaSessions(settings.engineUrl, settings.engineToken, id)
    history.value = r?.records || []
  } catch { history.value = [] }
}

onMounted(() => { newSession(); loadSessions(); loadProviders(); loadWork() })

const canSend = computed(() => Boolean(input.value.trim()) && !busy.value)
</script>

<template>
  <div class="wrap">
    <h2 style="margin:0 0 4px">Atopia（AI 用本项目工具）</h2>
    <p class="hint" style="margin:0 0 8px">
      <b>唯一</b>让 AI 调用本项目工具的入口：每次调用都过安全 Gate
      （L3 拒绝 · L2 必须你确认 · 全程审计 · 护栏限次）。
      只想"测模型通不通"请用 <b>Playground</b>（那里不给工具）。
    </p>

    <div class="tabs2">
      <button class="btn" :class="{ primary: tab === 'chat' }" @click="tab = 'chat'">
        💬 对话
      </button>
      <button class="btn" :class="{ primary: tab === 'tools' }" @click="tab = 'tools'">
        🧰 单一工具执行
      </button>
      <button class="btn" :class="{ primary: tab === 'work' }" @click="tab = 'work'; loadWork()">
        📁 工作区（上传/解析）
      </button>
      <span style="flex:1"></span>
      <label class="hint" v-if="tab === 'chat'">
        <input v-model="showSteps" type="checkbox" /> 显示工具调用细节
      </label>
      <button class="btn" v-if="tab === 'chat'" @click="newSession">新会话</button>
    </div>

    <!-- ============ 对话 ============ -->
    <template v-if="tab === 'chat'">
      <div class="picker">
        <span class="hint" style="margin:0">provider：</span>
        <select :value="provider" @change="onProviderChange">
          <option value="">（评阅段配置）</option>
          <option v-for="p in providers" :key="p.name" :value="p.name">
            {{ p.name }}{{ p.has_key ? '' : '（无 key）' }}
          </option>
        </select>
        <span class="hint" style="margin:0">模型：</span>
        <template v-if="hasModelChoices && !customModel">
          <select :value="model" @change="model = ($event.target as HTMLSelectElement).value; onModelChange()">
            <option value="">（默认）</option>
            <option v-for="m in modelsOfProvider" :key="m" :value="m">{{ m }}</option>
          </select>
        </template>
        <input v-else :value="model" placeholder="模型名（空=默认）" style="width:170px"
               @change="model = ($event.target as HTMLInputElement).value; onModelChange()" />
        <button class="btn small" @click="customModel = !customModel"
                :title="hasModelChoices ? '切换下拉/自定义输入' : '该 provider 暂无候选模型'">
          {{ customModel ? '用下拉' : '自定义' }}
        </button>
        <span v-if="provider" class="hint" style="margin:0">
          （该 provider 的请求头/鉴权生效）
        </span>
      </div>

      <div class="chat">
        <p v-if="!msgs.length" class="hint">
          例：「看看题库里 chap04 有多少题」「把 chap04 的知识点建议抽出来」
          「列出课堂资料里有哪些文件」。写入类操作会弹窗让你确认。
        </p>
        <div v-for="(m, i) in msgs" :key="i" class="msg" :class="m.role">
          <div class="who">
            {{ m.role === 'user' ? '你' : m.role === 'ai' ? 'Atopia' : '⚠️ 错误' }}
            <span v-if="m.protocol" class="hint">
              （{{ m.protocol }}{{ m.degraded ? ' · 已降级' : '' }}）
            </span>
          </div>
          <div class="bubble">{{ m.text }}</div>
          <details v-if="showSteps && (m.steps || []).length" class="steps">
            <summary class="hint" style="cursor:pointer">
              工具调用 {{ (m.steps || []).filter((s) => s.action === 'tool').length }} 次
            </summary>
            <ul>
              <li v-for="(s, k) in (m.steps || [])" :key="k">
                <template v-if="s.action === 'tool'">
                  <b>{{ s.tool }}</b>
                  <span class="hint">{{ JSON.stringify(s.args || {}) }}</span>
                  <b :style="{ color: s.ok ? '#16a34a' : '#dc2626' }">
                    {{ s.ok ? '✓' : '✗' }}{{ s.denied ? ' 已拒绝' : '' }}
                  </b>
                  <pre v-if="s.out || s.err" class="out">{{ (s.out || s.err || '').slice(0, 400) }}</pre>
                </template>
                <span v-else class="hint">{{ s.action }}</span>
              </li>
            </ul>
          </details>
        </div>
        <p v-if="busy" class="hint">Atopia 正在工作…（可能在调用工具）</p>
        <p v-if="errMsg" class="err">{{ errMsg }}</p>
      </div>

      <div class="composer">
        <textarea v-model="input" rows="2" placeholder="告诉 Atopia 你要做什么（Enter 发送，Shift+Enter 换行）"
                  @keydown.enter.exact.prevent="send(false)"></textarea>
        <button class="btn primary" :disabled="!canSend" @click="send(false)">
          {{ busy ? '执行中…' : '发送' }}
        </button>
      </div>

      <!-- L2 确认弹窗 -->
      <div v-if="pending" class="mask">
        <div class="dlg">
          <h3 style="margin:0 0 8px">确认让 Atopia 执行这个写入操作？</h3>
          <p class="hint" style="margin:0 0 6px">
            工具：<code>{{ pending.tool }}</code>（L2 写入，会修改工作区数据）
          </p>
          <pre class="out">{{ JSON.stringify(pending.args || {}, null, 1) }}</pre>
          <p class="hint" style="margin:0 0 8px">{{ pending.reason || '' }}</p>
          <div style="display:flex; gap:8px; justify-content:flex-end">
            <button class="btn" @click="pending = null">拒绝</button>
            <button class="btn primary" @click="confirmPending">我确认执行</button>
          </div>
        </div>
      </div>

      <details style="margin-top:12px" @toggle="loadSessions">
        <summary class="hint" style="cursor:pointer">会话历史（{{ sessions.length }}）</summary>
        <p v-if="!sessions.length" class="hint">（还没有会话记录。）</p>
        <ul v-else class="sess">
          <li v-for="s in sessions.slice(0, 20)" :key="s.id">
            <a href="javascript:;" @click="openSession(s.id)">
              <code>{{ s.id }}</code>
            </a>
            <span class="hint">{{ s.mtime }} · {{ s.turns }} 轮</span>
          </li>
        </ul>
        <pre v-if="history.length" class="out">{{ JSON.stringify(history, null, 1).slice(0, 3000) }}</pre>
      </details>
    </template>

    <!-- ============ D164：工作区 ============ -->
    <template v-else-if="tab === 'work'">
      <div class="work">
        <p class="hint" style="margin:0 0 6px">
          这里放你交给 Atopia 的<b>授课计划 / PPT</b>（落在
          <code>atopia/work/&lt;特征名&gt;/_upload/</code>，与课堂资料的
          <code>materials/_source/</code> <b>物理隔离</b>）。
          解析出的知识点可到「课堂资料」点<b>「📥 从 Atopia 复制」</b>确认后写入。
        </p>
        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin:6px 0">
          <label class="field">特征名
            <input v-model="workFeature" placeholder="如 26C1" style="width:120px"
                   @change="loadWorkDetail" />
          </label>
          <label class="field">或新建
            <input v-model="newFeature" placeholder="26C2" style="width:100px"
                   @keydown.enter="createWorkFeature" />
          </label>
          <button class="btn" :disabled="workBusy" @click="createWorkFeature">＋ 新建</button>
          <button class="btn primary" :disabled="workBusy" @click="pickWorkFiles">
            {{ workBusy ? '上传中…' : '⬆️ 上传文件' }}
          </button>
          <input ref="workInput" type="file" multiple style="display:none"
                 accept=".pptx,.ppt,.pdf,.docx,.doc,.png,.jpg,.jpeg,.md,.txt,.markdown"
                 @change="onWorkFiles" />
          <button class="btn" @click="loadWork">刷新</button>
          <span v-if="workMsg" class="hint" style="margin:0">{{ workMsg }}</span>
        </div>
        <p v-if="!workFiles.length" class="hint">（该特征名下还没有文件。）</p>
        <table v-else class="tbl">
          <thead><tr><th>文件</th><th>大小</th><th>位置</th><th>时间</th></tr></thead>
          <tbody>
            <tr v-for="f in workFiles" :key="f.file">
              <td>{{ f.name }}</td>
              <td class="c">{{ Math.round(f.bytes / 1024) }} KB</td>
              <td class="c">{{ f.dir === '_upload' ? '待解析' : '已解析' }}</td>
              <td class="c">{{ f.mtime }}</td>
            </tr>
          </tbody>
        </table>
        <details v-if="workText" style="margin-top:8px">
          <summary class="hint" style="cursor:pointer">查看可解析文本（md/txt）</summary>
          <pre class="md">{{ workText.slice(0, 3000) }}</pre>
        </details>
      </div>
    </template>

    <!-- ============ 单一工具执行（原面板） ============ -->
    <AtopiaPanel v-else :engine-addr="settings.engineUrl" :token="settings.engineToken" />
  </div>
</template>

<style scoped>
.wrap { padding: 12px 14px; }
.hint { color: #6b7280; font-size: 12px; }
.err { color: #b91c1c; font-size: 13px; }
.picker { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin: 0 0 8px;
          font-size: 13px; }
.picker select, .picker input { font-size: 13px; padding: 2px 6px; border: 1px solid #d1d5db;
                                border-radius: 6px; }
.tabs2 { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 8px 0; }
.chat { border: 1px solid #e5e7eb; border-radius: 10px; padding: 10px 12px;
        max-height: 52vh; overflow: auto; background: #fff; }
.msg { margin-bottom: 10px; }
.msg .who { font-size: 12px; color: #6b7280; margin-bottom: 2px; }
.bubble { white-space: pre-wrap; background: #f9fafb; border: 1px solid #e5e7eb;
          border-radius: 8px; padding: 6px 10px; font-size: 13px; }
.msg.user .bubble { background: #eff6ff; border-color: #bfdbfe; }
.msg.err .bubble { background: #fef2f2; border-color: #fecaca; color: #991b1b; }
.steps { margin-top: 4px; }
.steps ul { margin: 4px 0 0 18px; padding: 0; font-size: 12px; }
.out { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px; padding: 6px;
       font-size: 11px; white-space: pre-wrap; max-height: 160px; overflow: auto; }
.composer { display: flex; gap: 8px; margin-top: 8px; align-items: flex-end; }
.composer textarea { flex: 1; font-family: inherit; font-size: 13px; padding: 6px 8px;
                     border: 1px solid #d1d5db; border-radius: 8px; resize: vertical; }
.mask { position: fixed; inset: 0; background: rgba(15, 23, 42, .45); z-index: 60;
        display: flex; align-items: center; justify-content: center; }
.dlg { background: #fff; border-radius: 10px; padding: 16px 18px; width: min(560px, 92vw);
       box-shadow: 0 12px 40px rgba(0, 0, 0, .25); }
.sess { margin: 4px 0 0 16px; padding: 0; font-size: 12px; }
.work { border: 1px solid #e5e7eb; border-radius: 10px; padding: 10px 12px; }
.tbl { border-collapse: collapse; font-size: 13px; width: 100%; }
.tbl th, .tbl td { border: 1px solid #e5e7eb; padding: 4px 8px; }
.tbl th { background: #f9fafb; }
.tbl td.c { text-align: center; }
.md { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px; padding: 8px;
      font-size: 12px; max-height: 260px; overflow: auto; white-space: pre-wrap; }
</style>

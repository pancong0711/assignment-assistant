<script setup lang="ts">
/** D132：Atopia 工作区 —— AI 调用本项目工具的**受控**入口。
 *
 *  安全口径（docs/81）：L0/L1 直接执行；**L2 必须教师点击确认**；L3 不开放（连按钮都不给）。
 *  每次调用都在引擎侧写 journal（含 confirmed_by），本页只负责"看清楚 + 确认"。
 */
import { computed, onMounted, ref } from 'vue'
import {
  fetchAtopiaJournal, fetchAtopiaTools, postAtopiaLimits, runAtopiaTool,
  type AtopiaTool,
} from '../lib/engineClient'

const props = defineProps<{ engineAddr: string; token?: string }>()

const tools = ref<AtopiaTool[]>([])
const levels = ref<Record<string, string>>({})
const limits = ref<Record<string, number>>({})
const hardCaps = ref<Record<string, number>>({})
/* D137：护栏可编辑（受硬顶约束；保存前二次确认） */
const limDraft = ref<Record<string, number>>({})
const pendingLimits = ref<Record<string, number> | null>(null)
const limMsg = ref('')
const journal = ref<any[]>([])
const msg = ref('')
const busy = ref(false)

const selected = ref('')
const argsText = ref('{}')
const pending = ref<{ tool: AtopiaTool; args: Record<string, any> } | null>(null)
const output = ref('')

/** L3 不展示为"可执行"——只在末尾列出并明确写"不开放"。 */
const usable = computed(() => tools.value.filter((t) => t.level !== 'L3'))
const denied = computed(() => tools.value.filter((t) => t.level === 'L3'))
const grouped = computed(() => {
  const g: Record<string, AtopiaTool[]> = { L0: [], L1: [], L2: [] }
  for (const t of usable.value) (g[t.level] ||= []).push(t)
  return g
})
const cur = computed(() => tools.value.find((t) => t.name === selected.value) || null)
const LEVEL_NAME: Record<string, string> = {
  L0: 'L0 只读', L1: 'L1 预览（花模型成本）', L2: 'L2 写入（需确认）', L3: 'L3 不开放',
}
const LEVEL_COLOR: Record<string, string> = {
  L0: '#16a34a', L1: '#2563eb', L2: '#b45309', L3: '#9ca3af',
}

async function refresh() {
  busy.value = true
  msg.value = ''
  try {
    const r = await fetchAtopiaTools(props.engineAddr, props.token)
    if (!r?.ok) { msg.value = `读取工具失败：${r?.error || '未知错误'}`; return }
    tools.value = r.tools || []
    levels.value = r.levels || {}
    limits.value = r.limits || {}
    hardCaps.value = r.hardCaps || {}
    if (!Object.keys(limDraft.value).length) limDraft.value = { ...(r.limits || {}) }
    if (!selected.value && usable.value.length) selected.value = usable.value[0]!.name
    await loadJournal()
  } catch (e) {
    msg.value = `读取失败：${String((e as Error).message || e)}（引擎是否在线？）`
  } finally { busy.value = false }
}

function askSaveLimits() {
  const lim = { ...limDraft.value }
  const changed = Object.entries(lim).filter(([k, v]) => Number(v) !== Number(limits.value[k]))
  if (!changed.length) { limMsg.value = '没有改动'; return }
  // 超硬顶**先在前端拦一次**（引擎仍会再校验，这里只为更早给反馈）
  const over = changed.filter(([k, v]) => hardCaps.value[k] && Number(v) > hardCaps.value[k])
  if (over.length) {
    limMsg.value = over.map(([k, v]) => `${k}=${v} 超过硬顶 ${hardCaps.value[k]}`).join('；')
    return
  }
  pendingLimits.value = lim
}

async function confirmSaveLimits() {
  const lim = pendingLimits.value
  pendingLimits.value = null
  if (!lim) return
  try {
    const r = await postAtopiaLimits(props.engineAddr, props.token, lim)
    if (r?.ok) {
      limits.value = r.limits || lim
      limDraft.value = { ...(r.limits || lim) }
      hardCaps.value = r.hardCaps || hardCaps.value
      limMsg.value = '✅ 护栏已保存（下次会话生效）'
    } else {
      limMsg.value = `❌ ${r?.error || '保存失败'}`
    }
  } catch (e) {
    limMsg.value = `保存失败：${String((e as Error).message || e)}`
  }
}

const LIMIT_LABEL: Record<string, string> = {
  maxCallsPerSession: '单会话最多调用次数',
  maxLlmCallsPerSession: '其中会花模型钱的次数',
  callTimeoutSeconds: '单次调用超时（秒）',
  sessionSeconds: '会话总时长（秒）',
}

async function loadJournal() {
  try {
    const r = await fetchAtopiaJournal(props.engineAddr, props.token, 50)
    journal.value = (r?.records || []).slice().reverse()
  } catch { journal.value = [] }
}

function pick(name: string) {
  selected.value = name
  const t = tools.value.find((x) => x.name === name)
  // 按允许参数给出模板，减少手写错误
  const tpl: Record<string, string> = {}
  for (const k of Object.keys(t?.allowedArgs || {})) tpl[k] = ''
  argsText.value = JSON.stringify(tpl, null, 0)
}

function parseArgs(): Record<string, any> | null {
  try {
    const v = JSON.parse(argsText.value || '{}')
    if (typeof v !== 'object' || Array.isArray(v) || v === null) {
      msg.value = '参数必须是 JSON 对象'; return null
    }
    return v as Record<string, any>
  } catch (e) {
    msg.value = `参数不是合法 JSON：${String((e as Error).message)}`
    return null
  }
}

async function run() {
  const t = cur.value
  if (!t) { msg.value = '请先选择工具'; return }
  if (t.level === 'L3') { msg.value = 'L3 工具不开放'; return }
  const args = parseArgs()
  if (args === null) return
  if (t.level === 'L2') {
    // **二次确认**：把工具名 + 参数原样给教师看，默认不执行
    pending.value = { tool: t, args }
    return
  }
  await exec(t, args, '')
}

async function confirmRun() {
  const p = pending.value
  pending.value = null
  if (!p) return
  await exec(p.tool, p.args, 'teacher:pwa')
}

async function exec(t: AtopiaTool, args: Record<string, any>, confirm: string) {
  busy.value = true
  msg.value = ''
  try {
    const r = await runAtopiaTool(props.engineAddr, props.token,
                                      { tool: t.name, args, confirm })
    if (r?.ok) {
      msg.value = `✅ ${t.name} 执行成功（${r.ms}ms，exit ${r.exit}）`
      output.value = String(r.stdout || '')
    } else {
      msg.value = `❌ ${r?.error || '执行失败'}`
      output.value = String(r.stderr || r.stdout || '')
    }
    await loadJournal()
  } catch (e) {
    msg.value = `执行失败：${String((e as Error).message || e)}`
  } finally { busy.value = false }
}

onMounted(refresh)
defineExpose({ refresh })
</script>

<template>
  <div class="asst">
    <div class="head">
      <h3 style="margin:0">🧪 Atopia（AI 可调用的本项目工具）</h3>
      <span class="hint" style="margin:0">
        只读直接执行；<b>写入需你逐次确认</b>；危险工具不开放。每次调用都记审计日志。
      </span>
      <span style="flex:1"></span>
      <button class="btn small" :disabled="busy" @click="refresh">刷新</button>
    </div>

    <p v-if="msg" class="hint">{{ msg }}</p>

    <div class="grid">
      <div class="tools">
        <template v-for="lvl in ['L0', 'L1', 'L2']" :key="lvl">
          <h4 v-if="grouped[lvl]?.length" style="margin:8px 0 4px"
              :style="{ color: LEVEL_COLOR[lvl] }">
            {{ LEVEL_NAME[lvl] }}（{{ grouped[lvl]!.length }}）
          </h4>
          <div v-for="t in grouped[lvl]" :key="t.name" class="tool"
               :class="{ on: t.name === selected }" @click="pick(t.name)">
            <div class="tname">{{ t.name }}</div>
            <div class="hint" style="margin:0">{{ t.summary }}</div>
          </div>
        </template>
        <details v-if="denied.length" style="margin-top:10px">
          <summary class="hint" style="cursor:pointer">
            L3 危险工具（{{ denied.length }} 个，**不开放**）
          </summary>
          <div v-for="t in denied" :key="t.name" class="tool off">
            <div class="tname">{{ t.name }}</div>
            <div class="hint" style="margin:0">{{ t.summary }}</div>
          </div>
        </details>
      </div>

      <div class="run">
        <h4 style="margin:4px 0">执行</h4>
        <p v-if="!cur" class="hint">从左侧选择一个工具。</p>
        <template v-else>
          <p style="margin:0 0 4px">
            <code>{{ cur.argv.join(' ') }}</code>
            <span class="lv" :style="{ color: LEVEL_COLOR[cur.level] }">{{ cur.level }}</span>
          </p>
          <p class="hint" style="margin:0 0 4px">
            允许参数：{{ Object.keys(cur.allowedArgs).join(', ') || '（无）' }}
          </p>
          <textarea v-model="argsText" rows="3" class="args"
                    placeholder='{"kind": "qa"}'></textarea>
          <p style="margin:6px 0">
            <button class="btn" :disabled="busy || cur.level === 'L3'" @click="run">
              {{ cur.level === 'L2' ? '▶ 执行（需确认）' : '▶ 执行' }}
            </button>
          </p>

          <!-- L2 二次确认：显示将要执行的工具与参数 -->
          <div v-if="pending" class="confirm">
            <p style="margin:0 0 6px">
              ⚠️ <b>{{ pending.tool.name }}</b> 是<b>写入</b>操作，将修改工作区数据：
            </p>
            <pre class="args">{{ JSON.stringify(pending.args, null, 1) }}</pre>
            <p style="margin:6px 0 0">
              <button class="btn primary" :disabled="busy" @click="confirmRun">✅ 我确认执行</button>
              <button class="btn" style="margin-left:6px" @click="pending = null">取消</button>
            </p>
          </div>

          <pre v-if="output" class="out">{{ output }}</pre>
        </template>
      </div>
    </div>

    <!-- D137：护栏可编辑（受硬顶约束） -->
    <h4 style="margin:14px 0 4px">护栏（本次会话的调用上限）</h4>
    <p class="hint" style="margin:0 0 6px">
      数值可调，但**不能配成无限**——超过硬顶会被拒绝。
    </p>
    <div class="lim-grid">
      <label v-for="(lab, k) in LIMIT_LABEL" :key="k" class="lim-item">
        <span>{{ lab }}</span>
        <input v-model.number="limDraft[k]" type="number" min="1" style="width:90px" />
        <em class="hint">硬顶 {{ hardCaps[k] ?? '—' }}</em>
      </label>
    </div>
    <p style="margin:6px 0">
      <button class="btn" @click="askSaveLimits">保存护栏</button>
      <span v-if="limMsg" class="hint" style="margin-left:8px">{{ limMsg }}</span>
    </p>

    <div v-if="pendingLimits" class="confirm">
      <p style="margin:0 0 6px">⚠️ 将修改护栏（**影响后续每一次 AI 会话**）：</p>
      <pre class="args">{{ Object.entries(pendingLimits)
        .filter(([k, v]) => Number(v) !== Number(limits[k]))
        .map(([k, v]) => `${k}: ${limits[k]} → ${v}`).join('\n') }}</pre>
      <p style="margin:6px 0 0">
        <button class="btn primary" @click="confirmSaveLimits">✅ 我确认修改</button>
        <button class="btn" style="margin-left:6px" @click="pendingLimits = null">取消</button>
      </p>
    </div>

    <h4 style="margin:14px 0 4px">最近调用（审计日志）</h4>
    <p v-if="!journal.length" class="hint">（还没有调用记录。）</p>
    <table v-else class="jt">
      <thead>
        <tr><th>时间</th><th>工具</th><th>级别</th><th>状态</th><th>耗时</th><th>确认</th></tr>
      </thead>
      <tbody>
        <tr v-for="(r, i) in journal.slice(0, 20)" :key="i">
          <td>{{ r.ts }}</td>
          <td>{{ r.tool }}</td>
          <td class="c" :style="{ color: LEVEL_COLOR[r.level] }">{{ r.level }}</td>
          <td class="c" :style="{ color: r.status === 'ok' ? '#16a34a' : '#dc2626' }">
            {{ r.status }}
          </td>
          <td class="c">{{ r.ms }}ms</td>
          <td class="c">{{ r.confirmed_by || '—' }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.asst { border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px 12px; margin-top: 10px; }
.head { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.grid { display: grid; grid-template-columns: minmax(260px, 1fr) minmax(300px, 1.2fr);
        gap: 12px; align-items: start; margin-top: 8px; }
.tool { border: 1px solid #e5e7eb; border-radius: 6px; padding: 5px 8px; margin-bottom: 4px;
        cursor: pointer; }
.tool:hover { background: #f8fafc; }
.tool.on { background: #eff6ff; outline: 1px solid #bfdbfe; }
.tool.off { opacity: .55; cursor: not-allowed; }
.tname { font-size: 13px; font-weight: 600; }
.lv { margin-left: 6px; font-size: 11px; font-weight: 600; }
.lim-grid { display: flex; gap: 14px; flex-wrap: wrap; margin: 4px 0; }
.lim-item { display: flex; gap: 6px; align-items: center; font-size: 13px; }
.args { width: 100%; font-family: ui-monospace, monospace; font-size: 12px;
        border: 1px solid #e5e7eb; border-radius: 6px; padding: 6px; }
.confirm { border: 1px solid #fbbf24; background: #fffbeb; border-radius: 6px;
           padding: 8px; margin-top: 8px; }
.out { background: #0f172a; color: #e2e8f0; border-radius: 6px; padding: 8px;
       font-size: 12px; max-height: 260px; overflow: auto; white-space: pre-wrap; }
.jt { border-collapse: collapse; font-size: 12px; width: 100%; }
.jt th, .jt td { border: 1px solid #e5e7eb; padding: 3px 6px; }
.jt th { background: #f9fafb; }
.jt td.c { text-align: center; }
.hint { color: #6b7280; font-size: 12px; }
</style>

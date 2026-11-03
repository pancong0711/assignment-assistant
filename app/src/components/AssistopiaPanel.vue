<script setup lang="ts">
/** D132：Assistopia 工作区 —— AI 调用本项目工具的**受控**入口。
 *
 *  安全口径（docs/81）：L0/L1 直接执行；**L2 必须教师点击确认**；L3 不开放（连按钮都不给）。
 *  每次调用都在引擎侧写 journal（含 confirmed_by），本页只负责"看清楚 + 确认"。
 */
import { computed, onMounted, ref } from 'vue'
import {
  fetchAssistopiaJournal, fetchAssistopiaTools, runAssistopiaTool,
  type AssistopiaTool,
} from '../lib/engineClient'

const props = defineProps<{ engineAddr: string; token?: string }>()

const tools = ref<AssistopiaTool[]>([])
const levels = ref<Record<string, string>>({})
const limits = ref<Record<string, number>>({})
const journal = ref<any[]>([])
const msg = ref('')
const busy = ref(false)

const selected = ref('')
const argsText = ref('{}')
const pending = ref<{ tool: AssistopiaTool; args: Record<string, any> } | null>(null)
const output = ref('')

/** L3 不展示为"可执行"——只在末尾列出并明确写"不开放"。 */
const usable = computed(() => tools.value.filter((t) => t.level !== 'L3'))
const denied = computed(() => tools.value.filter((t) => t.level === 'L3'))
const grouped = computed(() => {
  const g: Record<string, AssistopiaTool[]> = { L0: [], L1: [], L2: [] }
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
    const r = await fetchAssistopiaTools(props.engineAddr, props.token)
    if (!r?.ok) { msg.value = `读取工具失败：${r?.error || '未知错误'}`; return }
    tools.value = r.tools || []
    levels.value = r.levels || {}
    limits.value = r.limits || {}
    if (!selected.value && usable.value.length) selected.value = usable.value[0]!.name
    await loadJournal()
  } catch (e) {
    msg.value = `读取失败：${String((e as Error).message || e)}（引擎是否在线？）`
  } finally { busy.value = false }
}

async function loadJournal() {
  try {
    const r = await fetchAssistopiaJournal(props.engineAddr, props.token, 50)
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

async function exec(t: AssistopiaTool, args: Record<string, any>, confirm: string) {
  busy.value = true
  msg.value = ''
  try {
    const r = await runAssistopiaTool(props.engineAddr, props.token,
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
      <h3 style="margin:0">🧪 Assistopia（AI 可调用的本项目工具）</h3>
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

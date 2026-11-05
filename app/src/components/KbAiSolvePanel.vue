<script setup lang="ts">
/** D152：题库 AI 作答面板（从 AiGradingPanel ⑦ 区**整体搬出**）。
 *
 *  为什么抽成组件：批阅页和「题库AI+」都用同一套能力，复制会导致口径漂移。
 *  这里保留原 ⑦ 区全部能力：题号多选 / 模型 / 置顶 / 写回 / 同时生成要点 /
 *  提示词模板 / 作答要求 / 题目预览 / solution 索引状态。
 *
 *  D152 新增：☑ 同时标注知识点到题库（一次调用完成 解答+要点+知识点）。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useKbStore } from '../stores/kb'
import {
  fetchKbCatalog, fetchPromptTemplates, fetchXxtLoginJob, mutatePromptTemplate,
  startKbAiSolve,
} from '../lib/engineClient'

const props = defineProps<{ engineAddr: string; token?: string }>()

const kbStore = useKbStore()

/* ---------- 题库目录 ---------- */
const kbCatalog = ref<{ kinds?: any[] }>({ kinds: [] })
const kbCatalogErr = ref('')
const kbKind = ref(''); const kbChap = ref(''); const kbIdsSel = ref<string[]>([]); const kbModel = ref('')
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
const kbPreview = computed(() => {
  const want = new Set(kbIdsSel.value)
  const picked = kbIdList.value.filter((i) => !want.size || want.has(i.id))
  return picked.map((i) => `${i.id}: ${i.content ?? ''}`).join('   ｜   ')
})
async function loadKbCatalog() {
  kbCatalogErr.value = ''
  const r = await fetchKbCatalog(props.engineAddr, props.token)
  kbCatalog.value = { kinds: r.kinds || [] }
  if (r.ok === false || !(r.kinds || []).length) {
    kbCatalogErr.value = r.error
      ? `读取题库目录失败：${r.error}（引擎在线吗？）`
      : '题库为空：请先在「题库编辑器」载入 xlsx'
  }
  if (!kbKind.value && kbKinds.value.length) {
    kbKind.value = kbKinds.value.includes('problems') ? 'problems' : kbKinds.value[0]
  }
}
watch(kbKind, () => { kbChap.value = ''; kbIdsSel.value = [] })
watch(kbChap, () => { kbIdsSel.value = [] })

/* ---------- 作答选项 ---------- */
const kbPin = ref(true); const kbApply = ref(false)
const kbWithRubric = ref(false); const kbPinRubric = ref(false)
/** D152：同时把知识点写回题库（走 apply_related，改前自动快照）
 *  D166：默认**勾选**——教师反馈「AI 作答后看不到知识点」，
 *  生成要点时知识点本就在同一次输出里，不写回等于白算。 */
const kbTagKnowledge = ref(true)
const kbRequirement = ref('')

/* ---------- 提示词模板（D108/D151） ---------- */
const promptTemplates = ref<{ id: string; name: string; text: string
                             default?: boolean; builtin?: boolean }[]>([])
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
  if (!promptTemplates.value.length) { promptMsg.value = '（未读到模板；引擎是否在线？）'; return }
  if (autoPickDefault && !promptSel.value) {
    const d = promptTemplates.value.find((t) => t.default)
    if (d) { promptSel.value = d.id; kbRequirement.value = d.text || '' }
  }
}
function pickPromptTemplate() {
  const t = promptTemplates.value.find((x) => x.id === promptSel.value)
  kbRequirement.value = t ? (t.text || '') : ''
  promptMsg.value = ''
}
async function setPromptDefault() {
  if (!promptSel.value) return
  promptBusy.value = true
  try {
    const r = await mutatePromptTemplate(props.engineAddr, props.token,
      { action: 'set_default', id: promptSel.value })
    promptMsg.value = r.ok ? '已设为默认' : `失败：${r.error || ''}`
    await loadPromptTemplates(false)
  } finally { promptBusy.value = false }
}
async function savePromptTemplate() {
  if (!promptSel.value) { promptMsg.value = '请先选择模板'; return }
  promptBusy.value = true
  try {
    const cur = promptTemplates.value.find((x) => x.id === promptSel.value)
    const r = await mutatePromptTemplate(props.engineAddr, props.token, {
      action: 'save', id: promptSel.value, name: cur?.name || promptSel.value,
      text: kbRequirement.value,
    })
    promptMsg.value = r.ok ? '已保存' : `失败：${r.error || ''}`
    await loadPromptTemplates(false)
  } finally { promptBusy.value = false }
}
async function savePromptAsNew() {
  const id = `custom-${Date.now().toString(36)}`
  promptBusy.value = true
  try {
    const r = await mutatePromptTemplate(props.engineAddr, props.token, {
      action: 'save', id, name: `自定义-${id.slice(-4)}`, text: kbRequirement.value,
    })
    if (r.ok) { promptSel.value = id; promptMsg.value = '已另存为新模板' }
    else promptMsg.value = `失败：${r.error || ''}`
    await loadPromptTemplates(false)
  } finally { promptBusy.value = false }
}
async function deletePromptTemplate() {
  if (!promptSel.value || promptIsBuiltin.value) return
  if (!window.confirm('删除该模板？')) return
  promptBusy.value = true
  try {
    const r = await mutatePromptTemplate(props.engineAddr, props.token,
      { action: 'delete', id: promptSel.value })
    promptMsg.value = r.ok ? '已删除' : `失败：${r.error || ''}`
    promptSel.value = ''
    await loadPromptTemplates()
  } finally { promptBusy.value = false }
}

/* ---------- 执行 ---------- */
const kbSolving = ref(false)
const kbSolveMsg = ref('')

function extractJobError(s: string): string {
  const m = /"error"\s*:\s*"([^"]{1,400})"/.exec(s)
  return m ? m[1] : ''
}

async function solveByKb() {
  const ids = [...kbIdsSel.value]
  if (!ids.length) {
    if (!kbChap.value) {
      if (!window.confirm(
        `未选择章节，也未勾选题号 → 将对 **整个「${kbKind.value}」题库** 作答`
        + (kbApply.value ? '（并写回/置顶生效答案）' : '（dry-run 预览）') + '。\n'
        + '题量可能很大且耗时长。确定继续？')) return
    } else {
      const n = kbIdList.value.length
      if (!window.confirm(
        `未勾选题号 → 将对整章「${kbChap.value}」（${n} 题）作答`
        + (kbApply.value ? '（并写回/置顶生效答案）' : '（dry-run 预览）') + '。\n确定继续？')) return
    }
  }
  kbSolving.value = true; kbSolveMsg.value = '正在启动题库 AI 作答……'
  try {
    const jobId = await startKbAiSolve(props.engineAddr, props.token, {
      kb: kbKind.value, chap: kbChap.value, ids, model: kbModel.value,
      pin: kbPin.value, apply: kbApply.value,
      withRubric: kbWithRubric.value,
      pinRubric: kbWithRubric.value && kbPinRubric.value,
      tagKnowledge: kbWithRubric.value && kbTagKnowledge.value,   // D152
      all: !ids.length && !kbChap.value,
      requirement: kbRequirement.value.trim(),
      requirementTemplate: promptSel.value,
    })
    const tick = async () => {
      try {
        const job = await fetchXxtLoginJob(props.engineAddr, props.token, jobId)
        const lines = job.lines || []
        kbSolveMsg.value = (lines.slice(-1)[0] || '进行中…').slice(-220)
        if (job.status === 'running') { window.setTimeout(tick, 2000); return }
        const tail = lines.slice(-6).join('\n')
        const failedN = /"failed"\s*:\s*(\d+)/.exec(tail)?.[1]
        const errs = [...tail.matchAll(/"error"\s*:\s*"([^"]{1,300})"/g)]
          .map((m) => m[1]).filter(Boolean)
        if (kbApply.value) {
          await kbStore.bumpSolutions()
          const pinDesc = kbWithRubric.value
            ? (kbPinRubric.value ? '已置顶（含要点）' : '未置顶（要点待你确认后再置顶）')
            : (kbPin.value ? '已置顶为生效答案' : '未置顶，仅追加版本')
          if (failedN && failedN !== '0') {
            kbSolveMsg.value = `❌ 有 ${failedN} 题作答失败（未写回）`
              + (errs.length ? `：${[...new Set(errs)].slice(0, 3).join('；')}` : '')
              + '　—— 已成功的题已写回；失败题可重试或换模型'
            return
          }
          kbSolveMsg.value = `✅ 作答并写回完成（${pinDesc}）`
            + (kbTagKnowledge.value && kbWithRubric.value ? '；知识点已同步标注' : '')
            + '：' + (lines.slice(-2).join(' ') || '')
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

onMounted(async () => {
  await loadKbCatalog()
  await loadPromptTemplates()
})
defineExpose({ loadKbCatalog, loadPromptTemplates })
</script>

<template>
  <div>
    <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap">
      <span v-if="kbCatalogErr" class="hint" style="color:#b45309">{{ kbCatalogErr }}</span>
      <button v-if="kbCatalogErr" class="btn small" @click="loadKbCatalog">重试</button>
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
      <input v-model="kbModel" placeholder="空=评阅段配置" style="width:170px" />
      <label class="field" title="默认勾选：AI 作答即成为生效答案">
        <input type="checkbox" v-model="kbPin" /> 作答后置顶
      </label>
      <label class="field" title="不勾=仅 dry-run 预览">
        <input type="checkbox" v-model="kbApply" /> 真正作答并写回
      </label>
      <label class="field" title="一次产出「参考解答 + 评阅要点 + 知识点」">
        <input type="checkbox" v-model="kbWithRubric" /> 同时生成评阅要点
      </label>
      <label v-if="kbWithRubric" class="field" title="默认不置顶：未确认的要点不该抢生效答案">
        <input type="checkbox" v-model="kbPinRubric" /> 同时置顶（跳过确认）
      </label>
      <!-- D152：知识点标注并入 -->
      <label v-if="kbWithRubric" class="field"
             title="把 AI 产出的知识点写回题库 knowledge（改前自动快照）">
        <input type="checkbox" v-model="kbTagKnowledge" /> 同时标注知识点到题库
      </label>
    </div>
    <p v-if="kbWithRubric" class="hint" style="margin:2px 0 0">
      ⓘ 要点与解答**同一次生成**。默认<b>不置顶</b>；<code>copy</code>/<code>summary</code> 按口径不生成 AI 要点。
    </p>

    <div style="margin:6px 0">
      <div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap; margin-bottom:4px">
        <label class="hint" style="margin:0">提示词模板：</label>
        <select v-model="promptSel" @change="pickPromptTemplate" style="min-width:220px">
          <option value="">（不使用模板 / 单次输入）</option>
          <option v-for="t in promptTemplates" :key="t.id" :value="t.id">
            {{ t.default ? '★ ' : '' }}{{ t.name }}{{ t.builtin ? '（内置）' : '' }}
          </option>
        </select>
        <button class="btn small" :disabled="promptBusy || !promptSel || promptIsDefault"
                @click="setPromptDefault">设为默认</button>
        <button class="btn small" :disabled="promptBusy || !kbRequirement.trim()"
                @click="savePromptTemplate">💾 保存</button>
        <button class="btn small" :disabled="promptBusy || !kbRequirement.trim()"
                @click="savePromptAsNew">＋ 另存为</button>
        <button class="btn small" :disabled="promptBusy || !promptSel || promptIsBuiltin"
                @click="deletePromptTemplate">🗑 删除</button>
      </div>
      <label class="hint" style="display:block; margin:0 0 4px">
        作答要求（作为「优先满足」附加到每题 prompt）：
      </label>
      <textarea v-model="kbRequirement" rows="3"
        placeholder="例：请画出示意图；用 LaTeX 公式完整推导；按「已知/求/解/答」结构写……"
        style="width:100%; max-width:760px; font-family:inherit; font-size:13px; padding:6px 8px;
               border:1px solid #d1d5db; border-radius:6px; resize:vertical"></textarea>
      <div class="hint" style="margin:2px 0 0">
        模板保存在 <code>&lt;workspace&gt;/prompts/ai-solve/</code>，CLI/AI 同样可用。
        <span v-if="promptMsg" style="color:#2563eb">｜{{ promptMsg }}</span>
      </div>
      <button class="btn" :disabled="kbSolving" @click="solveByKb" style="margin-top:6px">
        ▶ {{ kbApply ? 'AI 作答并写回' : 'AI 作答（dry-run）' }}
      </button>
    </div>

    <div class="hint" style="margin:4px 0 0">题目预览：
      <code v-if="kbPreview" style="display:inline-block; max-width:100%; overflow-x:auto;
            white-space:nowrap; vertical-align:bottom">{{ kbPreview }}</code>
      <span v-else>（未选题号：将按整章/整库作答）</span>
    </div>
    <p class="hint" style="margin:6px 0 0">
      AI 作答**不覆盖**原答案：每次新增一版（含模型名 + 时间戳），默认**置顶为生效答案**。
      索引状态：{{ kbStore.solutionsMsg || '（未刷新）' }}
    </p>
    <p class="hint" v-if="kbSolveMsg">{{ kbSolveMsg }}</p>
  </div>
</template>

<style scoped>
.hint { color: #6b7280; font-size: 12px; }
.field { display: flex; gap: 6px; align-items: center; font-size: 13px; }
</style>

<script setup lang="ts">
/** D130-T9：评阅规则卡。
 *
 *  解决"批阅提示词教师看不到也改不了"：分层开放（docs/78 §3.4）
 *   - 🔒 只读：题型 → 评阅侧重的**提示词正文**、评分算法名（完全可见，不可改）
 *   - ✏️ 可改数值：扣分分值 / 上限 / 长度倍率 / 阈值（带范围校验）
 *   - ➕ 可改扩展：题型 checklist 的检查项名称（如 copy 的"题目/过程/示意图"）
 *  配套：改动记 journal（引擎侧）、一键「恢复默认」；
 *  页面明示"影响后续批阅，不改已生成报告"（报告是纯组装产物，D127）。
 */
import { computed, onMounted, ref } from 'vue'
import {
  fetchGradingRules, resetGradingRules, saveGradingRules,
  type GradingRulesPayload,
} from '../lib/engineClient'

const props = defineProps<{ engineAddr: string; token?: string }>()
const emit = defineEmits<{ (e: 'notify', m: string): void }>()

const loading = ref(false)
const saving = ref(false)
const payload = ref<GradingRulesPayload | null>(null)
const draft = ref<Record<string, any>>({})
const msg = ref('')
const activeKind = ref('qa')

const KIND_LABEL: Record<string, string> = {
  problems: '计算/推导（逐处找错）',
  qa: '问答（要点完整性 + 示意图）',
  copy: '抄写（题目/过程/示意图）',
  distinguish: '辨析（长度档）',
  translation: '翻译（长度档）',
  innovation: '创新（长度档、宽松）',
  summary: '总结（知识点/公式/示意图）',
}
const MODE_LABEL: Record<string, string> = {
  errorCount: 'errorCount（逐处错误计分）',
  missingPoints: 'missingPoints（缺评阅要点计分）',
  checklist: 'checklist（逐项完整性计分）',
  lengthBased: 'lengthBased（作答长度档计分）',
}

/** ✏️ 可改数值字段的展示名（未列出的一律不开放编辑）。 */
const NUM_FIELDS: { key: string; label: string; hint?: string }[] = [
  { key: 'briefProcessDeduct', label: '过程简略扣分（每处）' },
  { key: 'allBriefRatio', label: '整体简略触发比例（0~1）' },
  { key: 'allBriefDeduct', label: '整体简略额外扣分（一次性）' },
  { key: 'perQuestionCap', label: '单题扣分上限' },
  { key: 'perErrorDeduct', label: '每处错误扣分' },
  { key: 'perMissingPointDeduct', label: '每个缺失要点扣分' },
  { key: 'missingDiagramDeduct', label: '缺示意图扣分' },
  { key: 'perMissingItemDeduct', label: '每缺一项扣分' },
  { key: 'lengthFactor', label: '长度基准倍率（题长 × n）' },
  { key: 'lengthFloorChars', label: '长度基准下限（字数）' },
  { key: 'irrelevantDeduct', label: '完全无关扣分' },
  { key: 'noSignatureDeduct', label: '无签名扣分' },
  { key: 'writingDeduct', label: '书写规范扣分上限' },
  { key: 'floor', label: '总分下限' },
]

const kinds = computed<string[]>(() => payload.value?.kinds || [])
const typeCfg = computed<Record<string, any>>(
  () => (draft.value.types?.[activeKind.value] || {}) as Record<string, any>)
const globalCfg = computed<Record<string, any>>(
  () => (draft.value.global || {}) as Record<string, any>)
const summaryText = computed<string>(
  () => String(payload.value?.summaries?.[activeKind.value] || ''))

/** 字段范围（引擎下发，前端只做即时提示；**权威校验在引擎**） */
function range(key: string): [number, number] | null {
  return payload.value?.numericRanges?.[key] || null
}
function outOfRange(key: string, v: any): boolean {
  const r = range(key)
  if (!r) return false
  const n = Number(v)
  return !Number.isFinite(n) || n < r[0] || n > r[1]
}

async function load() {
  loading.value = true
  msg.value = ''
  try {
    const p = await fetchGradingRules(props.engineAddr, props.token)
    payload.value = p
    draft.value = JSON.parse(JSON.stringify(p.rules || {}))
    if (!kinds.value.includes(activeKind.value)) {
      activeKind.value = kinds.value.find((k) => k === 'qa') || kinds.value[0] || 'qa'
    }
  } catch (e) {
    msg.value = `读取评阅规则失败：${String((e as Error).message || e)}`
  } finally { loading.value = false }
}

async function save() {
  // 前端先做一遍范围校验，避免把明显越界的值发到引擎
  for (const f of NUM_FIELDS) {
    if (f.key in globalCfg.value && outOfRange(f.key, globalCfg.value[f.key])) {
      msg.value = `❌ 全局规则「${f.label}」超出范围 ${JSON.stringify(range(f.key))}`
      return
    }
    if (f.key in typeCfg.value && outOfRange(f.key, typeCfg.value[f.key])) {
      msg.value = `❌ ${KIND_LABEL[activeKind.value] || activeKind.value}「${f.label}」`
        + `超出范围 ${JSON.stringify(range(f.key))}`
      return
    }
  }
  saving.value = true
  msg.value = ''
  try {
    const r = await saveGradingRules(props.engineAddr, props.token, draft.value)
    if (!r?.ok) {
      msg.value = `❌ 保存失败：${r?.error || (r?.errors || []).join('；') || '未知错误'}`
      return
    }
    const n = (r.changes || []).length
    msg.value = `✅ 已保存 ${n} 处改动（记入 journal）；**只影响后续批阅**，已生成的报告不变`
    emit('notify', msg.value)
    await load()
  } catch (e) {
    msg.value = `保存失败：${String((e as Error).message || e)}`
  } finally { saving.value = false }
}

async function resetAll() {
  if (!window.confirm('恢复**全部**评阅规则为内置默认？\n（当前改动会记入 journal，' +
                      '但会覆盖你的自定义数值。）')) return
  saving.value = true
  try {
    const r = await resetGradingRules(props.engineAddr, props.token)
    msg.value = r?.ok ? '✅ 已恢复默认规则' : `❌ 恢复失败：${r?.error || '未知错误'}`
    if (r?.ok) { emit('notify', msg.value); await load() }
  } catch (e) {
    msg.value = `恢复失败：${String((e as Error).message || e)}`
  } finally { saving.value = false }
}

/** ➕ 可改扩展：checklist 项名（逗号分隔 → 数组） */
function checklistText(): string {
  const v = typeCfg.value.checklist
  return Array.isArray(v) ? v.join('，') : ''
}
function setChecklist(ev: Event) {
  const raw = String((ev.target as HTMLInputElement).value || '')
  const items = raw.split(/[，,、;；]/).map((x) => x.trim()).filter(Boolean)
  if (!draft.value.types) draft.value.types = {}
  if (!draft.value.types[activeKind.value]) draft.value.types[activeKind.value] = {}
  draft.value.types[activeKind.value].checklist = items
}

onMounted(load)
defineExpose({ load })
</script>

<template>
  <div class="rules-card">
    <div class="rules-head">
      <h3 style="margin:0">⚖️ 评阅规则卡（按题目来源分型）</h3>
      <span class="hint" style="margin:0">
        改动<b>只影响后续批阅</b>，不改已生成报告；改动会记 journal。
        本卡只管<b>怎么扣分</b>；生成 AI 评阅要点请到「⑦ 题库 AI 作答」勾选
        「同时生成评阅要点」。
      </span>
      <span style="flex:1"></span>
      <button class="btn small" :disabled="loading" @click="load">重新读取</button>
      <button class="btn small" :disabled="saving" @click="resetAll">恢复默认</button>
      <button class="btn small primary" :disabled="saving || loading" @click="save">保存</button>
    </div>

    <p v-if="loading" class="hint">正在读取规则…</p>
    <p v-else-if="!payload?.ok && payload?.error" class="hint">读取失败：{{ payload.error }}</p>

    <template v-else>
      <div class="kind-tabs">
        <button v-for="k in kinds" :key="k" class="btn small"
                :class="{ primary: k === activeKind }" @click="activeKind = k">
          {{ k }}
        </button>
      </div>
      <p class="hint" style="margin:4px 0 8px">
        {{ KIND_LABEL[activeKind] || activeKind }} ·
        评分算法：{{ MODE_LABEL[typeCfg.mode] || typeCfg.mode || '—' }}
      </p>

      <!-- 🔒 只读：进 prompt 的规则摘要（= 教师此前根本看不到的那段文字） -->
      <details class="ro-block" open>
        <summary>🔒 只读 · 实际进入评阅提示词的规则摘要</summary>
        <pre class="ro-text">{{ summaryText }}</pre>
        <p class="hint" style="margin:4px 0">
          这段文字与「生成评阅要点」用的是同一份规则摘要，保证要点粒度与扣分方式匹配。
        </p>
      </details>

      <!-- ✏️ 可改数值：本题型 -->
      <h4 style="margin:12px 0 6px">✏️ 本题型可改数值</h4>
      <div class="num-grid">
        <label v-for="f in NUM_FIELDS" :key="'t-' + f.key"
               v-show="f.key in typeCfg" class="num-item">
          <span>{{ f.label }}</span>
          <input v-model.number="typeCfg[f.key]" type="number" step="any"
                 :class="{ bad: outOfRange(f.key, typeCfg[f.key]) }" />
          <em v-if="range(f.key)" class="hint">范围 {{ range(f.key)?.[0] }}~{{ range(f.key)?.[1] }}</em>
        </label>
      </div>
      <p v-if="!Object.keys(typeCfg).some((k) => NUM_FIELDS.some((f) => f.key === k))"
         class="hint">本题型没有可改数值（见上方只读摘要）。</p>

      <!-- ➕ 可改扩展：checklist 项名 -->
      <template v-if="'checklist' in typeCfg">
        <h4 style="margin:12px 0 6px">➕ 检查项名称（可改扩展）</h4>
        <input class="chk-input" :value="checklistText()" @change="setChecklist"
               placeholder="用中文逗号分隔，如：题目，解题过程，示意图" />
        <p class="hint" style="margin:4px 0">
          重命名检查项会改变报告里的用词；批阅仍然逐项判断是否达标。
        </p>
      </template>

      <!-- ✏️ 全局规则（跨题/跨作业） -->
      <details class="ro-block" style="margin-top:14px">
        <summary>✏️ 全局规则（跨题、跨作业）</summary>
        <div class="num-grid">
          <label v-for="f in NUM_FIELDS" :key="'g-' + f.key"
                 v-show="f.key in globalCfg" class="num-item">
            <span>{{ f.label }}</span>
            <input v-model.number="globalCfg[f.key]" type="number" step="any"
                   :class="{ bad: outOfRange(f.key, globalCfg[f.key]) }" />
            <em v-if="range(f.key)" class="hint">范围 {{ range(f.key)?.[0] }}~{{ range(f.key)?.[1] }}</em>
          </label>
        </div>
        <p class="hint" style="margin:4px 0">
          「整体简略」规则：≥设定比例的题目被判为过程简略时，对<b>总分一次性</b>扣分（不逐题累计）。
        </p>
      </details>

      <p v-if="msg" class="hint" style="margin-top:10px; white-space:pre-wrap">{{ msg }}</p>
      <p class="hint" style="margin-top:6px">
        规则文件：{{ payload?.file || '—' }}（引擎缺失时自动写入默认值）
      </p>
    </template>
  </div>
</template>

<style scoped>
.rules-card { border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px 12px; margin-top: 10px; }
.rules-head { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.kind-tabs { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.ro-block { background: #f9fafb; border: 1px dashed #d1d5db; border-radius: 6px; padding: 6px 8px; }
.ro-block summary { cursor: pointer; font-weight: 600; }
.ro-text { white-space: pre-wrap; margin: 6px 0 0; font-size: 12px; line-height: 1.6; }
.num-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 8px 14px; }
.num-item { display: flex; gap: 6px; align-items: center; font-size: 13px; }
.num-item span { flex: 1; }
.num-item input { width: 84px; }
.num-item input.bad { border-color: #dc2626; background: #fef2f2; }
.chk-input { width: 100%; max-width: 460px; }
.hint { color: #6b7280; font-size: 12px; }
</style>

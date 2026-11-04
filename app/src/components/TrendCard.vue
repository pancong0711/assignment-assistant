<script setup lang="ts">
/** D135：跨多次作业的知识点趋势（**只给教师**）。
 *
 *  数据来自引擎 `/grade/trend`（纯统计，不调 LLM）。
 *  作业序列按**评阅时间**排序；同一知识点在 ≥2 次作业出错 → 「反复出错」。
 *  用纯 SVG 画迷你折线，不引入图表库（离线可用）。
 */
import { computed, ref, watch } from 'vue'
import { fetchKnowledgeTrend, type TrendRecurring, type TrendStat } from '../lib/engineClient'

const props = defineProps<{
  engineAddr: string; token?: string
  classDir: string
  /** 外部触发重建（如刚批阅完） */
  reloadKey?: number
}>()

const loading = ref(false)
const stat = ref<TrendStat | null>(null)
const msg = ref('')
const showOneOff = ref(false)
const minRecur = ref(2)

const canLoad = computed(() => Boolean(props.classDir))

async function load() {
  if (!canLoad.value) { msg.value = '请先选择班级（需要班级目录）'; return }
  loading.value = true
  msg.value = ''
  try {
    const r = await fetchKnowledgeTrend(props.engineAddr, props.token,
                                        props.classDir, minRecur.value)
    if (!r?.ok) {
      stat.value = null
      msg.value = `❌ ${r?.error || '读取失败'}`
      return
    }
    stat.value = (r.stat || null) as TrendStat | null
  } catch (e) {
    stat.value = null
    msg.value = `读取失败：${String((e as Error).message || e)}`
  } finally {
    loading.value = false
  }
}

watch(() => [props.classDir, props.reloadKey], () => { if (canLoad.value) load() },
      { immediate: true })

const seq = computed(() => stat.value?.sequence || [])
const rec = computed(() => stat.value?.recurring || [])
const sum = computed(() => stat.value?.summary || { packs: 0, terms: 0, recurring: 0, persisting: 0 })

/** 迷你折线：横轴=作业序号，纵轴=出错率。 */
function sparkline(r: TrendRecurring): string {
  const pts = r.trail
  if (pts.length < 2) return ''
  const n = seq.value.length || pts.length
  const W = 120
  const H = 26
  const idx = (packId: string) => Math.max(0, seq.value.findIndex((s) => s.packId === packId))
  return pts.map((p) => {
    const x = n <= 1 ? 0 : (idx(p.packId) / (n - 1)) * W
    const y = H - Math.min(1, Math.max(0, p.rate)) * (H - 4) - 2
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}
</script>

<template>
  <div class="card">
    <div class="hd">
      <h3 style="margin:0">📈 知识点趋势（跨作业）</h3>
      <span class="hint">只给教师 · 同一知识点是否反复出错</span>
    </div>
    <div class="ctl">
      <label class="hint">最少出现次数
        <input v-model.number="minRecur" type="number" min="1" max="10" style="width:56px" />
      </label>
      <button class="btn" :disabled="loading || !canLoad" @click="load">
        {{ loading ? '读取中…' : '刷新' }}
      </button>
      <span v-if="msg" class="hint">{{ msg }}</span>
    </div>

    <p v-if="!loading && !seq.length && !msg" class="hint">
      该班级还没有评阅结果，无法生成趋势。
    </p>

    <template v-if="seq.length">
      <p class="hint" style="margin:4px 0">
        作业序列 {{ sum.packs }} 次 · 涉及知识点 {{ sum.terms }} 个 ·
        <b>反复出错 {{ sum.recurring }} 个</b>（仍在持续 {{ sum.persisting }} 个）
      </p>
      <ol class="seq">
        <li v-for="p in seq" :key="p.packId">
          <b>{{ p.name }}</b>
          <span class="hint">（{{ p.at || '—' }} · {{ p.students }} 人）</span>
        </li>
      </ol>

      <table v-if="rec.length" class="tbl">
        <thead>
          <tr><th>知识点</th><th>出现</th><th>走势</th><th>判定</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in rec" :key="r.term">
            <td><b>{{ r.term }}</b></td>
            <td class="c">{{ r.packs }} 次</td>
            <td class="c">
              <svg :width="120" :height="26" style="overflow:visible">
                <polyline :points="sparkline(r)" fill="none"
                          :stroke="r.persisting ? '#dc2626' : '#16a34a'" stroke-width="1.6" />
              </svg>
            </td>
            <td class="c">
              <b :style="{ color: r.persisting ? '#dc2626' : '#16a34a' }">
                {{ r.persisting ? '⚠️ 仍在持续' : '📉 有改善' }}
              </b>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="hint">没有知识点在 ≥{{ minRecur }} 次作业里反复出错。</p>

      <details v-if="(stat?.oneOff || []).length" style="margin-top:8px">
        <summary class="hint" style="cursor:pointer" @click="showOneOff = !showOneOff">
          仅出现一次的知识点（{{ (stat?.oneOff || []).length }} 个）
        </summary>
        <p class="hint" style="margin:4px 0">
          {{ (stat?.oneOff || []).map((x) => x.term).join('、') }}
        </p>
      </details>
    </template>
  </div>
</template>

<style scoped>
.card { border: 1px solid #e5e7eb; border-radius: 10px; padding: 10px 12px; margin-top: 12px; }
.hd { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
.ctl { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 8px 0; }
.hint { color: #6b7280; font-size: 12px; }
.tbl { border-collapse: collapse; font-size: 13px; width: 100%; }
.tbl th, .tbl td { border: 1px solid #e5e7eb; padding: 4px 8px; }
.tbl th { background: #f9fafb; }
.tbl td.c { text-align: center; }
.seq { margin: 4px 0 8px 18px; padding: 0; font-size: 12px; }
</style>

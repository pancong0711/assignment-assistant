<script setup lang="ts">
/** D126-B：教师总结报告（易错知识点 + 共现矩阵 + 得分率）。
 *
 *  **只给教师看**，与学生报告严格区分（不上传、不发学生）。
 *  纯 SVG 绘图，不引入图表库（离线可用、体积零增长）。
 *  数据来自引擎 `/grade/teacher-report`（纯统计，不调 LLM）。
 */
import { computed, ref, watch } from 'vue'
import { fetchTeacherReport, type TeacherReportStat } from '../lib/engineClient'

const props = defineProps<{
  engineAddr: string; token?: string
  classDir: string; taskId: string
  /** 外部触发重建（如刚生成完报告） */
  reloadKey?: number
}>()

const loading = ref(false)
const stat = ref<TeacherReportStat | null>(null)
const md = ref('')
const msg = ref('')
const showMd = ref(false)
/** D135：导出 PNG/PDF（附加能力；失败不影响报告本身） */
const exporting = ref<'png' | 'pdf' | ''>('')
const exportMsg = ref('')

async function exportReport(kind: 'png' | 'pdf') {
  if (!canLoad.value) return
  exporting.value = kind
  exportMsg.value = ''
  try {
    const r = await fetchTeacherReport(props.engineAddr, props.token, {
      classDir: props.classDir, taskId: props.taskId, export: kind,
    })
    if (!r?.ok) {
      exportMsg.value = `❌ ${r?.error || '导出失败'}${r?.hint ? `（${r.hint}）` : ''}`
      return
    }
    const path = kind === 'pdf' ? r.pdf : r.png
    exportMsg.value = path ? `✅ 已导出：${path}` : '❌ 未产出文件'
  } catch (e) {
    exportMsg.value = `导出失败：${String((e as Error).message || e)}`
  } finally { exporting.value = '' }
}

const canLoad = computed(() => Boolean(props.classDir && props.taskId))

async function load(rebuild = false) {
  if (!canLoad.value) {
    msg.value = '请先选择作业（需要班级目录 + 批阅目录键）'
    return
  }
  loading.value = true
  msg.value = ''
  try {
    const r = await fetchTeacherReport(props.engineAddr, props.token, {
      classDir: props.classDir, taskId: props.taskId, rebuild,
    })
    if (!r?.ok) {
      stat.value = null
      msg.value = `❌ ${r?.error || '读取失败'}${r?.hint ? `（${r.hint}）` : ''}`
      return
    }
    stat.value = r.stat || null
    md.value = r.markdown || ''
    const n = stat.value?.students ?? 0
    msg.value = n ? `✅ 已汇总 ${n} 名学生` : '（暂无评阅结果）'
  } catch (e) {
    msg.value = `读取失败：${String((e as Error).message || e)}`
  } finally { loading.value = false }
}

watch(() => [props.classDir, props.taskId, props.reloadKey], () => { void load() },
      { immediate: true })

/** 知识点共现矩阵：只取前 N 个知识点，避免图过大不可读。 */
const MATRIX_N = 8
const matrixTerms = computed<string[]>(() =>
  (stat.value?.knowledge_errors || []).slice(0, MATRIX_N).map((x) => x.term))

/** (i,j) → 同时出错人数（对称矩阵） */
const matrixCell = computed<Record<string, number>>(() => {
  const out: Record<string, number> = {}
  for (const c of stat.value?.cooccurrence || []) {
    out[`${c.a}|${c.b}`] = c.students
    out[`${c.b}|${c.a}`] = c.students
  }
  return out
})
const matrixMax = computed(() => {
  let m = 1
  for (const c of stat.value?.cooccurrence || []) m = Math.max(m, c.students)
  return m
})
function cellCount(a: string, b: string): number {
  return a === b ? 0 : (matrixCell.value[`${a}|${b}`] || 0)
}
function cellColor(n: number): string {
  if (!n) return '#f3f4f6'
  const t = Math.min(1, n / matrixMax.value)
  // 由浅黄到深红：越深=同时错的学生越多
  const r = 254, g = Math.round(254 - 150 * t), b = Math.round(240 - 200 * t)
  return `rgb(${r},${g},${b})`
}

/** 得分率柱状图几何 */
const BARS_W = 520
const BARS_H = 150
const barGeom = computed(() => {
  const rows = stat.value?.question_rates || []
  if (!rows.length) return []
  const gap = 10
  const w = Math.max(16, (BARS_W - gap * (rows.length - 1)) / rows.length)
  return rows.map((r, i) => ({
    ...r,
    x: i * (w + gap),
    w,
    h: Math.max(2, Math.round(r.rate * (BARS_H - 24))),
  }))
})
function rateColor(rate: number): string {
  if (rate >= 0.8) return '#16a34a'
  if (rate >= 0.6) return '#d97706'
  return '#dc2626'
}

const segments = computed(() => {
  const s = stat.value?.segments || {}
  return ['90-100', '80-89', '70-79', '60-69', '<60'].map((k) => ({ k, n: s[k] || 0 }))
})
const segMax = computed(() => Math.max(1, ...segments.value.map((x) => x.n)))
</script>

<template>
  <div class="teacher-card">
    <div class="tc-head">
      <h3 style="margin:0">📊 教师总结报告（易错知识点 / 共现 / 得分率）</h3>
      <span class="hint" style="margin:0">只给教师，<b>不上传、不发学生</b>；纯统计不调模型。</span>
      <span style="flex:1"></span>
      <button class="btn small" :disabled="loading || !canLoad" @click="load(true)">
        重新汇总
      </button>
      <button class="btn small" :disabled="exporting !== '' || !canLoad"
              @click="exportReport('png')">
        {{ exporting === 'png' ? '导出中…' : '导出 PNG' }}
      </button>
      <button class="btn small" :disabled="exporting !== '' || !canLoad"
              @click="exportReport('pdf')">
        {{ exporting === 'pdf' ? '导出中…' : '导出 PDF' }}
      </button>
    </div>

    <p v-if="!canLoad" class="hint">先在 ③ 区选择作业（需要班级目录 + 批阅目录键）。</p>
    <p v-else-if="loading" class="hint">正在汇总评阅结果…</p>
    <p v-else-if="msg" class="hint">{{ msg }}</p>
    <p v-if="exportMsg" class="hint">{{ exportMsg }}</p>

    <template v-if="stat && stat.students">
      <!-- 概览 -->
      <div class="ov">
        <div class="ov-item"><b>{{ stat.students }}</b><span>已评阅</span></div>
        <div class="ov-item"><b>{{ stat.avg }}</b><span>平均分</span></div>
        <div class="ov-item"><b>{{ stat.max }} / {{ stat.min }}</b><span>最高 / 最低</span></div>
        <div class="ov-item"><b>{{ stat.manual }}</b><span>需人工</span></div>
        <div class="ov-item"><b>{{ stat.substitution }}</b><span>顶替嫌疑</span></div>
      </div>

      <!-- 易错知识点 -->
      <h4>① 易错知识点（按出错人数）</h4>
      <p v-if="!stat.knowledge_errors.length" class="hint">
        （无知识点级错误记录：本次批阅可能没有产出 errors[].knowledge，或全班答对。）
      </p>
      <table v-else class="tc-table">
        <thead><tr><th>知识点</th><th>出错人数</th><th>出错率</th><th>题号</th></tr></thead>
        <tbody>
          <tr v-for="x in stat.knowledge_errors" :key="x.term">
            <td><b>{{ x.term }}</b></td>
            <td class="c">{{ x.students }}</td>
            <td class="c">{{ Math.round(x.rate * 100) }}%</td>
            <td class="c">{{ x.questions.join('、') || '—' }}</td>
          </tr>
        </tbody>
      </table>

      <!-- 共现矩阵 -->
      <h4>② 易错点共现矩阵（同生同时错的人数）</h4>
      <p v-if="matrixTerms.length < 2" class="hint">
        （知识点不足 2 个，无法形成共现矩阵。）
      </p>
      <div v-else class="mx-wrap">
        <svg :width="(MATRIX_N + 1) * 78" :height="(matrixTerms.length + 1) * 30"
             class="mx">
          <g v-for="(t, j) in matrixTerms" :key="'h' + t">
            <text :x="78 + j * 78" y="18" font-size="11" text-anchor="middle">
              {{ t.length > 5 ? t.slice(0, 5) + '…' : t }}
            </text>
          </g>
          <g v-for="(row, i) in matrixTerms" :key="'r' + row">
            <text x="74" :y="46 + i * 30" font-size="11" text-anchor="end">
              {{ row.length > 6 ? row.slice(0, 6) + '…' : row }}
            </text>
            <g v-for="(col, j) in matrixTerms" :key="'c' + i + '-' + j">
              <rect :x="78 + j * 78 - 30" :y="30 + i * 30" width="60" height="24"
                    rx="3" :fill="i === j ? '#e5e7eb' : cellColor(cellCount(row, col))"
                    stroke="#d1d5db" stroke-width="0.5" />
              <text v-if="i !== j && cellCount(row, col)"
                    :x="78 + j * 78" :y="46 + i * 30" font-size="11"
                    text-anchor="middle" fill="#111827">
                {{ cellCount(row, col) }}
              </text>
            </g>
          </g>
        </svg>
        <p class="hint" style="margin:4px 0">
          颜色越深=同时出错的学生越多（对角线为自身，不统计）。可用于判断是否同一个概念没讲透。
        </p>
      </div>

      <!-- 得分率 -->
      <h4>③ 逐题得分率（越低越该讲）</h4>
      <p v-if="!barGeom.length" class="hint">（无逐题分数记录。）</p>
      <template v-else>
        <svg :width="BARS_W" :height="BARS_H + 20" class="bars">
          <g v-for="b in barGeom" :key="'b' + b.id">
            <rect :x="b.x" :y="BARS_H - b.h" :width="b.w" :height="b.h"
                  :fill="rateColor(b.rate)" rx="2" />
            <text :x="b.x + b.w / 2" :y="BARS_H - b.h - 3" font-size="10"
                  text-anchor="middle">{{ Math.round(b.rate * 100) }}%</text>
            <text :x="b.x + b.w / 2" :y="BARS_H + 13" font-size="10"
                  text-anchor="middle">第{{ b.id }}题</text>
          </g>
        </svg>
        <p class="hint" style="margin:2px 0">
          绿 ≥80% ／ 橙 60–79% ／ 红 &lt;60%。满分按题数分摊（与计分口径一致）。
        </p>
      </template>

      <!-- 分数段 -->
      <h4>④ 分数段分布</h4>
      <div class="seg">
        <div v-for="s in segments" :key="s.k" class="seg-item">
          <div class="seg-bar-wrap">
            <div class="seg-bar" :style="{ height: `${Math.round((s.n / segMax) * 70)}px` }" />
          </div>
          <div class="hint" style="margin:0">{{ s.k }}</div>
          <div style="font-size:12px"><b>{{ s.n }}</b> 人</div>
        </div>
      </div>

      <!-- 题型 -->
      <template v-if="stat.kind_stats.length">
        <h4>⑤ 按题目来源（题型）</h4>
        <table class="tc-table">
          <thead><tr><th>题型</th><th>题次</th><th>平均扣分</th><th>累计扣分</th></tr></thead>
          <tbody>
            <tr v-for="k in stat.kind_stats" :key="k.kind">
              <td>{{ k.kind }}</td><td class="c">{{ k.questions }}</td>
              <td class="c">{{ k.avg_deduct }}</td><td class="c">{{ k.total_deduct }}</td>
            </tr>
          </tbody>
        </table>
      </template>

      <!-- 本章遗漏 -->
      <template v-if="stat.missing.length">
        <h4>⑥ 本章遗漏知识点（依据课堂资料清单）</h4>
        <table class="tc-table">
          <thead><tr><th>知识点</th><th>遗漏人数</th><th>占比</th></tr></thead>
          <tbody>
            <tr v-for="m in stat.missing" :key="m.term">
              <td><b>{{ m.term }}</b></td><td class="c">{{ m.students }}</td>
              <td class="c">{{ Math.round(m.rate * 100) }}%</td>
            </tr>
          </tbody>
        </table>
      </template>

      <p style="margin-top:10px">
        <button class="btn small" @click="showMd = !showMd">
          {{ showMd ? '收起 Markdown 原文' : '查看 Markdown 原文' }}
        </button>
      </p>
      <pre v-if="showMd" class="md">{{ md }}</pre>
    </template>
  </div>
</template>

<style scoped>
.teacher-card { border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px 12px;
                margin-top: 10px; }
.tc-head { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.ov { display: flex; gap: 10px; flex-wrap: wrap; margin: 8px 0; }
.ov-item { border: 1px solid #e5e7eb; border-radius: 6px; padding: 6px 10px;
           display: flex; flex-direction: column; min-width: 84px; }
.ov-item b { font-size: 16px; }
.ov-item span { font-size: 11px; color: #6b7280; }
.tc-table { border-collapse: collapse; font-size: 13px; margin-top: 4px; }
.tc-table th, .tc-table td { border: 1px solid #e5e7eb; padding: 3px 8px; }
.tc-table th { background: #f9fafb; font-weight: 600; }
.tc-table td.c { text-align: center; }
.mx-wrap { overflow: auto; max-width: 100%; }
.bars { display: block; }
.seg { display: flex; gap: 14px; align-items: flex-end; margin-top: 6px; }
.seg-item { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.seg-bar-wrap { height: 72px; display: flex; align-items: flex-end; }
.seg-bar { width: 26px; background: #2563eb; border-radius: 2px 2px 0 0; min-height: 1px; }
.md { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px; padding: 8px;
      font-size: 12px; max-height: 420px; overflow: auto; white-space: pre-wrap; }
.hint { color: #6b7280; font-size: 12px; }
</style>

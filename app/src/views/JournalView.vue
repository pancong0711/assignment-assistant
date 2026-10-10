<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { clearJournal, fetchJournal, type JournalEvent } from '../lib/engineClient'
import { useSettingsStore } from '../stores/settings'

/* D74-9：全局操作记录（所有选项卡的操作都在这里）。
 * 数据=引擎 xxt_home()/journal/YYYY-MM.jsonl（按月分片，保留 6 个月）。
 * 只读展示 + 时间范围过滤 + 导出 JSON + 清空；不做“重复操作”。 */
const settings = useSettingsStore()
const engUrl = computed(() => settings.engineUrl)
const tok = computed(() => settings.engineToken)

const events = ref<JournalEvent[]>([])
const stats = ref<{ files?: number; bytes?: number; months?: number }>({})
const start = ref('')
const end = ref('')
const kindFilter = ref('')
const msg = ref('')
const loading = ref(false)

function norm(dt: string): string {
  // datetime-local -> "YYYY-MM-DD HH:MM:SS"
  return dt ? dt.replace('T', ' ') + (dt.length === 16 ? ':00' : '') : ''
}

async function load() {
  loading.value = true
  msg.value = ''
  try {
    const r = await fetchJournal(engUrl.value, tok.value, {
      start: norm(start.value), end: norm(end.value),
      kind: kindFilter.value || undefined, limit: 1000,
    })
    events.value = r.events
    stats.value = r.stats
    if (!r.events.length) msg.value = '暂无操作记录（或当前时间范围内为空）'
  } catch (e) {
    msg.value = `引擎不可达或读取失败：${String(e)}`
  } finally {
    loading.value = false
  }
}

function paramText(e: JournalEvent): string {
  try { return JSON.stringify(e.params || {}) } catch { return '{}' }
}

function exportJson() {
  const blob = new Blob([JSON.stringify({
    exported_at: new Date().toISOString(),
    range: { start: norm(start.value), end: norm(end.value) },
    count: events.value.length,
    events: events.value,
  }, null, 2)], { type: 'application/json;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
  a.download = `operation-log-${stamp}.json`
  a.click()
  URL.revokeObjectURL(a.href)
}

async function clearAll() {
  if (!confirm(`清空全部操作记录？当前 ${events.value.length} 条（仅本机引擎，不可恢复）。`)) return
  try {
    const n = await clearJournal(engUrl.value, tok.value)
    msg.value = `已清空 ${n} 个日志文件`
    await load()
  } catch (e) {
    msg.value = `清空失败：${String(e)}`
  }
}

onMounted(load)
</script>

<template>
  <section>
    <h2>操作记录 <small style="font-weight:400;color:var(--c-muted)">全局 · 所有选项卡的操作 · 本机 JSONL · 保留 6 个月</small></h2>
    <div class="card">
      <p>
        <label class="field">从：<input v-model="start" type="datetime-local" /></label>
        <label class="field" style="margin-left:8px">到：<input v-model="end" type="datetime-local" /></label>
        <label class="field" style="margin-left:8px">类型：
          <input v-model="kindFilter" placeholder="如 xxt_extract" style="width:150px" />
        </label>
        <button class="btn primary" style="margin-left:8px" :disabled="loading" @click="load">
          {{ loading ? '读取中…' : '🔄 查询' }}
        </button>
        <button class="btn" style="margin-left:8px" :disabled="!events.length" @click="exportJson">⬇ 导出 JSON</button>
        <button class="btn" style="margin-left:8px" @click="clearAll">🗑 清空记录</button>
      </p>
      <p class="hint" style="color:var(--c-muted)">
        日志文件 {{ stats.files ?? 0 }} 个 · 约 {{ ((stats.bytes || 0) / 1024).toFixed(1) }} KB ·
        保留最近 {{ stats.months ?? 6 }} 个月（滚动删除）
      </p>
      <p v-if="msg" class="hint">{{ msg }}</p>
      <div style="overflow:auto; max-height:min(70vh, 620px); border:1px solid var(--c-border); border-radius:8px">
        <table style="width:100%; border-collapse:collapse">
          <thead>
            <tr style="position:sticky; top:0; background:var(--c-surface,#fff)">
              <th style="text-align:left; padding:6px 8px">时间</th>
              <th style="padding:6px 8px">类型</th>
              <th style="padding:6px 8px">来源</th>
              <th style="padding:6px 8px">结果</th>
              <th style="padding:6px 8px">run</th>
              <th style="padding:6px 8px">耗时</th>
              <th style="text-align:left; padding:6px 8px">参数 / 错误</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(e, i) in events" :key="i">
              <td style="padding:5px 8px; white-space:nowrap">{{ e.ts }}</td>
              <td style="padding:5px 8px; white-space:nowrap">{{ e.kind }}</td>
              <td style="padding:5px 8px; text-align:center">{{ e.source }}</td>
              <td style="padding:5px 8px; text-align:center"
                  :style="{ color: e.result === 'ok' ? 'var(--c-ok,#16a34a)' : 'var(--c-danger,#dc2626)' }">
                {{ e.result === 'ok' ? '✅' : '⚠ 失败' }}
              </td>
              <td style="padding:5px 8px; white-space:nowrap">{{ e.run_id || '—' }}</td>
              <td style="padding:5px 8px; text-align:right; white-space:nowrap">
                {{ e.duration_ms != null ? `${(e.duration_ms / 1000).toFixed(1)}s` : '—' }}
              </td>
              <td style="padding:5px 8px; font-size:12px; word-break:break-all">
                {{ paramText(e) }}
                <span v-if="e.error" style="color:var(--c-danger,#dc2626)">｜{{ e.error }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

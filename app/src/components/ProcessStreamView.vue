<script setup lang="ts">
/** D64-b：导航过程展示流（从 XxetongView 抽出的共享组件，§25.1-N3）。
 *  数据=run steps[]（engine 只读产物）+ /xxt/shot/<run>/<file> 截图端点；
 *  props：runId/steps/engineAddr/token；页宽横向滚动缩略卡流（卡=截图+动作+页标题）。
 *  复用件：学习通 tab（提取过程）、批阅 tab（批阅过程）同源同款。 */
import { toRef } from 'vue'

const props = defineProps<{
  runId: string
  steps: { action: string; detail?: string; title?: string; url?: string; ts?: string; shot?: string }[]
  engineAddr: string
  token?: string
}>()

const engUrl = toRef(props, 'engineAddr')
const tok = toRef(props, 'token')
const runId = toRef(props, 'runId')

function shotUrl(shot?: string): string {
  if (!shot) { return '' }
  const fname = shot.split('/').pop() || ''
  const tokArg = tok.value ? `?token=${encodeURIComponent(tok.value)}` : ''
  return `${engUrl.value.replace(/\/+$/, '')}/xxt/shot/${runId.value || ''}/${fname}${tokArg}`
}
</script>

<template>
  <div v-if="steps && steps.length">
    <div style="display:flex; gap:10px; overflow-x:auto; padding-bottom:6px">
      <div v-for="(st, i) in steps" :key="i"
           style="min-width:190px; border:1px solid var(--c-border); border-radius:8px; overflow:hidden; background:var(--c-surface,#fff)">
        <img v-if="st.shot" :src="shotUrl(st.shot)" :alt="st.action" style="width:190px; height:107px; object-fit:cover; display:block" />
        <div style="padding:6px 8px">
          <div style="font-size:12px"><b>{{ i+1 }}. {{ st.action }}</b></div>
          <div class="hint" style="font-size:11px; color:var(--c-muted); word-break:break-all">
            {{ st.detail || '' }} · {{ st.title || (st.url || '').slice(0, 46) }}<br /><span style="opacity:.7">{{ st.ts }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

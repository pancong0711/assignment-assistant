<script setup lang="ts">
/** D92-R4：逐生审核弹窗（左右两栏；与「作业预览-学习通」的只读逐生预览不同——
 *  右上=AI 批语（只读，可"另存修订版"）；右下=人工批阅 + 模式（不批阅/覆盖/人工在前+附件AI/修订AI）。
 *  左=学生作答图（可上/下一位、旋转）。保存写回双套草稿（不覆盖 AI 原文）。 */
import { computed, ref, watch } from 'vue'
import { saveXxtGradeDraft, xxtReviewFileUrl } from '../lib/engineClient'

const props = defineProps<{
  engineAddr: string; token?: string
  classId: string; workId: string
  students: { name: string; key: string; tag?: string }[]
  drafts: Record<string, any>
  startIndex?: number
}>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'saved'): void; (e: 'notify', m: string): void }>()

const idx = ref(props.startIndex ?? 0)
const rotate = ref(0)
const layout = ref<'cols' | 'rows'>('cols')
const msg = ref('')

const cur = computed(() => props.students[idx.value] || null)
const draft = computed(() => (cur.value ? (props.drafts[cur.value.key] || {}) : {}))
const aiSet = computed(() => draft.value.ai || {})
const revisionText = computed(() => String((draft.value.revision || {}).text || ''))

/** 作答图片：来自 drafts 里 images（若有），否则由预览端点提供（此处用 review file URL 由父级传入？）。
 *  简化：作答图片用草稿里可能带有的 images；无则提示去「作业预览-学习通」查看。 */
const answerImages = computed<string[]>(() => (draft.value.images as string[]) || [])

/* 人工批阅编辑态 */
const score = ref(''); const comment = ref(''); const humanMode = ref('none')
const revising = ref(false); const revDraft = ref('')

watch([idx, () => props.drafts], () => {
  const d = props.drafts[cur.value?.key || ''] || {}
  score.value = d?.human?.score !== undefined && d?.human?.score !== null
    ? String(d.human.score) : (d?.ai?.score !== undefined && d?.ai?.score !== null ? String(d.ai.score) : '100')
  comment.value = String(d?.human?.comment || '')
  humanMode.value = String(d?.humanMode || (d?.human?.used ? 'replace' : 'none'))
  revDraft.value = String((d?.revision || {}).text || '')
  revising.value = false
}, { immediate: true })

function prev() { if (idx.value > 0) idx.value-- }
function next() { if (idx.value < props.students.length - 1) idx.value++ }
function imgUrl(f: string) { return xxtReviewFileUrl(props.engineAddr, props.token, props.classId, props.workId, f) }

function startRevise() { revising.value = true; revDraft.value = revisionText.value || String(aiSet.value.comment || '') }

async function save() {
  const c = cur.value
  if (!c) return
  const n = score.value.trim() === '' ? null : Number(score.value)
  const payload: any = {
    classId: props.classId, workId: props.workId, key: c.key, student: c.name,
    human_mode: humanMode.value,
  }
  if (humanMode.value !== 'none') {
    payload.human = { score: Number.isFinite(n as number) ? n : null, comment: comment.value, used: true }
  }
  if (revising.value && revDraft.value.trim()) {
    payload.revision = { text: revDraft.value }
  }
  const r = await saveXxtGradeDraft(props.engineAddr, props.token, payload)
  if (r?.ok) { emit('notify', `已保存 ${c.name} 的审核（模式 ${humanMode.value}）`); emit('saved') }
  else msg.value = r?.error || '保存失败'
}
</script>

<template>
  <div class="backdrop" @click.self="emit('close')">
    <div class="modal" style="max-width:min(1200px,96vw); width:96vw; max-height:92vh; overflow:auto">
      <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap">
        <h3 style="margin:0">逐生审核：{{ cur?.name || '—' }}
          <span class="hint" style="font-weight:400">（第 {{ idx + 1 }} / {{ students.length }} 位 · tag {{ cur?.tag || '—' }}）</span>
        </h3>
        <span style="flex:1"></span>
        <button class="btn" :disabled="idx <= 0" @click="prev">← 上一位</button>
        <button class="btn" :disabled="idx >= students.length - 1" @click="next">下一位 →</button>
        <button class="btn" @click="rotate = (rotate - 90 + 360) % 360">↺ 左旋</button>
        <button class="btn" @click="rotate = (rotate + 90) % 360">↻ 右旋</button>
        <button class="btn" @click="layout = layout === 'cols' ? 'rows' : 'cols'">
          {{ layout === 'cols' ? '⇵ 上下布局' : '⇋ 左右布局' }}
        </button>
        <button class="btn" @click="emit('close')">关闭</button>
      </div>

      <div style="display:flex; gap:14px; align-items:flex-start; flex-wrap:wrap; margin-top:10px"
           :style="{ flexDirection: layout === 'rows' ? 'column' : 'row' }">
        <!-- 左栏：学生作答 -->
        <div :style="{ flex: layout === 'rows' ? 'none' : '1', minWidth: '280px', width: layout === 'rows' ? '100%' : 'auto' }">
          <h4>学生作答</h4>
          <div style="border:1px solid var(--c-border); border-radius:8px; padding:6px; max-height:62vh; overflow:auto;
                      display:flex; flex-direction:column; gap:8px">
            <img v-for="f in answerImages" :key="f" :src="imgUrl(f)" :alt="f"
                 :style="{ width:'100%', height:'auto', objectFit:'contain', transform:`rotate(${rotate}deg)`, borderRadius:'6px' }" />
            <span v-if="!answerImages.length" class="hint">（本弹窗未加载作答图：作答图请在「作业预览-学习通 → 逐生预览」查看；此处专注审核批语。）</span>
          </div>
        </div>

        <!-- 右栏：AI 批语（上）/ 人工批阅（下） -->
        <div :style="{ flex: layout === 'rows' ? 'none' : '1.1', minWidth: '300px', width: layout === 'rows' ? '100%' : 'auto' }">
          <h4>AI 批语 <span class="hint" style="font-weight:400">（只读基线{{ aiSet.score != null ? ` · 评分 ${aiSet.score}` : '' }}）</span></h4>
          <div style="border:1px solid var(--c-border); border-radius:8px; padding:8px; white-space:pre-wrap; min-height:80px;
                      background:var(--c-bg-soft,#f8fafc)">
            <span v-if="revisionText">（已另存修订版，见下）</span>
            <span v-else>{{ aiSet.comment || '（无 AI 批语：请先跑 AI 批阅）' }}</span>
          </div>
          <p style="margin:6px 0">
            <button class="btn small" @click="startRevise">{{ revisionText ? '编辑修订版' : '另存修订版…' }}</button>
            <span class="hint" style="margin-left:8px">
              修订 = 在 AI 批语基础上改；报告将按行**标红**改动，AI 原文不被覆盖。
            </span>
          </p>
          <textarea v-if="revising" v-model="revDraft" rows="5" style="width:100%; font-family:inherit"
                    placeholder="AI 批语的人工修订版（支持 LaTeX $...$）"></textarea>

          <h4 style="margin-top:10px">人工批阅（可选）</h4>
          <p style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin:0 0 6px">
            <label class="field">模式
              <select v-model="humanMode">
                <option value="none">不批阅（仅 AI）</option>
                <option value="replace">覆盖 AI（报告=人工批阅报告）</option>
                <option value="append">人工在前 + AI 作附件</option>
                <option value="revise">修订 AI（报告=AI批阅报告（人工修订））</option>
              </select>
            </label>
            <label class="field">分数 <input v-model="score" type="number" min="0" max="100" style="width:80px" /></label>
          </p>
          <textarea v-model="comment" rows="4" style="width:100%; font-family:inherit"
                    placeholder="人工批语（支持 LaTeX；模式=none/revise 时可留空）"></textarea>
          <p style="margin:8px 0 0; display:flex; gap:8px; align-items:center">
            <button class="btn primary" @click="save">💾 保存到本地（不覆盖 AI 原文）</button>
            <span class="hint" v-if="msg">{{ msg }}</span>
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/** D148：「知识点」选项卡 —— AI 知识点标注 + 题库 AI 作答 + 受控词表。
 *
 *  为什么单独一页：这几件事互相咬合（标注 → 词表 → 要点 → 批阅依据），
 *  放在题库编辑器里会被"编辑题目"的动线淹没。
 *
 *  安全口径：写题库（标注 apply / 写答案）都必须教师**显式确认**，先 dry-run 看影响面。
 */
import { computed, onMounted, ref } from 'vue'
import { useSettingsStore } from '../stores/settings'
import { KB_KINDS, KB_KIND_LABELS, type KbKind } from '../lib/kb'
import {
  fetchKbCatalog, fetchKnowledgeVocab, generateRubricBatch, tagKnowledge,
  type KnowledgeTerm,
} from '../lib/engineClient'

const settings = useSettingsStore()

/* ---------- 通用 ---------- */
const msg = ref('')
const busy = ref('')
const terms = ref<KnowledgeTerm[]>([])
const chaps = ref<string[]>([])
const kind = ref<KbKind>('problems')
const chap = ref('')

async function loadVocab() {
  try {
    const r = await fetchKnowledgeVocab(settings.engineUrl, settings.engineToken)
    terms.value = r?.terms || []
  } catch { terms.value = [] }
}

async function loadChaps() {
  try {
    const r = await fetchKbCatalog(settings.engineUrl, settings.engineToken)
    const set = new Set<string>()
    for (const k of Object.keys((r as any)?.catalog || {})) {
      for (const c of Object.keys((r as any).catalog[k] || {})) set.add(c)
    }
    chaps.value = [...set].sort()
    if (!chap.value && chaps.value.length) chap.value = chaps.value[0]!
  } catch { chaps.value = [] }
}

onMounted(async () => { await loadVocab(); await loadChaps() })

const termByChapter = computed(() => {
  const m: Record<string, KnowledgeTerm[]> = {}
  for (const t of terms.value) {
    const c = t.chapter || '（未归章）'
    ;(m[c] ||= []).push(t)
  }
  return m
})

/* ---------- ① AI 知识点标注 ---------- */
const tagDry = ref<{ updates: number; sample: any[] } | null>(null)
const tagForce = ref(false)

async function doTagPreview() {
  busy.value = 'tag'
  msg.value = ''
  tagDry.value = null
  try {
    const r = await tagKnowledge(settings.engineUrl, settings.engineToken, {
      kb: [kind.value], chap: chap.value ? [chap.value] : [], force: tagForce.value,
      dryRun: true,
    })
    if (!r?.ok) { msg.value = `❌ ${r?.error || '预览失败'}`; return }
    const ups = (r.updates || []) as any[]
    tagDry.value = { updates: ups.length, sample: ups.slice(0, 8) }
    msg.value = `预览完成：将更新 ${ups.length} 题的知识点`
  } catch (e) { msg.value = `预览失败：${String((e as Error).message || e)}` }
  finally { busy.value = '' }
}

async function doTagApply() {
  if (!window.confirm('将**写回题库**（知识点列），并自动快照。确认执行？')) return
  busy.value = 'tag'
  msg.value = '正在写回题库（可能需要几分钟）…'
  try {
    const r = await tagKnowledge(settings.engineUrl, settings.engineToken, {
      kb: [kind.value], chap: chap.value ? [chap.value] : [], force: tagForce.value,
      dryRun: false,
    })
    const n = (r?.updates || []).length
    const f = (r?.failed || []).length
    msg.value = r?.ok
      ? `✅ 已标注 ${n} 题${f ? `（${f} 题失败）` : ''}；词表已同步`
      : `❌ ${r?.error || '标注失败'}`
    tagDry.value = null
    await loadVocab()
  } catch (e) { msg.value = `标注失败：${String((e as Error).message || e)}` }
  finally { busy.value = '' }
}

/* ---------- ② 题库 AI 作答（生成要点） ---------- */
const rubKind = ref<KbKind>('problems')
const rubChap = ref('')
const rubForce = ref(false)
const rubPreview = ref<any[]>([])

async function doRubricPreview() {
  busy.value = 'rub'
  msg.value = ''
  rubPreview.value = []
  try {
    const r = await generateRubricBatch(settings.engineUrl, settings.engineToken, {
      kind: rubKind.value, chap: rubChap.value || undefined, apply: false,
    })
    if (r?.skipped) {
      msg.value = `⚠️ ${r.reason || '按口径不生成'}\n`
        + (r.howTo ? `\n怎么做：\n${r.howTo.join('\n')}` : '')
      return
    }
    if (!r?.ok) { msg.value = `❌ ${r?.error || '预览失败'}`; return }
    rubPreview.value = (r.preview || []) as any[]
    msg.value = `预览完成：${rubPreview.value.length} 题（尚未写入）`
  } catch (e) { msg.value = `预览失败：${String((e as Error).message || e)}` }
  finally { busy.value = '' }
}

async function doRubricApply() {
  if (!window.confirm('将把「参考解答 + 评阅要点」写入答案版本库（**默认不置顶**）。确认？')) return
  busy.value = 'rub'
  msg.value = '正在生成（可能需要几分钟）…'
  try {
    const r = await generateRubricBatch(settings.engineUrl, settings.engineToken, {
      kind: rubKind.value, chap: rubChap.value || undefined, apply: true,
      force: rubForce.value,
    })
    if (r?.skipped) { msg.value = `⚠️ ${r.reason || '按口径不生成'}`; return }
    const n = (r?.written || []).length
    msg.value = r?.ok ? `✅ 已写入 ${n} 题的要点（未置顶，需你核对后置顶）`
      : `❌ ${r?.error || '生成失败'}`
    rubPreview.value = []
  } catch (e) { msg.value = `生成失败：${String((e as Error).message || e)}` }
  finally { busy.value = '' }
}
</script>

<template>
  <div class="wrap">
    <h2 style="margin:0 0 4px">知识点（AI 标注 / 题库 AI 作答 / 词表）</h2>
    <p class="hint" style="margin:0 0 8px">
      批阅与教师报告里的“易错知识点”来自这里的标注；
      <b>写题库/写答案都会先快照，且需要你确认</b>。
    </p>
    <p v-if="msg" class="hint" style="white-space:pre-wrap; color:#7a5c00">{{ msg }}</p>

    <div class="grid">
      <!-- ① 标注 -->
      <section class="card">
        <h3>① AI 知识点标注</h3>
        <p class="hint">
          让 AI 读题目，把物理概念写进题库的 <code>related</code> 列。
          默认<b>只标未标注</b>的题（不覆盖教师已写的）。
        </p>
        <div class="row">
          <label class="field">题型
            <select v-model="kind">
              <option v-for="k in KB_KINDS" :key="k" :value="k">{{ KB_KIND_LABELS[k] || k }}</option>
            </select>
          </label>
          <label class="field">章节
            <select v-model="chap">
              <option value="">（全部章节）</option>
              <option v-for="c in chaps" :key="c" :value="c">{{ c }}</option>
            </select>
          </label>
          <label class="field"><input v-model="tagForce" type="checkbox" /> 覆盖已有标注</label>
        </div>
        <p style="margin:6px 0">
          <button class="btn" :disabled="busy !== ''" @click="doTagPreview">
            {{ busy === 'tag' ? '处理中…' : '① 预览（dry-run）' }}
          </button>
          <button class="btn primary" :disabled="busy !== '' || !tagDry"
                  @click="doTagApply">② 确认写回题库</button>
        </p>
        <template v-if="tagDry">
          <p class="hint">将更新 {{ tagDry.updates }} 题，示例：</p>
          <table class="tbl">
            <thead><tr><th>题号</th><th>建议知识点</th></tr></thead>
            <tbody>
              <tr v-for="(u, i) in tagDry.sample" :key="i">
                <td>{{ u.qid }}</td><td>{{ u.related }}</td>
              </tr>
            </tbody>
          </table>
        </template>
      </section>

      <!-- ② 要点 -->
      <section class="card">
        <h3>② 题库 AI 作答（参考解答 + 评阅要点）</h3>
        <p class="hint">
          一次产出「参考解答 + 评阅要点 + 知识点」，写入答案版本库；
          <b>默认不置顶</b>（你核对后再置顶才生效）。
        </p>
        <div class="row">
          <label class="field">题型
            <select v-model="rubKind">
              <option v-for="k in KB_KINDS" :key="k" :value="k">{{ KB_KIND_LABELS[k] || k }}</option>
            </select>
          </label>
          <label class="field">章节
            <select v-model="rubChap">
              <option value="">（全部章节）</option>
              <option v-for="c in chaps" :key="c" :value="c">{{ c }}</option>
            </select>
          </label>
          <label class="field"><input v-model="rubForce" type="checkbox" /> 强制（copy/summary）</label>
        </div>
        <p style="margin:6px 0">
          <button class="btn" :disabled="busy !== ''" @click="doRubricPreview">
            {{ busy === 'rub' ? '处理中…' : '① 预览' }}
          </button>
          <button class="btn primary" :disabled="busy !== ''" @click="doRubricApply">
            ② 生成并写入
          </button>
        </p>
        <details v-if="rubPreview.length" open>
          <summary class="hint" style="cursor:pointer">预览 {{ rubPreview.length }} 题</summary>
          <pre class="md">{{ rubPreview.slice(0, 3).map((x) => x.text).join('\n\n---\n\n') }}</pre>
        </details>
      </section>

      <!-- ③ 词表 -->
      <section class="card">
        <h3>③ 受控知识点词表</h3>
        <p class="hint">
          共 {{ terms.length }} 个术语（按章分组）。AI 标注时优先沿用这里的写法，避免同义漂移。
        </p>
        <p v-if="!terms.length" class="hint">
          （还没有词表：先做一次「① AI 知识点标注」，或 CLI <code>kb vocab harvest</code>。）
        </p>
        <details v-for="(ts, c) in termByChapter" :key="c">
          <summary class="hint" style="cursor:pointer">{{ c }}（{{ ts.length }}）</summary>
          <div class="terms">
            <span v-for="t in ts" :key="t.term" class="term">
              {{ t.term }}<template v-if="t.topic"> · {{ t.topic }}</template>
            </span>
          </div>
        </details>
      </section>
    </div>
  </div>
</template>

<style scoped>
.wrap { padding: 12px 14px; }
.grid { display: flex; flex-direction: column; gap: 14px; }
.card { border: 1px solid #e5e7eb; border-radius: 10px; padding: 10px 12px; }
.card h3 { margin: 0 0 6px; }
.hint { color: #6b7280; font-size: 12px; }
.row { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; margin: 6px 0; }
.field { display: flex; gap: 6px; align-items: center; font-size: 13px; }
.tbl { border-collapse: collapse; font-size: 12px; width: 100%; }
.tbl th, .tbl td { border: 1px solid #e5e7eb; padding: 3px 8px; }
.tbl th { background: #f9fafb; }
.md { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px; padding: 8px;
      font-size: 12px; max-height: 240px; overflow: auto; white-space: pre-wrap; }
.terms { display: flex; gap: 6px; flex-wrap: wrap; margin: 4px 0 6px; }
.term { background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 999px;
        padding: 1px 8px; font-size: 12px; }
</style>

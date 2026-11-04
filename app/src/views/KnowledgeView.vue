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
import KbAiSolvePanel from '../components/KbAiSolvePanel.vue'
import TeacherReportCard from '../components/TeacherReportCard.vue'
import TrendCard from '../components/TrendCard.vue'
import { KB_KINDS, KB_KIND_LABELS, type KbKind } from '../lib/kb'
import {
  PROMPT_CATEGORIES, PROMPT_CATEGORY_LABELS, fetchKbCatalog, fetchKnowledgeVocab,
  fetchPromptTemplatesByCategory, fetchTeacherReportMulti, fetchWorkspaceClasses,
  postPromptTemplateCategory,
  tagKnowledge, type KnowledgeTerm, type PromptCategory, type PromptTemplate,
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

onMounted(async () => {
  await loadVocab(); await loadChaps(); await loadTemplates(); await loadClasses()
})

/* ---------- ④ 提示词模板（D151：5 类 system prompt 可改/可存/可删） ---------- */
const tplCat = ref<PromptCategory>('evaluate')
const tplItems = ref<PromptTemplate[]>([])
const tplSel = ref('')
const tplText = ref('')
const tplName = ref('')
const tplBusy = ref(false)
const tplMsg = ref('')

const tplCurrent = computed(() => tplItems.value.find((t) => t.id === tplSel.value) || null)
const tplIsBuiltin = computed(() => !!tplCurrent.value?.builtin)

/* ---------- ⑤ 教师报告（D153：班级 / 作业包 / tag 多选） ---------- */
const wClasses = ref<Array<{ classDir: string; name: string; packs: string[] }>>([])
const selClasses = ref<string[]>([])
const selPacks = ref<string[]>([])
const selTags = ref<string>('')
const repBusy = ref(false)
const repStat = ref<any>(null)
const repSources = ref<string[]>([])
const repMsg = ref('')

/** 所有可选作业包（按所选班级取并集）。 */
const packOptions = computed(() => {
  const out = new Set<string>()
  for (const c of wClasses.value) {
    if (selClasses.value.length && !selClasses.value.includes(c.classDir)) continue
    for (const p of c.packs || []) out.add(p)
  }
  return [...out].sort()
})

async function loadClasses() {
  try {
    const r = await fetchWorkspaceClasses(settings.engineUrl, settings.engineToken)
    wClasses.value = r?.classes || []
  } catch { wClasses.value = [] }
}

async function genReport() {
  if (!selClasses.value.length || !selPacks.value.length) {
    repMsg.value = '请至少勾选一个班级和一个作业包'
    return
  }
  repBusy.value = true
  repMsg.value = '正在汇总…'
  try {
    const r = await fetchTeacherReportMulti(settings.engineUrl, settings.engineToken, {
      classDirs: selClasses.value, packIds: selPacks.value,
      tags: selTags.value.split(',').map((x) => x.trim()).filter(Boolean),
    })
    if (!r?.ok) {
      repStat.value = null
      repMsg.value = `❌ ${r?.error || '生成失败'}${r?.hint ? `（${r.hint}）` : ''}`
      return
    }
    repStat.value = r.stat || null
    repSources.value = r.sources || []
    repMsg.value = `✅ 已汇总 ${r.records} 份评阅（${repSources.value.length} 个作业包×班级）`
  } catch (e) {
    repMsg.value = `生成失败：${String((e as Error).message || e)}`
  } finally { repBusy.value = false }
}

async function loadTemplates() {
  try {
    const r = await fetchPromptTemplatesByCategory(settings.engineUrl, settings.engineToken,
                                                   tplCat.value)
    tplItems.value = r?.items || []
    if (!tplSel.value || !tplItems.value.some((t) => t.id === tplSel.value)) {
      tplSel.value = r?.default || tplItems.value[0]?.id || ''
    }
    pickTemplate()
  } catch { tplItems.value = [] }
}

function pickTemplate() {
  const t = tplCurrent.value
  tplName.value = t?.name || ''
  tplText.value = t?.text || ''
  tplMsg.value = t?.text ? '' : '（内容为空 = 使用代码内置默认；填写后覆盖）'
}

async function onTplCatChange() { tplSel.value = ''; await loadTemplates() }

async function saveTpl(asNew: boolean) {
  if (!tplText.value.trim()) { tplMsg.value = '内容为空'; return }
  const id = asNew ? `custom-${Date.now().toString(36)}` : tplSel.value
  if (!id) { tplMsg.value = '请先选择模板'; return }
  tplBusy.value = true
  try {
    const r = await postPromptTemplateCategory(settings.engineUrl, settings.engineToken, {
      category: tplCat.value, action: 'save', id,
      name: tplName.value || id, text: tplText.value,
    })
    if (!r?.ok) { tplMsg.value = `❌ ${r?.error || '保存失败'}`; return }
    tplSel.value = id
    tplItems.value = r.items || []
    tplMsg.value = '✅ 已保存（下次调用生效）'
  } catch (e) { tplMsg.value = `保存失败：${String((e as Error).message || e)}` }
  finally { tplBusy.value = false }
}

async function setTplDefault() {
  if (!tplSel.value) return
  tplBusy.value = true
  try {
    const r = await postPromptTemplateCategory(settings.engineUrl, settings.engineToken, {
      category: tplCat.value, action: 'default', id: tplSel.value,
    })
    tplItems.value = r?.items || tplItems.value
    tplMsg.value = r?.ok ? '✅ 已设为该类默认' : `❌ ${r?.error || ''}`
  } finally { tplBusy.value = false }
}

async function deleteTpl() {
  if (!tplSel.value || tplIsBuiltin.value) return
  if (!window.confirm('删除该模板？（不影响其他类别）')) return
  tplBusy.value = true
  try {
    const r = await postPromptTemplateCategory(settings.engineUrl, settings.engineToken, {
      category: tplCat.value, action: 'delete', id: tplSel.value,
    })
    if (!r?.ok) { tplMsg.value = `❌ ${r?.error || ''}`; return }
    tplItems.value = r.items || []
    tplSel.value = ''
    await loadTemplates()
    tplMsg.value = '✅ 已删除'
  } finally { tplBusy.value = false }
}

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

      <!-- ② 题库 AI 作答（D152：⑦ 区整体平移过来，能力与批阅页一致） -->
      <section class="card">
        <h3>② 题库 AI 作答（参考解答 + 评阅要点 + 知识点）</h3>
        <p class="hint">
          一次可完成三件事：参考解答 / 评阅要点 / 知识点标注。
          默认<b>不置顶</b>（你核对后再置顶才生效）。
        </p>
        <KbAiSolvePanel :engine-addr="settings.engineUrl" :token="settings.engineToken" />
      </section>

      <!-- ④ 提示词模板（D151） -->
      <section class="card">
        <h3>④ 提示词模板（可改 / 可存 / 可另存 / 可删）</h3>
        <p class="hint">
          不选模板 = 使用<b>内置默认</b>（与改动前完全一致）。
          <code>转录</code>/<code>批阅</code> 两类改完请先跑一次试跑验证。
        </p>
        <div class="row">
          <label class="field">类别
            <select :value="tplCat" @change="tplCat = ($event.target as HTMLSelectElement).value as PromptCategory; onTplCatChange()">
              <option v-for="c in PROMPT_CATEGORIES" :key="c" :value="c">
                {{ PROMPT_CATEGORY_LABELS[c] }}
              </option>
            </select>
          </label>
          <label class="field">模板
            <select v-model="tplSel" @change="pickTemplate">
              <option v-for="t in tplItems" :key="t.id" :value="t.id">
                {{ t.default ? '★ ' : '' }}{{ t.name }}{{ t.builtin ? '（内置）' : '' }}
              </option>
            </select>
          </label>
          <span v-if="tplIsBuiltin" class="hint">内置模板不可删（可"另存为"后修改）</span>
        </div>
        <label class="field" style="display:block; margin:4px 0">
          名称 <input v-model="tplName" style="width:260px" />
        </label>
        <textarea v-model="tplText" rows="6"
                  placeholder="留空 = 使用代码内置默认"
                  style="width:100%; max-width:820px; font-family:monospace; font-size:12px;
                         padding:6px 8px; border:1px solid #d1d5db; border-radius:6px"></textarea>
        <p style="margin:6px 0">
          <button class="btn" :disabled="tplBusy" @click="saveTpl(false)">💾 保存</button>
          <button class="btn" :disabled="tplBusy" @click="saveTpl(true)">＋ 另存为</button>
          <button class="btn" :disabled="tplBusy || !tplSel" @click="setTplDefault">设为默认</button>
          <button class="btn" :disabled="tplBusy || !tplSel || tplIsBuiltin" @click="deleteTpl">🗑 删除</button>
          <span v-if="tplMsg" class="hint" style="margin-left:8px">{{ tplMsg }}</span>
        </p>
      </section>

      <!-- ⑤ 教师报告（D153：多选班级/作业包/tag） -->
      <section class="card">
        <h3>⑤ 教师总结报告（可多选班级 / 作业包 / tag）</h3>
        <p class="hint">
          勾选多个班级与作业包即可看**宏观**情况；tag 留空 = 全部学生。
        </p>
        <p v-if="!wClasses.length" class="hint">
          （还没有班级目录：先在「AI 辅助批阅」跑一次批阅。）
        </p>
        <template v-else>
          <div class="row">
            <span class="hint" style="margin:0">班级：</span>
            <label v-for="c in wClasses" :key="c.classDir" class="field">
              <input v-model="selClasses" type="checkbox" :value="c.classDir" />
              {{ c.name }}（{{ (c.packs || []).length }} 个作业包）
            </label>
          </div>
          <div class="row">
            <span class="hint" style="margin:0">作业包：</span>
            <label v-for="p in packOptions" :key="p" class="field">
              <input v-model="selPacks" type="checkbox" :value="p" />
              {{ p }}
            </label>
            <span v-if="!packOptions.length" class="hint">（所选班级还没有评阅结果）</span>
          </div>
          <div class="row">
            <label class="field">tag（逗号分隔，留空=全部）
              <input v-model="selTags" placeholder="top,middle" style="width:200px" />
            </label>
            <button class="btn primary" :disabled="repBusy" @click="genReport">
              {{ repBusy ? '汇总中…' : '生成报告' }}
            </button>
            <span v-if="repMsg" class="hint" style="margin:0">{{ repMsg }}</span>
          </div>
          <p v-if="repSources.length" class="hint" style="margin:2px 0">
            本次汇总：{{ repSources.join('；') }}
          </p>
          <div v-if="repStat" style="margin-top:8px">
            <table class="tbl">
              <thead><tr><th>指标</th><th>值</th></tr></thead>
              <tbody>
                <tr><td>已评阅</td><td>{{ repStat.students }} 人</td></tr>
                <tr><td>平均分</td><td>{{ repStat.avg }}</td></tr>
                <tr><td>最高 / 最低</td><td>{{ repStat.max }} / {{ repStat.min }}</td></tr>
                <tr><td>易错知识点（前 5）</td>
                  <td>{{ (repStat.knowledge_errors || []).slice(0, 5)
                    .map((x: any) => `${x.term}(${x.students}人)`).join('、') || '—' }}</td></tr>
              </tbody>
            </table>
          </div>
        </template>

        <!-- 单次作业的详细报告卡 / 跨作业趋势卡（D153：从批阅页搬来） -->
        <template v-if="repSources.length === 1 && selClasses.length">
          <TeacherReportCard :engine-addr="settings.engineUrl" :token="settings.engineToken"
                             :class-dir="selClasses[0]!" :task-id="selPacks[0]!"
                             :reload-key="0" />
        </template>
        <TrendCard v-if="selClasses.length === 1"
                   :engine-addr="settings.engineUrl" :token="settings.engineToken"
                   :class-dir="selClasses[0]!" :reload-key="0" />
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

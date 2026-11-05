<script setup lang="ts">
/** D148：「知识点」选项卡 —— AI 知识点标注 + 题库 AI 作答 + 受控词表。
 *
 *  为什么单独一页：这几件事互相咬合（标注 → 词表 → 要点 → 批阅依据），
 *  放在题库编辑器里会被"编辑题目"的动线淹没。
 *
 *  安全口径：写题库（标注 apply / 写答案）都必须教师**显式确认**，先 dry-run 看影响面。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useSettingsStore } from '../stores/settings'
import KbAiSolvePanel from '../components/KbAiSolvePanel.vue'
import { tidyKbRelated, applyKbRelatedTidy, type RelatedTidyItem,
  fetchErrorRates, fetchCooccurrence, type ErrorRateReport,
  type CooccurrenceGraph } from '../lib/engineClient'
import TeacherReportCard from '../components/TeacherReportCard.vue'
import TrendCard from '../components/TrendCard.vue'
import { KB_KINDS, KB_KIND_LABELS, type KbKind } from '../lib/kb'
import {
  PROMPT_CATEGORIES, PROMPT_CATEGORY_LABELS, fetchKbCatalog, fetchKnowledgeVocab,
  fetchPromptTemplatesByCategory, fetchTeacherReportMulti, fetchWorkspaceClasses,
  postPromptTemplateCategory,
  tagKnowledge, type KbCatalogKind, type KnowledgeTerm, type PromptCategory,
  type PromptTemplate,
} from '../lib/engineClient'

const settings = useSettingsStore()

/* ---------- 通用 ---------- */
const msg = ref('')
const busy = ref('')
const terms = ref<KnowledgeTerm[]>([])
const kind = ref<KbKind>('problems')
const chap = ref('')

async function loadVocab() {
  try {
    const r = await fetchKnowledgeVocab(settings.engineUrl, settings.engineToken)
    terms.value = r?.terms || []
  } catch { terms.value = [] }
}

/* D164 修复：此前读的是 `r.catalog`（**接口不返回这个字段**，只有 `kinds`）
 * → 章节列表永远为空，看起来像"不能选章节 / 等于全选"。 */
const catalog = ref<KbCatalogKind[]>([])

/** 当前题型下的章节（切题型时联动）。 */
const chaps = computed<string[]>(() => {
  const k = catalog.value.find((x) => x.kind === kind.value)
  return (k?.chapters || []).map((c) => c.chap)
})

async function loadChaps() {
  try {
    const r = await fetchKbCatalog(settings.engineUrl, settings.engineToken)
    catalog.value = r?.kinds || []
    if (!chaps.value.includes(chap.value)) chap.value = chaps.value[0] || ''
  } catch { catalog.value = [] }
}

/** 切题型时，若当前章节不属于新题型 → 回到该题型第一个章节。 */
watch(kind, () => {
  if (!chaps.value.includes(chap.value)) chap.value = chaps.value[0] || ''
})

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

/* ---------- D166：AI 再整理（归一/合并/拆分，逐题确认） ---------- */
const tidyItems = ref<RelatedTidyItem[]>([])
const tidyPick = ref<Set<string>>(new Set())
const tidyForce = ref(false)
const tidyMsg = ref('')
const tidyBusy = ref(false)

async function doTidyPreview() {
  tidyBusy.value = true
  tidyMsg.value = '正在让 AI 整理知识点（会产生模型费用）…'
  tidyItems.value = []
  tidyPick.value = new Set()
  try {
    const r = await tidyKbRelated(settings.engineUrl, settings.engineToken, {
      kb: kind.value, chap: chap.value || undefined, force: tidyForce.value,
    })
    if (!r?.ok) { tidyMsg.value = `❌ ${r?.error || '整理失败'}`; return }
    const items = (r.items || []).filter((it) => it.diff?.changed)
    tidyItems.value = items
    // 默认勾选**有变化**的题（没变化的不用教师操作）
    tidyPick.value = new Set(items.map((it) => it.qid))
    const skipped = (r.skipped || []).length
    tidyMsg.value = items.length
      ? `整理完成：${items.length} 题有建议变更${skipped ? `；${skipped} 题跳过（教师锁定）` : ''}。逐题核对后勾选写入。`
      : `整理完成：没有需要变更的题目${skipped ? `（${skipped} 题因教师锁定被跳过）` : ''}。`
  } catch (e) {
    tidyMsg.value = `整理失败：${String((e as Error).message || e)}`
  } finally { tidyBusy.value = false }
}

function toggleTidy(qid: string) {
  const s = new Set(tidyPick.value)
  if (s.has(qid)) s.delete(qid); else s.add(qid)
  tidyPick.value = s
}

async function doTidyApply() {
  const picked = tidyItems.value.filter((it) => tidyPick.value.has(it.qid))
  if (!picked.length) { tidyMsg.value = '没有勾选任何题目'; return }
  if (!window.confirm(`将把 ${picked.length} 题的知识点写回题库（追加新版本 + 自动快照）。确认？`)) return
  tidyBusy.value = true
  try {
    const r = await applyKbRelatedTidy(settings.engineUrl, settings.engineToken,
      picked.map((it) => ({ qid: it.qid, kb: it.kb, chap: it.chap,
                            terms: it.diff.after, note: it.note || 'AI 再整理' })))
    tidyMsg.value = r?.ok
      ? `✅ 已写入 ${r.written} 题（旧版本保留，可回退）`
      : `❌ ${r?.error || '写入失败'}`
    if (r?.ok) { tidyItems.value = []; tidyPick.value = new Set() }
  } catch (e) {
    tidyMsg.value = `写入失败：${String((e as Error).message || e)}`
  } finally { tidyBusy.value = false }
}

/* ---------- D168：知识点加权失误率 + 共现（多班 × 多包 × 多 tag） ---------- */
const anaBusy = ref(false)
const anaMsg = ref('')
const anaReport = ref<ErrorRateReport | null>(null)
const anaCo = ref<{ overall?: CooccurrenceGraph; byTag?: Record<string, CooccurrenceGraph>
                    tags?: string[] } | null>(null)
const anaClusters = ref<Array<{ id: string; members: string[]; size: number }>>([])
const anaOnlyKnown = ref(true)

async function runAnalysis() {
  if (!selClasses.value.length) { anaMsg.value = '请先勾选班级'; return }
  const packs = packOptions.value.filter((p) => selPacks.value.includes(p))
  if (!packs.length) { anaMsg.value = '请先勾选作业包'; return }
  anaBusy.value = true
  anaMsg.value = '正在统计…'
  anaReport.value = null
  anaCo.value = null
  anaClusters.value = []
  try {
    const tags = selTags.value.split(/[,，\s]+/).map((x) => x.trim()).filter(Boolean)
    const rep = await fetchErrorRates(settings.engineUrl, settings.engineToken,
      { classes: selClasses.value, packs, tags, onlyKnown: anaOnlyKnown.value })
    if (!rep?.ok) { anaMsg.value = `❌ ${rep?.error || '统计失败'}`; return }
    anaReport.value = rep
    const co = await fetchCooccurrence(settings.engineUrl, settings.engineToken,
      { classes: selClasses.value, packs, tags, n: 2 })
    if (co?.ok && co.graphs) {
      anaCo.value = co.graphs
      anaClusters.value = co.clusters?.clusters || []
    }
    anaMsg.value = `✅ 统计完成：${(rep.items || []).length} 个知识点`
      + (rep.tagSource === 'roster' ? '；⚠ 部分作业包没有 roster 快照，tag 取自当前名单' : '')
  } catch (e) {
    anaMsg.value = `统计失败：${String((e as Error).message || e)}`
  } finally { anaBusy.value = false }
}

function confOf(rep: ErrorRateReport | null) {
  return rep?.confidence || { level: 'ok' as const, reasons: [] }
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

      <!-- ①-B D166：AI 再整理（归一/合并/拆分） -->
      <section class="card">
        <h3>①-B AI 再整理知识点（归一 / 合并 / 拆分）</h3>
        <p class="hint">
          把同一概念的不同写法合并（如「动量守恒律」→「动量守恒」）、统一到受控词表术语。
          <b>只产出建议</b>，你逐题核对勾选后才写回（追加版本，不覆盖历史）。
          教师锁定的题默认跳过。
        </p>
        <div class="row">
          <label class="field"><input v-model="tidyForce" type="checkbox" />
            连教师锁定的题也整理（慎用）</label>
          <button class="btn" :disabled="tidyBusy" @click="doTidyPreview">
            {{ tidyBusy ? '整理中…' : '🤖 生成整理建议' }}
          </button>
          <button class="btn primary" :disabled="tidyBusy || !tidyPick.size"
                  @click="doTidyApply">
            写入勾选的 {{ tidyPick.size }} 题
          </button>
        </div>
        <p v-if="tidyMsg" class="hint" style="white-space:pre-wrap">{{ tidyMsg }}</p>
        <table v-if="tidyItems.length" class="tbl">
          <thead>
            <tr><th style="width:30px"></th><th>题号</th><th>整理前</th><th>整理后</th><th>说明</th></tr>
          </thead>
          <tbody>
            <tr v-for="it in tidyItems" :key="it.qid">
              <td><input type="checkbox" :checked="tidyPick.has(it.qid)"
                         @change="toggleTidy(it.qid)" /></td>
              <td>{{ it.qid }}</td>
              <td class="hint">{{ it.diff.before.join('、') || '（空）' }}</td>
              <td>
                <span v-for="t in it.diff.after" :key="t" class="term" style="margin-right:4px">{{ t }}</span>
                <span v-for="t in it.diff.removed" :key="'r' + t"
                      class="hint" style="margin-right:4px; text-decoration:line-through">{{ t }}</span>
              </td>
              <td class="hint">{{ it.note || '—' }}</td>
            </tr>
          </tbody>
        </table>
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

      <!-- ⑤-B D168：知识点加权失误率 + 共现（可跨班/跨包/跨 tag） -->
      <section class="card">
        <h3>⑤-B 知识点失误分析（加权失误率 / 共现 / 自然聚类）</h3>
        <p class="hint">
          口径：<b>扣分制无固定每题满分</b>，所以看<b>失误次数</b>而不是得分率；
          同一题同一知识点错 2 次记 2 次。
          <b>加权失误率</b> = Σ_tag（该 tag 失误率 × 该 tag 已提交人数占比），单位「次/人」。
          统计口径以 <code>docs/112-D168</code> 为准。
        </p>
        <div class="row">
          <label class="field"><input v-model="anaOnlyKnown" type="checkbox" />
            只统计词表内/已标注术语（词表外单独计数）</label>
          <button class="btn" :disabled="anaBusy" @click="runAnalysis">
            {{ anaBusy ? '统计中…' : '📊 统计失误率与共现' }}
          </button>
          <span v-if="anaMsg" class="hint" style="margin:0">{{ anaMsg }}</span>
        </div>

        <template v-if="anaReport?.items?.length">
          <p class="hint" style="margin:6px 0 2px">
            提交人数：{{ anaReport.totalSubmitted }} 人
            <span v-if="anaReport.submittedByTag">
              （{{ Object.entries(anaReport.submittedByTag)
                    .map(([k, v]) => `${k}:${v}`).join('，') }}）
            </span>
            <span v-if="anaReport.tagSource === 'snapshot'">· tag 取自<b>作业包快照</b>（可复现）</span>
            <span v-else-if="anaReport.tagSource === 'roster'" style="color:#b45309">
              · ⚠ tag 取自<b>当前名单</b>（该包没有快照，建议先在班级页冻结）
            </span>
          </p>
          <p v-if="confOf(anaReport).level === 'low'" style="color:#b45309; font-size:12px; margin:0 0 6px">
            ⚠ 样本可信度低：{{ confOf(anaReport).reasons.join('；') }}
            —— 失误率数字仅供参考
          </p>
          <table class="tbl">
            <thead>
              <tr>
                <th>知识点</th><th>加权失误率</th><th>失误次数</th><th>出错人数</th>
                <th>分 tag 明细</th><th>涉及题号</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="it in anaReport.items" :key="it.term">
                <td>{{ it.term }}</td>
                <td><b>{{ it.rate }}</b></td>
                <td class="c">{{ it.errorCount }}</td>
                <td class="c">{{ it.errStudents }}</td>
                <td class="hint">
                  {{ Object.entries(it.byTag).map(([k, v]) => `${k}:${v}`).join('，') || '—' }}
                </td>
                <td class="hint">{{ it.questions.join('、') || '—' }}</td>
              </tr>
            </tbody>
          </table>
          <p v-if="Object.keys(anaReport.unclassified || {}).length"
             class="hint" style="margin:4px 0 0; color:#b45309">
            词表外术语（未进主统计）：
            {{ Object.entries(anaReport.unclassified || {}).map(([k, v]) => `${k}×${v}`).join('，') }}
          </p>
          <p v-if="anaReport.crossPack && Object.keys(anaReport.crossPack.terms || {}).length"
             class="hint" style="margin:4px 0 0">
            跨包口径（Σ失误 ÷ Σ总题数 = {{ anaReport.crossPack.totalQuestions }} 题）：
            {{ Object.entries(anaReport.crossPack.terms)
                .map(([k, v]) => `${k} ${v.rate}（${v.errorCount}次 / ${v.totalQuestions}题）`)
                .join('；') }}
          </p>
        </template>

        <template v-if="anaCo?.tags?.length">
          <h4 style="margin:10px 0 2px">知识点共现（每个 tag 一张图）</h4>
          <p class="hint" style="margin:0 0 4px">
            <b>归一化关联</b> = P(共现) ÷ ∏P(单项)：&gt;1 表示比随机更常同时出错。
            tag 必须拆开看——不同档位的学生错法不同，混算会糊成一团。
          </p>
          <p class="hint" style="margin:0 0 2px"><b>全局</b>（{{ anaCo.overall?.total }} 题）</p>
          <p v-if="!(anaCo.overall?.combos || []).length" class="hint">（无共现组合）</p>
          <ul v-else style="margin:0 0 6px 16px; padding:0; font-size:13px">
            <li v-for="c in (anaCo.overall?.combos || []).slice(0, 8)" :key="c.terms.join('+')">
              {{ c.terms.join(' ＋ ') }}　共现 {{ c.count }} 次 · 关联 {{ c.association }}
            </li>
          </ul>
          <details v-for="t in anaCo.tags" :key="t" style="margin-bottom:4px">
            <summary class="hint" style="cursor:pointer">
              tag「{{ t }}」：{{ anaCo.byTag?.[t]?.total }} 题，
              {{ (anaCo.byTag?.[t]?.combos || []).length }} 组共现
            </summary>
            <ul style="margin:2px 0 0 16px; padding:0; font-size:13px">
              <li v-for="c in (anaCo.byTag?.[t]?.combos || []).slice(0, 8)"
                  :key="t + c.terms.join('+')">
                {{ c.terms.join(' ＋ ') }}　共现 {{ c.count }} 次 · 关联 {{ c.association }}
              </li>
              <li v-if="!(anaCo.byTag?.[t]?.combos || []).length" class="hint">（无共现组合）</li>
            </ul>
          </details>
          <template v-if="anaClusters.length">
            <p class="hint" style="margin:6px 0 2px">
              自然聚类（按共现耦合，不依赖章节层级）：
            </p>
            <div v-for="c in anaClusters" :key="c.id" style="margin-bottom:3px">
              <span class="hint">{{ c.id }}（{{ c.size }}）：</span>
              <span v-for="m in c.members" :key="m" class="term" style="margin-right:4px">{{ m }}</span>
            </div>
          </template>
        </template>
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

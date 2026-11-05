import { defineComponent as _defineComponent } from 'vue'
import { computed, onMounted, ref, watch } from 'vue'
import { useSettingsStore } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/stores/settings'
import KbAiSolvePanel from '/home/bot2603/Projects/2609-assignment-assistant/app/tests/KbAiSolvePanel.compiled-pi5ca0.ts'
import { tidyKbRelated, applyKbRelatedTidy, type RelatedTidyItem } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/engineClient'
import TeacherReportCard from '/home/bot2603/Projects/2609-assignment-assistant/app/tests/TeacherReportCard.compiled-gbyede.ts'
import TrendCard from '/home/bot2603/Projects/2609-assignment-assistant/app/tests/TrendCard.compiled-dfiz13.ts'
import { KB_KINDS, KB_KIND_LABELS, type KbKind } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/kb'
import {
  PROMPT_CATEGORIES, PROMPT_CATEGORY_LABELS, fetchKbCatalog, fetchKnowledgeVocab,
  fetchPromptTemplatesByCategory, fetchTeacherReportMulti, fetchWorkspaceClasses,
  postPromptTemplateCategory,
  tagKnowledge, type KbCatalogKind, type KnowledgeTerm, type PromptCategory,
  type PromptTemplate,
} from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/engineClient'


const __sfc_main = /*@__PURE__*/_defineComponent({
  __name: 'KnowledgeView',
  setup(__props, { expose: __expose }) {
  __expose();

/** D148：「知识点」选项卡 —— AI 知识点标注 + 题库 AI 作答 + 受控词表。
 *
 *  为什么单独一页：这几件事互相咬合（标注 → 词表 → 要点 → 批阅依据），
 *  放在题库编辑器里会被"编辑题目"的动线淹没。
 *
 *  安全口径：写题库（标注 apply / 写答案）都必须教师**显式确认**，先 dry-run 看影响面。
 */
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


const __returned__ = { settings, msg, busy, terms, kind, chap, loadVocab, catalog, chaps, loadChaps, tplCat, tplItems, tplSel, tplText, tplName, tplBusy, tplMsg, tplCurrent, tplIsBuiltin, wClasses, selClasses, selPacks, selTags, repBusy, repStat, repSources, repMsg, packOptions, loadClasses, genReport, loadTemplates, pickTemplate, onTplCatChange, saveTpl, setTplDefault, deleteTpl, termByChapter, tagDry, tagForce, doTagPreview, doTagApply, tidyItems, tidyPick, tidyForce, tidyMsg, tidyBusy, doTidyPreview, toggleTidy, doTidyApply, KbAiSolvePanel, TeacherReportCard, TrendCard, get KB_KINDS() { return KB_KINDS }, get KB_KIND_LABELS() { return KB_KIND_LABELS }, get PROMPT_CATEGORIES() { return PROMPT_CATEGORIES }, get PROMPT_CATEGORY_LABELS() { return PROMPT_CATEGORY_LABELS } }
Object.defineProperty(__returned__, '__isScriptSetup', { enumerable: false, value: true })
return __returned__
}

})
import { createElementVNode as _createElementVNode, createTextVNode as _createTextVNode, toDisplayString as _toDisplayString, openBlock as _openBlock, createElementBlock as _createElementBlock, createCommentVNode as _createCommentVNode, renderList as _renderList, Fragment as _Fragment, vModelSelect as _vModelSelect, withDirectives as _withDirectives, vModelCheckbox as _vModelCheckbox, createVNode as _createVNode, vModelText as _vModelText, createBlock as _createBlock } from "vue"

const _hoisted_1 = { class: "wrap" }
const _hoisted_2 = {
  key: 0,
  class: "hint",
  style: {"white-space":"pre-wrap","color":"#7a5c00"}
}
const _hoisted_3 = { class: "grid" }
const _hoisted_4 = { class: "card" }
const _hoisted_5 = { class: "row" }
const _hoisted_6 = { class: "field" }
const _hoisted_7 = ["value"]
const _hoisted_8 = { class: "field" }
const _hoisted_9 = ["value"]
const _hoisted_10 = { class: "field" }
const _hoisted_11 = { style: {"margin":"6px 0"} }
const _hoisted_12 = ["disabled"]
const _hoisted_13 = ["disabled"]
const _hoisted_14 = { class: "hint" }
const _hoisted_15 = { class: "tbl" }
const _hoisted_16 = { class: "card" }
const _hoisted_17 = { class: "row" }
const _hoisted_18 = { class: "field" }
const _hoisted_19 = ["disabled"]
const _hoisted_20 = ["disabled"]
const _hoisted_21 = {
  key: 0,
  class: "hint",
  style: {"white-space":"pre-wrap"}
}
const _hoisted_22 = {
  key: 1,
  class: "tbl"
}
const _hoisted_23 = ["checked", "onChange"]
const _hoisted_24 = { class: "hint" }
const _hoisted_25 = { class: "hint" }
const _hoisted_26 = { class: "card" }
const _hoisted_27 = { class: "card" }
const _hoisted_28 = { class: "row" }
const _hoisted_29 = { class: "field" }
const _hoisted_30 = ["value"]
const _hoisted_31 = ["value"]
const _hoisted_32 = { class: "field" }
const _hoisted_33 = ["value"]
const _hoisted_34 = {
  key: 0,
  class: "hint"
}
const _hoisted_35 = {
  class: "field",
  style: {"display":"block","margin":"4px 0"}
}
const _hoisted_36 = { style: {"margin":"6px 0"} }
const _hoisted_37 = ["disabled"]
const _hoisted_38 = ["disabled"]
const _hoisted_39 = ["disabled"]
const _hoisted_40 = ["disabled"]
const _hoisted_41 = {
  key: 0,
  class: "hint",
  style: {"margin-left":"8px"}
}
const _hoisted_42 = { class: "card" }
const _hoisted_43 = {
  key: 0,
  class: "hint"
}
const _hoisted_44 = { class: "row" }
const _hoisted_45 = ["value"]
const _hoisted_46 = { class: "row" }
const _hoisted_47 = ["value"]
const _hoisted_48 = {
  key: 0,
  class: "hint"
}
const _hoisted_49 = { class: "row" }
const _hoisted_50 = { class: "field" }
const _hoisted_51 = ["disabled"]
const _hoisted_52 = {
  key: 0,
  class: "hint",
  style: {"margin":"0"}
}
const _hoisted_53 = {
  key: 0,
  class: "hint",
  style: {"margin":"2px 0"}
}
const _hoisted_54 = {
  key: 1,
  style: {"margin-top":"8px"}
}
const _hoisted_55 = { class: "tbl" }
const _hoisted_56 = { class: "card" }
const _hoisted_57 = { class: "hint" }
const _hoisted_58 = {
  key: 0,
  class: "hint"
}
const _hoisted_59 = {
  class: "hint",
  style: {"cursor":"pointer"}
}
const _hoisted_60 = { class: "terms" }

export function render(_ctx, _cache, $props, $setup, $data, $options) {
  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _cache[43] || (_cache[43] = _createElementVNode("h2", { style: {"margin":"0 0 4px"} }, "知识点（AI 标注 / 题库 AI 作答 / 词表）", -1 /* CACHED */)),
    _cache[44] || (_cache[44] = _createElementVNode("p", {
      class: "hint",
      style: {"margin":"0 0 8px"}
    }, [
      _createTextVNode(" 批阅与教师报告里的“易错知识点”来自这里的标注； "),
      _createElementVNode("b", null, "写题库/写答案都会先快照，且需要你确认"),
      _createTextVNode("。 ")
    ], -1 /* CACHED */)),
    ($setup.msg)
      ? (_openBlock(), _createElementBlock("p", _hoisted_2, _toDisplayString($setup.msg), 1 /* TEXT */))
      : _createCommentVNode("v-if", true),
    _createElementVNode("div", _hoisted_3, [
      _createCommentVNode(" ① 标注 "),
      _createElementVNode("section", _hoisted_4, [
        _cache[18] || (_cache[18] = _createElementVNode("h3", null, "① AI 知识点标注", -1 /* CACHED */)),
        _cache[19] || (_cache[19] = _createElementVNode("p", { class: "hint" }, [
          _createTextVNode(" 让 AI 读题目，把物理概念写进题库的 "),
          _createElementVNode("code", null, "related"),
          _createTextVNode(" 列。 默认"),
          _createElementVNode("b", null, "只标未标注"),
          _createTextVNode("的题（不覆盖教师已写的）。 ")
        ], -1 /* CACHED */)),
        _createElementVNode("div", _hoisted_5, [
          _createElementVNode("label", _hoisted_6, [
            _cache[13] || (_cache[13] = _createTextVNode("题型 ", -1 /* CACHED */)),
            _withDirectives(_createElementVNode("select", {
              "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => (($setup.kind) = $event))
            }, [
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.KB_KINDS, (k) => {
                return (_openBlock(), _createElementBlock("option", {
                  key: k,
                  value: k
                }, _toDisplayString($setup.KB_KIND_LABELS[k] || k), 9 /* TEXT, PROPS */, _hoisted_7))
              }), 128 /* KEYED_FRAGMENT */))
            ], 512 /* NEED_PATCH */), [
              [_vModelSelect, $setup.kind]
            ])
          ]),
          _createElementVNode("label", _hoisted_8, [
            _cache[15] || (_cache[15] = _createTextVNode("章节 ", -1 /* CACHED */)),
            _withDirectives(_createElementVNode("select", {
              "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => (($setup.chap) = $event))
            }, [
              _cache[14] || (_cache[14] = _createElementVNode("option", { value: "" }, "（全部章节）", -1 /* CACHED */)),
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.chaps, (c) => {
                return (_openBlock(), _createElementBlock("option", {
                  key: c,
                  value: c
                }, _toDisplayString(c), 9 /* TEXT, PROPS */, _hoisted_9))
              }), 128 /* KEYED_FRAGMENT */))
            ], 512 /* NEED_PATCH */), [
              [_vModelSelect, $setup.chap]
            ])
          ]),
          _createElementVNode("label", _hoisted_10, [
            _withDirectives(_createElementVNode("input", {
              "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => (($setup.tagForce) = $event)),
              type: "checkbox"
            }, null, 512 /* NEED_PATCH */), [
              [_vModelCheckbox, $setup.tagForce]
            ]),
            _cache[16] || (_cache[16] = _createTextVNode(" 覆盖已有标注", -1 /* CACHED */))
          ])
        ]),
        _createElementVNode("p", _hoisted_11, [
          _createElementVNode("button", {
            class: "btn",
            disabled: $setup.busy !== '',
            onClick: $setup.doTagPreview
          }, _toDisplayString($setup.busy === 'tag' ? '处理中…' : '① 预览（dry-run）'), 9 /* TEXT, PROPS */, _hoisted_12),
          _createElementVNode("button", {
            class: "btn primary",
            disabled: $setup.busy !== '' || !$setup.tagDry,
            onClick: $setup.doTagApply
          }, "② 确认写回题库", 8 /* PROPS */, _hoisted_13)
        ]),
        ($setup.tagDry)
          ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
              _createElementVNode("p", _hoisted_14, "将更新 " + _toDisplayString($setup.tagDry.updates) + " 题，示例：", 1 /* TEXT */),
              _createElementVNode("table", _hoisted_15, [
                _cache[17] || (_cache[17] = _createElementVNode("thead", null, [
                  _createElementVNode("tr", null, [
                    _createElementVNode("th", null, "题号"),
                    _createElementVNode("th", null, "建议知识点")
                  ])
                ], -1 /* CACHED */)),
                _createElementVNode("tbody", null, [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.tagDry.sample, (u, i) => {
                    return (_openBlock(), _createElementBlock("tr", { key: i }, [
                      _createElementVNode("td", null, _toDisplayString(u.qid), 1 /* TEXT */),
                      _createElementVNode("td", null, _toDisplayString(u.related), 1 /* TEXT */)
                    ]))
                  }), 128 /* KEYED_FRAGMENT */))
                ])
              ])
            ], 64 /* STABLE_FRAGMENT */))
          : _createCommentVNode("v-if", true)
      ]),
      _createCommentVNode(" ①-B D166：AI 再整理（归一/合并/拆分） "),
      _createElementVNode("section", _hoisted_16, [
        _cache[22] || (_cache[22] = _createElementVNode("h3", null, "①-B AI 再整理知识点（归一 / 合并 / 拆分）", -1 /* CACHED */)),
        _cache[23] || (_cache[23] = _createElementVNode("p", { class: "hint" }, [
          _createTextVNode(" 把同一概念的不同写法合并（如「动量守恒律」→「动量守恒」）、统一到受控词表术语。 "),
          _createElementVNode("b", null, "只产出建议"),
          _createTextVNode("，你逐题核对勾选后才写回（追加版本，不覆盖历史）。 教师锁定的题默认跳过。 ")
        ], -1 /* CACHED */)),
        _createElementVNode("div", _hoisted_17, [
          _createElementVNode("label", _hoisted_18, [
            _withDirectives(_createElementVNode("input", {
              "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => (($setup.tidyForce) = $event)),
              type: "checkbox"
            }, null, 512 /* NEED_PATCH */), [
              [_vModelCheckbox, $setup.tidyForce]
            ]),
            _cache[20] || (_cache[20] = _createTextVNode(" 连教师锁定的题也整理（慎用）", -1 /* CACHED */))
          ]),
          _createElementVNode("button", {
            class: "btn",
            disabled: $setup.tidyBusy,
            onClick: $setup.doTidyPreview
          }, _toDisplayString($setup.tidyBusy ? '整理中…' : '🤖 生成整理建议'), 9 /* TEXT, PROPS */, _hoisted_19),
          _createElementVNode("button", {
            class: "btn primary",
            disabled: $setup.tidyBusy || !$setup.tidyPick.size,
            onClick: $setup.doTidyApply
          }, " 写入勾选的 " + _toDisplayString($setup.tidyPick.size) + " 题 ", 9 /* TEXT, PROPS */, _hoisted_20)
        ]),
        ($setup.tidyMsg)
          ? (_openBlock(), _createElementBlock("p", _hoisted_21, _toDisplayString($setup.tidyMsg), 1 /* TEXT */))
          : _createCommentVNode("v-if", true),
        ($setup.tidyItems.length)
          ? (_openBlock(), _createElementBlock("table", _hoisted_22, [
              _cache[21] || (_cache[21] = _createElementVNode("thead", null, [
                _createElementVNode("tr", null, [
                  _createElementVNode("th", { style: {"width":"30px"} }),
                  _createElementVNode("th", null, "题号"),
                  _createElementVNode("th", null, "整理前"),
                  _createElementVNode("th", null, "整理后"),
                  _createElementVNode("th", null, "说明")
                ])
              ], -1 /* CACHED */)),
              _createElementVNode("tbody", null, [
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.tidyItems, (it) => {
                  return (_openBlock(), _createElementBlock("tr", {
                    key: it.qid
                  }, [
                    _createElementVNode("td", null, [
                      _createElementVNode("input", {
                        type: "checkbox",
                        checked: $setup.tidyPick.has(it.qid),
                        onChange: $event => ($setup.toggleTidy(it.qid))
                      }, null, 40 /* PROPS, NEED_HYDRATION */, _hoisted_23)
                    ]),
                    _createElementVNode("td", null, _toDisplayString(it.qid), 1 /* TEXT */),
                    _createElementVNode("td", _hoisted_24, _toDisplayString(it.diff.before.join('、') || '（空）'), 1 /* TEXT */),
                    _createElementVNode("td", null, [
                      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(it.diff.after, (t) => {
                        return (_openBlock(), _createElementBlock("span", {
                          key: t,
                          class: "term",
                          style: {"margin-right":"4px"}
                        }, _toDisplayString(t), 1 /* TEXT */))
                      }), 128 /* KEYED_FRAGMENT */)),
                      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(it.diff.removed, (t) => {
                        return (_openBlock(), _createElementBlock("span", {
                          key: 'r' + t,
                          class: "hint",
                          style: {"margin-right":"4px","text-decoration":"line-through"}
                        }, _toDisplayString(t), 1 /* TEXT */))
                      }), 128 /* KEYED_FRAGMENT */))
                    ]),
                    _createElementVNode("td", _hoisted_25, _toDisplayString(it.note || '—'), 1 /* TEXT */)
                  ]))
                }), 128 /* KEYED_FRAGMENT */))
              ])
            ]))
          : _createCommentVNode("v-if", true)
      ]),
      _createCommentVNode(" ② 题库 AI 作答（D152：⑦ 区整体平移过来，能力与批阅页一致） "),
      _createElementVNode("section", _hoisted_26, [
        _cache[24] || (_cache[24] = _createElementVNode("h3", null, "② 题库 AI 作答（参考解答 + 评阅要点 + 知识点）", -1 /* CACHED */)),
        _cache[25] || (_cache[25] = _createElementVNode("p", { class: "hint" }, [
          _createTextVNode(" 一次可完成三件事：参考解答 / 评阅要点 / 知识点标注。 默认"),
          _createElementVNode("b", null, "不置顶"),
          _createTextVNode("（你核对后再置顶才生效）。 ")
        ], -1 /* CACHED */)),
        _createVNode($setup["KbAiSolvePanel"], {
          "engine-addr": $setup.settings.engineUrl,
          token: $setup.settings.engineToken
        }, null, 8 /* PROPS */, ["engine-addr", "token"])
      ]),
      _createCommentVNode(" ④ 提示词模板（D151） "),
      _createElementVNode("section", _hoisted_27, [
        _cache[29] || (_cache[29] = _createElementVNode("h3", null, "④ 提示词模板（可改 / 可存 / 可另存 / 可删）", -1 /* CACHED */)),
        _cache[30] || (_cache[30] = _createElementVNode("p", { class: "hint" }, [
          _createTextVNode(" 不选模板 = 使用"),
          _createElementVNode("b", null, "内置默认"),
          _createTextVNode("（与改动前完全一致）。 "),
          _createElementVNode("code", null, "转录"),
          _createTextVNode("/"),
          _createElementVNode("code", null, "批阅"),
          _createTextVNode(" 两类改完请先跑一次试跑验证。 ")
        ], -1 /* CACHED */)),
        _createElementVNode("div", _hoisted_28, [
          _createElementVNode("label", _hoisted_29, [
            _cache[26] || (_cache[26] = _createTextVNode("类别 ", -1 /* CACHED */)),
            _createElementVNode("select", {
              value: $setup.tplCat,
              onChange: _cache[4] || (_cache[4] = $event => {$setup.tplCat = ($event.target as HTMLSelectElement).value as PromptCategory; $setup.onTplCatChange()})
            }, [
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.PROMPT_CATEGORIES, (c) => {
                return (_openBlock(), _createElementBlock("option", {
                  key: c,
                  value: c
                }, _toDisplayString($setup.PROMPT_CATEGORY_LABELS[c]), 9 /* TEXT, PROPS */, _hoisted_31))
              }), 128 /* KEYED_FRAGMENT */))
            ], 40 /* PROPS, NEED_HYDRATION */, _hoisted_30)
          ]),
          _createElementVNode("label", _hoisted_32, [
            _cache[27] || (_cache[27] = _createTextVNode("模板 ", -1 /* CACHED */)),
            _withDirectives(_createElementVNode("select", {
              "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => (($setup.tplSel) = $event)),
              onChange: $setup.pickTemplate
            }, [
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.tplItems, (t) => {
                return (_openBlock(), _createElementBlock("option", {
                  key: t.id,
                  value: t.id
                }, _toDisplayString(t.default ? '★ ' : '') + _toDisplayString(t.name) + _toDisplayString(t.builtin ? '（内置）' : ''), 9 /* TEXT, PROPS */, _hoisted_33))
              }), 128 /* KEYED_FRAGMENT */))
            ], 544 /* NEED_HYDRATION, NEED_PATCH */), [
              [_vModelSelect, $setup.tplSel]
            ])
          ]),
          ($setup.tplIsBuiltin)
            ? (_openBlock(), _createElementBlock("span", _hoisted_34, "内置模板不可删（可\"另存为\"后修改）"))
            : _createCommentVNode("v-if", true)
        ]),
        _createElementVNode("label", _hoisted_35, [
          _cache[28] || (_cache[28] = _createTextVNode(" 名称 ", -1 /* CACHED */)),
          _withDirectives(_createElementVNode("input", {
            "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => (($setup.tplName) = $event)),
            style: {"width":"260px"}
          }, null, 512 /* NEED_PATCH */), [
            [_vModelText, $setup.tplName]
          ])
        ]),
        _withDirectives(_createElementVNode("textarea", {
          "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => (($setup.tplText) = $event)),
          rows: "6",
          placeholder: "留空 = 使用代码内置默认",
          style: {"width":"100%","max-width":"820px","font-family":"monospace","font-size":"12px","padding":"6px 8px","border":"1px solid #d1d5db","border-radius":"6px"}
        }, null, 512 /* NEED_PATCH */), [
          [_vModelText, $setup.tplText]
        ]),
        _createElementVNode("p", _hoisted_36, [
          _createElementVNode("button", {
            class: "btn",
            disabled: $setup.tplBusy,
            onClick: _cache[8] || (_cache[8] = $event => ($setup.saveTpl(false)))
          }, "💾 保存", 8 /* PROPS */, _hoisted_37),
          _createElementVNode("button", {
            class: "btn",
            disabled: $setup.tplBusy,
            onClick: _cache[9] || (_cache[9] = $event => ($setup.saveTpl(true)))
          }, "＋ 另存为", 8 /* PROPS */, _hoisted_38),
          _createElementVNode("button", {
            class: "btn",
            disabled: $setup.tplBusy || !$setup.tplSel,
            onClick: $setup.setTplDefault
          }, "设为默认", 8 /* PROPS */, _hoisted_39),
          _createElementVNode("button", {
            class: "btn",
            disabled: $setup.tplBusy || !$setup.tplSel || $setup.tplIsBuiltin,
            onClick: $setup.deleteTpl
          }, "🗑 删除", 8 /* PROPS */, _hoisted_40),
          ($setup.tplMsg)
            ? (_openBlock(), _createElementBlock("span", _hoisted_41, _toDisplayString($setup.tplMsg), 1 /* TEXT */))
            : _createCommentVNode("v-if", true)
        ])
      ]),
      _createCommentVNode(" ⑤ 教师报告（D153：多选班级/作业包/tag） "),
      _createElementVNode("section", _hoisted_42, [
        _cache[39] || (_cache[39] = _createElementVNode("h3", null, "⑤ 教师总结报告（可多选班级 / 作业包 / tag）", -1 /* CACHED */)),
        _cache[40] || (_cache[40] = _createElementVNode("p", { class: "hint" }, " 勾选多个班级与作业包即可看**宏观**情况；tag 留空 = 全部学生。 ", -1 /* CACHED */)),
        (!$setup.wClasses.length)
          ? (_openBlock(), _createElementBlock("p", _hoisted_43, " （还没有班级目录：先在「AI 辅助批阅」跑一次批阅。） "))
          : (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
              _createElementVNode("div", _hoisted_44, [
                _cache[31] || (_cache[31] = _createElementVNode("span", {
                  class: "hint",
                  style: {"margin":"0"}
                }, "班级：", -1 /* CACHED */)),
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.wClasses, (c) => {
                  return (_openBlock(), _createElementBlock("label", {
                    key: c.classDir,
                    class: "field"
                  }, [
                    _withDirectives(_createElementVNode("input", {
                      "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => (($setup.selClasses) = $event)),
                      type: "checkbox",
                      value: c.classDir
                    }, null, 8 /* PROPS */, _hoisted_45), [
                      [_vModelCheckbox, $setup.selClasses]
                    ]),
                    _createTextVNode(" " + _toDisplayString(c.name) + "（" + _toDisplayString((c.packs || []).length) + " 个作业包） ", 1 /* TEXT */)
                  ]))
                }), 128 /* KEYED_FRAGMENT */))
              ]),
              _createElementVNode("div", _hoisted_46, [
                _cache[32] || (_cache[32] = _createElementVNode("span", {
                  class: "hint",
                  style: {"margin":"0"}
                }, "作业包：", -1 /* CACHED */)),
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.packOptions, (p) => {
                  return (_openBlock(), _createElementBlock("label", {
                    key: p,
                    class: "field"
                  }, [
                    _withDirectives(_createElementVNode("input", {
                      "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => (($setup.selPacks) = $event)),
                      type: "checkbox",
                      value: p
                    }, null, 8 /* PROPS */, _hoisted_47), [
                      [_vModelCheckbox, $setup.selPacks]
                    ]),
                    _createTextVNode(" " + _toDisplayString(p), 1 /* TEXT */)
                  ]))
                }), 128 /* KEYED_FRAGMENT */)),
                (!$setup.packOptions.length)
                  ? (_openBlock(), _createElementBlock("span", _hoisted_48, "（所选班级还没有评阅结果）"))
                  : _createCommentVNode("v-if", true)
              ]),
              _createElementVNode("div", _hoisted_49, [
                _createElementVNode("label", _hoisted_50, [
                  _cache[33] || (_cache[33] = _createTextVNode("tag（逗号分隔，留空=全部） ", -1 /* CACHED */)),
                  _withDirectives(_createElementVNode("input", {
                    "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => (($setup.selTags) = $event)),
                    placeholder: "top,middle",
                    style: {"width":"200px"}
                  }, null, 512 /* NEED_PATCH */), [
                    [_vModelText, $setup.selTags]
                  ])
                ]),
                _createElementVNode("button", {
                  class: "btn primary",
                  disabled: $setup.repBusy,
                  onClick: $setup.genReport
                }, _toDisplayString($setup.repBusy ? '汇总中…' : '生成报告'), 9 /* TEXT, PROPS */, _hoisted_51),
                ($setup.repMsg)
                  ? (_openBlock(), _createElementBlock("span", _hoisted_52, _toDisplayString($setup.repMsg), 1 /* TEXT */))
                  : _createCommentVNode("v-if", true)
              ]),
              ($setup.repSources.length)
                ? (_openBlock(), _createElementBlock("p", _hoisted_53, " 本次汇总：" + _toDisplayString($setup.repSources.join('；')), 1 /* TEXT */))
                : _createCommentVNode("v-if", true),
              ($setup.repStat)
                ? (_openBlock(), _createElementBlock("div", _hoisted_54, [
                    _createElementVNode("table", _hoisted_55, [
                      _cache[38] || (_cache[38] = _createElementVNode("thead", null, [
                        _createElementVNode("tr", null, [
                          _createElementVNode("th", null, "指标"),
                          _createElementVNode("th", null, "值")
                        ])
                      ], -1 /* CACHED */)),
                      _createElementVNode("tbody", null, [
                        _createElementVNode("tr", null, [
                          _cache[34] || (_cache[34] = _createElementVNode("td", null, "已评阅", -1 /* CACHED */)),
                          _createElementVNode("td", null, _toDisplayString($setup.repStat.students) + " 人", 1 /* TEXT */)
                        ]),
                        _createElementVNode("tr", null, [
                          _cache[35] || (_cache[35] = _createElementVNode("td", null, "平均分", -1 /* CACHED */)),
                          _createElementVNode("td", null, _toDisplayString($setup.repStat.avg), 1 /* TEXT */)
                        ]),
                        _createElementVNode("tr", null, [
                          _cache[36] || (_cache[36] = _createElementVNode("td", null, "最高 / 最低", -1 /* CACHED */)),
                          _createElementVNode("td", null, _toDisplayString($setup.repStat.max) + " / " + _toDisplayString($setup.repStat.min), 1 /* TEXT */)
                        ]),
                        _createElementVNode("tr", null, [
                          _cache[37] || (_cache[37] = _createElementVNode("td", null, "易错知识点（前 5）", -1 /* CACHED */)),
                          _createElementVNode("td", null, _toDisplayString(($setup.repStat.knowledge_errors || []).slice(0, 5)
                    .map((x) => `${x.term}(${x.students}人)`).join('、') || '—'), 1 /* TEXT */)
                        ])
                      ])
                    ])
                  ]))
                : _createCommentVNode("v-if", true)
            ], 64 /* STABLE_FRAGMENT */)),
        _createCommentVNode(" 单次作业的详细报告卡 / 跨作业趋势卡（D153：从批阅页搬来） "),
        ($setup.repSources.length === 1 && $setup.selClasses.length)
          ? (_openBlock(), _createBlock($setup["TeacherReportCard"], {
              key: 2,
              "engine-addr": $setup.settings.engineUrl,
              token: $setup.settings.engineToken,
              "class-dir": $setup.selClasses[0]!,
              "task-id": $setup.selPacks[0]!,
              "reload-key": 0
            }, null, 8 /* PROPS */, ["engine-addr", "token", "class-dir", "task-id"]))
          : _createCommentVNode("v-if", true),
        ($setup.selClasses.length === 1)
          ? (_openBlock(), _createBlock($setup["TrendCard"], {
              key: 3,
              "engine-addr": $setup.settings.engineUrl,
              token: $setup.settings.engineToken,
              "class-dir": $setup.selClasses[0]!,
              "reload-key": 0
            }, null, 8 /* PROPS */, ["engine-addr", "token", "class-dir"]))
          : _createCommentVNode("v-if", true)
      ]),
      _createCommentVNode(" ③ 词表 "),
      _createElementVNode("section", _hoisted_56, [
        _cache[42] || (_cache[42] = _createElementVNode("h3", null, "③ 受控知识点词表", -1 /* CACHED */)),
        _createElementVNode("p", _hoisted_57, " 共 " + _toDisplayString($setup.terms.length) + " 个术语（按章分组）。AI 标注时优先沿用这里的写法，避免同义漂移。 ", 1 /* TEXT */),
        (!$setup.terms.length)
          ? (_openBlock(), _createElementBlock("p", _hoisted_58, [...(_cache[41] || (_cache[41] = [
              _createTextVNode(" （还没有词表：先做一次「① AI 知识点标注」，或 CLI ", -1 /* CACHED */),
              _createElementVNode("code", null, "kb vocab harvest", -1 /* CACHED */),
              _createTextVNode("。） ", -1 /* CACHED */)
            ]))]))
          : _createCommentVNode("v-if", true),
        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.termByChapter, (ts, c) => {
          return (_openBlock(), _createElementBlock("details", { key: c }, [
            _createElementVNode("summary", _hoisted_59, _toDisplayString(c) + "（" + _toDisplayString(ts.length) + "）", 1 /* TEXT */),
            _createElementVNode("div", _hoisted_60, [
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(ts, (t) => {
                return (_openBlock(), _createElementBlock("span", {
                  key: t.term,
                  class: "term"
                }, [
                  _createTextVNode(_toDisplayString(t.term), 1 /* TEXT */),
                  (t.topic)
                    ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                        _createTextVNode(" · " + _toDisplayString(t.topic), 1 /* TEXT */)
                      ], 64 /* STABLE_FRAGMENT */))
                    : _createCommentVNode("v-if", true)
                ]))
              }), 128 /* KEYED_FRAGMENT */))
            ])
          ]))
        }), 128 /* KEYED_FRAGMENT */))
      ])
    ])
  ]))
}
__sfc_main.render = render
export default __sfc_main

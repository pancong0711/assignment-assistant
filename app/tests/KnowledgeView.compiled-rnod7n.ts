import { defineComponent as _defineComponent } from 'vue'
import { computed, onMounted, ref } from 'vue'
import { useSettingsStore } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/stores/settings'
import { KB_KINDS, KB_KIND_LABELS, type KbKind } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/kb'
import {
  PROMPT_CATEGORIES, PROMPT_CATEGORY_LABELS, fetchKbCatalog, fetchKnowledgeVocab,
  fetchPromptTemplatesByCategory, generateRubricBatch, postPromptTemplateCategory,
  tagKnowledge, type KnowledgeTerm, type PromptCategory, type PromptTemplate,
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

onMounted(async () => { await loadVocab(); await loadChaps(); await loadTemplates() })

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

const __returned__ = { settings, msg, busy, terms, chaps, kind, chap, loadVocab, loadChaps, tplCat, tplItems, tplSel, tplText, tplName, tplBusy, tplMsg, tplCurrent, tplIsBuiltin, loadTemplates, pickTemplate, onTplCatChange, saveTpl, setTplDefault, deleteTpl, termByChapter, tagDry, tagForce, doTagPreview, doTagApply, rubKind, rubChap, rubForce, rubPreview, doRubricPreview, doRubricApply, get KB_KINDS() { return KB_KINDS }, get KB_KIND_LABELS() { return KB_KIND_LABELS }, get PROMPT_CATEGORIES() { return PROMPT_CATEGORIES }, get PROMPT_CATEGORY_LABELS() { return PROMPT_CATEGORY_LABELS } }
Object.defineProperty(__returned__, '__isScriptSetup', { enumerable: false, value: true })
return __returned__
}

})
import { createElementVNode as _createElementVNode, createTextVNode as _createTextVNode, toDisplayString as _toDisplayString, openBlock as _openBlock, createElementBlock as _createElementBlock, createCommentVNode as _createCommentVNode, renderList as _renderList, Fragment as _Fragment, vModelSelect as _vModelSelect, withDirectives as _withDirectives, vModelCheckbox as _vModelCheckbox, vModelText as _vModelText } from "vue"

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
const _hoisted_19 = ["value"]
const _hoisted_20 = { class: "field" }
const _hoisted_21 = ["value"]
const _hoisted_22 = { class: "field" }
const _hoisted_23 = { style: {"margin":"6px 0"} }
const _hoisted_24 = ["disabled"]
const _hoisted_25 = ["disabled"]
const _hoisted_26 = {
  key: 0,
  open: ""
}
const _hoisted_27 = {
  class: "hint",
  style: {"cursor":"pointer"}
}
const _hoisted_28 = { class: "md" }
const _hoisted_29 = { class: "card" }
const _hoisted_30 = { class: "row" }
const _hoisted_31 = { class: "field" }
const _hoisted_32 = ["value"]
const _hoisted_33 = ["value"]
const _hoisted_34 = { class: "field" }
const _hoisted_35 = ["value"]
const _hoisted_36 = {
  key: 0,
  class: "hint"
}
const _hoisted_37 = {
  class: "field",
  style: {"display":"block","margin":"4px 0"}
}
const _hoisted_38 = { style: {"margin":"6px 0"} }
const _hoisted_39 = ["disabled"]
const _hoisted_40 = ["disabled"]
const _hoisted_41 = ["disabled"]
const _hoisted_42 = ["disabled"]
const _hoisted_43 = {
  key: 0,
  class: "hint",
  style: {"margin-left":"8px"}
}
const _hoisted_44 = { class: "card" }
const _hoisted_45 = { class: "hint" }
const _hoisted_46 = {
  key: 0,
  class: "hint"
}
const _hoisted_47 = {
  class: "hint",
  style: {"cursor":"pointer"}
}
const _hoisted_48 = { class: "terms" }

export function render(_ctx, _cache, $props, $setup, $data, $options) {
  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _cache[32] || (_cache[32] = _createElementVNode("h2", { style: {"margin":"0 0 4px"} }, "知识点（AI 标注 / 题库 AI 作答 / 词表）", -1 /* CACHED */)),
    _cache[33] || (_cache[33] = _createElementVNode("p", {
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
        _cache[17] || (_cache[17] = _createElementVNode("h3", null, "① AI 知识点标注", -1 /* CACHED */)),
        _cache[18] || (_cache[18] = _createElementVNode("p", { class: "hint" }, [
          _createTextVNode(" 让 AI 读题目，把物理概念写进题库的 "),
          _createElementVNode("code", null, "related"),
          _createTextVNode(" 列。 默认"),
          _createElementVNode("b", null, "只标未标注"),
          _createTextVNode("的题（不覆盖教师已写的）。 ")
        ], -1 /* CACHED */)),
        _createElementVNode("div", _hoisted_5, [
          _createElementVNode("label", _hoisted_6, [
            _cache[12] || (_cache[12] = _createTextVNode("题型 ", -1 /* CACHED */)),
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
            _cache[14] || (_cache[14] = _createTextVNode("章节 ", -1 /* CACHED */)),
            _withDirectives(_createElementVNode("select", {
              "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => (($setup.chap) = $event))
            }, [
              _cache[13] || (_cache[13] = _createElementVNode("option", { value: "" }, "（全部章节）", -1 /* CACHED */)),
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
            _cache[15] || (_cache[15] = _createTextVNode(" 覆盖已有标注", -1 /* CACHED */))
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
                _cache[16] || (_cache[16] = _createElementVNode("thead", null, [
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
      _createCommentVNode(" ② 要点 "),
      _createElementVNode("section", _hoisted_16, [
        _cache[23] || (_cache[23] = _createElementVNode("h3", null, "② 题库 AI 作答（参考解答 + 评阅要点）", -1 /* CACHED */)),
        _cache[24] || (_cache[24] = _createElementVNode("p", { class: "hint" }, [
          _createTextVNode(" 一次产出「参考解答 + 评阅要点 + 知识点」，写入答案版本库； "),
          _createElementVNode("b", null, "默认不置顶"),
          _createTextVNode("（你核对后再置顶才生效）。 ")
        ], -1 /* CACHED */)),
        _createElementVNode("div", _hoisted_17, [
          _createElementVNode("label", _hoisted_18, [
            _cache[19] || (_cache[19] = _createTextVNode("题型 ", -1 /* CACHED */)),
            _withDirectives(_createElementVNode("select", {
              "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => (($setup.rubKind) = $event))
            }, [
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.KB_KINDS, (k) => {
                return (_openBlock(), _createElementBlock("option", {
                  key: k,
                  value: k
                }, _toDisplayString($setup.KB_KIND_LABELS[k] || k), 9 /* TEXT, PROPS */, _hoisted_19))
              }), 128 /* KEYED_FRAGMENT */))
            ], 512 /* NEED_PATCH */), [
              [_vModelSelect, $setup.rubKind]
            ])
          ]),
          _createElementVNode("label", _hoisted_20, [
            _cache[21] || (_cache[21] = _createTextVNode("章节 ", -1 /* CACHED */)),
            _withDirectives(_createElementVNode("select", {
              "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => (($setup.rubChap) = $event))
            }, [
              _cache[20] || (_cache[20] = _createElementVNode("option", { value: "" }, "（全部章节）", -1 /* CACHED */)),
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.chaps, (c) => {
                return (_openBlock(), _createElementBlock("option", {
                  key: c,
                  value: c
                }, _toDisplayString(c), 9 /* TEXT, PROPS */, _hoisted_21))
              }), 128 /* KEYED_FRAGMENT */))
            ], 512 /* NEED_PATCH */), [
              [_vModelSelect, $setup.rubChap]
            ])
          ]),
          _createElementVNode("label", _hoisted_22, [
            _withDirectives(_createElementVNode("input", {
              "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => (($setup.rubForce) = $event)),
              type: "checkbox"
            }, null, 512 /* NEED_PATCH */), [
              [_vModelCheckbox, $setup.rubForce]
            ]),
            _cache[22] || (_cache[22] = _createTextVNode(" 强制（copy/summary）", -1 /* CACHED */))
          ])
        ]),
        _createElementVNode("p", _hoisted_23, [
          _createElementVNode("button", {
            class: "btn",
            disabled: $setup.busy !== '',
            onClick: $setup.doRubricPreview
          }, _toDisplayString($setup.busy === 'rub' ? '处理中…' : '① 预览'), 9 /* TEXT, PROPS */, _hoisted_24),
          _createElementVNode("button", {
            class: "btn primary",
            disabled: $setup.busy !== '',
            onClick: $setup.doRubricApply
          }, " ② 生成并写入 ", 8 /* PROPS */, _hoisted_25)
        ]),
        ($setup.rubPreview.length)
          ? (_openBlock(), _createElementBlock("details", _hoisted_26, [
              _createElementVNode("summary", _hoisted_27, "预览 " + _toDisplayString($setup.rubPreview.length) + " 题", 1 /* TEXT */),
              _createElementVNode("pre", _hoisted_28, _toDisplayString($setup.rubPreview.slice(0, 3).map((x) => x.text).join('\n\n---\n\n')), 1 /* TEXT */)
            ]))
          : _createCommentVNode("v-if", true)
      ]),
      _createCommentVNode(" ④ 提示词模板（D151） "),
      _createElementVNode("section", _hoisted_29, [
        _cache[28] || (_cache[28] = _createElementVNode("h3", null, "④ 提示词模板（可改 / 可存 / 可另存 / 可删）", -1 /* CACHED */)),
        _cache[29] || (_cache[29] = _createElementVNode("p", { class: "hint" }, [
          _createTextVNode(" 不选模板 = 使用"),
          _createElementVNode("b", null, "内置默认"),
          _createTextVNode("（与改动前完全一致）。 "),
          _createElementVNode("code", null, "转录"),
          _createTextVNode("/"),
          _createElementVNode("code", null, "批阅"),
          _createTextVNode(" 两类改完请先跑一次试跑验证。 ")
        ], -1 /* CACHED */)),
        _createElementVNode("div", _hoisted_30, [
          _createElementVNode("label", _hoisted_31, [
            _cache[25] || (_cache[25] = _createTextVNode("类别 ", -1 /* CACHED */)),
            _createElementVNode("select", {
              value: $setup.tplCat,
              onChange: _cache[6] || (_cache[6] = $event => {$setup.tplCat = ($event.target as HTMLSelectElement).value as PromptCategory; $setup.onTplCatChange()})
            }, [
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.PROMPT_CATEGORIES, (c) => {
                return (_openBlock(), _createElementBlock("option", {
                  key: c,
                  value: c
                }, _toDisplayString($setup.PROMPT_CATEGORY_LABELS[c]), 9 /* TEXT, PROPS */, _hoisted_33))
              }), 128 /* KEYED_FRAGMENT */))
            ], 40 /* PROPS, NEED_HYDRATION */, _hoisted_32)
          ]),
          _createElementVNode("label", _hoisted_34, [
            _cache[26] || (_cache[26] = _createTextVNode("模板 ", -1 /* CACHED */)),
            _withDirectives(_createElementVNode("select", {
              "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => (($setup.tplSel) = $event)),
              onChange: $setup.pickTemplate
            }, [
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.tplItems, (t) => {
                return (_openBlock(), _createElementBlock("option", {
                  key: t.id,
                  value: t.id
                }, _toDisplayString(t.default ? '★ ' : '') + _toDisplayString(t.name) + _toDisplayString(t.builtin ? '（内置）' : ''), 9 /* TEXT, PROPS */, _hoisted_35))
              }), 128 /* KEYED_FRAGMENT */))
            ], 544 /* NEED_HYDRATION, NEED_PATCH */), [
              [_vModelSelect, $setup.tplSel]
            ])
          ]),
          ($setup.tplIsBuiltin)
            ? (_openBlock(), _createElementBlock("span", _hoisted_36, "内置模板不可删（可\"另存为\"后修改）"))
            : _createCommentVNode("v-if", true)
        ]),
        _createElementVNode("label", _hoisted_37, [
          _cache[27] || (_cache[27] = _createTextVNode(" 名称 ", -1 /* CACHED */)),
          _withDirectives(_createElementVNode("input", {
            "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => (($setup.tplName) = $event)),
            style: {"width":"260px"}
          }, null, 512 /* NEED_PATCH */), [
            [_vModelText, $setup.tplName]
          ])
        ]),
        _withDirectives(_createElementVNode("textarea", {
          "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => (($setup.tplText) = $event)),
          rows: "6",
          placeholder: "留空 = 使用代码内置默认",
          style: {"width":"100%","max-width":"820px","font-family":"monospace","font-size":"12px","padding":"6px 8px","border":"1px solid #d1d5db","border-radius":"6px"}
        }, null, 512 /* NEED_PATCH */), [
          [_vModelText, $setup.tplText]
        ]),
        _createElementVNode("p", _hoisted_38, [
          _createElementVNode("button", {
            class: "btn",
            disabled: $setup.tplBusy,
            onClick: _cache[10] || (_cache[10] = $event => ($setup.saveTpl(false)))
          }, "💾 保存", 8 /* PROPS */, _hoisted_39),
          _createElementVNode("button", {
            class: "btn",
            disabled: $setup.tplBusy,
            onClick: _cache[11] || (_cache[11] = $event => ($setup.saveTpl(true)))
          }, "＋ 另存为", 8 /* PROPS */, _hoisted_40),
          _createElementVNode("button", {
            class: "btn",
            disabled: $setup.tplBusy || !$setup.tplSel,
            onClick: $setup.setTplDefault
          }, "设为默认", 8 /* PROPS */, _hoisted_41),
          _createElementVNode("button", {
            class: "btn",
            disabled: $setup.tplBusy || !$setup.tplSel || $setup.tplIsBuiltin,
            onClick: $setup.deleteTpl
          }, "🗑 删除", 8 /* PROPS */, _hoisted_42),
          ($setup.tplMsg)
            ? (_openBlock(), _createElementBlock("span", _hoisted_43, _toDisplayString($setup.tplMsg), 1 /* TEXT */))
            : _createCommentVNode("v-if", true)
        ])
      ]),
      _createCommentVNode(" ③ 词表 "),
      _createElementVNode("section", _hoisted_44, [
        _cache[31] || (_cache[31] = _createElementVNode("h3", null, "③ 受控知识点词表", -1 /* CACHED */)),
        _createElementVNode("p", _hoisted_45, " 共 " + _toDisplayString($setup.terms.length) + " 个术语（按章分组）。AI 标注时优先沿用这里的写法，避免同义漂移。 ", 1 /* TEXT */),
        (!$setup.terms.length)
          ? (_openBlock(), _createElementBlock("p", _hoisted_46, [...(_cache[30] || (_cache[30] = [
              _createTextVNode(" （还没有词表：先做一次「① AI 知识点标注」，或 CLI ", -1 /* CACHED */),
              _createElementVNode("code", null, "kb vocab harvest", -1 /* CACHED */),
              _createTextVNode("。） ", -1 /* CACHED */)
            ]))]))
          : _createCommentVNode("v-if", true),
        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.termByChapter, (ts, c) => {
          return (_openBlock(), _createElementBlock("details", { key: c }, [
            _createElementVNode("summary", _hoisted_47, _toDisplayString(c) + "（" + _toDisplayString(ts.length) + "）", 1 /* TEXT */),
            _createElementVNode("div", _hoisted_48, [
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

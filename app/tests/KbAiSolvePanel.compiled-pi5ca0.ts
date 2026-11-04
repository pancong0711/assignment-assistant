import { defineComponent as _defineComponent } from 'vue'
import { computed, onMounted, ref, watch } from 'vue'
import { useKbStore } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/stores/kb'
import {
  fetchKbCatalog, fetchPromptTemplates, fetchXxtLoginJob, mutatePromptTemplate,
  startKbAiSolve,
} from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/engineClient'


const __sfc_main = /*@__PURE__*/_defineComponent({
  __name: 'KbAiSolvePanel',
  props: {
    engineAddr: { type: String, required: true },
    token: { type: String, required: false }
  },
  setup(__props: any, { expose: __expose }) {

/** D152：题库 AI 作答面板（从 AiGradingPanel ⑦ 区**整体搬出**）。
 *
 *  为什么抽成组件：批阅页和「题库AI+」都用同一套能力，复制会导致口径漂移。
 *  这里保留原 ⑦ 区全部能力：题号多选 / 模型 / 置顶 / 写回 / 同时生成要点 /
 *  提示词模板 / 作答要求 / 题目预览 / solution 索引状态。
 *
 *  D152 新增：☑ 同时标注知识点到题库（一次调用完成 解答+要点+知识点）。
 */
const props = __props

const kbStore = useKbStore()

/* ---------- 题库目录 ---------- */
const kbCatalog = ref<{ kinds?: any[] }>({ kinds: [] })
const kbCatalogErr = ref('')
const kbKind = ref(''); const kbChap = ref(''); const kbIdsSel = ref<string[]>([]); const kbModel = ref('')
const kbKinds = computed<string[]>(() => (kbCatalog.value.kinds || []).map((k: any) => k.kind))
const kbChapters = computed<string[]>(() => {
  const k = (kbCatalog.value.kinds || []).find((x: any) => x.kind === kbKind.value)
  return (k?.chapters || []).map((c: any) => c.chap)
})
const kbIdList = computed<{ id: string; content?: string }[]>(() => {
  const k = (kbCatalog.value.kinds || []).find((x: any) => x.kind === kbKind.value)
  const c = (k?.chapters || []).find((x: any) => x.chap === kbChap.value)
  return c?.ids || []
})
const kbPreview = computed(() => {
  const want = new Set(kbIdsSel.value)
  const picked = kbIdList.value.filter((i) => !want.size || want.has(i.id))
  return picked.map((i) => `${i.id}: ${i.content ?? ''}`).join('   ｜   ')
})
async function loadKbCatalog() {
  kbCatalogErr.value = ''
  const r = await fetchKbCatalog(props.engineAddr, props.token)
  kbCatalog.value = { kinds: r.kinds || [] }
  if (r.ok === false || !(r.kinds || []).length) {
    kbCatalogErr.value = r.error
      ? `读取题库目录失败：${r.error}（引擎在线吗？）`
      : '题库为空：请先在「题库编辑器」载入 xlsx'
  }
  if (!kbKind.value && kbKinds.value.length) {
    kbKind.value = kbKinds.value.includes('problems') ? 'problems' : kbKinds.value[0]
  }
}
watch(kbKind, () => { kbChap.value = ''; kbIdsSel.value = [] })
watch(kbChap, () => { kbIdsSel.value = [] })

/* ---------- 作答选项 ---------- */
const kbPin = ref(true); const kbApply = ref(false)
const kbWithRubric = ref(false); const kbPinRubric = ref(false)
/** D152：同时把知识点写回题库（走 apply_related，改前自动快照） */
const kbTagKnowledge = ref(false)
const kbRequirement = ref('')

/* ---------- 提示词模板（D108/D151） ---------- */
const promptTemplates = ref<{ id: string; name: string; text: string
                             default?: boolean; builtin?: boolean }[]>([])
const promptSel = ref('')
const promptBusy = ref(false)
const promptMsg = ref('')
const promptIsBuiltin = computed(() =>
  !!promptTemplates.value.find((t) => t.id === promptSel.value)?.builtin)
const promptIsDefault = computed(() =>
  !!promptTemplates.value.find((t) => t.id === promptSel.value)?.default)

async function loadPromptTemplates(autoPickDefault = true) {
  const r = await fetchPromptTemplates(props.engineAddr, props.token)
  promptTemplates.value = r.items || []
  if (!promptTemplates.value.length) { promptMsg.value = '（未读到模板；引擎是否在线？）'; return }
  if (autoPickDefault && !promptSel.value) {
    const d = promptTemplates.value.find((t) => t.default)
    if (d) { promptSel.value = d.id; kbRequirement.value = d.text || '' }
  }
}
function pickPromptTemplate() {
  const t = promptTemplates.value.find((x) => x.id === promptSel.value)
  kbRequirement.value = t ? (t.text || '') : ''
  promptMsg.value = ''
}
async function setPromptDefault() {
  if (!promptSel.value) return
  promptBusy.value = true
  try {
    const r = await mutatePromptTemplate(props.engineAddr, props.token,
      { action: 'set_default', id: promptSel.value })
    promptMsg.value = r.ok ? '已设为默认' : `失败：${r.error || ''}`
    await loadPromptTemplates(false)
  } finally { promptBusy.value = false }
}
async function savePromptTemplate() {
  if (!promptSel.value) { promptMsg.value = '请先选择模板'; return }
  promptBusy.value = true
  try {
    const cur = promptTemplates.value.find((x) => x.id === promptSel.value)
    const r = await mutatePromptTemplate(props.engineAddr, props.token, {
      action: 'save', id: promptSel.value, name: cur?.name || promptSel.value,
      text: kbRequirement.value,
    })
    promptMsg.value = r.ok ? '已保存' : `失败：${r.error || ''}`
    await loadPromptTemplates(false)
  } finally { promptBusy.value = false }
}
async function savePromptAsNew() {
  const id = `custom-${Date.now().toString(36)}`
  promptBusy.value = true
  try {
    const r = await mutatePromptTemplate(props.engineAddr, props.token, {
      action: 'save', id, name: `自定义-${id.slice(-4)}`, text: kbRequirement.value,
    })
    if (r.ok) { promptSel.value = id; promptMsg.value = '已另存为新模板' }
    else promptMsg.value = `失败：${r.error || ''}`
    await loadPromptTemplates(false)
  } finally { promptBusy.value = false }
}
async function deletePromptTemplate() {
  if (!promptSel.value || promptIsBuiltin.value) return
  if (!window.confirm('删除该模板？')) return
  promptBusy.value = true
  try {
    const r = await mutatePromptTemplate(props.engineAddr, props.token,
      { action: 'delete', id: promptSel.value })
    promptMsg.value = r.ok ? '已删除' : `失败：${r.error || ''}`
    promptSel.value = ''
    await loadPromptTemplates()
  } finally { promptBusy.value = false }
}

/* ---------- 执行 ---------- */
const kbSolving = ref(false)
const kbSolveMsg = ref('')

function extractJobError(s: string): string {
  const m = /"error"\s*:\s*"([^"]{1,400})"/.exec(s)
  return m ? m[1] : ''
}

async function solveByKb() {
  const ids = [...kbIdsSel.value]
  if (!ids.length) {
    if (!kbChap.value) {
      if (!window.confirm(
        `未选择章节，也未勾选题号 → 将对 **整个「${kbKind.value}」题库** 作答`
        + (kbApply.value ? '（并写回/置顶生效答案）' : '（dry-run 预览）') + '。\n'
        + '题量可能很大且耗时长。确定继续？')) return
    } else {
      const n = kbIdList.value.length
      if (!window.confirm(
        `未勾选题号 → 将对整章「${kbChap.value}」（${n} 题）作答`
        + (kbApply.value ? '（并写回/置顶生效答案）' : '（dry-run 预览）') + '。\n确定继续？')) return
    }
  }
  kbSolving.value = true; kbSolveMsg.value = '正在启动题库 AI 作答……'
  try {
    const jobId = await startKbAiSolve(props.engineAddr, props.token, {
      kb: kbKind.value, chap: kbChap.value, ids, model: kbModel.value,
      pin: kbPin.value, apply: kbApply.value,
      withRubric: kbWithRubric.value,
      pinRubric: kbWithRubric.value && kbPinRubric.value,
      tagKnowledge: kbWithRubric.value && kbTagKnowledge.value,   // D152
      all: !ids.length && !kbChap.value,
      requirement: kbRequirement.value.trim(),
      requirementTemplate: promptSel.value,
    })
    const tick = async () => {
      try {
        const job = await fetchXxtLoginJob(props.engineAddr, props.token, jobId)
        const lines = job.lines || []
        kbSolveMsg.value = (lines.slice(-1)[0] || '进行中…').slice(-220)
        if (job.status === 'running') { window.setTimeout(tick, 2000); return }
        const tail = lines.slice(-6).join('\n')
        const failedN = /"failed"\s*:\s*(\d+)/.exec(tail)?.[1]
        const errs = [...tail.matchAll(/"error"\s*:\s*"([^"]{1,300})"/g)]
          .map((m) => m[1]).filter(Boolean)
        if (kbApply.value) {
          await kbStore.bumpSolutions()
          const pinDesc = kbWithRubric.value
            ? (kbPinRubric.value ? '已置顶（含要点）' : '未置顶（要点待你确认后再置顶）')
            : (kbPin.value ? '已置顶为生效答案' : '未置顶，仅追加版本')
          if (failedN && failedN !== '0') {
            kbSolveMsg.value = `❌ 有 ${failedN} 题作答失败（未写回）`
              + (errs.length ? `：${[...new Set(errs)].slice(0, 3).join('；')}` : '')
              + '　—— 已成功的题已写回；失败题可重试或换模型'
            return
          }
          kbSolveMsg.value = `✅ 作答并写回完成（${pinDesc}）`
            + (kbTagKnowledge.value && kbWithRubric.value ? '；知识点已同步标注' : '')
            + '：' + (lines.slice(-2).join(' ') || '')
          return
        }
        kbSolveMsg.value = 'dry-run 预览完成：' + (lines.slice(-2).join(' ') || '')
      } catch (e) { kbSolveMsg.value = extractJobError(String(e)) || String(e) }
    }
    tick()
  } catch (e) {
    kbSolveMsg.value = String((e as Error).message || e)
  } finally {
    kbSolving.value = false
  }
}

onMounted(async () => {
  await loadKbCatalog()
  await loadPromptTemplates()
})
__expose({ loadKbCatalog, loadPromptTemplates })

const __returned__ = { props, kbStore, kbCatalog, kbCatalogErr, kbKind, kbChap, kbIdsSel, kbModel, kbKinds, kbChapters, kbIdList, kbPreview, loadKbCatalog, kbPin, kbApply, kbWithRubric, kbPinRubric, kbTagKnowledge, kbRequirement, promptTemplates, promptSel, promptBusy, promptMsg, promptIsBuiltin, promptIsDefault, loadPromptTemplates, pickPromptTemplate, setPromptDefault, savePromptTemplate, savePromptAsNew, deletePromptTemplate, kbSolving, kbSolveMsg, extractJobError, solveByKb }
Object.defineProperty(__returned__, '__isScriptSetup', { enumerable: false, value: true })
return __returned__
}

})
import { toDisplayString as _toDisplayString, openBlock as _openBlock, createElementBlock as _createElementBlock, createCommentVNode as _createCommentVNode, createElementVNode as _createElementVNode, renderList as _renderList, Fragment as _Fragment, vModelSelect as _vModelSelect, withDirectives as _withDirectives, vModelText as _vModelText, vModelCheckbox as _vModelCheckbox, createTextVNode as _createTextVNode } from "vue"

const _hoisted_1 = { style: {"display":"flex","gap":"8px","align-items":"center","flex-wrap":"wrap"} }
const _hoisted_2 = {
  key: 0,
  class: "hint",
  style: {"color":"#b45309"}
}
const _hoisted_3 = ["value"]
const _hoisted_4 = ["value"]
const _hoisted_5 = ["value"]
const _hoisted_6 = {
  class: "field",
  title: "默认勾选：AI 作答即成为生效答案"
}
const _hoisted_7 = {
  class: "field",
  title: "不勾=仅 dry-run 预览"
}
const _hoisted_8 = {
  class: "field",
  title: "一次产出「参考解答 + 评阅要点 + 知识点」"
}
const _hoisted_9 = {
  key: 2,
  class: "field",
  title: "默认不置顶：未确认的要点不该抢生效答案"
}
const _hoisted_10 = {
  key: 3,
  class: "field",
  title: "把 AI 产出的知识点写回题库 knowledge（改前自动快照）"
}
const _hoisted_11 = {
  key: 0,
  class: "hint",
  style: {"margin":"2px 0 0"}
}
const _hoisted_12 = { style: {"margin":"6px 0"} }
const _hoisted_13 = { style: {"display":"flex","gap":"6px","align-items":"center","flex-wrap":"wrap","margin-bottom":"4px"} }
const _hoisted_14 = ["value"]
const _hoisted_15 = ["disabled"]
const _hoisted_16 = ["disabled"]
const _hoisted_17 = ["disabled"]
const _hoisted_18 = ["disabled"]
const _hoisted_19 = {
  class: "hint",
  style: {"margin":"2px 0 0"}
}
const _hoisted_20 = {
  key: 0,
  style: {"color":"#2563eb"}
}
const _hoisted_21 = ["disabled"]
const _hoisted_22 = {
  class: "hint",
  style: {"margin":"4px 0 0"}
}
const _hoisted_23 = {
  key: 0,
  style: {"display":"inline-block","max-width":"100%","overflow-x":"auto","white-space":"nowrap","vertical-align":"bottom"}
}
const _hoisted_24 = { key: 1 }
const _hoisted_25 = {
  class: "hint",
  style: {"margin":"6px 0 0"}
}
const _hoisted_26 = {
  key: 1,
  class: "hint"
}

export function render(_ctx, _cache, $props, $setup, $data, $options) {
  return (_openBlock(), _createElementBlock("div", null, [
    _createElementVNode("div", _hoisted_1, [
      ($setup.kbCatalogErr)
        ? (_openBlock(), _createElementBlock("span", _hoisted_2, _toDisplayString($setup.kbCatalogErr), 1 /* TEXT */))
        : _createCommentVNode("v-if", true),
      ($setup.kbCatalogErr)
        ? (_openBlock(), _createElementBlock("button", {
            key: 1,
            class: "btn small",
            onClick: $setup.loadKbCatalog
          }, "重试"))
        : _createCommentVNode("v-if", true),
      _cache[18] || (_cache[18] = _createElementVNode("span", {
        class: "hint",
        style: {"margin":"0"}
      }, "题库：", -1 /* CACHED */)),
      _withDirectives(_createElementVNode("select", {
        "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => (($setup.kbKind) = $event)),
        style: {"min-width":"120px"}
      }, [
        _cache[11] || (_cache[11] = _createElementVNode("option", { value: "" }, "（选择题库）", -1 /* CACHED */)),
        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.kbKinds, (k) => {
          return (_openBlock(), _createElementBlock("option", {
            key: k,
            value: k
          }, _toDisplayString(k), 9 /* TEXT, PROPS */, _hoisted_3))
        }), 128 /* KEYED_FRAGMENT */))
      ], 512 /* NEED_PATCH */), [
        [_vModelSelect, $setup.kbKind]
      ]),
      _cache[19] || (_cache[19] = _createElementVNode("span", {
        class: "hint",
        style: {"margin":"0"}
      }, "章节：", -1 /* CACHED */)),
      _withDirectives(_createElementVNode("select", {
        "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => (($setup.kbChap) = $event)),
        style: {"min-width":"130px"}
      }, [
        _cache[12] || (_cache[12] = _createElementVNode("option", { value: "" }, "（整库）", -1 /* CACHED */)),
        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.kbChapters, (c) => {
          return (_openBlock(), _createElementBlock("option", {
            key: c,
            value: c
          }, _toDisplayString(c), 9 /* TEXT, PROPS */, _hoisted_4))
        }), 128 /* KEYED_FRAGMENT */))
      ], 512 /* NEED_PATCH */), [
        [_vModelSelect, $setup.kbChap]
      ]),
      _cache[20] || (_cache[20] = _createElementVNode("span", {
        class: "hint",
        style: {"margin":"0"}
      }, "题号：", -1 /* CACHED */)),
      _withDirectives(_createElementVNode("select", {
        "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => (($setup.kbIdsSel) = $event)),
        multiple: "",
        style: {"min-width":"200px","min-height":"64px"},
        title: "多选；不选=整章"
      }, [
        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.kbIdList, (i) => {
          return (_openBlock(), _createElementBlock("option", {
            key: i.id,
            value: i.id
          }, _toDisplayString(i.id), 9 /* TEXT, PROPS */, _hoisted_5))
        }), 128 /* KEYED_FRAGMENT */))
      ], 512 /* NEED_PATCH */), [
        [_vModelSelect, $setup.kbIdsSel]
      ]),
      _cache[21] || (_cache[21] = _createElementVNode("span", {
        class: "hint",
        style: {"margin":"0"}
      }, "模型：", -1 /* CACHED */)),
      _withDirectives(_createElementVNode("input", {
        "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => (($setup.kbModel) = $event)),
        placeholder: "空=评阅段配置",
        style: {"width":"170px"}
      }, null, 512 /* NEED_PATCH */), [
        [_vModelText, $setup.kbModel]
      ]),
      _createElementVNode("label", _hoisted_6, [
        _withDirectives(_createElementVNode("input", {
          type: "checkbox",
          "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => (($setup.kbPin) = $event))
        }, null, 512 /* NEED_PATCH */), [
          [_vModelCheckbox, $setup.kbPin]
        ]),
        _cache[13] || (_cache[13] = _createTextVNode(" 作答后置顶 ", -1 /* CACHED */))
      ]),
      _createElementVNode("label", _hoisted_7, [
        _withDirectives(_createElementVNode("input", {
          type: "checkbox",
          "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => (($setup.kbApply) = $event))
        }, null, 512 /* NEED_PATCH */), [
          [_vModelCheckbox, $setup.kbApply]
        ]),
        _cache[14] || (_cache[14] = _createTextVNode(" 真正作答并写回 ", -1 /* CACHED */))
      ]),
      _createElementVNode("label", _hoisted_8, [
        _withDirectives(_createElementVNode("input", {
          type: "checkbox",
          "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => (($setup.kbWithRubric) = $event))
        }, null, 512 /* NEED_PATCH */), [
          [_vModelCheckbox, $setup.kbWithRubric]
        ]),
        _cache[15] || (_cache[15] = _createTextVNode(" 同时生成评阅要点 ", -1 /* CACHED */))
      ]),
      ($setup.kbWithRubric)
        ? (_openBlock(), _createElementBlock("label", _hoisted_9, [
            _withDirectives(_createElementVNode("input", {
              type: "checkbox",
              "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => (($setup.kbPinRubric) = $event))
            }, null, 512 /* NEED_PATCH */), [
              [_vModelCheckbox, $setup.kbPinRubric]
            ]),
            _cache[16] || (_cache[16] = _createTextVNode(" 同时置顶（跳过确认） ", -1 /* CACHED */))
          ]))
        : _createCommentVNode("v-if", true),
      _createCommentVNode(" D152：知识点标注并入 "),
      ($setup.kbWithRubric)
        ? (_openBlock(), _createElementBlock("label", _hoisted_10, [
            _withDirectives(_createElementVNode("input", {
              type: "checkbox",
              "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => (($setup.kbTagKnowledge) = $event))
            }, null, 512 /* NEED_PATCH */), [
              [_vModelCheckbox, $setup.kbTagKnowledge]
            ]),
            _cache[17] || (_cache[17] = _createTextVNode(" 同时标注知识点到题库 ", -1 /* CACHED */))
          ]))
        : _createCommentVNode("v-if", true)
    ]),
    ($setup.kbWithRubric)
      ? (_openBlock(), _createElementBlock("p", _hoisted_11, [...(_cache[22] || (_cache[22] = [
          _createTextVNode(" ⓘ 要点与解答**同一次生成**。默认", -1 /* CACHED */),
          _createElementVNode("b", null, "不置顶", -1 /* CACHED */),
          _createTextVNode("；", -1 /* CACHED */),
          _createElementVNode("code", null, "copy", -1 /* CACHED */),
          _createTextVNode("/", -1 /* CACHED */),
          _createElementVNode("code", null, "summary", -1 /* CACHED */),
          _createTextVNode(" 按口径不生成 AI 要点。 ", -1 /* CACHED */)
        ]))]))
      : _createCommentVNode("v-if", true),
    _createElementVNode("div", _hoisted_12, [
      _createElementVNode("div", _hoisted_13, [
        _cache[24] || (_cache[24] = _createElementVNode("label", {
          class: "hint",
          style: {"margin":"0"}
        }, "提示词模板：", -1 /* CACHED */)),
        _withDirectives(_createElementVNode("select", {
          "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => (($setup.promptSel) = $event)),
          onChange: $setup.pickPromptTemplate,
          style: {"min-width":"220px"}
        }, [
          _cache[23] || (_cache[23] = _createElementVNode("option", { value: "" }, "（不使用模板 / 单次输入）", -1 /* CACHED */)),
          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.promptTemplates, (t) => {
            return (_openBlock(), _createElementBlock("option", {
              key: t.id,
              value: t.id
            }, _toDisplayString(t.default ? '★ ' : '') + _toDisplayString(t.name) + _toDisplayString(t.builtin ? '（内置）' : ''), 9 /* TEXT, PROPS */, _hoisted_14))
          }), 128 /* KEYED_FRAGMENT */))
        ], 544 /* NEED_HYDRATION, NEED_PATCH */), [
          [_vModelSelect, $setup.promptSel]
        ]),
        _createElementVNode("button", {
          class: "btn small",
          disabled: $setup.promptBusy || !$setup.promptSel || $setup.promptIsDefault,
          onClick: $setup.setPromptDefault
        }, "设为默认", 8 /* PROPS */, _hoisted_15),
        _createElementVNode("button", {
          class: "btn small",
          disabled: $setup.promptBusy || !$setup.kbRequirement.trim(),
          onClick: $setup.savePromptTemplate
        }, "💾 保存", 8 /* PROPS */, _hoisted_16),
        _createElementVNode("button", {
          class: "btn small",
          disabled: $setup.promptBusy || !$setup.kbRequirement.trim(),
          onClick: $setup.savePromptAsNew
        }, "＋ 另存为", 8 /* PROPS */, _hoisted_17),
        _createElementVNode("button", {
          class: "btn small",
          disabled: $setup.promptBusy || !$setup.promptSel || $setup.promptIsBuiltin,
          onClick: $setup.deletePromptTemplate
        }, "🗑 删除", 8 /* PROPS */, _hoisted_18)
      ]),
      _cache[28] || (_cache[28] = _createElementVNode("label", {
        class: "hint",
        style: {"display":"block","margin":"0 0 4px"}
      }, " 作答要求（作为「优先满足」附加到每题 prompt）： ", -1 /* CACHED */)),
      _withDirectives(_createElementVNode("textarea", {
        "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => (($setup.kbRequirement) = $event)),
        rows: "3",
        placeholder: "例：请画出示意图；用 LaTeX 公式完整推导；按「已知/求/解/答」结构写……",
        style: {"width":"100%","max-width":"760px","font-family":"inherit","font-size":"13px","padding":"6px 8px","border":"1px solid #d1d5db","border-radius":"6px","resize":"vertical"}
      }, null, 512 /* NEED_PATCH */), [
        [_vModelText, $setup.kbRequirement]
      ]),
      _createElementVNode("div", _hoisted_19, [
        _cache[25] || (_cache[25] = _createTextVNode(" 模板保存在 ", -1 /* CACHED */)),
        _cache[26] || (_cache[26] = _createElementVNode("code", null, "<workspace>/prompts/ai-solve/", -1 /* CACHED */)),
        _cache[27] || (_cache[27] = _createTextVNode("，CLI/AI 同样可用。 ", -1 /* CACHED */)),
        ($setup.promptMsg)
          ? (_openBlock(), _createElementBlock("span", _hoisted_20, "｜" + _toDisplayString($setup.promptMsg), 1 /* TEXT */))
          : _createCommentVNode("v-if", true)
      ]),
      _createElementVNode("button", {
        class: "btn",
        disabled: $setup.kbSolving,
        onClick: $setup.solveByKb,
        style: {"margin-top":"6px"}
      }, " ▶ " + _toDisplayString($setup.kbApply ? 'AI 作答并写回' : 'AI 作答（dry-run）'), 9 /* TEXT, PROPS */, _hoisted_21)
    ]),
    _createElementVNode("div", _hoisted_22, [
      _cache[29] || (_cache[29] = _createTextVNode("题目预览： ", -1 /* CACHED */)),
      ($setup.kbPreview)
        ? (_openBlock(), _createElementBlock("code", _hoisted_23, _toDisplayString($setup.kbPreview), 1 /* TEXT */))
        : (_openBlock(), _createElementBlock("span", _hoisted_24, "（未选题号：将按整章/整库作答）"))
    ]),
    _createElementVNode("p", _hoisted_25, " AI 作答**不覆盖**原答案：每次新增一版（含模型名 + 时间戳），默认**置顶为生效答案**。 索引状态：" + _toDisplayString($setup.kbStore.solutionsMsg || '（未刷新）'), 1 /* TEXT */),
    ($setup.kbSolveMsg)
      ? (_openBlock(), _createElementBlock("p", _hoisted_26, _toDisplayString($setup.kbSolveMsg), 1 /* TEXT */))
      : _createCommentVNode("v-if", true)
  ]))
}
__sfc_main.render = render
export default __sfc_main

import { defineComponent as _defineComponent } from 'vue'
import { computed, onMounted, ref } from 'vue'
import {
  fetchGradingRules, resetGradingRules, saveGradingRules,
  type GradingRulesPayload,
} from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/engineClient'


const __sfc_main = /*@__PURE__*/_defineComponent({
  __name: 'GradingRulesCard',
  props: {
    engineAddr: { type: String, required: true },
    token: { type: String, required: false }
  },
  emits: ["notify"],
  setup(__props: any, { expose: __expose, emit: __emit }) {

/** D130-T9：评阅规则卡。
 *
 *  解决"批阅提示词教师看不到也改不了"：分层开放（docs/78 §3.4）
 *   - 🔒 只读：题型 → 评阅侧重的**提示词正文**、评分算法名（完全可见，不可改）
 *   - ✏️ 可改数值：扣分分值 / 上限 / 长度倍率 / 阈值（带范围校验）
 *   - ➕ 可改扩展：题型 checklist 的检查项名称（如 copy 的"题目/过程/示意图"）
 *  配套：改动记 journal（引擎侧）、一键「恢复默认」；
 *  页面明示"影响后续批阅，不改已生成报告"（报告是纯组装产物，D127）。
 */
const props = __props
const emit = __emit

const loading = ref(false)
const saving = ref(false)
const payload = ref<GradingRulesPayload | null>(null)
const draft = ref<Record<string, any>>({})
const msg = ref('')
const activeKind = ref('qa')

const KIND_LABEL: Record<string, string> = {
  problems: '计算/推导（逐处找错）',
  qa: '问答（要点完整性 + 示意图）',
  copy: '抄写（题目/过程/示意图）',
  distinguish: '辨析（长度档）',
  translation: '翻译（长度档）',
  innovation: '创新（长度档、宽松）',
  summary: '总结（知识点/公式/示意图）',
}
const MODE_LABEL: Record<string, string> = {
  errorCount: 'errorCount（逐处错误计分）',
  missingPoints: 'missingPoints（缺评阅要点计分）',
  checklist: 'checklist（逐项完整性计分）',
  lengthBased: 'lengthBased（作答长度档计分）',
}

/** ✏️ 可改数值字段的展示名（未列出的一律不开放编辑）。 */
const NUM_FIELDS: { key: string; label: string; hint?: string }[] = [
  { key: 'briefProcessDeduct', label: '过程简略扣分（每处）' },
  { key: 'allBriefRatio', label: '整体简略触发比例（0~1）' },
  { key: 'allBriefDeduct', label: '整体简略额外扣分（一次性）' },
  { key: 'perQuestionCap', label: '单题扣分上限' },
  { key: 'perErrorDeduct', label: '每处错误扣分' },
  { key: 'perMissingPointDeduct', label: '每个缺失要点扣分' },
  { key: 'missingDiagramDeduct', label: '缺示意图扣分' },
  { key: 'perMissingItemDeduct', label: '每缺一项扣分' },
  { key: 'lengthFactor', label: '长度基准倍率（题长 × n）' },
  { key: 'lengthFloorChars', label: '长度基准下限（字数）' },
  { key: 'irrelevantDeduct', label: '完全无关扣分' },
  // D170-T9：抄写题（topicMatch）专用
  { key: 'minChars', label: '抄写字数下限（字）' },
  { key: 'topicMismatchDeduct', label: '主题不符扣分' },
  { key: 'noSignatureDeduct', label: '无签名扣分' },
  { key: 'writingDeduct', label: '书写规范扣分上限' },
  { key: 'floor', label: '总分下限' },
]

const kinds = computed<string[]>(() => payload.value?.kinds || [])
const typeCfg = computed<Record<string, any>>(
  () => (draft.value.types?.[activeKind.value] || {}) as Record<string, any>)
const globalCfg = computed<Record<string, any>>(
  () => (draft.value.global || {}) as Record<string, any>)
const summaryText = computed<string>(
  () => String(payload.value?.summaries?.[activeKind.value] || ''))

/** 字段范围（引擎下发，前端只做即时提示；**权威校验在引擎**） */
function range(key: string): [number, number] | null {
  return payload.value?.numericRanges?.[key] || null
}
function outOfRange(key: string, v: any): boolean {
  const r = range(key)
  if (!r) return false
  const n = Number(v)
  return !Number.isFinite(n) || n < r[0] || n > r[1]
}

async function load() {
  loading.value = true
  msg.value = ''
  try {
    const p = await fetchGradingRules(props.engineAddr, props.token)
    payload.value = p
    draft.value = JSON.parse(JSON.stringify(p.rules || {}))
    if (!kinds.value.includes(activeKind.value)) {
      activeKind.value = kinds.value.find((k) => k === 'qa') || kinds.value[0] || 'qa'
    }
  } catch (e) {
    msg.value = `读取评阅规则失败：${String((e as Error).message || e)}`
  } finally { loading.value = false }
}

async function save() {
  // 前端先做一遍范围校验，避免把明显越界的值发到引擎
  for (const f of NUM_FIELDS) {
    if (f.key in globalCfg.value && outOfRange(f.key, globalCfg.value[f.key])) {
      msg.value = `❌ 全局规则「${f.label}」超出范围 ${JSON.stringify(range(f.key))}`
      return
    }
    if (f.key in typeCfg.value && outOfRange(f.key, typeCfg.value[f.key])) {
      msg.value = `❌ ${KIND_LABEL[activeKind.value] || activeKind.value}「${f.label}」`
        + `超出范围 ${JSON.stringify(range(f.key))}`
      return
    }
  }
  saving.value = true
  msg.value = ''
  try {
    const r = await saveGradingRules(props.engineAddr, props.token, draft.value)
    if (!r?.ok) {
      msg.value = `❌ 保存失败：${r?.error || (r?.errors || []).join('；') || '未知错误'}`
      return
    }
    const n = (r.changes || []).length
    msg.value = `✅ 已保存 ${n} 处改动（记入 journal）；**只影响后续批阅**，已生成的报告不变`
    emit('notify', msg.value)
    await load()
  } catch (e) {
    msg.value = `保存失败：${String((e as Error).message || e)}`
  } finally { saving.value = false }
}

async function resetAll() {
  if (!window.confirm('恢复**全部**评阅规则为内置默认？\n（当前改动会记入 journal，' +
                      '但会覆盖你的自定义数值。）')) return
  saving.value = true
  try {
    const r = await resetGradingRules(props.engineAddr, props.token)
    msg.value = r?.ok ? '✅ 已恢复默认规则' : `❌ 恢复失败：${r?.error || '未知错误'}`
    if (r?.ok) { emit('notify', msg.value); await load() }
  } catch (e) {
    msg.value = `恢复失败：${String((e as Error).message || e)}`
  } finally { saving.value = false }
}

/** ➕ 可改扩展：checklist 项名（逗号分隔 → 数组） */
function checklistText(): string {
  const v = typeCfg.value.checklist
  return Array.isArray(v) ? v.join('，') : ''
}
function setChecklist(ev: Event) {
  const raw = String((ev.target as HTMLInputElement).value || '')
  const items = raw.split(/[，,、;；]/).map((x) => x.trim()).filter(Boolean)
  if (!draft.value.types) draft.value.types = {}
  if (!draft.value.types[activeKind.value]) draft.value.types[activeKind.value] = {}
  draft.value.types[activeKind.value].checklist = items
}

onMounted(load)
__expose({ load })

const __returned__ = { props, emit, loading, saving, payload, draft, msg, activeKind, KIND_LABEL, MODE_LABEL, NUM_FIELDS, kinds, typeCfg, globalCfg, summaryText, range, outOfRange, load, save, resetAll, checklistText, setChecklist }
Object.defineProperty(__returned__, '__isScriptSetup', { enumerable: false, value: true })
return __returned__
}

})
import { createElementVNode as _createElementVNode, createTextVNode as _createTextVNode, openBlock as _openBlock, createElementBlock as _createElementBlock, createCommentVNode as _createCommentVNode, toDisplayString as _toDisplayString, renderList as _renderList, Fragment as _Fragment, normalizeClass as _normalizeClass, vModelText as _vModelText, withDirectives as _withDirectives, vShow as _vShow } from "vue"

const _hoisted_1 = { class: "rules-card" }
const _hoisted_2 = { class: "rules-head" }
const _hoisted_3 = ["disabled"]
const _hoisted_4 = ["disabled"]
const _hoisted_5 = ["disabled"]
const _hoisted_6 = {
  key: 0,
  class: "hint"
}
const _hoisted_7 = {
  key: 1,
  class: "hint"
}
const _hoisted_8 = { class: "kind-tabs" }
const _hoisted_9 = ["onClick"]
const _hoisted_10 = {
  class: "hint",
  style: {"margin":"4px 0 8px"}
}
const _hoisted_11 = {
  class: "ro-block",
  open: ""
}
const _hoisted_12 = { class: "ro-text" }
const _hoisted_13 = { class: "num-grid" }
const _hoisted_14 = ["onUpdate:modelValue"]
const _hoisted_15 = {
  key: 0,
  class: "hint"
}
const _hoisted_16 = {
  key: 0,
  class: "hint"
}
const _hoisted_17 = ["value"]
const _hoisted_18 = {
  class: "ro-block",
  style: {"margin-top":"14px"}
}
const _hoisted_19 = { class: "num-grid" }
const _hoisted_20 = ["onUpdate:modelValue"]
const _hoisted_21 = {
  key: 0,
  class: "hint"
}
const _hoisted_22 = {
  key: 2,
  class: "hint",
  style: {"margin-top":"10px","white-space":"pre-wrap"}
}
const _hoisted_23 = {
  class: "hint",
  style: {"margin-top":"6px"}
}

export function render(_ctx, _cache, $props, $setup, $data, $options) {
  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createElementVNode("div", _hoisted_2, [
      _cache[0] || (_cache[0] = _createElementVNode("h3", { style: {"margin":"0"} }, "⚖️ 评阅规则卡（按题目来源分型）", -1 /* CACHED */)),
      _cache[1] || (_cache[1] = _createElementVNode("span", {
        class: "hint",
        style: {"margin":"0"}
      }, [
        _createTextVNode(" 改动"),
        _createElementVNode("b", null, "只影响后续批阅"),
        _createTextVNode("，不改已生成报告；改动会记 journal。 本卡只管"),
        _createElementVNode("b", null, "怎么扣分"),
        _createTextVNode("；生成 AI 评阅要点请到「⑦ 题库 AI 作答」勾选 「同时生成评阅要点」。 ")
      ], -1 /* CACHED */)),
      _cache[2] || (_cache[2] = _createElementVNode("span", { style: {"flex":"1"} }, null, -1 /* CACHED */)),
      _createElementVNode("button", {
        class: "btn small",
        disabled: $setup.loading,
        onClick: $setup.load
      }, "重新读取", 8 /* PROPS */, _hoisted_3),
      _createElementVNode("button", {
        class: "btn small",
        disabled: $setup.saving,
        onClick: $setup.resetAll
      }, "恢复默认", 8 /* PROPS */, _hoisted_4),
      _createElementVNode("button", {
        class: "btn small primary",
        disabled: $setup.saving || $setup.loading,
        onClick: $setup.save
      }, "保存", 8 /* PROPS */, _hoisted_5)
    ]),
    ($setup.loading)
      ? (_openBlock(), _createElementBlock("p", _hoisted_6, "正在读取规则…"))
      : (!$setup.payload?.ok && $setup.payload?.error)
        ? (_openBlock(), _createElementBlock("p", _hoisted_7, "读取失败：" + _toDisplayString($setup.payload.error), 1 /* TEXT */))
        : (_openBlock(), _createElementBlock(_Fragment, { key: 2 }, [
            _createElementVNode("div", _hoisted_8, [
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.kinds, (k) => {
                return (_openBlock(), _createElementBlock("button", {
                  key: k,
                  class: _normalizeClass(["btn small", { primary: k === $setup.activeKind }]),
                  onClick: $event => ($setup.activeKind = k)
                }, _toDisplayString(k), 11 /* TEXT, CLASS, PROPS */, _hoisted_9))
              }), 128 /* KEYED_FRAGMENT */))
            ]),
            _createElementVNode("p", _hoisted_10, _toDisplayString($setup.KIND_LABEL[$setup.activeKind] || $setup.activeKind) + " · 评分算法：" + _toDisplayString($setup.MODE_LABEL[$setup.typeCfg.mode] || $setup.typeCfg.mode || '—'), 1 /* TEXT */),
            _createCommentVNode(" 🔒 只读：进 prompt 的规则摘要（= 教师此前根本看不到的那段文字） "),
            _createElementVNode("details", _hoisted_11, [
              _cache[3] || (_cache[3] = _createElementVNode("summary", null, "🔒 只读 · 实际进入评阅提示词的规则摘要", -1 /* CACHED */)),
              _createElementVNode("pre", _hoisted_12, _toDisplayString($setup.summaryText), 1 /* TEXT */),
              _cache[4] || (_cache[4] = _createElementVNode("p", {
                class: "hint",
                style: {"margin":"4px 0"}
              }, " 这段文字与「生成评阅要点」用的是同一份规则摘要，保证要点粒度与扣分方式匹配。 ", -1 /* CACHED */))
            ]),
            _createCommentVNode(" ✏️ 可改数值：本题型 "),
            _cache[9] || (_cache[9] = _createElementVNode("h4", { style: {"margin":"12px 0 6px"} }, "✏️ 本题型可改数值", -1 /* CACHED */)),
            _createElementVNode("div", _hoisted_13, [
              (_openBlock(), _createElementBlock(_Fragment, null, _renderList($setup.NUM_FIELDS, (f) => {
                return _withDirectives(_createElementVNode("label", {
                  key: 't-' + f.key,
                  class: "num-item"
                }, [
                  _createElementVNode("span", null, _toDisplayString(f.label), 1 /* TEXT */),
                  _withDirectives(_createElementVNode("input", {
                    "onUpdate:modelValue": $event => (($setup.typeCfg[f.key]) = $event),
                    type: "number",
                    step: "any",
                    class: _normalizeClass({ bad: $setup.outOfRange(f.key, $setup.typeCfg[f.key]) })
                  }, null, 10 /* CLASS, PROPS */, _hoisted_14), [
                    [
                      _vModelText,
                      $setup.typeCfg[f.key],
                      void 0,
                      { number: true }
                    ]
                  ]),
                  ($setup.range(f.key))
                    ? (_openBlock(), _createElementBlock("em", _hoisted_15, "范围 " + _toDisplayString($setup.range(f.key)?.[0]) + "~" + _toDisplayString($setup.range(f.key)?.[1]), 1 /* TEXT */))
                    : _createCommentVNode("v-if", true)
                ], 512 /* NEED_PATCH */), [
                  [_vShow, f.key in $setup.typeCfg]
                ])
              }), 64 /* STABLE_FRAGMENT */))
            ]),
            (!Object.keys($setup.typeCfg).some((k) => $setup.NUM_FIELDS.some((f) => f.key === k)))
              ? (_openBlock(), _createElementBlock("p", _hoisted_16, "本题型没有可改数值（见上方只读摘要）。"))
              : _createCommentVNode("v-if", true),
            _createCommentVNode(" ➕ 可改扩展：checklist 项名 "),
            ('checklist' in $setup.typeCfg)
              ? (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                  _cache[5] || (_cache[5] = _createElementVNode("h4", { style: {"margin":"12px 0 6px"} }, "➕ 检查项名称（可改扩展）", -1 /* CACHED */)),
                  _createElementVNode("input", {
                    class: "chk-input",
                    value: $setup.checklistText(),
                    onChange: $setup.setChecklist,
                    placeholder: "用中文逗号分隔，如：题目，解题过程，示意图"
                  }, null, 40 /* PROPS, NEED_HYDRATION */, _hoisted_17),
                  _cache[6] || (_cache[6] = _createElementVNode("p", {
                    class: "hint",
                    style: {"margin":"4px 0"}
                  }, " 重命名检查项会改变报告里的用词；批阅仍然逐项判断是否达标。 ", -1 /* CACHED */))
                ], 64 /* STABLE_FRAGMENT */))
              : _createCommentVNode("v-if", true),
            _createCommentVNode(" ✏️ 全局规则（跨题/跨作业） "),
            _createElementVNode("details", _hoisted_18, [
              _cache[7] || (_cache[7] = _createElementVNode("summary", null, "✏️ 全局规则（跨题、跨作业）", -1 /* CACHED */)),
              _createElementVNode("div", _hoisted_19, [
                (_openBlock(), _createElementBlock(_Fragment, null, _renderList($setup.NUM_FIELDS, (f) => {
                  return _withDirectives(_createElementVNode("label", {
                    key: 'g-' + f.key,
                    class: "num-item"
                  }, [
                    _createElementVNode("span", null, _toDisplayString(f.label), 1 /* TEXT */),
                    _withDirectives(_createElementVNode("input", {
                      "onUpdate:modelValue": $event => (($setup.globalCfg[f.key]) = $event),
                      type: "number",
                      step: "any",
                      class: _normalizeClass({ bad: $setup.outOfRange(f.key, $setup.globalCfg[f.key]) })
                    }, null, 10 /* CLASS, PROPS */, _hoisted_20), [
                      [
                        _vModelText,
                        $setup.globalCfg[f.key],
                        void 0,
                        { number: true }
                      ]
                    ]),
                    ($setup.range(f.key))
                      ? (_openBlock(), _createElementBlock("em", _hoisted_21, "范围 " + _toDisplayString($setup.range(f.key)?.[0]) + "~" + _toDisplayString($setup.range(f.key)?.[1]), 1 /* TEXT */))
                      : _createCommentVNode("v-if", true)
                  ], 512 /* NEED_PATCH */), [
                    [_vShow, f.key in $setup.globalCfg]
                  ])
                }), 64 /* STABLE_FRAGMENT */))
              ]),
              _cache[8] || (_cache[8] = _createElementVNode("p", {
                class: "hint",
                style: {"margin":"4px 0"}
              }, [
                _createTextVNode(" 「整体简略」规则：≥设定比例的题目被判为过程简略时，对"),
                _createElementVNode("b", null, "总分一次性"),
                _createTextVNode("扣分（不逐题累计）。 ")
              ], -1 /* CACHED */))
            ]),
            ($setup.msg)
              ? (_openBlock(), _createElementBlock("p", _hoisted_22, _toDisplayString($setup.msg), 1 /* TEXT */))
              : _createCommentVNode("v-if", true),
            _createElementVNode("p", _hoisted_23, " 规则文件：" + _toDisplayString($setup.payload?.file || '—') + "（引擎缺失时自动写入默认值） ", 1 /* TEXT */)
          ], 64 /* STABLE_FRAGMENT */))
  ]))
}
__sfc_main.render = render
export default __sfc_main

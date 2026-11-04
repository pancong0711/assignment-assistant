import { defineComponent as _defineComponent } from 'vue'
import { computed, ref, watch } from 'vue'
import { fetchKnowledgeTrend, type TrendRecurring, type TrendStat } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/engineClient'


const __sfc_main = /*@__PURE__*/_defineComponent({
  __name: 'TrendCard',
  props: {
    engineAddr: { type: String, required: true },
    token: { type: String, required: false },
    classDir: { type: String, required: true },
    reloadKey: { type: Number, required: false }
  },
  setup(__props: any, { expose: __expose }) {
  __expose();

/** D135：跨多次作业的知识点趋势（**只给教师**）。
 *
 *  数据来自引擎 `/grade/trend`（纯统计，不调 LLM）。
 *  作业序列按**评阅时间**排序；同一知识点在 ≥2 次作业出错 → 「反复出错」。
 *  用纯 SVG 画迷你折线，不引入图表库（离线可用）。
 */
const props = __props

const loading = ref(false)
const stat = ref<TrendStat | null>(null)
const msg = ref('')
const showOneOff = ref(false)
const minRecur = ref(2)

const canLoad = computed(() => Boolean(props.classDir))

async function load() {
  if (!canLoad.value) { msg.value = '请先选择班级（需要班级目录）'; return }
  loading.value = true
  msg.value = ''
  try {
    const r = await fetchKnowledgeTrend(props.engineAddr, props.token,
                                        props.classDir, minRecur.value)
    if (!r?.ok) {
      stat.value = null
      msg.value = `❌ ${r?.error || '读取失败'}`
      return
    }
    stat.value = (r.stat || null) as TrendStat | null
  } catch (e) {
    stat.value = null
    msg.value = `读取失败：${String((e as Error).message || e)}`
  } finally {
    loading.value = false
  }
}

watch(() => [props.classDir, props.reloadKey], () => { if (canLoad.value) load() },
      { immediate: true })

const seq = computed(() => stat.value?.sequence || [])
const rec = computed(() => stat.value?.recurring || [])
const sum = computed(() => stat.value?.summary || { packs: 0, terms: 0, recurring: 0, persisting: 0 })

/** 迷你折线：横轴=作业序号，纵轴=出错率。 */
function sparkline(r: TrendRecurring): string {
  const pts = r.trail
  if (pts.length < 2) return ''
  const n = seq.value.length || pts.length
  const W = 120
  const H = 26
  const idx = (packId: string) => Math.max(0, seq.value.findIndex((s) => s.packId === packId))
  return pts.map((p) => {
    const x = n <= 1 ? 0 : (idx(p.packId) / (n - 1)) * W
    const y = H - Math.min(1, Math.max(0, p.rate)) * (H - 4) - 2
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}

const __returned__ = { props, loading, stat, msg, showOneOff, minRecur, canLoad, load, seq, rec, sum, sparkline }
Object.defineProperty(__returned__, '__isScriptSetup', { enumerable: false, value: true })
return __returned__
}

})
import { createElementVNode as _createElementVNode, vModelText as _vModelText, withDirectives as _withDirectives, createTextVNode as _createTextVNode, toDisplayString as _toDisplayString, openBlock as _openBlock, createElementBlock as _createElementBlock, createCommentVNode as _createCommentVNode, renderList as _renderList, Fragment as _Fragment, normalizeStyle as _normalizeStyle } from "vue"

const _hoisted_1 = { class: "card" }
const _hoisted_2 = { class: "ctl" }
const _hoisted_3 = { class: "hint" }
const _hoisted_4 = ["disabled"]
const _hoisted_5 = {
  key: 0,
  class: "hint"
}
const _hoisted_6 = {
  key: 0,
  class: "hint"
}
const _hoisted_7 = {
  class: "hint",
  style: {"margin":"4px 0"}
}
const _hoisted_8 = { class: "seq" }
const _hoisted_9 = { class: "hint" }
const _hoisted_10 = {
  key: 0,
  class: "tbl"
}
const _hoisted_11 = { class: "c" }
const _hoisted_12 = { class: "c" }
const _hoisted_13 = {
  width: 120,
  height: 26,
  style: {"overflow":"visible"}
}
const _hoisted_14 = ["points", "stroke"]
const _hoisted_15 = { class: "c" }
const _hoisted_16 = {
  key: 1,
  class: "hint"
}
const _hoisted_17 = {
  key: 2,
  style: {"margin-top":"8px"}
}
const _hoisted_18 = {
  class: "hint",
  style: {"margin":"4px 0"}
}

export function render(_ctx, _cache, $props, $setup, $data, $options) {
  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _cache[4] || (_cache[4] = _createElementVNode("div", { class: "hd" }, [
      _createElementVNode("h3", { style: {"margin":"0"} }, "📈 知识点趋势（跨作业）"),
      _createElementVNode("span", { class: "hint" }, "只给教师 · 同一知识点是否反复出错")
    ], -1 /* CACHED */)),
    _createElementVNode("div", _hoisted_2, [
      _createElementVNode("label", _hoisted_3, [
        _cache[2] || (_cache[2] = _createTextVNode("最少出现次数 ", -1 /* CACHED */)),
        _withDirectives(_createElementVNode("input", {
          "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => (($setup.minRecur) = $event)),
          type: "number",
          min: "1",
          max: "10",
          style: {"width":"56px"}
        }, null, 512 /* NEED_PATCH */), [
          [
            _vModelText,
            $setup.minRecur,
            void 0,
            { number: true }
          ]
        ])
      ]),
      _createElementVNode("button", {
        class: "btn",
        disabled: $setup.loading || !$setup.canLoad,
        onClick: $setup.load
      }, _toDisplayString($setup.loading ? '读取中…' : '刷新'), 9 /* TEXT, PROPS */, _hoisted_4),
      ($setup.msg)
        ? (_openBlock(), _createElementBlock("span", _hoisted_5, _toDisplayString($setup.msg), 1 /* TEXT */))
        : _createCommentVNode("v-if", true)
    ]),
    (!$setup.loading && !$setup.seq.length && !$setup.msg)
      ? (_openBlock(), _createElementBlock("p", _hoisted_6, " 该班级还没有评阅结果，无法生成趋势。 "))
      : _createCommentVNode("v-if", true),
    ($setup.seq.length)
      ? (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
          _createElementVNode("p", _hoisted_7, [
            _createTextVNode(" 作业序列 " + _toDisplayString($setup.sum.packs) + " 次 · 涉及知识点 " + _toDisplayString($setup.sum.terms) + " 个 · ", 1 /* TEXT */),
            _createElementVNode("b", null, "反复出错 " + _toDisplayString($setup.sum.recurring) + " 个", 1 /* TEXT */),
            _createTextVNode("（仍在持续 " + _toDisplayString($setup.sum.persisting) + " 个） ", 1 /* TEXT */)
          ]),
          _createElementVNode("ol", _hoisted_8, [
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.seq, (p) => {
              return (_openBlock(), _createElementBlock("li", {
                key: p.packId
              }, [
                _createElementVNode("b", null, _toDisplayString(p.name), 1 /* TEXT */),
                _createElementVNode("span", _hoisted_9, "（" + _toDisplayString(p.at || '—') + " · " + _toDisplayString(p.students) + " 人）", 1 /* TEXT */)
              ]))
            }), 128 /* KEYED_FRAGMENT */))
          ]),
          ($setup.rec.length)
            ? (_openBlock(), _createElementBlock("table", _hoisted_10, [
                _cache[3] || (_cache[3] = _createElementVNode("thead", null, [
                  _createElementVNode("tr", null, [
                    _createElementVNode("th", null, "知识点"),
                    _createElementVNode("th", null, "出现"),
                    _createElementVNode("th", null, "走势"),
                    _createElementVNode("th", null, "判定")
                  ])
                ], -1 /* CACHED */)),
                _createElementVNode("tbody", null, [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.rec, (r) => {
                    return (_openBlock(), _createElementBlock("tr", {
                      key: r.term
                    }, [
                      _createElementVNode("td", null, [
                        _createElementVNode("b", null, _toDisplayString(r.term), 1 /* TEXT */)
                      ]),
                      _createElementVNode("td", _hoisted_11, _toDisplayString(r.packs) + " 次", 1 /* TEXT */),
                      _createElementVNode("td", _hoisted_12, [
                        (_openBlock(), _createElementBlock("svg", _hoisted_13, [
                          _createElementVNode("polyline", {
                            points: $setup.sparkline(r),
                            fill: "none",
                            stroke: r.persisting ? '#dc2626' : '#16a34a',
                            "stroke-width": "1.6"
                          }, null, 8 /* PROPS */, _hoisted_14)
                        ]))
                      ]),
                      _createElementVNode("td", _hoisted_15, [
                        _createElementVNode("b", {
                          style: _normalizeStyle({ color: r.persisting ? '#dc2626' : '#16a34a' })
                        }, _toDisplayString(r.persisting ? '⚠️ 仍在持续' : '📉 有改善'), 5 /* TEXT, STYLE */)
                      ])
                    ]))
                  }), 128 /* KEYED_FRAGMENT */))
                ])
              ]))
            : (_openBlock(), _createElementBlock("p", _hoisted_16, "没有知识点在 ≥" + _toDisplayString($setup.minRecur) + " 次作业里反复出错。", 1 /* TEXT */)),
          (($setup.stat?.oneOff || []).length)
            ? (_openBlock(), _createElementBlock("details", _hoisted_17, [
                _createElementVNode("summary", {
                  class: "hint",
                  style: {"cursor":"pointer"},
                  onClick: _cache[1] || (_cache[1] = $event => ($setup.showOneOff = !$setup.showOneOff))
                }, " 仅出现一次的知识点（" + _toDisplayString(($setup.stat?.oneOff || []).length) + " 个） ", 1 /* TEXT */),
                _createElementVNode("p", _hoisted_18, _toDisplayString(($setup.stat?.oneOff || []).map((x) => x.term).join('、')), 1 /* TEXT */)
              ]))
            : _createCommentVNode("v-if", true)
        ], 64 /* STABLE_FRAGMENT */))
      : _createCommentVNode("v-if", true)
  ]))
}
__sfc_main.render = render
export default __sfc_main

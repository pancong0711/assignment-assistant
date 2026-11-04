import { defineComponent as _defineComponent } from 'vue'
import { computed, onMounted, ref } from 'vue'
import {
  fetchAtopiaJournal, fetchAtopiaTools, postAtopiaLimits, runAtopiaTool,
  type AtopiaTool,
} from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/engineClient'


const __sfc_main = /*@__PURE__*/_defineComponent({
  __name: 'AtopiaPanel',
  props: {
    engineAddr: { type: String, required: true },
    token: { type: String, required: false }
  },
  setup(__props: any, { expose: __expose }) {

/** D132：Atopia 工作区 —— AI 调用本项目工具的**受控**入口。
 *
 *  安全口径（docs/81）：L0/L1 直接执行；**L2 必须教师点击确认**；L3 不开放（连按钮都不给）。
 *  每次调用都在引擎侧写 journal（含 confirmed_by），本页只负责"看清楚 + 确认"。
 */
const props = __props

const tools = ref<AtopiaTool[]>([])
const levels = ref<Record<string, string>>({})
const limits = ref<Record<string, number>>({})
const hardCaps = ref<Record<string, number>>({})
/* D137：护栏可编辑（受硬顶约束；保存前二次确认） */
const limDraft = ref<Record<string, number>>({})
const pendingLimits = ref<Record<string, number> | null>(null)
const limMsg = ref('')
const journal = ref<any[]>([])
const msg = ref('')
const busy = ref(false)

const selected = ref('')
const argsText = ref('{}')
const pending = ref<{ tool: AtopiaTool; args: Record<string, any> } | null>(null)
const output = ref('')

/** L3 不展示为"可执行"——只在末尾列出并明确写"不开放"。 */
const usable = computed(() => tools.value.filter((t) => t.level !== 'L3'))
const denied = computed(() => tools.value.filter((t) => t.level === 'L3'))
const grouped = computed(() => {
  const g: Record<string, AtopiaTool[]> = { L0: [], L1: [], L2: [] }
  for (const t of usable.value) (g[t.level] ||= []).push(t)
  return g
})
const cur = computed(() => tools.value.find((t) => t.name === selected.value) || null)
const LEVEL_NAME: Record<string, string> = {
  L0: 'L0 只读', L1: 'L1 预览（花模型成本）', L2: 'L2 写入（需确认）', L3: 'L3 不开放',
}
const LEVEL_COLOR: Record<string, string> = {
  L0: '#16a34a', L1: '#2563eb', L2: '#b45309', L3: '#9ca3af',
}

async function refresh() {
  busy.value = true
  msg.value = ''
  try {
    const r = await fetchAtopiaTools(props.engineAddr, props.token)
    if (!r?.ok) { msg.value = `读取工具失败：${r?.error || '未知错误'}`; return }
    tools.value = r.tools || []
    levels.value = r.levels || {}
    limits.value = r.limits || {}
    hardCaps.value = r.hardCaps || {}
    if (!Object.keys(limDraft.value).length) limDraft.value = { ...(r.limits || {}) }
    if (!selected.value && usable.value.length) selected.value = usable.value[0]!.name
    await loadJournal()
  } catch (e) {
    msg.value = `读取失败：${String((e as Error).message || e)}（引擎是否在线？）`
  } finally { busy.value = false }
}

function askSaveLimits() {
  const lim = { ...limDraft.value }
  const changed = Object.entries(lim).filter(([k, v]) => Number(v) !== Number(limits.value[k]))
  if (!changed.length) { limMsg.value = '没有改动'; return }
  // 超硬顶**先在前端拦一次**（引擎仍会再校验，这里只为更早给反馈）
  const over = changed.filter(([k, v]) => hardCaps.value[k] && Number(v) > hardCaps.value[k])
  if (over.length) {
    limMsg.value = over.map(([k, v]) => `${k}=${v} 超过硬顶 ${hardCaps.value[k]}`).join('；')
    return
  }
  pendingLimits.value = lim
}

async function confirmSaveLimits() {
  const lim = pendingLimits.value
  pendingLimits.value = null
  if (!lim) return
  try {
    const r = await postAtopiaLimits(props.engineAddr, props.token, lim)
    if (r?.ok) {
      limits.value = r.limits || lim
      limDraft.value = { ...(r.limits || lim) }
      hardCaps.value = r.hardCaps || hardCaps.value
      limMsg.value = '✅ 护栏已保存（下次会话生效）'
    } else {
      limMsg.value = `❌ ${r?.error || '保存失败'}`
    }
  } catch (e) {
    limMsg.value = `保存失败：${String((e as Error).message || e)}`
  }
}

const LIMIT_LABEL: Record<string, string> = {
  maxCallsPerSession: '单会话最多调用次数',
  maxLlmCallsPerSession: '其中会花模型钱的次数',
  callTimeoutSeconds: '单次调用超时（秒）',
  sessionSeconds: '会话总时长（秒）',
}

async function loadJournal() {
  try {
    const r = await fetchAtopiaJournal(props.engineAddr, props.token, 50)
    journal.value = (r?.records || []).slice().reverse()
  } catch { journal.value = [] }
}

function pick(name: string) {
  selected.value = name
  const t = tools.value.find((x) => x.name === name)
  // 按允许参数给出模板，减少手写错误
  const tpl: Record<string, string> = {}
  for (const k of Object.keys(t?.allowedArgs || {})) tpl[k] = ''
  argsText.value = JSON.stringify(tpl, null, 0)
}

function parseArgs(): Record<string, any> | null {
  try {
    const v = JSON.parse(argsText.value || '{}')
    if (typeof v !== 'object' || Array.isArray(v) || v === null) {
      msg.value = '参数必须是 JSON 对象'; return null
    }
    return v as Record<string, any>
  } catch (e) {
    msg.value = `参数不是合法 JSON：${String((e as Error).message)}`
    return null
  }
}

async function run() {
  const t = cur.value
  if (!t) { msg.value = '请先选择工具'; return }
  if (t.level === 'L3') { msg.value = 'L3 工具不开放'; return }
  const args = parseArgs()
  if (args === null) return
  if (t.level === 'L2') {
    // **二次确认**：把工具名 + 参数原样给教师看，默认不执行
    pending.value = { tool: t, args }
    return
  }
  await exec(t, args, '')
}

async function confirmRun() {
  const p = pending.value
  pending.value = null
  if (!p) return
  await exec(p.tool, p.args, 'teacher:pwa')
}

async function exec(t: AtopiaTool, args: Record<string, any>, confirm: string) {
  busy.value = true
  msg.value = ''
  try {
    const r = await runAtopiaTool(props.engineAddr, props.token,
                                      { tool: t.name, args, confirm })
    if (r?.ok) {
      msg.value = `✅ ${t.name} 执行成功（${r.ms}ms，exit ${r.exit}）`
      output.value = String(r.stdout || '')
    } else {
      msg.value = `❌ ${r?.error || '执行失败'}`
      output.value = String(r.stderr || r.stdout || '')
    }
    await loadJournal()
  } catch (e) {
    msg.value = `执行失败：${String((e as Error).message || e)}`
  } finally { busy.value = false }
}

onMounted(refresh)
__expose({ refresh })

const __returned__ = { props, tools, levels, limits, hardCaps, limDraft, pendingLimits, limMsg, journal, msg, busy, selected, argsText, pending, output, usable, denied, grouped, cur, LEVEL_NAME, LEVEL_COLOR, refresh, askSaveLimits, confirmSaveLimits, LIMIT_LABEL, loadJournal, pick, parseArgs, run, confirmRun, exec }
Object.defineProperty(__returned__, '__isScriptSetup', { enumerable: false, value: true })
return __returned__
}

})
import { createElementVNode as _createElementVNode, createTextVNode as _createTextVNode, toDisplayString as _toDisplayString, openBlock as _openBlock, createElementBlock as _createElementBlock, createCommentVNode as _createCommentVNode, renderList as _renderList, Fragment as _Fragment, normalizeStyle as _normalizeStyle, normalizeClass as _normalizeClass, vModelText as _vModelText, withDirectives as _withDirectives } from "vue"

const _hoisted_1 = { class: "asst" }
const _hoisted_2 = { class: "head" }
const _hoisted_3 = ["disabled"]
const _hoisted_4 = {
  key: 0,
  class: "hint"
}
const _hoisted_5 = { class: "grid" }
const _hoisted_6 = { class: "tools" }
const _hoisted_7 = ["onClick"]
const _hoisted_8 = { class: "tname" }
const _hoisted_9 = {
  class: "hint",
  style: {"margin":"0"}
}
const _hoisted_10 = {
  key: 0,
  style: {"margin-top":"10px"}
}
const _hoisted_11 = {
  class: "hint",
  style: {"cursor":"pointer"}
}
const _hoisted_12 = { class: "tname" }
const _hoisted_13 = {
  class: "hint",
  style: {"margin":"0"}
}
const _hoisted_14 = { class: "run" }
const _hoisted_15 = {
  key: 0,
  class: "hint"
}
const _hoisted_16 = { style: {"margin":"0 0 4px"} }
const _hoisted_17 = {
  class: "hint",
  style: {"margin":"0 0 4px"}
}
const _hoisted_18 = { style: {"margin":"6px 0"} }
const _hoisted_19 = ["disabled"]
const _hoisted_20 = {
  key: 0,
  class: "confirm"
}
const _hoisted_21 = { style: {"margin":"0 0 6px"} }
const _hoisted_22 = { class: "args" }
const _hoisted_23 = { style: {"margin":"6px 0 0"} }
const _hoisted_24 = ["disabled"]
const _hoisted_25 = {
  key: 1,
  class: "out"
}
const _hoisted_26 = { class: "lim-grid" }
const _hoisted_27 = ["onUpdate:modelValue"]
const _hoisted_28 = { class: "hint" }
const _hoisted_29 = { style: {"margin":"6px 0"} }
const _hoisted_30 = {
  key: 0,
  class: "hint",
  style: {"margin-left":"8px"}
}
const _hoisted_31 = {
  key: 1,
  class: "confirm"
}
const _hoisted_32 = { class: "args" }
const _hoisted_33 = { style: {"margin":"6px 0 0"} }
const _hoisted_34 = {
  key: 2,
  class: "hint"
}
const _hoisted_35 = {
  key: 3,
  class: "jt"
}
const _hoisted_36 = { class: "c" }
const _hoisted_37 = { class: "c" }

export function render(_ctx, _cache, $props, $setup, $data, $options) {
  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createElementVNode("div", _hoisted_2, [
      _cache[3] || (_cache[3] = _createElementVNode("h3", { style: {"margin":"0"} }, "🧪 Atopia（AI 可调用的本项目工具）", -1 /* CACHED */)),
      _cache[4] || (_cache[4] = _createElementVNode("span", {
        class: "hint",
        style: {"margin":"0"}
      }, [
        _createTextVNode(" 只读直接执行；"),
        _createElementVNode("b", null, "写入需你逐次确认"),
        _createTextVNode("；危险工具不开放。每次调用都记审计日志。 ")
      ], -1 /* CACHED */)),
      _cache[5] || (_cache[5] = _createElementVNode("span", { style: {"flex":"1"} }, null, -1 /* CACHED */)),
      _createElementVNode("button", {
        class: "btn small",
        disabled: $setup.busy,
        onClick: $setup.refresh
      }, "刷新", 8 /* PROPS */, _hoisted_3)
    ]),
    ($setup.msg)
      ? (_openBlock(), _createElementBlock("p", _hoisted_4, _toDisplayString($setup.msg), 1 /* TEXT */))
      : _createCommentVNode("v-if", true),
    _createElementVNode("div", _hoisted_5, [
      _createElementVNode("div", _hoisted_6, [
        (_openBlock(), _createElementBlock(_Fragment, null, _renderList(['L0', 'L1', 'L2'], (lvl) => {
          return (_openBlock(), _createElementBlock(_Fragment, { key: lvl }, [
            ($setup.grouped[lvl]?.length)
              ? (_openBlock(), _createElementBlock("h4", {
                  key: 0,
                  style: _normalizeStyle([{"margin":"8px 0 4px"}, { color: $setup.LEVEL_COLOR[lvl] }])
                }, _toDisplayString($setup.LEVEL_NAME[lvl]) + "（" + _toDisplayString($setup.grouped[lvl]!.length) + "） ", 5 /* TEXT, STYLE */))
              : _createCommentVNode("v-if", true),
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.grouped[lvl], (t) => {
              return (_openBlock(), _createElementBlock("div", {
                key: t.name,
                class: _normalizeClass(["tool", { on: t.name === $setup.selected }]),
                onClick: $event => ($setup.pick(t.name))
              }, [
                _createElementVNode("div", _hoisted_8, _toDisplayString(t.name), 1 /* TEXT */),
                _createElementVNode("div", _hoisted_9, _toDisplayString(t.summary), 1 /* TEXT */)
              ], 10 /* CLASS, PROPS */, _hoisted_7))
            }), 128 /* KEYED_FRAGMENT */))
          ], 64 /* STABLE_FRAGMENT */))
        }), 64 /* STABLE_FRAGMENT */)),
        ($setup.denied.length)
          ? (_openBlock(), _createElementBlock("details", _hoisted_10, [
              _createElementVNode("summary", _hoisted_11, " L3 危险工具（" + _toDisplayString($setup.denied.length) + " 个，**不开放**） ", 1 /* TEXT */),
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.denied, (t) => {
                return (_openBlock(), _createElementBlock("div", {
                  key: t.name,
                  class: "tool off"
                }, [
                  _createElementVNode("div", _hoisted_12, _toDisplayString(t.name), 1 /* TEXT */),
                  _createElementVNode("div", _hoisted_13, _toDisplayString(t.summary), 1 /* TEXT */)
                ]))
              }), 128 /* KEYED_FRAGMENT */))
            ]))
          : _createCommentVNode("v-if", true)
      ]),
      _createElementVNode("div", _hoisted_14, [
        _cache[10] || (_cache[10] = _createElementVNode("h4", { style: {"margin":"4px 0"} }, "执行", -1 /* CACHED */)),
        (!$setup.cur)
          ? (_openBlock(), _createElementBlock("p", _hoisted_15, "从左侧选择一个工具。"))
          : (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
              _createElementVNode("p", _hoisted_16, [
                _createElementVNode("code", null, _toDisplayString($setup.cur.argv.join(' ')), 1 /* TEXT */),
                _createElementVNode("span", {
                  class: "lv",
                  style: _normalizeStyle({ color: $setup.LEVEL_COLOR[$setup.cur.level] })
                }, _toDisplayString($setup.cur.level), 5 /* TEXT, STYLE */)
              ]),
              _createElementVNode("p", _hoisted_17, " 允许参数：" + _toDisplayString(Object.keys($setup.cur.allowedArgs).join(', ') || '（无）'), 1 /* TEXT */),
              _withDirectives(_createElementVNode("textarea", {
                "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => (($setup.argsText) = $event)),
                rows: "3",
                class: "args",
                placeholder: "{\"kind\": \"qa\"}"
              }, null, 512 /* NEED_PATCH */), [
                [_vModelText, $setup.argsText]
              ]),
              _createElementVNode("p", _hoisted_18, [
                _createElementVNode("button", {
                  class: "btn",
                  disabled: $setup.busy || $setup.cur.level === 'L3',
                  onClick: $setup.run
                }, _toDisplayString($setup.cur.level === 'L2' ? '▶ 执行（需确认）' : '▶ 执行'), 9 /* TEXT, PROPS */, _hoisted_19)
              ]),
              _createCommentVNode(" L2 二次确认：显示将要执行的工具与参数 "),
              ($setup.pending)
                ? (_openBlock(), _createElementBlock("div", _hoisted_20, [
                    _createElementVNode("p", _hoisted_21, [
                      _cache[6] || (_cache[6] = _createTextVNode(" ⚠️ ", -1 /* CACHED */)),
                      _createElementVNode("b", null, _toDisplayString($setup.pending.tool.name), 1 /* TEXT */),
                      _cache[7] || (_cache[7] = _createTextVNode(" 是", -1 /* CACHED */)),
                      _cache[8] || (_cache[8] = _createElementVNode("b", null, "写入", -1 /* CACHED */)),
                      _cache[9] || (_cache[9] = _createTextVNode("操作，将修改工作区数据： ", -1 /* CACHED */))
                    ]),
                    _createElementVNode("pre", _hoisted_22, _toDisplayString(JSON.stringify($setup.pending.args, null, 1)), 1 /* TEXT */),
                    _createElementVNode("p", _hoisted_23, [
                      _createElementVNode("button", {
                        class: "btn primary",
                        disabled: $setup.busy,
                        onClick: $setup.confirmRun
                      }, "✅ 我确认执行", 8 /* PROPS */, _hoisted_24),
                      _createElementVNode("button", {
                        class: "btn",
                        style: {"margin-left":"6px"},
                        onClick: _cache[1] || (_cache[1] = $event => ($setup.pending = null))
                      }, "取消")
                    ])
                  ]))
                : _createCommentVNode("v-if", true),
              ($setup.output)
                ? (_openBlock(), _createElementBlock("pre", _hoisted_25, _toDisplayString($setup.output), 1 /* TEXT */))
                : _createCommentVNode("v-if", true)
            ], 64 /* STABLE_FRAGMENT */))
      ])
    ]),
    _createCommentVNode(" D137：护栏可编辑（受硬顶约束） "),
    _cache[13] || (_cache[13] = _createElementVNode("h4", { style: {"margin":"14px 0 4px"} }, "护栏（本次会话的调用上限）", -1 /* CACHED */)),
    _cache[14] || (_cache[14] = _createElementVNode("p", {
      class: "hint",
      style: {"margin":"0 0 6px"}
    }, " 数值可调，但**不能配成无限**——超过硬顶会被拒绝。 ", -1 /* CACHED */)),
    _createElementVNode("div", _hoisted_26, [
      (_openBlock(), _createElementBlock(_Fragment, null, _renderList($setup.LIMIT_LABEL, (lab, k) => {
        return _createElementVNode("label", {
          key: k,
          class: "lim-item"
        }, [
          _createElementVNode("span", null, _toDisplayString(lab), 1 /* TEXT */),
          _withDirectives(_createElementVNode("input", {
            "onUpdate:modelValue": $event => (($setup.limDraft[k]) = $event),
            type: "number",
            min: "1",
            style: {"width":"90px"}
          }, null, 8 /* PROPS */, _hoisted_27), [
            [
              _vModelText,
              $setup.limDraft[k],
              void 0,
              { number: true }
            ]
          ]),
          _createElementVNode("em", _hoisted_28, "硬顶 " + _toDisplayString($setup.hardCaps[k] ?? '—'), 1 /* TEXT */)
        ])
      }), 64 /* STABLE_FRAGMENT */))
    ]),
    _createElementVNode("p", _hoisted_29, [
      _createElementVNode("button", {
        class: "btn",
        onClick: $setup.askSaveLimits
      }, "保存护栏"),
      ($setup.limMsg)
        ? (_openBlock(), _createElementBlock("span", _hoisted_30, _toDisplayString($setup.limMsg), 1 /* TEXT */))
        : _createCommentVNode("v-if", true)
    ]),
    ($setup.pendingLimits)
      ? (_openBlock(), _createElementBlock("div", _hoisted_31, [
          _cache[11] || (_cache[11] = _createElementVNode("p", { style: {"margin":"0 0 6px"} }, "⚠️ 将修改护栏（**影响后续每一次 AI 会话**）：", -1 /* CACHED */)),
          _createElementVNode("pre", _hoisted_32, _toDisplayString(Object.entries($setup.pendingLimits)
        .filter(([k, v]) => Number(v) !== Number($setup.limits[k]))
        .map(([k, v]) => `${k}: ${$setup.limits[k]} → ${v}`).join('\n')), 1 /* TEXT */),
          _createElementVNode("p", _hoisted_33, [
            _createElementVNode("button", {
              class: "btn primary",
              onClick: $setup.confirmSaveLimits
            }, "✅ 我确认修改"),
            _createElementVNode("button", {
              class: "btn",
              style: {"margin-left":"6px"},
              onClick: _cache[2] || (_cache[2] = $event => ($setup.pendingLimits = null))
            }, "取消")
          ])
        ]))
      : _createCommentVNode("v-if", true),
    _cache[15] || (_cache[15] = _createElementVNode("h4", { style: {"margin":"14px 0 4px"} }, "最近调用（审计日志）", -1 /* CACHED */)),
    (!$setup.journal.length)
      ? (_openBlock(), _createElementBlock("p", _hoisted_34, "（还没有调用记录。）"))
      : (_openBlock(), _createElementBlock("table", _hoisted_35, [
          _cache[12] || (_cache[12] = _createElementVNode("thead", null, [
            _createElementVNode("tr", null, [
              _createElementVNode("th", null, "时间"),
              _createElementVNode("th", null, "工具"),
              _createElementVNode("th", null, "级别"),
              _createElementVNode("th", null, "状态"),
              _createElementVNode("th", null, "耗时"),
              _createElementVNode("th", null, "确认")
            ])
          ], -1 /* CACHED */)),
          _createElementVNode("tbody", null, [
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.journal.slice(0, 20), (r, i) => {
              return (_openBlock(), _createElementBlock("tr", { key: i }, [
                _createElementVNode("td", null, _toDisplayString(r.ts), 1 /* TEXT */),
                _createElementVNode("td", null, _toDisplayString(r.tool), 1 /* TEXT */),
                _createElementVNode("td", {
                  class: "c",
                  style: _normalizeStyle({ color: $setup.LEVEL_COLOR[r.level] })
                }, _toDisplayString(r.level), 5 /* TEXT, STYLE */),
                _createElementVNode("td", {
                  class: "c",
                  style: _normalizeStyle({ color: r.status === 'ok' ? '#16a34a' : '#dc2626' })
                }, _toDisplayString(r.status), 5 /* TEXT, STYLE */),
                _createElementVNode("td", _hoisted_36, _toDisplayString(r.ms) + "ms", 1 /* TEXT */),
                _createElementVNode("td", _hoisted_37, _toDisplayString(r.confirmed_by || '—'), 1 /* TEXT */)
              ]))
            }), 128 /* KEYED_FRAGMENT */))
          ])
        ]))
  ]))
}
__sfc_main.render = render
export default __sfc_main

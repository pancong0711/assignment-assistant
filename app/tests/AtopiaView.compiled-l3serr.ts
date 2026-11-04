import { defineComponent as _defineComponent } from 'vue'
import { computed, onMounted, ref } from 'vue'
import { useSettingsStore } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/stores/settings'
import AtopiaPanel from '/home/bot2603/Projects/2609-assignment-assistant/app/tests/AtopiaPanel.compiled-1l2ros.ts'
import {
  askAtopia, fetchAtopiaSessions, fetchLlmConfig,
  type AtopiaAskResult, type AtopiaStep, type LlmProvider,
} from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/engineClient'

const LS_PROV = 'atopia.provider'
const LS_MODEL = 'atopia.model'
interface Msg {
  role: 'user' | 'ai' | 'tool' | 'err'
  text: string
  steps?: AtopiaStep[]
  protocol?: string
  degraded?: boolean
}

const __sfc_main = /*@__PURE__*/_defineComponent({
  __name: 'AtopiaView',
  setup(__props, { expose: __expose }) {
  __expose();

/** D140：Atopia 独立选项卡 —— 让 AI 用本项目工具的**唯一**入口。
 *
 *  分工（docs/89 §1）：
 *   - Playground = 单次调用测模型（**不给工具**，避免绕过 Gate 的旁路）；
 *   - Atopia    = 多轮对话 + 调工具，每一次调用都过 Gate
 *                 （L3 拒绝 / L2 教师逐次确认 / 审计 / 护栏）。
 */
const settings = useSettingsStore()
const tab = ref<'chat' | 'tools'>('chat')

/* ---------- D146：provider / 模型选择 ----------
   与 Playground 同源（/llm/config）；空值 = 沿用「评阅段」配置。
   选择记在 localStorage，下次打开沿用。 */
const providers = ref<LlmProvider[]>([])
const provider = ref(localStorage.getItem(LS_PROV) || '')
const model = ref(localStorage.getItem(LS_MODEL) || '')
const customModel = ref(false)

const modelsOfProvider = computed(() => {
  const p = providers.value.find((x) => x.name === provider.value)
  return (p?.models || []) as string[]
})
const hasModelChoices = computed(() => modelsOfProvider.value.length > 0)

function onProviderChange() {
  localStorage.setItem(LS_PROV, provider.value)
  // 换 provider → 旧模型名多半不适用，清空回落到该 provider 默认
  model.value = ''
  localStorage.setItem(LS_MODEL, '')
  customModel.value = false
  // 会话中途换 provider 会让上下文/缓存错位 → 明确新建会话
  if (msgs.value.length) {
    newSession()
    errMsg.value = '已切换 provider：为保证上下文与缓存正确，已开始新会话。'
  }
}

function onModelChange() {
  localStorage.setItem(LS_MODEL, model.value)
}

async function loadProviders() {
  try {
    const r = await fetchLlmConfig(settings.engineUrl, settings.engineToken)
    providers.value = r?.providers || []
  } catch { providers.value = [] }
}

/* ---------- 对话 ---------- */
const msgs = ref<Msg[]>([])
const input = ref('')
const busy = ref(false)
const sessionId = ref('')
const errMsg = ref('')
const pending = ref<{ tool?: string; args?: Record<string, any>; reason?: string } | null>(null)
const showSteps = ref(true)

function newSession() {
  sessionId.value = `chat-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
  msgs.value = []
  errMsg.value = ''
  pending.value = null
}

async function send(confirmed = false) {
  const task = input.value.trim()
  if (!task || busy.value) return
  if (!sessionId.value) newSession()
  busy.value = true
  errMsg.value = ''
  if (!confirmed) {
    msgs.value.push({ role: 'user', text: task })
    input.value = ''
  }
  try {
    const r: AtopiaAskResult = await askAtopia(settings.engineUrl, settings.engineToken, {
      task: confirmed
        ? `${task}（教师已确认执行写入操作）`
        : task,
      sessionId: sessionId.value,
      confirmed,
      confirmedBy: confirmed ? 'teacher:pwa' : undefined,
      provider: provider.value || undefined,
      model: model.value || undefined,
    })
    if (r?.sessionId) sessionId.value = r.sessionId
    if (r?.pendingConfirm) {
      // L2：**不自动执行**，弹窗让教师看清工具名与参数
      pending.value = r.pendingConfirm
      msgs.value.push({
        role: 'ai',
        text: `要我调用写入工具「${r.pendingConfirm.tool}」，需要你确认。`,
        steps: r.steps, protocol: r.protocol, degraded: r.degraded,
      })
      return
    }
    if (!r?.ok) {
      msgs.value.push({ role: 'err', text: r?.error || '执行失败', steps: r?.steps })
      return
    }
    msgs.value.push({
      role: 'ai', text: r.answer || '（没有文字回答）',
      steps: r.steps, protocol: r.protocol, degraded: r.degraded,
    })
  } catch (e) {
    errMsg.value = String((e as Error).message || e)
  } finally {
    busy.value = false
  }
}

async function confirmPending() {
  const p = pending.value
  pending.value = null
  if (!p) return
  // 教师确认后**重发原始任务**（同一 task 文本），并标记 confirmed
  const last = [...msgs.value].reverse().find((m) => m.role === 'user')
  if (!last) return
  input.value = last.text
  await send(true)
}

/* ---------- 会话历史 ---------- */
const sessions = ref<{ id: string; turns: number; mtime: string }[]>([])
const history = ref<any[]>([])
async function loadSessions() {
  try {
    const r = await fetchAtopiaSessions(settings.engineUrl, settings.engineToken)
    sessions.value = r?.sessions || []
  } catch { sessions.value = [] }
}
async function openSession(id: string) {
  try {
    const r = await fetchAtopiaSessions(settings.engineUrl, settings.engineToken, id)
    history.value = r?.records || []
  } catch { history.value = [] }
}

onMounted(() => { newSession(); loadSessions(); loadProviders() })

const canSend = computed(() => Boolean(input.value.trim()) && !busy.value)

const __returned__ = { settings, tab, LS_PROV, LS_MODEL, providers, provider, model, customModel, modelsOfProvider, hasModelChoices, onProviderChange, onModelChange, loadProviders, msgs, input, busy, sessionId, errMsg, pending, showSteps, newSession, send, confirmPending, sessions, history, loadSessions, openSession, canSend, AtopiaPanel }
Object.defineProperty(__returned__, '__isScriptSetup', { enumerable: false, value: true })
return __returned__
}

})
import { createElementVNode as _createElementVNode, createTextVNode as _createTextVNode, normalizeClass as _normalizeClass, vModelCheckbox as _vModelCheckbox, withDirectives as _withDirectives, openBlock as _openBlock, createElementBlock as _createElementBlock, createCommentVNode as _createCommentVNode, renderList as _renderList, Fragment as _Fragment, toDisplayString as _toDisplayString, normalizeStyle as _normalizeStyle, vModelText as _vModelText, withModifiers as _withModifiers, withKeys as _withKeys, createVNode as _createVNode } from "vue"

const _hoisted_1 = { class: "wrap" }
const _hoisted_2 = { class: "tabs2" }
const _hoisted_3 = {
  key: 0,
  class: "hint"
}
const _hoisted_4 = { class: "picker" }
const _hoisted_5 = ["value"]
const _hoisted_6 = ["value"]
const _hoisted_7 = ["value"]
const _hoisted_8 = ["value"]
const _hoisted_9 = ["value"]
const _hoisted_10 = ["title"]
const _hoisted_11 = {
  key: 2,
  class: "hint",
  style: {"margin":"0"}
}
const _hoisted_12 = { class: "chat" }
const _hoisted_13 = {
  key: 0,
  class: "hint"
}
const _hoisted_14 = { class: "who" }
const _hoisted_15 = {
  key: 0,
  class: "hint"
}
const _hoisted_16 = { class: "bubble" }
const _hoisted_17 = {
  key: 0,
  class: "steps"
}
const _hoisted_18 = {
  class: "hint",
  style: {"cursor":"pointer"}
}
const _hoisted_19 = { class: "hint" }
const _hoisted_20 = {
  key: 0,
  class: "out"
}
const _hoisted_21 = {
  key: 1,
  class: "hint"
}
const _hoisted_22 = {
  key: 1,
  class: "hint"
}
const _hoisted_23 = {
  key: 2,
  class: "err"
}
const _hoisted_24 = { class: "composer" }
const _hoisted_25 = ["disabled"]
const _hoisted_26 = {
  key: 0,
  class: "mask"
}
const _hoisted_27 = { class: "dlg" }
const _hoisted_28 = {
  class: "hint",
  style: {"margin":"0 0 6px"}
}
const _hoisted_29 = { class: "out" }
const _hoisted_30 = {
  class: "hint",
  style: {"margin":"0 0 8px"}
}
const _hoisted_31 = { style: {"display":"flex","gap":"8px","justify-content":"flex-end"} }
const _hoisted_32 = {
  class: "hint",
  style: {"cursor":"pointer"}
}
const _hoisted_33 = {
  key: 0,
  class: "hint"
}
const _hoisted_34 = {
  key: 1,
  class: "sess"
}
const _hoisted_35 = ["onClick"]
const _hoisted_36 = { class: "hint" }
const _hoisted_37 = {
  key: 2,
  class: "out"
}

export function render(_ctx, _cache, $props, $setup, $data, $options) {
  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _cache[19] || (_cache[19] = _createElementVNode("h2", { style: {"margin":"0 0 4px"} }, "Atopia（AI 用本项目工具）", -1 /* CACHED */)),
    _cache[20] || (_cache[20] = _createElementVNode("p", {
      class: "hint",
      style: {"margin":"0 0 8px"}
    }, [
      _createElementVNode("b", null, "唯一"),
      _createTextVNode("让 AI 调用本项目工具的入口：每次调用都过安全 Gate （L3 拒绝 · L2 必须你确认 · 全程审计 · 护栏限次）。 只想\"测模型通不通\"请用 "),
      _createElementVNode("b", null, "Playground"),
      _createTextVNode("（那里不给工具）。 ")
    ], -1 /* CACHED */)),
    _createElementVNode("div", _hoisted_2, [
      _createElementVNode("button", {
        class: _normalizeClass(["btn", { primary: $setup.tab === 'chat' }]),
        onClick: _cache[0] || (_cache[0] = $event => ($setup.tab = 'chat'))
      }, " 💬 对话 ", 2 /* CLASS */),
      _createElementVNode("button", {
        class: _normalizeClass(["btn", { primary: $setup.tab === 'tools' }]),
        onClick: _cache[1] || (_cache[1] = $event => ($setup.tab = 'tools'))
      }, " 🧰 单一工具执行 ", 2 /* CLASS */),
      _cache[11] || (_cache[11] = _createElementVNode("span", { style: {"flex":"1"} }, null, -1 /* CACHED */)),
      ($setup.tab === 'chat')
        ? (_openBlock(), _createElementBlock("label", _hoisted_3, [
            _withDirectives(_createElementVNode("input", {
              "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => (($setup.showSteps) = $event)),
              type: "checkbox"
            }, null, 512 /* NEED_PATCH */), [
              [_vModelCheckbox, $setup.showSteps]
            ]),
            _cache[10] || (_cache[10] = _createTextVNode(" 显示工具调用细节 ", -1 /* CACHED */))
          ]))
        : _createCommentVNode("v-if", true),
      ($setup.tab === 'chat')
        ? (_openBlock(), _createElementBlock("button", {
            key: 1,
            class: "btn",
            onClick: $setup.newSession
          }, "新会话"))
        : _createCommentVNode("v-if", true)
    ]),
    _createCommentVNode(" ============ 对话 ============ "),
    ($setup.tab === 'chat')
      ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
          _createElementVNode("div", _hoisted_4, [
            _cache[14] || (_cache[14] = _createElementVNode("span", {
              class: "hint",
              style: {"margin":"0"}
            }, "provider：", -1 /* CACHED */)),
            _createElementVNode("select", {
              value: $setup.provider,
              onChange: $setup.onProviderChange
            }, [
              _cache[12] || (_cache[12] = _createElementVNode("option", { value: "" }, "（评阅段配置）", -1 /* CACHED */)),
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.providers, (p) => {
                return (_openBlock(), _createElementBlock("option", {
                  key: p.name,
                  value: p.name
                }, _toDisplayString(p.name) + _toDisplayString(p.has_key ? '' : '（无 key）'), 9 /* TEXT, PROPS */, _hoisted_6))
              }), 128 /* KEYED_FRAGMENT */))
            ], 40 /* PROPS, NEED_HYDRATION */, _hoisted_5),
            _cache[15] || (_cache[15] = _createElementVNode("span", {
              class: "hint",
              style: {"margin":"0"}
            }, "模型：", -1 /* CACHED */)),
            ($setup.hasModelChoices && !$setup.customModel)
              ? (_openBlock(), _createElementBlock("select", {
                  key: 0,
                  value: $setup.model,
                  onChange: _cache[3] || (_cache[3] = $event => {$setup.model = ($event.target as HTMLSelectElement).value; $setup.onModelChange()})
                }, [
                  _cache[13] || (_cache[13] = _createElementVNode("option", { value: "" }, "（默认）", -1 /* CACHED */)),
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.modelsOfProvider, (m) => {
                    return (_openBlock(), _createElementBlock("option", {
                      key: m,
                      value: m
                    }, _toDisplayString(m), 9 /* TEXT, PROPS */, _hoisted_8))
                  }), 128 /* KEYED_FRAGMENT */))
                ], 40 /* PROPS, NEED_HYDRATION */, _hoisted_7))
              : (_openBlock(), _createElementBlock("input", {
                  key: 1,
                  value: $setup.model,
                  placeholder: "模型名（空=默认）",
                  style: {"width":"170px"},
                  onChange: _cache[4] || (_cache[4] = $event => {$setup.model = ($event.target as HTMLInputElement).value; $setup.onModelChange()})
                }, null, 40 /* PROPS, NEED_HYDRATION */, _hoisted_9)),
            _createElementVNode("button", {
              class: "btn small",
              onClick: _cache[5] || (_cache[5] = $event => ($setup.customModel = !$setup.customModel)),
              title: $setup.hasModelChoices ? '切换下拉/自定义输入' : '该 provider 暂无候选模型'
            }, _toDisplayString($setup.customModel ? '用下拉' : '自定义'), 9 /* TEXT, PROPS */, _hoisted_10),
            ($setup.provider)
              ? (_openBlock(), _createElementBlock("span", _hoisted_11, " （该 provider 的请求头/鉴权生效） "))
              : _createCommentVNode("v-if", true)
          ]),
          _createElementVNode("div", _hoisted_12, [
            (!$setup.msgs.length)
              ? (_openBlock(), _createElementBlock("p", _hoisted_13, " 例：「看看题库里 chap04 有多少题」「把 chap04 的知识点建议抽出来」 「列出课堂资料里有哪些文件」。写入类操作会弹窗让你确认。 "))
              : _createCommentVNode("v-if", true),
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.msgs, (m, i) => {
              return (_openBlock(), _createElementBlock("div", {
                key: i,
                class: _normalizeClass(["msg", m.role])
              }, [
                _createElementVNode("div", _hoisted_14, [
                  _createTextVNode(_toDisplayString(m.role === 'user' ? '你' : m.role === 'ai' ? 'Atopia' : '⚠️ 错误') + " ", 1 /* TEXT */),
                  (m.protocol)
                    ? (_openBlock(), _createElementBlock("span", _hoisted_15, " （" + _toDisplayString(m.protocol) + _toDisplayString(m.degraded ? ' · 已降级' : '') + "） ", 1 /* TEXT */))
                    : _createCommentVNode("v-if", true)
                ]),
                _createElementVNode("div", _hoisted_16, _toDisplayString(m.text), 1 /* TEXT */),
                ($setup.showSteps && (m.steps || []).length)
                  ? (_openBlock(), _createElementBlock("details", _hoisted_17, [
                      _createElementVNode("summary", _hoisted_18, " 工具调用 " + _toDisplayString((m.steps || []).filter((s) => s.action === 'tool').length) + " 次 ", 1 /* TEXT */),
                      _createElementVNode("ul", null, [
                        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList((m.steps || []), (s, k) => {
                          return (_openBlock(), _createElementBlock("li", { key: k }, [
                            (s.action === 'tool')
                              ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                                  _createElementVNode("b", null, _toDisplayString(s.tool), 1 /* TEXT */),
                                  _createElementVNode("span", _hoisted_19, _toDisplayString(JSON.stringify(s.args || {})), 1 /* TEXT */),
                                  _createElementVNode("b", {
                                    style: _normalizeStyle({ color: s.ok ? '#16a34a' : '#dc2626' })
                                  }, _toDisplayString(s.ok ? '✓' : '✗') + _toDisplayString(s.denied ? ' 已拒绝' : ''), 5 /* TEXT, STYLE */),
                                  (s.out || s.err)
                                    ? (_openBlock(), _createElementBlock("pre", _hoisted_20, _toDisplayString((s.out || s.err || '').slice(0, 400)), 1 /* TEXT */))
                                    : _createCommentVNode("v-if", true)
                                ], 64 /* STABLE_FRAGMENT */))
                              : (_openBlock(), _createElementBlock("span", _hoisted_21, _toDisplayString(s.action), 1 /* TEXT */))
                          ]))
                        }), 128 /* KEYED_FRAGMENT */))
                      ])
                    ]))
                  : _createCommentVNode("v-if", true)
              ], 2 /* CLASS */))
            }), 128 /* KEYED_FRAGMENT */)),
            ($setup.busy)
              ? (_openBlock(), _createElementBlock("p", _hoisted_22, "Atopia 正在工作…（可能在调用工具）"))
              : _createCommentVNode("v-if", true),
            ($setup.errMsg)
              ? (_openBlock(), _createElementBlock("p", _hoisted_23, _toDisplayString($setup.errMsg), 1 /* TEXT */))
              : _createCommentVNode("v-if", true)
          ]),
          _createElementVNode("div", _hoisted_24, [
            _withDirectives(_createElementVNode("textarea", {
              "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => (($setup.input) = $event)),
              rows: "2",
              placeholder: "告诉 Atopia 你要做什么（Enter 发送，Shift+Enter 换行）",
              onKeydown: _cache[7] || (_cache[7] = _withKeys(_withModifiers($event => ($setup.send(false)), ["exact","prevent"]), ["enter"]))
            }, null, 544 /* NEED_HYDRATION, NEED_PATCH */), [
              [_vModelText, $setup.input]
            ]),
            _createElementVNode("button", {
              class: "btn primary",
              disabled: !$setup.canSend,
              onClick: _cache[8] || (_cache[8] = $event => ($setup.send(false)))
            }, _toDisplayString($setup.busy ? '执行中…' : '发送'), 9 /* TEXT, PROPS */, _hoisted_25)
          ]),
          _createCommentVNode(" L2 确认弹窗 "),
          ($setup.pending)
            ? (_openBlock(), _createElementBlock("div", _hoisted_26, [
                _createElementVNode("div", _hoisted_27, [
                  _cache[18] || (_cache[18] = _createElementVNode("h3", { style: {"margin":"0 0 8px"} }, "确认让 Atopia 执行这个写入操作？", -1 /* CACHED */)),
                  _createElementVNode("p", _hoisted_28, [
                    _cache[16] || (_cache[16] = _createTextVNode(" 工具：", -1 /* CACHED */)),
                    _createElementVNode("code", null, _toDisplayString($setup.pending.tool), 1 /* TEXT */),
                    _cache[17] || (_cache[17] = _createTextVNode("（L2 写入，会修改工作区数据） ", -1 /* CACHED */))
                  ]),
                  _createElementVNode("pre", _hoisted_29, _toDisplayString(JSON.stringify($setup.pending.args || {}, null, 1)), 1 /* TEXT */),
                  _createElementVNode("p", _hoisted_30, _toDisplayString($setup.pending.reason || ''), 1 /* TEXT */),
                  _createElementVNode("div", _hoisted_31, [
                    _createElementVNode("button", {
                      class: "btn",
                      onClick: _cache[9] || (_cache[9] = $event => ($setup.pending = null))
                    }, "拒绝"),
                    _createElementVNode("button", {
                      class: "btn primary",
                      onClick: $setup.confirmPending
                    }, "我确认执行")
                  ])
                ])
              ]))
            : _createCommentVNode("v-if", true),
          _createElementVNode("details", {
            style: {"margin-top":"12px"},
            onToggle: $setup.loadSessions
          }, [
            _createElementVNode("summary", _hoisted_32, "会话历史（" + _toDisplayString($setup.sessions.length) + "）", 1 /* TEXT */),
            (!$setup.sessions.length)
              ? (_openBlock(), _createElementBlock("p", _hoisted_33, "（还没有会话记录。）"))
              : (_openBlock(), _createElementBlock("ul", _hoisted_34, [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.sessions.slice(0, 20), (s) => {
                    return (_openBlock(), _createElementBlock("li", {
                      key: s.id
                    }, [
                      _createElementVNode("a", {
                        href: "javascript:;",
                        onClick: $event => ($setup.openSession(s.id))
                      }, [
                        _createElementVNode("code", null, _toDisplayString(s.id), 1 /* TEXT */)
                      ], 8 /* PROPS */, _hoisted_35),
                      _createElementVNode("span", _hoisted_36, _toDisplayString(s.mtime) + " · " + _toDisplayString(s.turns) + " 轮", 1 /* TEXT */)
                    ]))
                  }), 128 /* KEYED_FRAGMENT */))
                ])),
            ($setup.history.length)
              ? (_openBlock(), _createElementBlock("pre", _hoisted_37, _toDisplayString(JSON.stringify($setup.history, null, 1).slice(0, 3000)), 1 /* TEXT */))
              : _createCommentVNode("v-if", true)
          ], 32 /* NEED_HYDRATION */)
        ], 64 /* STABLE_FRAGMENT */))
      : (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
          _createCommentVNode(" ============ 单一工具执行（原面板） ============ "),
          _createVNode($setup["AtopiaPanel"], {
            "engine-addr": $setup.settings.engineUrl,
            token: $setup.settings.engineToken
          }, null, 8 /* PROPS */, ["engine-addr", "token"])
        ], 2112 /* STABLE_FRAGMENT, DEV_ROOT_FRAGMENT */))
  ]))
}
__sfc_main.render = render
export default __sfc_main

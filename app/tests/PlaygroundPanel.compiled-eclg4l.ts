import { defineComponent as _defineComponent } from 'vue'
import { computed, onMounted, ref, watch } from 'vue'
import {
  fetchLlmConfig, fetchPlaygroundRecords, mutatePlaygroundFolder, mutatePlaygroundRecord,
  playgroundAsk, playgroundBatch, postLlmProvider, uploadPlaygroundAttachment, type PlaygroundRecord,
} from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/engineClient'

const DRAFT_KEY = 'assignment-assistant.playground.draft.v1'

const __sfc_main = /*@__PURE__*/_defineComponent({
  __name: 'PlaygroundPanel',
  props: {
    engineAddr: { type: String, required: true },
    token: { type: String, required: false }
  },
  setup(__props: any, { expose: __expose }) {
  __expose();

/** D90 Playground —— 单次调用大模型做试验（无多轮上下文）。
 *  提问（文本 + 图片/文档附件）+ provider/模型选择 → 一次调用 → 呈现回复；
 *  支持批量发送；问题/答案本地留档（<ws>/playground/records/）+ 文件夹管理/勾选查看/移动/删除。
 *  与 D86 provider/key 安全同口径（key 只在引擎侧，绝不下发/入日志）。 */
const props = __props

/* ---------- provider / 模型选择（D90 明确要求） ---------- */
const providers = ref<Array<{ name: string; models?: string[]; has_key?: boolean }>>([])
const provider = ref('')          // '' = 用 D86 评阅段配置
const model = ref('')             // 选中的模型名（或自定义输入）
const customModel = ref(false)    // 是否切到"自定义输入"
const temperature = ref<number | null>(null)
const modelsOfProvider = computed(() =>
  (providers.value.find((p) => p.name === provider.value)?.models || []))

async function loadProviders() {
  try {
    const cfg = await fetchLlmConfig(props.engineAddr, props.token)
    providers.value = (cfg?.providers || []) as any[]
  } catch { providers.value = [] }
}
/** 有候选模型才用下拉；否则提示去 ① 记录，或直接自定义输入。 */
const hasModelChoices = computed(() => modelsOfProvider.value.length > 0)

/** D91-M3：把当前模型名记录为 provider 的候选（写 models[]，与 ① 区"填写即记录"同源）。 */
async function rememberModel() {
  const name = model.value.trim()
  if (!provider.value) { msg.value = '请先选 provider（评阅段配置无法记录候选）'; return }
  if (!name) { msg.value = '请先填/选一个模型名'; return }
  const r = await postLlmProvider(props.engineAddr, props.token,
    { action: 'set', name: provider.value, model: name })
  if (r?.ok) { await loadProviders(); msg.value = `已记录候选模型「${name}」到 provider「${provider.value}」` }
  else msg.value = r?.error || '记录失败'
}
async function forgetModel(name: string) {
  if (!provider.value || !name) return
  const r = await postLlmProvider(props.engineAddr, props.token,
    { action: 'set', name: provider.value, forget_model: name })
  if (r?.ok) {
    if (model.value === name) model.value = ''
    await loadProviders()
    msg.value = `已从 provider「${provider.value}」删除候选「${name}」`
  } else msg.value = r?.error || '删除失败'
}

/* ---------- 提问 ---------- */
const question = ref('')
const attachments = ref<Array<{ name: string; path: string; kind: string }>>([])
const busy = ref(false)
const answer = ref('')
const lastModel = ref('')
const msg = ref('')
const batchMode = ref(false)
const batchText = ref('')          // 每行一个问题
const folder = ref('默认')

function onPickFiles(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  uploadFiles(files)
  input.value = ''
}
async function uploadFiles(files: File[]) {
  for (const f of files) {
    const dataUrl = await readAsDataURL(f)
    try {
      const r = await uploadPlaygroundAttachment(props.engineAddr, props.token, { name: f.name, data: dataUrl })
      if (r?.ok && r.path) attachments.value.push({ name: r.name || f.name, path: r.path, kind: r.kind || '' })
      else msg.value = r?.error || `上传失败：${f.name}`
    } catch {
      // 引擎离线：退化为仅文件名（引擎会提示附件不存在）——不阻塞提问
      attachments.value.push({ name: f.name, path: '', kind: '（未上传：引擎离线）' })
    }
  }
}
function readAsDataURL(f: File): Promise<string> {
  return new Promise((resolve) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => resolve('')
    reader.readAsDataURL(f)
  })
}
function removeAttachment(i: number) { attachments.value.splice(i, 1) }

async function doAsk() {
  if (busy.value) return
  if (!question.value.trim() && !attachments.value.length) { msg.value = '请输入问题或添加附件'; return }
  busy.value = true; msg.value = '正在调用大模型……'; answer.value = ''
  try {
    const r = await playgroundAsk(props.engineAddr, props.token, {
      question: question.value, attachments: attachments.value.map((a) => a.path).filter(Boolean),
      provider: provider.value, model: model.value, temperature: temperature.value, folder: folder.value,
    })
    if (r?.ok) { answer.value = r.answer || ''; lastModel.value = r.model || ''; msg.value = '完成（已留档）' }
    else msg.value = r?.error || '调用失败'
  } catch (e) { msg.value = String((e as Error).message || e) }
  finally { busy.value = false; loadRecords() }
}

async function doBatch() {
  if (busy.value) return
  const qs = batchText.value.split('\n').map((x) => x.trim()).filter(Boolean)
  if (!qs.length) { msg.value = '请每行填一个问题'; return }
  busy.value = true; msg.value = `批量发送 ${qs.length} 条……`; answer.value = ''
  try {
    const r = await playgroundBatch(props.engineAddr, props.token, {
      questions: qs, attachments: attachments.value.map((a) => a.path).filter(Boolean),
      provider: provider.value, model: model.value, folder: folder.value,
    })
    if (r?.ok) {
      answer.value = (r.results || []).map((x, i) =>
        `### 第 ${i + 1} 问\n\n${x.question}\n\n${x.ok ? x.answer : '（失败：' + (x.error || '') + '）'}`).join('\n\n---\n\n')
      msg.value = `完成：成功 ${r.succeeded}/${r.total}（已留档）`
    } else msg.value = r?.error || '批量失败'
  } catch (e) { msg.value = String((e as Error).message || e) }
  finally { busy.value = false; loadRecords() }
}

/* ---------- 记录管理 ---------- */
const records = ref<PlaygroundRecord[]>([])
const folders = ref<string[]>(['默认'])
const selected = ref<string[]>([])
const expanded = ref('')           // 展开查看的记录 id
const newFolder = ref('')

async function loadRecords() {
  try {
    const r = await fetchPlaygroundRecords(props.engineAddr, props.token)
    records.value = r?.records || []
    folders.value = r?.folders || ['默认']
  } catch { /* 引擎离线：保留现状 */ }
}
const grouped = computed(() => {
  const g: Record<string, PlaygroundRecord[]> = {}
  for (const f of folders.value) g[f] = []
  for (const rec of records.value) {
    const f = rec.folder && folders.value.includes(rec.folder) ? rec.folder : folders.value[0]
    ;(g[f] = g[f] || []).push(rec)
  }
  return g
})
function toggleSelect(id: string) {
  const i = selected.value.indexOf(id)
  if (i >= 0) selected.value.splice(i, 1); else selected.value.push(id)
}
async function delOne(id: string) {
  await mutatePlaygroundRecord(props.engineAddr, props.token, { action: 'delete', id })
  selected.value = selected.value.filter((x) => x !== id)
  await loadRecords()
}
async function delSelected() {
  for (const id of [...selected.value]) {
    await mutatePlaygroundRecord(props.engineAddr, props.token, { action: 'delete', id })
  }
  selected.value = []; await loadRecords()
}
async function moveSelected(target: string) {
  if (!selected.value.length) return
  await mutatePlaygroundRecord(props.engineAddr, props.token, { action: 'move', ids: selected.value, folder: target })
  selected.value = []; await loadRecords()
}
async function addFolder() {
  if (!newFolder.value.trim()) return
  await mutatePlaygroundFolder(props.engineAddr, props.token, { action: 'new', name: newFolder.value.trim() })
  newFolder.value = ''; await loadRecords()
}
async function delFolder(name: string) {
  await mutatePlaygroundFolder(props.engineAddr, props.token, { action: 'delete', name })
  await loadRecords()
}

/* ---------- 回复渲染（沙箱 iframe + 自托管 KaTeX，离线可渲染） ---------- */
const answerHtml = computed(() => {
  // 用沙箱 iframe + 自托管 KaTeX auto-render（离线可渲染）；纯文本安全回填。
  // 注意：拼接 '</scr'+'ipt>' 避免 SFC 的 <script> 被提前闭合。
  const ST = '<' + 'script'
  const SE = '</scr' + 'ipt>'
  // KaTeX auto-render 初始化（纯字符串，避免污染被转译的函数；delimiters 覆盖 $$ $ \( \) \[ \]）
  const katexInit =
    'var el=document.getElementById("c");' +
    'if(el&&window.renderMathInElement){try{renderMathInElement(el,{delimiters:[' +
    '{left:"$$",right:"$$",display:true},{left:"$",right:"$",display:false},' +
    '{left:"\\(",right:"\\)",display:false},{left:"\\[",right:"\\]",display:true}' +
    ']})}catch(e){}}'
  return [
    '<!doctype html><html><head><meta charset="utf-8">',
    '<link rel="stylesheet" href="./katex/katex.min.css">',
    '<style>body{font-family:system-ui,sans-serif;font-size:14px;line-height:1.7;padding:12px;color:#1f2937}',
    'h3{margin:.6em 0 .3em}pre{background:#f5f6f8;padding:8px;border-radius:6px;overflow:auto}',
    'code{background:#f0f1f3;padding:1px 4px;border-radius:3px}</style></head><body>',
    '<div id="c"></div>',
    ST + '>window.__ans=' + JSON.stringify(answer.value || '') + ';document.getElementById("c").textContent=window.__ans;' + SE,
    ST + ' src="./katex/katex.min.js">' + SE,
    ST + ' src="./katex/contrib/auto-render.min.js">' + SE,
    ST + '>' + katexInit + SE,
    '</body></html>',
  ].join('')
})

/* ---------- D91-M4：输入草稿自动保存（localStorage；刷新不丢，可清空） ---------- */
function saveDraft() {
  try {
    localStorage.setItem(DRAFT_KEY, JSON.stringify({
      provider: provider.value, model: model.value, customModel: customModel.value,
      temperature: temperature.value, folder: folder.value, batchMode: batchMode.value,
      question: question.value, batchText: batchText.value, attachments: attachments.value,
    }))
  } catch { /* 容量/隐私降级 */ }
}
function loadDraft() {
  try {
    const d = JSON.parse(localStorage.getItem(DRAFT_KEY) ?? 'null')
    if (!d || typeof d !== 'object') return
    provider.value = String(d.provider ?? '')
    model.value = String(d.model ?? '')
    customModel.value = !!d.customModel
    temperature.value = d.temperature ?? null
    folder.value = String(d.folder ?? '默认')
    batchMode.value = !!d.batchMode
    question.value = String(d.question ?? '')
    batchText.value = String(d.batchText ?? '')
    attachments.value = Array.isArray(d.attachments) ? d.attachments : []
  } catch { /* ignore */ }
}
function clearDraft() {
  question.value = ''; batchText.value = ''; attachments.value = []
  try { localStorage.removeItem(DRAFT_KEY) } catch { /* ignore */ }
  msg.value = '已清空草稿'
}
// 任一输入变化即存（自动保存）
watch([provider, model, customModel, temperature, folder, batchMode, question, batchText, attachments],
      saveDraft, { deep: true })

onMounted(() => { loadProviders(); loadRecords(); loadDraft() })

const __returned__ = { props, providers, provider, model, customModel, temperature, modelsOfProvider, loadProviders, hasModelChoices, rememberModel, forgetModel, question, attachments, busy, answer, lastModel, msg, batchMode, batchText, folder, onPickFiles, uploadFiles, readAsDataURL, removeAttachment, doAsk, doBatch, records, folders, selected, expanded, newFolder, loadRecords, grouped, toggleSelect, delOne, delSelected, moveSelected, addFolder, delFolder, answerHtml, DRAFT_KEY, saveDraft, loadDraft, clearDraft }
Object.defineProperty(__returned__, '__isScriptSetup', { enumerable: false, value: true })
return __returned__
}

})
import { createElementVNode as _createElementVNode, createTextVNode as _createTextVNode, renderList as _renderList, Fragment as _Fragment, openBlock as _openBlock, createElementBlock as _createElementBlock, toDisplayString as _toDisplayString, vModelSelect as _vModelSelect, withDirectives as _withDirectives, createCommentVNode as _createCommentVNode, vModelText as _vModelText, vModelCheckbox as _vModelCheckbox, createStaticVNode as _createStaticVNode } from "vue"

const _hoisted_1 = { style: {"display":"flex","gap":"8px","align-items":"center","flex-wrap":"wrap","margin-bottom":"6px"} }
const _hoisted_2 = ["value"]
const _hoisted_3 = ["value"]
const _hoisted_4 = ["title"]
const _hoisted_5 = { class: "field" }
const _hoisted_6 = ["value"]
const _hoisted_7 = { style: {"display":"flex","gap":"8px","align-items":"flex-start","flex-wrap":"wrap"} }
const _hoisted_8 = { style: {"flex":"1 1 360px","min-width":"320px"} }
const _hoisted_9 = { class: "field" }
const _hoisted_10 = { style: {"margin":"6px 0","display":"flex","gap":"8px","align-items":"center","flex-wrap":"wrap"} }
const _hoisted_11 = ["disabled"]
const _hoisted_12 = ["disabled"]
const _hoisted_13 = {
  key: 2,
  class: "hint",
  style: {"margin":"0"}
}
const _hoisted_14 = { class: "hint" }
const _hoisted_15 = ["onClick"]
const _hoisted_16 = {
  key: 2,
  class: "hint"
}
const _hoisted_17 = { style: {"flex":"1 1 360px","min-width":"320px"} }
const _hoisted_18 = ["srcdoc"]
const _hoisted_19 = { style: {"display":"flex","gap":"8px","align-items":"center","flex-wrap":"wrap","margin":"0 0 6px"} }
const _hoisted_20 = {
  class: "hint",
  style: {"margin":"0"}
}
const _hoisted_21 = ["disabled"]
const _hoisted_22 = ["value"]
const _hoisted_23 = ["disabled"]
const _hoisted_24 = { style: {"display":"flex","align-items":"center","gap":"8px"} }
const _hoisted_25 = {
  class: "hint",
  style: {"margin":"0"}
}
const _hoisted_26 = ["onClick"]
const _hoisted_27 = {
  key: 0,
  class: "grid",
  style: {"font-size":"12px","width":"100%"}
}
const _hoisted_28 = ["checked", "onChange"]
const _hoisted_29 = { style: {"white-space":"nowrap"} }
const _hoisted_30 = { style: {"white-space":"nowrap"} }
const _hoisted_31 = ["title"]
const _hoisted_32 = { style: {"white-space":"nowrap"} }
const _hoisted_33 = ["onClick"]
const _hoisted_34 = ["onClick"]
const _hoisted_35 = { key: 0 }
const _hoisted_36 = { colspan: "4" }
const _hoisted_37 = { style: {"border":"1px solid var(--c-border)","border-radius":"6px","padding":"6px","white-space":"pre-wrap"} }
const _hoisted_38 = {
  key: 0,
  class: "hint"
}
const _hoisted_39 = { style: {"margin-top":"6px"} }
const _hoisted_40 = {
  key: 1,
  style: {"color":"#b91c1c"}
}
const _hoisted_41 = {
  key: 1,
  class: "hint",
  style: {"margin":"2px 0 0"}
}

export function render(_ctx, _cache, $props, $setup, $data, $options) {
  return (_openBlock(), _createElementBlock("div", null, [
    _cache[27] || (_cache[27] = _createStaticVNode("<h3 style=\"margin-top:14px;\">⑧ Playground（单次调用大模型 · 无多轮上下文）</h3><p class=\"hint\" style=\"margin:0 0 6px;\"> 这里只做<b>单次调用</b>：测模型/测连通性/看一次回答的质量，<b>不保存上下文</b>， 也<b>不会</b>调用本项目的工具。 需要<b>多轮对话</b>或让 AI <b>使用本项目工具</b>，请到顶部 <b>Atopia</b> 选项卡（所有工具调用都会经过安全 Gate）。 </p><p class=\"hint\" style=\"margin:0 0 6px;\"> 提问（文本 + 图片/文档附件）→ 一次调用 → 呈现回复；支持批量；问题与答案**本地留档**（<code>&lt;ws&gt;/playground/</code>）。 文档支持 pdf/docx/txt（旧版 .doc 请转 docx/pdf）。输入内容**自动保存到本浏览器**（刷新不丢）。 </p>", 3)),
    _createElementVNode("div", _hoisted_1, [
      _cache[15] || (_cache[15] = _createElementVNode("span", {
        class: "hint",
        style: {"margin":"0"}
      }, "provider：", -1 /* CACHED */)),
      _withDirectives(_createElementVNode("select", {
        "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => (($setup.provider) = $event)),
        style: {"min-width":"160px"}
      }, [
        _cache[12] || (_cache[12] = _createElementVNode("option", { value: "" }, "（评阅段配置）", -1 /* CACHED */)),
        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.providers, (p) => {
          return (_openBlock(), _createElementBlock("option", {
            key: p.name,
            value: p.name
          }, _toDisplayString(p.name) + _toDisplayString(p.has_key ? '' : '（无 key）'), 9 /* TEXT, PROPS */, _hoisted_2))
        }), 128 /* KEYED_FRAGMENT */))
      ], 512 /* NEED_PATCH */), [
        [_vModelSelect, $setup.provider]
      ]),
      _cache[16] || (_cache[16] = _createElementVNode("span", {
        class: "hint",
        style: {"margin":"0"}
      }, "模型：", -1 /* CACHED */)),
      ($setup.hasModelChoices && !$setup.customModel)
        ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
            _withDirectives(_createElementVNode("select", {
              "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => (($setup.model) = $event)),
              style: {"min-width":"160px"}
            }, [
              _cache[13] || (_cache[13] = _createElementVNode("option", { value: "" }, "（默认）", -1 /* CACHED */)),
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.modelsOfProvider, (m) => {
                return (_openBlock(), _createElementBlock("option", {
                  key: m,
                  value: m
                }, _toDisplayString(m), 9 /* TEXT, PROPS */, _hoisted_3))
              }), 128 /* KEYED_FRAGMENT */))
            ], 512 /* NEED_PATCH */), [
              [_vModelSelect, $setup.model]
            ]),
            ($setup.model)
              ? (_openBlock(), _createElementBlock("button", {
                  key: 0,
                  class: "btn small",
                  title: "删除该候选模型",
                  onClick: _cache[2] || (_cache[2] = $event => ($setup.forgetModel($setup.model)))
                }, "✕"))
              : _createCommentVNode("v-if", true)
          ], 64 /* STABLE_FRAGMENT */))
        : _withDirectives((_openBlock(), _createElementBlock("input", {
            key: 1,
            "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => (($setup.model) = $event)),
            placeholder: "模型名（空=默认）",
            style: {"width":"180px"}
          }, null, 512 /* NEED_PATCH */)), [
            [_vModelText, $setup.model]
          ]),
      _createElementVNode("button", {
        class: "btn small",
        onClick: _cache[4] || (_cache[4] = $event => ($setup.customModel = !$setup.customModel)),
        title: $setup.hasModelChoices ? '切换到自定义输入/下拉' : '该 provider 暂无候选：填模型名后可记录'
      }, _toDisplayString($setup.customModel ? '用下拉' : '自定义'), 9 /* TEXT, PROPS */, _hoisted_4),
      _createElementVNode("button", {
        class: "btn small",
        title: "把当前模型名记录为候选（下次可下拉选）",
        onClick: $setup.rememberModel
      }, "＋记录候选"),
      _createElementVNode("label", _hoisted_5, [
        _cache[14] || (_cache[14] = _createTextVNode("temperature：", -1 /* CACHED */)),
        _withDirectives(_createElementVNode("input", {
          type: "number",
          step: "0.1",
          min: "0",
          max: "2",
          "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => (($setup.temperature) = $event)),
          style: {"width":"64px"}
        }, null, 512 /* NEED_PATCH */), [
          [
            _vModelText,
            $setup.temperature,
            void 0,
            { number: true }
          ]
        ])
      ]),
      _cache[17] || (_cache[17] = _createElementVNode("span", {
        class: "hint",
        style: {"margin":"0"}
      }, "归入文件夹：", -1 /* CACHED */)),
      _withDirectives(_createElementVNode("select", {
        "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => (($setup.folder) = $event)),
        style: {"min-width":"120px"}
      }, [
        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.folders, (f) => {
          return (_openBlock(), _createElementBlock("option", {
            key: f,
            value: f
          }, _toDisplayString(f), 9 /* TEXT, PROPS */, _hoisted_6))
        }), 128 /* KEYED_FRAGMENT */))
      ], 512 /* NEED_PATCH */), [
        [_vModelSelect, $setup.folder]
      ])
    ]),
    _createElementVNode("div", _hoisted_7, [
      _createElementVNode("div", _hoisted_8, [
        _createElementVNode("label", _hoisted_9, [
          _withDirectives(_createElementVNode("input", {
            type: "checkbox",
            "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => (($setup.batchMode) = $event))
          }, null, 512 /* NEED_PATCH */), [
            [_vModelCheckbox, $setup.batchMode]
          ]),
          _cache[18] || (_cache[18] = _createTextVNode(" 批量模式（每行一个问题）", -1 /* CACHED */))
        ]),
        (!$setup.batchMode)
          ? _withDirectives((_openBlock(), _createElementBlock("textarea", {
              key: 0,
              "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => (($setup.question) = $event)),
              rows: "4",
              placeholder: "输入问题（支持 LaTeX，如 $E=mc^2$）",
              style: {"width":"100%","font-family":"inherit"}
            }, null, 512 /* NEED_PATCH */)), [
              [_vModelText, $setup.question]
            ])
          : _withDirectives((_openBlock(), _createElementBlock("textarea", {
              key: 1,
              "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => (($setup.batchText) = $event)),
              rows: "6",
              placeholder: "每行一个问题",
              style: {"width":"100%","font-family":"inherit"}
            }, null, 512 /* NEED_PATCH */)), [
              [_vModelText, $setup.batchText]
            ]),
        _createElementVNode("p", _hoisted_10, [
          _cache[19] || (_cache[19] = _createElementVNode("label", {
            class: "btn small as-label",
            for: "pg-file"
          }, "＋ 添加附件（图片/pdf/docx/txt）", -1 /* CACHED */)),
          _createElementVNode("input", {
            id: "pg-file",
            type: "file",
            multiple: "",
            hidden: "",
            onChange: $setup.onPickFiles
          }, null, 32 /* NEED_HYDRATION */),
          (!$setup.batchMode)
            ? (_openBlock(), _createElementBlock("button", {
                key: 0,
                class: "btn primary",
                disabled: $setup.busy,
                onClick: $setup.doAsk
              }, "▶ 提问", 8 /* PROPS */, _hoisted_11))
            : (_openBlock(), _createElementBlock("button", {
                key: 1,
                class: "btn primary",
                disabled: $setup.busy,
                onClick: $setup.doBatch
              }, "▶ 批量发送", 8 /* PROPS */, _hoisted_12)),
          _createElementVNode("button", {
            class: "btn small",
            title: "清空输入草稿（提问/批量/附件）",
            onClick: $setup.clearDraft
          }, "清空草稿"),
          ($setup.lastModel)
            ? (_openBlock(), _createElementBlock("span", _hoisted_13, "模型：" + _toDisplayString($setup.lastModel), 1 /* TEXT */))
            : _createCommentVNode("v-if", true)
        ]),
        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.attachments, (a, i) => {
          return (_openBlock(), _createElementBlock("p", {
            class: "hint",
            style: {"margin":"0"},
            key: i
          }, [
            _createTextVNode(" 附件：" + _toDisplayString(a.name) + " ", 1 /* TEXT */),
            _createElementVNode("span", _hoisted_14, "(" + _toDisplayString(a.kind) + ")", 1 /* TEXT */),
            _createElementVNode("button", {
              class: "btn small",
              style: {"margin-left":"6px"},
              onClick: $event => ($setup.removeAttachment(i))
            }, "移除", 8 /* PROPS */, _hoisted_15)
          ]))
        }), 128 /* KEYED_FRAGMENT */)),
        ($setup.msg)
          ? (_openBlock(), _createElementBlock("p", _hoisted_16, _toDisplayString($setup.msg), 1 /* TEXT */))
          : _createCommentVNode("v-if", true)
      ]),
      _createElementVNode("div", _hoisted_17, [
        _cache[20] || (_cache[20] = _createElementVNode("p", {
          class: "hint",
          style: {"margin":"0 0 4px"}
        }, "回复：", -1 /* CACHED */)),
        _createElementVNode("iframe", {
          srcdoc: $setup.answerHtml,
          title: "模型回复",
          style: {"width":"100%","height":"340px","border":"1px solid var(--c-border)","border-radius":"8px","background":"#fff"}
        }, null, 8 /* PROPS */, _hoisted_18)
      ])
    ]),
    _cache[28] || (_cache[28] = _createElementVNode("h4", { style: {"margin":"16px 0 6px"} }, "记录管理（本地留档）", -1 /* CACHED */)),
    _createElementVNode("p", _hoisted_19, [
      _withDirectives(_createElementVNode("input", {
        "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => (($setup.newFolder) = $event)),
        placeholder: "新建文件夹名",
        style: {"width":"150px"}
      }, null, 512 /* NEED_PATCH */), [
        [_vModelText, $setup.newFolder]
      ]),
      _createElementVNode("button", {
        class: "btn small",
        onClick: $setup.addFolder
      }, "新建文件夹"),
      _createElementVNode("span", _hoisted_20, "已选 " + _toDisplayString($setup.selected.length) + " 条：", 1 /* TEXT */),
      _createElementVNode("select", {
        onChange: _cache[11] || (_cache[11] = $event => ($setup.moveSelected(($event.target as HTMLSelectElement).value || $setup.folders[0]))),
        disabled: !$setup.selected.length
      }, [
        _cache[21] || (_cache[21] = _createElementVNode("option", { value: "" }, "移动到…", -1 /* CACHED */)),
        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.folders, (f) => {
          return (_openBlock(), _createElementBlock("option", {
            key: f,
            value: f
          }, _toDisplayString(f), 9 /* TEXT, PROPS */, _hoisted_22))
        }), 128 /* KEYED_FRAGMENT */))
      ], 40 /* PROPS, NEED_HYDRATION */, _hoisted_21),
      _createElementVNode("button", {
        class: "btn small",
        disabled: !$setup.selected.length,
        onClick: $setup.delSelected
      }, "删除所选", 8 /* PROPS */, _hoisted_23),
      _cache[22] || (_cache[22] = _createElementVNode("span", { style: {"flex":"1"} }, null, -1 /* CACHED */)),
      _createElementVNode("button", {
        class: "btn small",
        onClick: $setup.loadRecords
      }, "刷新")
    ]),
    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.folders, (f) => {
      return (_openBlock(), _createElementBlock("div", {
        key: f,
        style: {"margin-bottom":"8px"}
      }, [
        _createElementVNode("div", _hoisted_24, [
          _createElementVNode("b", null, "📁 " + _toDisplayString(f), 1 /* TEXT */),
          _createElementVNode("span", _hoisted_25, "（" + _toDisplayString(($setup.grouped[f] || []).length) + " 条）", 1 /* TEXT */),
          ($setup.folders.length > 1 && f !== $setup.folders[0])
            ? (_openBlock(), _createElementBlock("button", {
                key: 0,
                class: "btn small",
                onClick: $event => ($setup.delFolder(f))
              }, "删除文件夹", 8 /* PROPS */, _hoisted_26))
            : _createCommentVNode("v-if", true)
        ]),
        (($setup.grouped[f] || []).length)
          ? (_openBlock(), _createElementBlock("table", _hoisted_27, [
              _cache[26] || (_cache[26] = _createElementVNode("thead", null, [
                _createElementVNode("tr", null, [
                  _createElementVNode("th", { style: {"width":"28px"} }),
                  _createElementVNode("th", null, "时间"),
                  _createElementVNode("th", null, "provider/模型"),
                  _createElementVNode("th", null, "问题"),
                  _createElementVNode("th", { style: {"width":"120px"} }, "操作")
                ])
              ], -1 /* CACHED */)),
              _createElementVNode("tbody", null, [
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.grouped[f], (rec) => {
                  return (_openBlock(), _createElementBlock(_Fragment, {
                    key: rec.id
                  }, [
                    _createElementVNode("tr", null, [
                      _createElementVNode("td", null, [
                        _createElementVNode("input", {
                          type: "checkbox",
                          checked: $setup.selected.includes(rec.id),
                          onChange: $event => ($setup.toggleSelect(rec.id))
                        }, null, 40 /* PROPS, NEED_HYDRATION */, _hoisted_28)
                      ]),
                      _createElementVNode("td", _hoisted_29, _toDisplayString(rec.at), 1 /* TEXT */),
                      _createElementVNode("td", _hoisted_30, _toDisplayString(rec.provider) + " / " + _toDisplayString(rec.model || '—'), 1 /* TEXT */),
                      _createElementVNode("td", {
                        style: {"max-width":"360px","overflow":"hidden","text-overflow":"ellipsis","white-space":"nowrap"},
                        title: rec.question
                      }, _toDisplayString(rec.question), 9 /* TEXT, PROPS */, _hoisted_31),
                      _createElementVNode("td", _hoisted_32, [
                        _createElementVNode("button", {
                          class: "btn small",
                          onClick: $event => ($setup.expanded = $setup.expanded === rec.id ? '' : rec.id)
                        }, _toDisplayString($setup.expanded === rec.id ? '收起' : '查看'), 9 /* TEXT, PROPS */, _hoisted_33),
                        _createElementVNode("button", {
                          class: "btn small",
                          style: {"margin-left":"4px"},
                          onClick: $event => ($setup.delOne(rec.id))
                        }, "删除", 8 /* PROPS */, _hoisted_34)
                      ])
                    ]),
                    ($setup.expanded === rec.id)
                      ? (_openBlock(), _createElementBlock("tr", _hoisted_35, [
                          _cache[25] || (_cache[25] = _createElementVNode("td", null, null, -1 /* CACHED */)),
                          _createElementVNode("td", _hoisted_36, [
                            _createElementVNode("div", _hoisted_37, [
                              _createElementVNode("div", null, [
                                _cache[23] || (_cache[23] = _createElementVNode("b", null, "问：", -1 /* CACHED */)),
                                _createTextVNode(_toDisplayString(rec.question), 1 /* TEXT */)
                              ]),
                              ((rec.attachments || []).length)
                                ? (_openBlock(), _createElementBlock("div", _hoisted_38, "附件：" + _toDisplayString((rec.attachments || []).join('、')), 1 /* TEXT */))
                                : _createCommentVNode("v-if", true),
                              _createElementVNode("div", _hoisted_39, [
                                _cache[24] || (_cache[24] = _createElementVNode("b", null, "答：", -1 /* CACHED */)),
                                _createTextVNode(_toDisplayString(rec.answer || '（无）'), 1 /* TEXT */)
                              ]),
                              (rec.error)
                                ? (_openBlock(), _createElementBlock("div", _hoisted_40, "错误：" + _toDisplayString(rec.error), 1 /* TEXT */))
                                : _createCommentVNode("v-if", true)
                            ])
                          ])
                        ]))
                      : _createCommentVNode("v-if", true)
                  ], 64 /* STABLE_FRAGMENT */))
                }), 128 /* KEYED_FRAGMENT */))
              ])
            ]))
          : (_openBlock(), _createElementBlock("p", _hoisted_41, "（空）"))
      ]))
    }), 128 /* KEYED_FRAGMENT */))
  ]))
}
__sfc_main.render = render
export default __sfc_main

import { defineComponent as _defineComponent } from 'vue'

const __sfc_main = /*@__PURE__*/_defineComponent({
  __name: 'PreviewTableCard',
  props: {
    title: { type: String, required: true },
    preview: { type: [Object, null], required: true },
    fileName: { type: String, required: false },
    tone: { type: String, required: false }
  },
  setup(__props: any, { expose: __expose }) {
  __expose();

/** VC-4/VC-6 复用预览卡（docs/14 §VC-4/§VC-6）：表头 + 前 3 行 + 列映射说明。
 *  名单导入（VC-4）与成绩源导入（VC-6）共用同一结构模型 PreviewTable ——
 *  教师在导入后即时核对解析结构（宽松列名 rule 与引擎同款，已在 lib 层完成映射）。
 *  纯展示组件：不持有状态、不依赖 store（数据由父级通过 props 注入）。 */



const __returned__ = {  }
Object.defineProperty(__returned__, '__isScriptSetup', { enumerable: false, value: true })
return __returned__
}

})
import { toDisplayString as _toDisplayString, openBlock as _openBlock, createElementBlock as _createElementBlock, createCommentVNode as _createCommentVNode, createTextVNode as _createTextVNode, createElementVNode as _createElementVNode, renderList as _renderList, Fragment as _Fragment, normalizeClass as _normalizeClass } from "vue"

const _hoisted_1 = {
  key: 0,
  class: "card preview-table-card"
}
const _hoisted_2 = {
  key: 0,
  style: {"font-weight":"400","color":"var(--c-muted)"}
}
const _hoisted_3 = { class: "hint" }
const _hoisted_4 = { style: {"overflow":"auto","max-height":"420px","border":"1px solid var(--c-border)","border-radius":"8px"} }
const _hoisted_5 = { class: "grid preview-table" }

export function render(_ctx, _cache, $props, $setup, $data, $options) {
  return ($props.preview)
    ? (_openBlock(), _createElementBlock("div", _hoisted_1, [
        _createElementVNode("h2", null, [
          _createTextVNode(_toDisplayString($props.title) + " ", 1 /* TEXT */),
          ($props.fileName)
            ? (_openBlock(), _createElementBlock("small", _hoisted_2, _toDisplayString($props.fileName), 1 /* TEXT */))
            : _createCommentVNode("v-if", true)
        ]),
        ($props.preview.notes.length)
          ? (_openBlock(), _createElementBlock("p", {
              key: 0,
              class: _normalizeClass(["hint", { notice: $props.tone === 'warn' }])
            }, [
              _cache[0] || (_cache[0] = _createTextVNode(" 列映射说明（与引擎同款宽松列名 rule）：", -1 /* CACHED */)),
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($props.preview.notes, (n) => {
                return (_openBlock(), _createElementBlock("code", {
                  key: n,
                  style: {"display":"inline-block","margin":"1px 4px 1px 0"}
                }, _toDisplayString(n), 1 /* TEXT */))
              }), 128 /* KEYED_FRAGMENT */))
            ], 2 /* CLASS */))
          : _createCommentVNode("v-if", true),
        _createElementVNode("p", _hoisted_3, [
          _cache[1] || (_cache[1] = _createTextVNode("导入 ", -1 /* CACHED */)),
          _createElementVNode("b", null, _toDisplayString($props.preview.rowCount), 1 /* TEXT */),
          _cache[2] || (_cache[2] = _createTextVNode(" 条；下表 = **全文件预览模式**（表头 + 实际数据行，最多 500 行可滚动，D47-6）。", -1 /* CACHED */))
        ]),
        _createElementVNode("div", _hoisted_4, [
          _createElementVNode("table", _hoisted_5, [
            _createElementVNode("thead", null, [
              _createElementVNode("tr", null, [
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($props.preview.headers, (h) => {
                  return (_openBlock(), _createElementBlock("th", { key: h }, _toDisplayString(h), 1 /* TEXT */))
                }), 128 /* KEYED_FRAGMENT */))
              ])
            ]),
            _createElementVNode("tbody", null, [
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($props.preview.rows, (r, i) => {
                return (_openBlock(), _createElementBlock("tr", { key: i }, [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(r, (c, j) => {
                    return (_openBlock(), _createElementBlock("td", { key: j }, _toDisplayString(c), 1 /* TEXT */))
                  }), 128 /* KEYED_FRAGMENT */))
                ]))
              }), 128 /* KEYED_FRAGMENT */))
            ])
          ])
        ])
      ]))
    : _createCommentVNode("v-if", true)
}
__sfc_main.render = render
export default __sfc_main

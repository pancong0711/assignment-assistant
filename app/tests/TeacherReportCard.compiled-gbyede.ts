import { defineComponent as _defineComponent } from 'vue'
import { computed, ref, watch } from 'vue'
import { fetchTeacherReport, type TeacherReportStat } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/engineClient'

const MATRIX_N = 8
const BARS_W = 520
const BARS_H = 150

const __sfc_main = /*@__PURE__*/_defineComponent({
  __name: 'TeacherReportCard',
  props: {
    engineAddr: { type: String, required: true },
    token: { type: String, required: false },
    classDir: { type: String, required: true },
    taskId: { type: String, required: true },
    reloadKey: { type: Number, required: false }
  },
  setup(__props: any, { expose: __expose }) {
  __expose();

/** D126-B：教师总结报告（易错知识点 + 共现矩阵 + 得分率）。
 *
 *  **只给教师看**，与学生报告严格区分（不上传、不发学生）。
 *  纯 SVG 绘图，不引入图表库（离线可用、体积零增长）。
 *  数据来自引擎 `/grade/teacher-report`（纯统计，不调 LLM）。
 */
const props = __props

const loading = ref(false)
const stat = ref<TeacherReportStat | null>(null)
const md = ref('')
const msg = ref('')
const showMd = ref(false)
/** D135：导出 PNG/PDF（附加能力；失败不影响报告本身） */
const exporting = ref<'png' | 'pdf' | ''>('')
const exportMsg = ref('')

async function exportReport(kind: 'png' | 'pdf') {
  if (!canLoad.value) return
  exporting.value = kind
  exportMsg.value = ''
  try {
    const r = await fetchTeacherReport(props.engineAddr, props.token, {
      classDir: props.classDir, taskId: props.taskId, export: kind,
    })
    if (!r?.ok) {
      exportMsg.value = `❌ ${r?.error || '导出失败'}${r?.hint ? `（${r.hint}）` : ''}`
      return
    }
    const path = kind === 'pdf' ? r.pdf : r.png
    exportMsg.value = path ? `✅ 已导出：${path}` : '❌ 未产出文件'
  } catch (e) {
    exportMsg.value = `导出失败：${String((e as Error).message || e)}`
  } finally { exporting.value = '' }
}

const canLoad = computed(() => Boolean(props.classDir && props.taskId))

async function load(rebuild = false) {
  if (!canLoad.value) {
    msg.value = '请先选择作业（需要班级目录 + 批阅目录键）'
    return
  }
  loading.value = true
  msg.value = ''
  try {
    const r = await fetchTeacherReport(props.engineAddr, props.token, {
      classDir: props.classDir, taskId: props.taskId, rebuild,
    })
    if (!r?.ok) {
      stat.value = null
      msg.value = `❌ ${r?.error || '读取失败'}${r?.hint ? `（${r.hint}）` : ''}`
      return
    }
    stat.value = r.stat || null
    md.value = r.markdown || ''
    const n = stat.value?.students ?? 0
    msg.value = n ? `✅ 已汇总 ${n} 名学生` : '（暂无评阅结果）'
  } catch (e) {
    msg.value = `读取失败：${String((e as Error).message || e)}`
  } finally { loading.value = false }
}

watch(() => [props.classDir, props.taskId, props.reloadKey], () => { void load() },
      { immediate: true })

/** 知识点共现矩阵：只取前 N 个知识点，避免图过大不可读。 */
const matrixTerms = computed<string[]>(() =>
  (stat.value?.knowledge_errors || []).slice(0, MATRIX_N).map((x) => x.term))

/** (i,j) → 同时出错人数（对称矩阵） */
const matrixCell = computed<Record<string, number>>(() => {
  const out: Record<string, number> = {}
  for (const c of stat.value?.cooccurrence || []) {
    out[`${c.a}|${c.b}`] = c.students
    out[`${c.b}|${c.a}`] = c.students
  }
  return out
})
const matrixMax = computed(() => {
  let m = 1
  for (const c of stat.value?.cooccurrence || []) m = Math.max(m, c.students)
  return m
})
function cellCount(a: string, b: string): number {
  return a === b ? 0 : (matrixCell.value[`${a}|${b}`] || 0)
}
function cellColor(n: number): string {
  if (!n) return '#f3f4f6'
  const t = Math.min(1, n / matrixMax.value)
  // 由浅黄到深红：越深=同时错的学生越多
  const r = 254, g = Math.round(254 - 150 * t), b = Math.round(240 - 200 * t)
  return `rgb(${r},${g},${b})`
}

/** 得分率柱状图几何 */
const barGeom = computed(() => {
  const rows = stat.value?.question_rates || []
  if (!rows.length) return []
  const gap = 10
  const w = Math.max(16, (BARS_W - gap * (rows.length - 1)) / rows.length)
  return rows.map((r, i) => ({
    ...r,
    x: i * (w + gap),
    w,
    h: Math.max(2, Math.round(r.rate * (BARS_H - 24))),
  }))
})
function rateColor(rate: number): string {
  if (rate >= 0.8) return '#16a34a'
  if (rate >= 0.6) return '#d97706'
  return '#dc2626'
}

const segments = computed(() => {
  const s = stat.value?.segments || {}
  return ['90-100', '80-89', '70-79', '60-69', '<60'].map((k) => ({ k, n: s[k] || 0 }))
})
const segMax = computed(() => Math.max(1, ...segments.value.map((x) => x.n)))

const __returned__ = { props, loading, stat, md, msg, showMd, exporting, exportMsg, exportReport, canLoad, load, MATRIX_N, matrixTerms, matrixCell, matrixMax, cellCount, cellColor, BARS_W, BARS_H, barGeom, rateColor, segments, segMax }
Object.defineProperty(__returned__, '__isScriptSetup', { enumerable: false, value: true })
return __returned__
}

})
import { createElementVNode as _createElementVNode, createTextVNode as _createTextVNode, toDisplayString as _toDisplayString, openBlock as _openBlock, createElementBlock as _createElementBlock, createCommentVNode as _createCommentVNode, renderList as _renderList, Fragment as _Fragment, normalizeStyle as _normalizeStyle } from "vue"

const _hoisted_1 = { class: "teacher-card" }
const _hoisted_2 = { class: "tc-head" }
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
const _hoisted_8 = {
  key: 2,
  class: "hint"
}
const _hoisted_9 = {
  key: 3,
  class: "hint"
}
const _hoisted_10 = { class: "ov" }
const _hoisted_11 = { class: "ov-item" }
const _hoisted_12 = { class: "ov-item" }
const _hoisted_13 = { class: "ov-item" }
const _hoisted_14 = { class: "ov-item" }
const _hoisted_15 = { class: "ov-item" }
const _hoisted_16 = {
  key: 0,
  class: "hint"
}
const _hoisted_17 = {
  class: "hint",
  style: {"margin":"2px 0"}
}
const _hoisted_18 = { class: "tc-table" }
const _hoisted_19 = { class: "c" }
const _hoisted_20 = { class: "c" }
const _hoisted_21 = { class: "c" }
const _hoisted_22 = {
  key: 2,
  class: "tc-table"
}
const _hoisted_23 = { class: "c" }
const _hoisted_24 = { class: "c" }
const _hoisted_25 = { class: "c" }
const _hoisted_26 = {
  key: 3,
  class: "hint"
}
const _hoisted_27 = {
  key: 4,
  class: "mx-wrap"
}
const _hoisted_28 = ["width", "height"]
const _hoisted_29 = ["x"]
const _hoisted_30 = ["y"]
const _hoisted_31 = ["x", "y", "fill"]
const _hoisted_32 = ["x", "y"]
const _hoisted_33 = {
  key: 5,
  class: "hint"
}
const _hoisted_34 = ["height"]
const _hoisted_35 = ["x", "y", "width", "height", "fill"]
const _hoisted_36 = ["x", "y"]
const _hoisted_37 = ["x", "y"]
const _hoisted_38 = { class: "seg" }
const _hoisted_39 = { class: "seg-bar-wrap" }
const _hoisted_40 = {
  class: "hint",
  style: {"margin":"0"}
}
const _hoisted_41 = { style: {"font-size":"12px"} }
const _hoisted_42 = { class: "tc-table" }
const _hoisted_43 = { class: "c" }
const _hoisted_44 = { class: "c" }
const _hoisted_45 = { class: "c" }
const _hoisted_46 = { class: "tc-table" }
const _hoisted_47 = { class: "c" }
const _hoisted_48 = { class: "c" }
const _hoisted_49 = { style: {"margin-top":"10px"} }
const _hoisted_50 = {
  key: 9,
  class: "md"
}

export function render(_ctx, _cache, $props, $setup, $data, $options) {
  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createElementVNode("div", _hoisted_2, [
      _cache[4] || (_cache[4] = _createElementVNode("h3", { style: {"margin":"0"} }, "📊 教师总结报告（易错知识点 / 共现 / 得分率）", -1 /* CACHED */)),
      _cache[5] || (_cache[5] = _createElementVNode("span", {
        class: "hint",
        style: {"margin":"0"}
      }, [
        _createTextVNode("只给教师，"),
        _createElementVNode("b", null, "不上传、不发学生"),
        _createTextVNode("；纯统计不调模型。")
      ], -1 /* CACHED */)),
      _cache[6] || (_cache[6] = _createElementVNode("span", { style: {"flex":"1"} }, null, -1 /* CACHED */)),
      _createElementVNode("button", {
        class: "btn small",
        disabled: $setup.loading || !$setup.canLoad,
        onClick: _cache[0] || (_cache[0] = $event => ($setup.load(true)))
      }, " 重新汇总 ", 8 /* PROPS */, _hoisted_3),
      _createElementVNode("button", {
        class: "btn small",
        disabled: $setup.exporting !== '' || !$setup.canLoad,
        onClick: _cache[1] || (_cache[1] = $event => ($setup.exportReport('png')))
      }, _toDisplayString($setup.exporting === 'png' ? '导出中…' : '导出 PNG'), 9 /* TEXT, PROPS */, _hoisted_4),
      _createElementVNode("button", {
        class: "btn small",
        disabled: $setup.exporting !== '' || !$setup.canLoad,
        onClick: _cache[2] || (_cache[2] = $event => ($setup.exportReport('pdf')))
      }, _toDisplayString($setup.exporting === 'pdf' ? '导出中…' : '导出 PDF'), 9 /* TEXT, PROPS */, _hoisted_5)
    ]),
    (!$setup.canLoad)
      ? (_openBlock(), _createElementBlock("p", _hoisted_6, "先在 ③ 区选择作业（需要班级目录 + 批阅目录键）。"))
      : ($setup.loading)
        ? (_openBlock(), _createElementBlock("p", _hoisted_7, "正在汇总评阅结果…"))
        : ($setup.msg)
          ? (_openBlock(), _createElementBlock("p", _hoisted_8, _toDisplayString($setup.msg), 1 /* TEXT */))
          : _createCommentVNode("v-if", true),
    ($setup.exportMsg)
      ? (_openBlock(), _createElementBlock("p", _hoisted_9, _toDisplayString($setup.exportMsg), 1 /* TEXT */))
      : _createCommentVNode("v-if", true),
    ($setup.stat && $setup.stat.students)
      ? (_openBlock(), _createElementBlock(_Fragment, { key: 4 }, [
          _createCommentVNode(" 概览 "),
          _createElementVNode("div", _hoisted_10, [
            _createElementVNode("div", _hoisted_11, [
              _createElementVNode("b", null, _toDisplayString($setup.stat.students), 1 /* TEXT */),
              _cache[7] || (_cache[7] = _createElementVNode("span", null, "已评阅", -1 /* CACHED */))
            ]),
            _createElementVNode("div", _hoisted_12, [
              _createElementVNode("b", null, _toDisplayString($setup.stat.avg), 1 /* TEXT */),
              _cache[8] || (_cache[8] = _createElementVNode("span", null, "平均分", -1 /* CACHED */))
            ]),
            _createElementVNode("div", _hoisted_13, [
              _createElementVNode("b", null, _toDisplayString($setup.stat.max) + " / " + _toDisplayString($setup.stat.min), 1 /* TEXT */),
              _cache[9] || (_cache[9] = _createElementVNode("span", null, "最高 / 最低", -1 /* CACHED */))
            ]),
            _createElementVNode("div", _hoisted_14, [
              _createElementVNode("b", null, _toDisplayString($setup.stat.manual), 1 /* TEXT */),
              _cache[10] || (_cache[10] = _createElementVNode("span", null, "需人工", -1 /* CACHED */))
            ]),
            _createElementVNode("div", _hoisted_15, [
              _createElementVNode("b", null, _toDisplayString($setup.stat.substitution), 1 /* TEXT */),
              _cache[11] || (_cache[11] = _createElementVNode("span", null, "顶替嫌疑", -1 /* CACHED */))
            ])
          ]),
          _createCommentVNode(" 易错知识点 "),
          _cache[22] || (_cache[22] = _createElementVNode("h4", null, "① 易错知识点（按出错人数）", -1 /* CACHED */)),
          (!$setup.stat.knowledge_errors.length)
            ? (_openBlock(), _createElementBlock("p", _hoisted_16, " （无知识点级错误记录：本次批阅可能没有产出 errors[].knowledge，或全班答对。） "))
            : (($setup.stat.byTopic || []).length)
              ? (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                  _createCommentVNode(" D138：有主题时按「块」分组展示（教师看得出\"整条线没掌握\"） "),
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.stat.byTopic, (g) => {
                    return (_openBlock(), _createElementBlock("div", {
                      key: g.topic,
                      style: {"margin-bottom":"8px"}
                    }, [
                      _createElementVNode("p", _hoisted_17, [
                        _cache[12] || (_cache[12] = _createTextVNode("📚 ", -1 /* CACHED */)),
                        _createElementVNode("b", null, _toDisplayString(g.topic), 1 /* TEXT */)
                      ]),
                      _createElementVNode("table", _hoisted_18, [
                        _cache[13] || (_cache[13] = _createElementVNode("thead", null, [
                          _createElementVNode("tr", null, [
                            _createElementVNode("th", null, "知识点"),
                            _createElementVNode("th", null, "出错人数"),
                            _createElementVNode("th", null, "出错率"),
                            _createElementVNode("th", null, "题号")
                          ])
                        ], -1 /* CACHED */)),
                        _createElementVNode("tbody", null, [
                          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(g.items, (x) => {
                            return (_openBlock(), _createElementBlock("tr", {
                              key: x.term
                            }, [
                              _createElementVNode("td", null, [
                                _createElementVNode("b", null, _toDisplayString(x.term), 1 /* TEXT */)
                              ]),
                              _createElementVNode("td", _hoisted_19, _toDisplayString(x.students), 1 /* TEXT */),
                              _createElementVNode("td", _hoisted_20, _toDisplayString(Math.round(x.rate * 100)) + "%", 1 /* TEXT */),
                              _createElementVNode("td", _hoisted_21, _toDisplayString(x.questions.join('、') || '—'), 1 /* TEXT */)
                            ]))
                          }), 128 /* KEYED_FRAGMENT */))
                        ])
                      ])
                    ]))
                  }), 128 /* KEYED_FRAGMENT */))
                ], 64 /* STABLE_FRAGMENT */))
              : (_openBlock(), _createElementBlock("table", _hoisted_22, [
                  _cache[14] || (_cache[14] = _createElementVNode("thead", null, [
                    _createElementVNode("tr", null, [
                      _createElementVNode("th", null, "知识点"),
                      _createElementVNode("th", null, "出错人数"),
                      _createElementVNode("th", null, "出错率"),
                      _createElementVNode("th", null, "题号")
                    ])
                  ], -1 /* CACHED */)),
                  _createElementVNode("tbody", null, [
                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.stat.knowledge_errors, (x) => {
                      return (_openBlock(), _createElementBlock("tr", {
                        key: x.term
                      }, [
                        _createElementVNode("td", null, [
                          _createElementVNode("b", null, _toDisplayString(x.term), 1 /* TEXT */)
                        ]),
                        _createElementVNode("td", _hoisted_23, _toDisplayString(x.students), 1 /* TEXT */),
                        _createElementVNode("td", _hoisted_24, _toDisplayString(Math.round(x.rate * 100)) + "%", 1 /* TEXT */),
                        _createElementVNode("td", _hoisted_25, _toDisplayString(x.questions.join('、') || '—'), 1 /* TEXT */)
                      ]))
                    }), 128 /* KEYED_FRAGMENT */))
                  ])
                ])),
          _createCommentVNode(" 共现矩阵 "),
          _cache[23] || (_cache[23] = _createElementVNode("h4", null, "② 易错点共现矩阵（同生同时错的人数）", -1 /* CACHED */)),
          ($setup.matrixTerms.length < 2)
            ? (_openBlock(), _createElementBlock("p", _hoisted_26, " （知识点不足 2 个，无法形成共现矩阵。） "))
            : (_openBlock(), _createElementBlock("div", _hoisted_27, [
                (_openBlock(), _createElementBlock("svg", {
                  width: ($setup.MATRIX_N + 1) * 78,
                  height: ($setup.matrixTerms.length + 1) * 30,
                  class: "mx"
                }, [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.matrixTerms, (t, j) => {
                    return (_openBlock(), _createElementBlock("g", {
                      key: 'h' + t
                    }, [
                      _createElementVNode("text", {
                        x: 78 + j * 78,
                        y: "18",
                        "font-size": "11",
                        "text-anchor": "middle"
                      }, _toDisplayString(t.length > 5 ? t.slice(0, 5) + '…' : t), 9 /* TEXT, PROPS */, _hoisted_29)
                    ]))
                  }), 128 /* KEYED_FRAGMENT */)),
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.matrixTerms, (row, i) => {
                    return (_openBlock(), _createElementBlock("g", {
                      key: 'r' + row
                    }, [
                      _createElementVNode("text", {
                        x: "74",
                        y: 46 + i * 30,
                        "font-size": "11",
                        "text-anchor": "end"
                      }, _toDisplayString(row.length > 6 ? row.slice(0, 6) + '…' : row), 9 /* TEXT, PROPS */, _hoisted_30),
                      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.matrixTerms, (col, j) => {
                        return (_openBlock(), _createElementBlock("g", {
                          key: 'c' + i + '-' + j
                        }, [
                          _createElementVNode("rect", {
                            x: 78 + j * 78 - 30,
                            y: 30 + i * 30,
                            width: "60",
                            height: "24",
                            rx: "3",
                            fill: i === j ? '#e5e7eb' : $setup.cellColor($setup.cellCount(row, col)),
                            stroke: "#d1d5db",
                            "stroke-width": "0.5"
                          }, null, 8 /* PROPS */, _hoisted_31),
                          (i !== j && $setup.cellCount(row, col))
                            ? (_openBlock(), _createElementBlock("text", {
                                key: 0,
                                x: 78 + j * 78,
                                y: 46 + i * 30,
                                "font-size": "11",
                                "text-anchor": "middle",
                                fill: "#111827"
                              }, _toDisplayString($setup.cellCount(row, col)), 9 /* TEXT, PROPS */, _hoisted_32))
                            : _createCommentVNode("v-if", true)
                        ]))
                      }), 128 /* KEYED_FRAGMENT */))
                    ]))
                  }), 128 /* KEYED_FRAGMENT */))
                ], 8 /* PROPS */, _hoisted_28)),
                _cache[15] || (_cache[15] = _createElementVNode("p", {
                  class: "hint",
                  style: {"margin":"4px 0"}
                }, " 颜色越深=同时出错的学生越多（对角线为自身，不统计）。可用于判断是否同一个概念没讲透。 ", -1 /* CACHED */))
              ])),
          _createCommentVNode(" 得分率 "),
          _cache[24] || (_cache[24] = _createElementVNode("h4", null, "③ 逐题得分率（越低越该讲）", -1 /* CACHED */)),
          (!$setup.barGeom.length)
            ? (_openBlock(), _createElementBlock("p", _hoisted_33, "（无逐题分数记录。）"))
            : (_openBlock(), _createElementBlock(_Fragment, { key: 6 }, [
                (_openBlock(), _createElementBlock("svg", {
                  width: $setup.BARS_W,
                  height: $setup.BARS_H + 20,
                  class: "bars"
                }, [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.barGeom, (b) => {
                    return (_openBlock(), _createElementBlock("g", {
                      key: 'b' + b.id
                    }, [
                      _createElementVNode("rect", {
                        x: b.x,
                        y: $setup.BARS_H - b.h,
                        width: b.w,
                        height: b.h,
                        fill: $setup.rateColor(b.rate),
                        rx: "2"
                      }, null, 8 /* PROPS */, _hoisted_35),
                      _createElementVNode("text", {
                        x: b.x + b.w / 2,
                        y: $setup.BARS_H - b.h - 3,
                        "font-size": "10",
                        "text-anchor": "middle"
                      }, _toDisplayString(Math.round(b.rate * 100)) + "%", 9 /* TEXT, PROPS */, _hoisted_36),
                      _createElementVNode("text", {
                        x: b.x + b.w / 2,
                        y: $setup.BARS_H + 13,
                        "font-size": "10",
                        "text-anchor": "middle"
                      }, "第" + _toDisplayString(b.id) + "题", 9 /* TEXT, PROPS */, _hoisted_37)
                    ]))
                  }), 128 /* KEYED_FRAGMENT */))
                ], 8 /* PROPS */, _hoisted_34)),
                _cache[16] || (_cache[16] = _createElementVNode("p", {
                  class: "hint",
                  style: {"margin":"2px 0"}
                }, " 绿 ≥80% ／ 橙 60–79% ／ 红 <60%。满分按题数分摊（与计分口径一致）。 ", -1 /* CACHED */))
              ], 64 /* STABLE_FRAGMENT */)),
          _createCommentVNode(" 分数段 "),
          _cache[25] || (_cache[25] = _createElementVNode("h4", null, "④ 分数段分布", -1 /* CACHED */)),
          _createElementVNode("div", _hoisted_38, [
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.segments, (s) => {
              return (_openBlock(), _createElementBlock("div", {
                key: s.k,
                class: "seg-item"
              }, [
                _createElementVNode("div", _hoisted_39, [
                  _createElementVNode("div", {
                    class: "seg-bar",
                    style: _normalizeStyle({ height: `${Math.round((s.n / $setup.segMax) * 70)}px` })
                  }, null, 4 /* STYLE */)
                ]),
                _createElementVNode("div", _hoisted_40, _toDisplayString(s.k), 1 /* TEXT */),
                _createElementVNode("div", _hoisted_41, [
                  _createElementVNode("b", null, _toDisplayString(s.n), 1 /* TEXT */),
                  _cache[17] || (_cache[17] = _createTextVNode(" 人", -1 /* CACHED */))
                ])
              ]))
            }), 128 /* KEYED_FRAGMENT */))
          ]),
          _createCommentVNode(" 题型 "),
          ($setup.stat.kind_stats.length)
            ? (_openBlock(), _createElementBlock(_Fragment, { key: 7 }, [
                _cache[19] || (_cache[19] = _createElementVNode("h4", null, "⑤ 按题目来源（题型）", -1 /* CACHED */)),
                _createElementVNode("table", _hoisted_42, [
                  _cache[18] || (_cache[18] = _createElementVNode("thead", null, [
                    _createElementVNode("tr", null, [
                      _createElementVNode("th", null, "题型"),
                      _createElementVNode("th", null, "题次"),
                      _createElementVNode("th", null, "平均扣分"),
                      _createElementVNode("th", null, "累计扣分")
                    ])
                  ], -1 /* CACHED */)),
                  _createElementVNode("tbody", null, [
                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.stat.kind_stats, (k) => {
                      return (_openBlock(), _createElementBlock("tr", {
                        key: k.kind
                      }, [
                        _createElementVNode("td", null, _toDisplayString(k.kind), 1 /* TEXT */),
                        _createElementVNode("td", _hoisted_43, _toDisplayString(k.questions), 1 /* TEXT */),
                        _createElementVNode("td", _hoisted_44, _toDisplayString(k.avg_deduct), 1 /* TEXT */),
                        _createElementVNode("td", _hoisted_45, _toDisplayString(k.total_deduct), 1 /* TEXT */)
                      ]))
                    }), 128 /* KEYED_FRAGMENT */))
                  ])
                ])
              ], 64 /* STABLE_FRAGMENT */))
            : _createCommentVNode("v-if", true),
          _createCommentVNode(" 本章遗漏 "),
          ($setup.stat.missing.length)
            ? (_openBlock(), _createElementBlock(_Fragment, { key: 8 }, [
                _cache[21] || (_cache[21] = _createElementVNode("h4", null, "⑥ 本章遗漏知识点（依据课堂资料清单）", -1 /* CACHED */)),
                _createElementVNode("table", _hoisted_46, [
                  _cache[20] || (_cache[20] = _createElementVNode("thead", null, [
                    _createElementVNode("tr", null, [
                      _createElementVNode("th", null, "知识点"),
                      _createElementVNode("th", null, "遗漏人数"),
                      _createElementVNode("th", null, "占比")
                    ])
                  ], -1 /* CACHED */)),
                  _createElementVNode("tbody", null, [
                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.stat.missing, (m) => {
                      return (_openBlock(), _createElementBlock("tr", {
                        key: m.term
                      }, [
                        _createElementVNode("td", null, [
                          _createElementVNode("b", null, _toDisplayString(m.term), 1 /* TEXT */)
                        ]),
                        _createElementVNode("td", _hoisted_47, _toDisplayString(m.students), 1 /* TEXT */),
                        _createElementVNode("td", _hoisted_48, _toDisplayString(Math.round(m.rate * 100)) + "%", 1 /* TEXT */)
                      ]))
                    }), 128 /* KEYED_FRAGMENT */))
                  ])
                ])
              ], 64 /* STABLE_FRAGMENT */))
            : _createCommentVNode("v-if", true),
          _createElementVNode("p", _hoisted_49, [
            _createElementVNode("button", {
              class: "btn small",
              onClick: _cache[3] || (_cache[3] = $event => ($setup.showMd = !$setup.showMd))
            }, _toDisplayString($setup.showMd ? '收起 Markdown 原文' : '查看 Markdown 原文'), 1 /* TEXT */)
          ]),
          ($setup.showMd)
            ? (_openBlock(), _createElementBlock("pre", _hoisted_50, _toDisplayString($setup.md), 1 /* TEXT */))
            : _createCommentVNode("v-if", true)
        ], 64 /* STABLE_FRAGMENT */))
      : _createCommentVNode("v-if", true)
  ]))
}
__sfc_main.render = render
export default __sfc_main

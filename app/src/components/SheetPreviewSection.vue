<script setup lang="ts">
/**
 * SheetPreviewSection.vue — 作业纸设计的「预览 + 清单」独立段（docs/05-D45 ③段）。
 *
 * D43-3/4/6（docs/05-D45 域归属收口）：模板预览改为同一 HTML 打印模板的 iframe
 * 实时渲染（KaTeX 同源渲染公式）；「内容开关」☑显示参考答案 / ☑显示学生示例
 * （默认**均不勾**，用户拍板）——同时约束 本预览 / 清单行「预览」/ 「预览全部连排」
 * 以及④输出段的打印/下载（开关通过 defineModel 双向同步给父级 → 输出段 props）。
 * 作业纸清单合卡（全页唯一一份，D43-4）。
 *
 * 预览域分层（D43-6）：本段全部 = 模板级预览；整班分层预览唯一入口在「班级与标签」页。
 */
import { computed, ref, watch } from 'vue'
import { STUDENT_TAG_LABELS, type KbKind } from '../lib/kb'
import { useKbStore } from '../stores/kb'
import { useSettingsStore } from '../stores/settings'
import { useTaskpadStore } from '../stores/taskpad'
import { usePackStore } from '../stores/packs'
import { parseTaskpad, padInferredTag, resolveGrid, type Taskpad } from '../lib/taskpad'
import { downloadData } from '../lib/fsAccess'
import {
  stringifySheetHtml, buildSelfContainedHtml, expandPadItems,
  SYNTHETIC_STUDENTS, BLANK_STUDENT,
  type SheetHtmlItem, type SheetHtmlPadInput,
} from '../lib/sheetHtml'
import SheetHtmlPreviewModal from './SheetHtmlPreviewModal.vue'
import { reflowPad, shouldReflow } from '../lib/measureLayout'
import type { LayoutResult } from '../lib/autoLayout'

const props = defineProps<{ includeAnswers: boolean; showSamples: boolean; includeWatermark: boolean; includePageText: boolean }>()
const emit = defineEmits<{
  (e: 'update:includeAnswers', v: boolean): void
  (e: 'update:showSamples', v: boolean): void
  (e: 'update:includeWatermark', v: boolean): void
  (e: 'update:includePageText', v: boolean): void
  (e: 'notify', msg: string): void
}>()

const kb = useKbStore()
const pad = useTaskpadStore()
const settings = useSettingsStore()
const packStore = usePackStore()
const status = ref('')

const includeAnswers = computed(() => props.includeAnswers)
const showSamples = computed(() => props.showSamples)
const includeAnswersModel = computed({
  get: () => props.includeAnswers,
  set: (v: boolean) => emit('update:includeAnswers', v),
})
const showSamplesModel = computed({
  get: () => props.showSamples,
  set: (v: boolean) => emit('update:showSamples', v),
})
/** D43-7：水印图层 / 页码大字两开关（默认勾=现状） */
const wmLayerModel = computed({
  get: () => props.includeWatermark,
  set: (v: boolean) => emit('update:includeWatermark', v),
})
const wmPageTextModel = computed({
  get: () => props.includePageText,
  set: (v: boolean) => emit('update:includePageText', v),
})


function notify(m: string) { emit('notify', m) }

/* ---------- 运行数据 ---------- */
// D100-T7：依赖 kb.solutionsRev —— AI 作答/置顶完成后索引刷新即可触发预览重建
const sheetHtmlItems = computed<SheetHtmlItem[]>(() => {
  void kb.solutionsRev
  return itemsFor(pad.current)
})

function itemsFor(p: Taskpad): SheetHtmlItem[] {
  // D100-T7：注入生效答案解析器（版本库置顶/最新版 → 回落 xlsx 列）
  return expandPadItems(p, (kind) => kb.book(kind as KbKind), kb.effectiveSolution)
}

/* ---------- D103：预排版（带答案时自动重排；内容/版式变化即重测） ---------- */
const layoutResult = ref<LayoutResult | null>(null)
const layoutMsg = ref('')
let layoutTimer = 0
let layoutSeq = 0

/** 自动重排：防抖 260ms（测量较重），并用序号丢弃过期结果。 */
function scheduleReflow() {
  clearTimeout(layoutTimer)
  const seq = ++layoutSeq
  layoutTimer = window.setTimeout(async () => {
    const p = pad.current
    const items = sheetHtmlItems.value
    if (!shouldReflow(p, includeAnswers.value)) {
      layoutResult.value = null
      layoutMsg.value = ''
      return
    }
    try {
      const r = await reflowPad(p, items)
      if (seq !== layoutSeq) return                 // 期间又有新变更 → 丢弃
      layoutResult.value = r ? r.layout : null
      const warn = r?.layout?.warnings?.length ? `；⚠ ${r.layout.warnings[0]}` : ''
      layoutMsg.value = r
        ? `已按「每页最多 ${r.layout.geometry.rows * r.layout.geometry.cols} 格」预排版：${r.layout.pages.length} 页`
          + (r.downgraded ? '（版式已自动降级）' : '') + warn
        : ''
    } catch (e) {
      if (seq !== layoutSeq) return
      layoutResult.value = null
      layoutMsg.value = `预排版失败（已回退旧版式）：${(e as Error).message}`
    }
  }, 260)
}

watch([() => pad.current, sheetHtmlItems, includeAnswers], scheduleReflow, { deep: true, immediate: true })

/* ---------- 模板口径（与 SheetOutputSection 同一函数语义） ---------- */
function templateStudents(): SheetHtmlPadInput['students'] {
  return showSamples.value ? SYNTHETIC_STUDENTS : [BLANK_STUDENT]
}
function templateHtml(inputs: SheetHtmlPadInput[] | SheetHtmlPadInput): string {
  return stringifySheetHtml(inputs, {
    students: templateStudents(),
    includeSolution: includeAnswers.value,
    includeWatermark: props.includeWatermark,
    includePageText: props.includePageText,
    wmAssets: settings.wmAssets,
    wmStyles: settings.wmStyles,
    figAssets: settings.figAssets,
    katex: 'relative',
  })
}

/* ---------- 实时预览（iframe srcdoc；编辑防抖 180ms） ---------- */
const liveHtml = ref('')
let liveTimer = 0
function buildLiveHtml(): string {
  return templateHtml([{
    pad: JSON.parse(JSON.stringify(pad.current)),
    items: sheetHtmlItems.value,
    layout: layoutResult.value,     // D103：有预排版 → 按格渲染
  }])
}
function scheduleLive() {
  clearTimeout(liveTimer)
  liveTimer = window.setTimeout(() => { liveHtml.value = buildLiveHtml() }, 180)
}
const liveKey = computed(() =>
  JSON.stringify([pad.current, sheetHtmlItems.value, includeAnswers.value, showSamples.value,
    props.includeWatermark, props.includePageText, settings.wmAssets, layoutResult.value]))
watch(liveKey, scheduleLive, { immediate: true })

/* ---------- 弹层预览（清单行/全部连排 & 当前模板细看） ---------- */
const showHtmlOverlay = ref(false)
const overlayHtml = ref('')
const overlayTitle = ref('')
const overlayInputsKey = ref('[]')

function openPreview(pads: SheetHtmlPadInput[], title: string) {
  if (!pads.length) return
  overlayInputsKey.value = JSON.stringify(pads)
  overlayHtml.value = templateHtml(pads)
  overlayTitle.value = title
  showHtmlOverlay.value = true
}

async function downloadOverlayHtml() {
  try {
    const inputs = JSON.parse(overlayInputsKey.value) as SheetHtmlPadInput[]
    const html = await buildSelfContainedHtml(inputs, {
      students: templateStudents(),
      includeSolution: includeAnswers.value,
      includeWatermark: props.includeWatermark,
      includePageText: props.includePageText,
      wmAssets: settings.wmAssets,
    wmStyles: settings.wmStyles,
      figAssets: settings.figAssets,
    })
    downloadData(html, `sheet-preview-${new Date().toISOString().slice(0, 10)}.html`, 'text/html')
    notify(`已下载自包含 HTML（ KaTeX 内联，离线可开；${includeAnswers.value ? '含' : '不含'}参考答案 · ${showSamples.value ? '示例 2 份' : '空白 1 份'}）。`)
  } catch (e) {
    notify(`下载 HTML 失败：${(e as Error).message}`)
  }
}

/* ---------- 清单行「预览」（模板态） ---------- */
function previewPad(id: string) {
  const entry = pad.saved.find((s) => s.id === id)
  if (!entry) { status.value = `清单中未找到 ${id}。`; notify(status.value); return }
  try {
    const p = parseTaskpad(JSON.parse(entry.json))
    openPreview([{ pad: p, items: itemsFor(p) }], `作业纸预览 · ${id}`)
    status.value = `已打开 ${id} 预览（同一 HTML 模板；${includeAnswers.value ? '含' : '不含'}参考答案 · ${showSamples.value ? '示例 2 份' : '空白 1 份'}）。`
    notify(status.value)
  } catch (e) {
    status.value = `作业纸 ${id} 预览失败（JSON 损坏）：${(e as Error).message}`
    notify(status.value)
  }
}

/** 全部清单作业纸连排预览（模板态） */
function previewAllPads() {
  const sources: SheetHtmlPadInput[] = []
  let bad = 0
  for (const s of pad.saved) {
    try {
      const p = parseTaskpad(JSON.parse(s.json))
      sources.push({ pad: p, items: itemsFor(p) })
    } catch { bad++ }
  }
  if (!sources.length) { status.value = '清单为空或全部 JSON 损坏：无可预览作业纸。'; notify(status.value); return }
  openPreview(sources, `全部作业纸连排预览 · ${sources.length} 份`)
  status.value = `已连排预览 ${sources.length} 份作业纸（多包不分页；@page 方向取第一份${bad ? `；${bad} 份 JSON 损坏已跳过` : ''}）。`
  notify(status.value)
}

/* ---------- 作业纸清单（D43-4：全页唯一一份） ---------- */
interface PadMeta { id: string; items: number; questions: number; orientation: string; perPage: number; grid: string; targetTag: string; inferredTag: string | null; selection: string }
const library = computed<PadMeta[]>(() => {
  // D91-M1：③段清单**只显示当前作业包内**作业纸；未选包 → 空（提示去上方选/建包）
  if (!packStore.currentId) return []
  const allow = new Set(packStore.currentPadRefs.map((r) => r.padId))
  const src = pad.saved.filter((s) => allow.has(s.id))
  return src.map((s) => {
    try {
      const p = parseTaskpad(JSON.parse(s.json))
      return {
        id: p.id,
        // D93-S4：选题章节/题号（kb: chap: id1、id2；多组用 " ; " 连接）
        selection: (p.items || []).map((it) => {
          const ids = (it.ids || []).join('、')
          return `${it.kb}/${it.chap}${ids ? ': ' + ids : ''}`
        }).join(' ; ') || '—',
        items: p.items.length,
        questions: p.items.reduce((n, i) => n + i.ids.length, 0),
        orientation: p.layout.orientation === 'landscape' ? '横版' : '竖版',
        perPage: p.layout.per_page,
        grid: (() => {
          const g = resolveGrid(p.layout)
          return `${g.rows}×${g.cols}`
        })(),
        targetTag: p.target_tag ?? '',
        inferredTag: padInferredTag(p.items, p.target_tag),
      }
    } catch {
      return { id: s.id, selection: '?', items: 0, questions: 0, orientation: '?', perPage: 0, grid: '?×?', targetTag: '', inferredTag: null }
    }
  })
})

/* ---------- D91-M1：跨包移动 / 复制引用 / 另存为新作业纸到目标包 ---------- */
const moveTarget = ref('')          // 目标包 id
const otherPacks = computed(() => packStore.packs.filter((p) => p.id !== packStore.currentId))

function loadFromLibrary(id: string) {
  if (pad.openFromLibrary(id)) notify(`已载入作业纸 ${id}（回到①段继续编辑；保存会覆盖清单中的同名条目）。`)
  else notify(`清单中未找到 ${id}。`)
}

async function movePadTo(id: string) {
  if (!moveTarget.value) { notify('请先选择目标作业包'); return }
  const r = await packStore.movePadToPack(id, moveTarget.value)
  notify(r.ok ? `已把作业纸 ${id} 移动到作业包「${moveTarget.value}」` : `移动失败：${r.error ?? '引擎离线'}`)
}
async function copyPadRefTo(id: string) {
  if (!moveTarget.value) { notify('请先选择目标作业包'); return }
  const r = await packStore.copyPadRefToPack(id, moveTarget.value)
  notify(r.ok ? `已把作业纸 ${id} 的引用复制到作业包「${moveTarget.value}」（改一处两包同步）` : `复制失败：${r.error ?? '引擎离线'}`)
}
async function saveNewPadTo(id: string) {
  if (!moveTarget.value) { notify('请先选择目标作业包'); return }
  const newId = pad.duplicateSavedAsNew(id)
  if (!newId) { notify(`另存失败：未找到作业纸 ${id}`); return }
  const r = await packStore.copyPadRefToPack(newId, moveTarget.value)
  notify(r.ok ? `已另存为新作业纸 ${newId} 到作业包「${moveTarget.value}」（两包独立）` : `另存失败：${r.error ?? '引擎离线'}`)
}

function removeFromLibrary(id: string) {
  pad.removeFromLibrary(id)
  notify(`已从清单删除作业纸 ${id}（仅删除清单记录，不影响已导出文件）。`)
}

</script>

<template>
  <div class="card" id="preview" style="flex:1 1 520px; min-width:440px">
    <h2>③ 模板预览（同一 HTML 打印模板 · iframe 实时 · D43-3）</h2>
    <p>
      <label class="field" title="D43-6：勾选后预览/打印/下载包含『参考答案：…』行">
        <input type="checkbox" v-model="includeAnswersModel" /> 显示参考答案
      </label>
      <label class="field" title="D43-6：勾选后按合成 学生A/B 预览 2 份；不勾 = 页眉学籍三空位、1 份空白模板">
        <input type="checkbox" v-model="showSamplesModel" /> 显示学生示例
      </label>
      <label class="field" title="D43-7：不勾 = 水印图层整层不画（含三槽占位框）；与①段「启用水印」属性是 AND 关系">
        <input type="checkbox" v-model="wmLayerModel" /> 显示水印图层
      </label>
      <label class="field" title="D43-7：不勾 = 「第 N 页」大字水印不画（图层不受影响）">
        <input type="checkbox" v-model="wmPageTextModel" /> 显示页码大字
      </label>
      <button class="btn" style="margin-left:8px" @click="openPreview([{ pad: JSON.parse(JSON.stringify(pad.current)), items: sheetHtmlItems }], `作业纸预览 · ${pad.current.id}`)">🔍 弹窗细看</button>
    </p>
    <p class="hint">
      预览 = 打印产物同源（stringifySheetHtml，与 CLI <code>assist sheet html</code> 同模板）；
      公式用 PWA 内置同源 KaTeX（./katex/）渲染，<b>离线也正确显示</b>。
      两个开关同时约束 清单行「预览」/「预览全部连排」与④段输出（docs/13 D43-6）。
    </p>
    <iframe v-if="liveHtml" class="live-frame" :srcdoc="liveHtml" title="作业纸模板实时预览（同一 HTML 打印模板）" aria-label="作业纸模板实时预览：Tab 聚焦后可用方向键滚动预览文档" tabindex="0"></iframe>
    <p class="hint" v-if="!sheetHtmlItems.length">尚未选题（items 为空）：预览只有页眉/页脚/水印骨架；到②段选题后回来看版式效果。版式/水印/页眉页脚改动实时生效。</p>

    <h3>作业纸清单（{{ packStore.currentId ? `作业包「${packStore.currentId}」内` : "全部已保存作业纸" }} · 全页唯一一份）</h3>
    <p>
      <button class="btn" title="每个保存的作业纸各出一连段（模板态，受上方开关约束）" @click="previewAllPads">👁 预览全部作业纸（连排 · 模板态）</button>
    </p>
    <table class="grid" v-if="library.length" style="font-size:12px">
      <thead>
        <tr><th>id</th><th>目标 tag</th><th title="题库/章节: 题号">选题（章节/题号）</th><th>题数</th><th>版式</th><th style="width:260px">操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="m in library" :key="m.id">
          <td style="max-width:120px; word-break:break-all">{{ m.id }}</td>
          <td style="white-space:nowrap">
            {{ m.targetTag ? (STUDENT_TAG_LABELS[m.targetTag] ?? m.targetTag) : (m.inferredTag ? `自动推断：${m.inferredTag}` : '⚠ 混合 tag 未绑定') }}
          </td>
          <td style="max-width:360px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap" :title="m.selection">{{ m.selection }}</td>
          <td style="text-align:center">{{ m.questions }}</td>
          <td style="white-space:nowrap">{{ m.orientation }} / {{ m.perPage }}题页 · {{ m.grid }}</td>
          <td style="white-space:nowrap">
            <button class="btn small" @click="loadFromLibrary(m.id)">载入</button>
            <button class="btn small" style="margin-left:4px" @click="previewPad(m.id)" title="该作业纸的模板态预览（同一 HTML 模板 overlay）">预览</button>
            <button class="btn small" style="margin-left:4px" @click="removeFromLibrary(m.id)">删除</button>
            <div style="margin-top:4px; display:flex; gap:4px; align-items:center; flex-wrap:wrap">
              <select v-model="moveTarget" style="max-width:130px" title="选择目标作业包">
                <option value="">目标包…</option>
                <option v-for="pk in otherPacks" :key="pk.id" :value="pk.id">{{ pk.id }}</option>
              </select>
              <button class="btn small" :disabled="!moveTarget" @click="movePadTo(m.id)" title="从本包移除并加入目标包">移动</button>
              <button class="btn small" :disabled="!moveTarget" @click="copyPadRefTo(m.id)" title="本包保留 + 目标包加入同一作业纸引用（改一处两包同步）">复制引用</button>
              <button class="btn small" :disabled="!moveTarget" @click="saveNewPadTo(m.id)" title="以本张另存为新 id 的作业纸加入目标包（两包独立）">另存新纸</button>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
    <p class="hint" v-else>{{ packStore.currentId ? "本包内暂无作业纸：点「仅保存」把当前作业纸纳入本包，或在「作业包」栏调整包内引用。" : "请先在上方「作业包」栏选择或新建一个作业包——清单只显示当前包内的作业纸。" }}</p>
    <p class="hint" v-if="status">{{ status }}</p>

    <SheetHtmlPreviewModal
      v-if="showHtmlOverlay"
      :html="overlayHtml"
      :title="overlayTitle"
      @close="showHtmlOverlay = false"
      @download="downloadOverlayHtml"
    />
  </div>
</template>

<style scoped>
.live-frame {
  width: 100%; height: 560px; border: 1px solid var(--c-border);
  border-radius: 8px; background: #e8ecf3;
}
</style>

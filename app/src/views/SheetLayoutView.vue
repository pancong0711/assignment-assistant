<script setup lang="ts">
/**
 * SheetLayoutView.vue — 作业纸设计的「① 版式与头部」段（docs/05-D45 段序收口）。
 *
 * D45（docs/13）：仅保留编辑表单：顶部工具栏（新建/克隆/导入/仅保存，D43-2）+
 * 版式（orientation/per_page/页眉页脚，D19）+ 作业纸头部（docs/04 §1）+ 水印编辑器（D27）。
 * 预览与清单 → SheetPreviewSection（③段）；输出与交付 → SheetOutputSection（④段）；
 * 内容/变体 → SheetContentView（②段）；grade → 「批阅」选项卡（D43-5）。
 * 开关状态（includeAnswers/showSamples）挂父级 SheetDesignView，由②③段共享。
 */
import { computed, ref, watch } from 'vue'
import { useKbStore } from '../stores/kb'
import { useTaskpadStore } from '../stores/taskpad'
import { useSettingsStore } from '../stores/settings'
import { usePackStore } from '../stores/packs'
import { pickReadFile } from '../lib/fsAccess'
import { WATERMARK_POS_LABELS, MAX_PER_PAGE, MAX_GRID_DIM, autoSquareGrid, defaultGrid, resolveGrid, type PerPage } from '../lib/taskpad'

const kb = useKbStore()
const pad = useTaskpadStore()
const settings = useSettingsStore()
const packStore = usePackStore()

const status = ref('')

const emit0 = defineEmits<{ (e: 'notify', msg: string): void }>()
function notify(m: string) { status.value = m; emit0('notify', m) }

/* ---------- 导入 / 导出 / 新建 ---------- */
function newTaskpadClone(cloneStyle: boolean) {
  pad.newPad(cloneStyle)
  syncFromPad()
  notify(cloneStyle
    ? '已新建空作业纸（克隆了当前版式/页眉页脚/水印配置）。选题请到②段。'
    : '已新建空作业纸（默认版式）。选题请到②段。')
}

async function importTaskpadFile() {
  const f = await pickReadFile('application/json,.json')
  if (!f) return
  try {
    const p = pad.importJson(await f.text())
    syncFromPad()
    notify(`已导入作业纸 ${p.id}（${p.items.length} 组选题），可继续编辑。`)
  } catch (e) {
    notify(`作业纸导入失败：${(e as Error).message}`)
  }
}

/* ---------- 版式编辑（D61：per_page + 显式 grid_rows×grid_cols） ---------- */
function setOrientation(o: 'portrait' | 'landscape') {
  pad.setOrientation(o)
}

function setPerPage(v: PerPage) {
  pad.setPerPage(Number(v))
}

/* ---------- D61：显式 rows×cols 网格 ---------- */
const gridInfo = computed(() => resolveGrid(pad.current.layout))
const gridRows = computed({
  get: () => pad.current.layout.grid_rows ?? gridInfo.value.rows,
  set: (v: number) => {
    const n = Math.min(MAX_GRID_DIM, Math.max(1, Math.round(Number(v) || 1)))
    pad.setGridSize(n, pad.current.layout.grid_cols ?? gridInfo.value.cols)
  },
})
const gridCols = computed({
  get: () => pad.current.layout.grid_cols ?? gridInfo.value.cols,
  set: (v: number) => {
    const n = Math.min(MAX_GRID_DIM, Math.max(1, Math.round(Number(v) || 1)))
    pad.setGridSize(pad.current.layout.grid_rows ?? gridInfo.value.rows, n)
  },
})
const gridDisplay = computed(() => {
  const r = Number(gridRows.value)
  const c = Number(gridCols.value)
  return { rows: r, cols: c, capacity: r * c, empty: Math.max(0, r * c - pad.current.layout.per_page) }
})
function resetDefaultGrid() {
  const g = defaultGrid(pad.current.layout.per_page)
  pad.setGridSize(g.rows, g.cols)
  notify(`已按 N=${pad.current.layout.per_page} 重置为 ${g.rows}行×${g.cols}列（默认 N/2×2）`)
}
function resetSquareGrid() {
  const g = autoSquareGrid(pad.current.layout.per_page)
  pad.setGridSize(g.rows, g.cols)
  notify(`已按 N=${pad.current.layout.per_page} 匀好为 ${g.rows}行×${g.cols}列（最接近方阵）`)
}
const gridWarning = computed(() => {
  const r = Number(gridRows.value); const c = Number(gridCols.value); const n = pad.current.layout.per_page
  if (r * c < n) return `⚠ 当前网格容量 ${r}×${c}=${r * c} < 每页题数 ${n}；渲染时会回退到方向默认网格，请调大行/列数。`
  return ''
})

/* ---------- 页眉页脚 ---------- */
const headTitle = ref('')
const footerText = ref('')

watch(headTitle, (v) => { pad.current.layout.header.title = v })
watch(footerText, (v) => { pad.current.layout.footer.text = v })
function figureCfg() { return pad.current.layout.figure ?? (pad.current.layout.figure = { scale: 1, pos: 'text-right' }) }
function setFigureScale(v: number) { figureCfg().scale = Math.max(0.1, Math.min(2, Number(v) || 1)) }
function setFigurePos(v: string) { figureCfg().pos = (v as 'text-right' | 'text-left' | 'below-left' | 'below-right') }
/** D82-C：题图最大框（mm）；非法值回落缺省 45×60，与引擎同口径。 */
function setFigureMaxW(v: unknown) {
  const n = Number(v)
  figureCfg().max_w_mm = Number.isFinite(n) && n >= 10 && n <= 180 ? n : 45
}
function setFigureMaxH(v: unknown) {
  const n = Number(v)
  figureCfg().max_h_mm = Number.isFinite(n) && n >= 10 && n <= 240 ? n : 60
}
/** D82：题号规则 auto=连续 1./2.；id=题库题号。 */
function setNumbering(v: string) { pad.current.layout.numbering = v === 'id' ? 'id' : 'auto' }
/** D83-3：题号缩进 none/first/hanging（默认 none）。 */
function setIndent(v: string) { pad.current.layout.indent = v === 'first' ? 'first' : v === 'hanging' ? 'hanging' : 'none' }

// 从作业纸初始化表单（当前包切换/载入/导入后也同步；③段载入后通过 current.id 触发）
function syncFromPad() {
  headTitle.value = String(pad.current.layout.header.title ?? '')
  footerText.value = String(pad.current.layout.footer.text ?? '')
}
syncFromPad()
watch(() => pad.current.id, () => syncFromPad())

/* ---------- 水印编辑器（阶段4a：watermark items 列表，兼容 legacy 三槽） ---------- */
const wmPosGrid = ['lt', 'mt', 'rt', 'lm', 'mm', 'rm', 'lb', 'mb', 'rb'] as const

/** 上传图片 → 新增图层。
 *  D87：引擎在线时经 `POST /watermark/upload` 落到 `<ws>/assets/watermark/`，
 *  items[].image 写**相对 assets_dir** 的 `watermark/<文件名>`（引擎各通道可直接命中）；
 *  离线时退回 dataURL 存 settings.wmAssets，仅本浏览器预览有效（明确提示）。 */
async function addWatermarkImage(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  if (!files.length) return
  for (const f of files) {
    const dataUrl = await readAsDataURL(f)
    // 先存本地预览（离线/在线都保留，用于九宫格缩略图）
    settings.persistWmAsset(f.name, dataUrl)
    const rel = await settings.uploadWmImage(f.name, dataUrl)
    const image = rel || `watermark/${f.name}`  // 相对 assets_dir 口径（D87 §3.1）
    const item = { image, pos: 'rb' as const, ratio: 0.25, alpha: 0.5 }
    pad.current.watermark.items = [...(pad.current.watermark.items ?? []), item]
    notify(rel
      ? `已上传 ${f.name} → <ws>/assets/${rel}（引擎各通道可直接命中）`
      : `已添加水印图层 ${f.name}：引擎离线，图片仅存本浏览器预览；请把图片放到 <ws>/assets/watermark/ 后引擎才会读。`)
  }
  input.value = ''
}

function readAsDataURL(f: File): Promise<string> {
  return new Promise((resolve) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => resolve('')
    reader.readAsDataURL(f)
  })
}

/* ---------- D87 §3.3：命名样式下拉 + 新建/重命名/复制/删除/设为默认 + style_ref ---------- */
const wmStyleRef = computed({
  get: () => pad.current.watermark.style_ref ?? '',
  set: (v: string) => { pad.current.watermark.style_ref = v || undefined },
})
const wmStyleName = ref('')
const wmStylesBusy = ref(false)
/** 当前编辑图层所属的命名样式（空 = 直接编辑作业纸内联 items）。 */
const wmEditStyle = ref('')

let wmStylesLoadedOnce = false
watch(() => settings.engineOnline, async (on: boolean) => {
  if (on && !wmStylesLoadedOnce) { wmStylesLoadedOnce = true; await settings.refreshWmStyles() }
}, { immediate: true })

function styleByName(name: string) {
  return settings.wmStyles.find((x) => x.name === name)
}
/** 载入某命名样式的图层到编辑器（写入 style_ref；items 为只读预览→“副本到作业纸”）。 */
function loadStyle(name: string) {
  wmEditStyle.value = name
  wmStyleName.value = name
}
/** 把当前图层“另存为”命名样式（新建/覆盖），并让作业纸引用它。 */
async function saveAsStyle() {
  const name = (wmStyleName.value || '').trim()
  if (!name) { notify('请先填样式名'); return }
  wmStylesBusy.value = true
  const r = await settings.saveWmStyle({
    action: 'save', name,
    style: {
      enabled: pad.current.watermark.enabled !== false,
      pageText: pad.current.watermark.pageText !== false,
      items: (pad.current.watermark.items ?? []).map((it) => ({ ...it })),
    },
  })
  wmStylesBusy.value = false
  if (r.ok) {
    wmStyleRef.value = name
    wmEditStyle.value = name
    notify(`已另存为样式「${name}」并让本作业纸引用它`)
  } else {
    notify(`保存样式失败：${r.error ?? '引擎离线或未就绪'}（离线时样式仅可本地预览，不落盘）`)
  }
}
/** 把某命名样式的图层复制到当前作业纸内联 items（脱离 style_ref）。 */
function copyStyleToPad(name: string) {
  const st = styleByName(name)
  if (!st) { notify('样式不存在或尚未拉取'); return }
  pad.current.watermark.items = (st.items ?? []).map((it) => ({
    image: String(it.image ?? ''),
    pos: (it.pos ?? 'rb') as never,
    ratio: Number(it.ratio ?? 0.25),
    alpha: Number(it.alpha ?? 0.5),
  }))
  wmStyleRef.value = ''
  notify(`已把样式「${name}」的图层复制到本作业纸（不再引用样式）`)
}
async function renameStyle() {
  const old = wmEditStyle.value
  const nw = (wmStyleName.value || '').trim()
  if (!old || !nw || nw === old) { notify('请选择样式并填入新名字'); return }
  wmStylesBusy.value = true
  const r = await settings.saveWmStyle({ action: 'rename', name: old, new_name: nw })
  wmStylesBusy.value = false
  if (r.ok) {
    if (wmStyleRef.value === old) wmStyleRef.value = nw
    wmEditStyle.value = nw
    notify(`已重命名为「${nw}」`)
  } else notify(`重命名失败：${r.error ?? '引擎离线'}`)
}
async function deleteStyle() {
  const name = wmEditStyle.value
  if (!name) { notify('请先选择要删除的样式'); return }
  wmStylesBusy.value = true
  const r = await settings.saveWmStyle({ action: 'delete', name })
  wmStylesBusy.value = false
  if (r.ok) {
    if (wmStyleRef.value === name) wmStyleRef.value = ''
    wmEditStyle.value = ''
    notify(`已删除样式「${name}」`)
  } else notify(`删除失败：${r.error ?? '引擎离线'}`)
}
async function setDefaultStyle() {
  const name = wmEditStyle.value
  if (!name) { notify('请先选择要设为默认的样式'); return }
  wmStylesBusy.value = true
  const r = await settings.saveWmStyle({ action: 'set_default', name })
  wmStylesBusy.value = false
  notify(r.ok ? `已把「${name}」设为默认样式` : `设为默认失败：${r.error ?? '引擎离线'}`)
}

function wmMove(idx: number, dir: -1 | 1) {
  const items = pad.current.watermark.items ?? []
  const j = idx + dir
  if (j < 0 || j >= items.length) return
  const next = [...items]
  ;[next[idx], next[j]] = [next[j], next[idx]]
  pad.current.watermark.items = next
}

function wmRemove(idx: number) {
  const items = pad.current.watermark.items ?? []
  pad.current.watermark.items = items.filter((_, i) => i !== idx)
}

/** 页码文字水印开关（write-through 到 watermark.pageText，缺省 true）。 */
const pageTextOn = computed({
  get: () => pad.current.watermark.pageText !== false,
  set: (v: boolean) => { pad.current.watermark.pageText = v },
})

/** 导出 JSON（D45：从④段触发 → 委托 SheetOutputSection；此处保留「仅保存」） */
function saveOnly() {
  pad.saveToLibrary()
  // D89-N1/N2：若已选作业包，自动把本张作业纸纳入包（tag 取 target_tag/推断）
  const pk = packStore.currentId
  if (pk) {
    const tag = pad.current.target_tag ?? ''
    packStore.addPad(pad.current.id, tag)
    packStore.mutate({ action: 'save', id: pk, pack: packStore.current ?? {} })
    notify(`已保存作业纸「${pad.current.id}」并纳入作业包「${pk}」（继续编辑会覆盖同名条目）。`)
  } else {
    notify('已保存到作业纸清单（③段清单可见；继续编辑会覆盖同名条目）。提示：可在顶部「作业包」栏新建包以按次作业组织。')
  }
}
</script>

<template>
  <section>
    <!-- ============ 工具栏（D43-2：保存进新建一栏） ============ -->
    <div class="card" id="form">
      <h2>① 版式与头部 <small style="font-weight:400;color:var(--c-muted)">工具栏 / 版式 / 页眉页脚 / 作业纸头部 / 水印（docs/05-D45）</small></h2>
      <p class="hint">
        作业纸 JSON 交给 engine： <code>assist sheet make --task &lt;file&gt;</code> 即可出打印级 PDF（D1 CLI 超集）。
        grade 批阅配置在「批阅」选项卡（可留空 = 仅出作业纸，schema 不变）。
      </p>
      <div class="notice" v-if="!kb.hasData">题库为空：请先到「题库编辑器」载入 xlsx 或示例数据，再到②段选题。</div>
      <p>
        <button class="btn" @click="newTaskpadClone(false)">新建作业纸</button>
        <button class="btn" style="margin-left:8px" @click="newTaskpadClone(true)" title="新建空作业纸，克隆当前版式/页眉页脚/水印配置">新建（克隆当前版式）</button>
        <label class="btn as-label btn-file" style="margin-left:8px" for="pad-file">导入作业纸 JSON…</label>
        <input type="file" accept=".json,application/json" hidden id="pad-file" @change="importTaskpadFile" />
        <button class="btn primary" style="margin-left:8px" @click="saveOnly" title="存入③段清单（D43-2：保存与新建同一栏）">仅保存</button>
      </p>
      <p class="hint" v-if="status">{{ status }}</p>
    </div>

    <div style="display:flex; gap:16px; align-items:flex-start; flex-wrap:wrap">
      <!-- ============ 版式 / 页眉页脚 / 作业纸头部（grade/打印/导出已迁出） ============ -->
      <div class="card" style="flex:0 0 380px; min-width:320px">
        <h2>版式 / 页眉页脚 / 作业纸头部</h2>
        <p>
          <label class="field"><input type="radio" name="orient" :checked="pad.current.layout.orientation === 'portrait'" @change="setOrientation('portrait')" />竖版 A4</label>
          <label class="field"><input type="radio" name="orient" :checked="pad.current.layout.orientation === 'landscape'" @change="setOrientation('landscape')" />横版 A4</label>
          <label class="field">每页题数 N：
            <select :value="pad.current.layout.per_page" @change="setPerPage(Number(($event.target as HTMLSelectElement).value) as PerPage)" title="1–12（D61：题数 + 显式行列网格；缺省 竖1横2）">
              <option v-for="n in MAX_PER_PAGE" :key="n" :value="n">{{ n }}</option>
            </select>
          </label>
          <label class="field">行：<input type="number" min="1" :max="MAX_GRID_DIM" step="1" v-model.number="gridRows" style="width:64px" /></label>
          <label class="field">列：<input type="number" min="1" :max="MAX_GRID_DIM" step="1" v-model.number="gridCols" style="width:64px" /></label>
          <button class="btn small" @click="resetDefaultGrid">按 N 重置默认</button>
          <button class="btn small" style="margin-left:6px" @click="resetSquareGrid">均匀方阵</button>
        </p>
        <p class="hint">
          D61 网格语义：N 题/页，行×列 可容纳 N 题时多余格子留空（空位在阅读顺序末尾）。
          竖版=行优先（左→右、上→下）；横版=列优先（上→下、左→右）。
          当前容量 {{ gridDisplay.rows }}×{{ gridDisplay.cols }}={{ gridDisplay.capacity }}，空位 {{ gridDisplay.empty }} 个。
          <span v-if="gridWarning" class="status-fail">{{ gridWarning }}</span>
          预览/打印虚线分隔与引擎 PDF 同口径。
        </p>
        <p>
          <label class="field">页眉标题：<input type="text" v-model="headTitle" style="width:180px" @change="pad.current.layout.header.title = headTitle" /></label>
          <label class="field">页脚：<input type="text" v-model="footerText" style="width:150px" @change="pad.current.layout.footer.text = footerText" /></label>
          <label class="field">题图缩放：
            <input type="range" min="0.2" max="2" step="0.1" :value="figureCfg().scale ?? 1"
                   @input="setFigureScale(Number(($event.target as HTMLInputElement).value))" />
            <span class="hint">{{ (figureCfg().scale ?? 1).toFixed(1) }}×</span>
          </label>
          <label class="field">题图位置：
            <select :value="figureCfg().pos ?? 'text-right'" @change="setFigurePos(($event.target as HTMLSelectElement).value)">
              <option value="text-right">文左图右（同行）</option>
              <option value="text-left">文右图左（同行）</option>
              <option value="below-left">题文满行·图下一行左</option>
              <option value="below-right">题文满行·图下一行右</option>
            </select>
          </label>
          <label class="field">题图最大宽：
            <input type="number" min="10" max="180" step="5" style="width:70px"
                   :value="figureCfg().max_w_mm ?? 45"
                   @change="setFigureMaxW(($event.target as HTMLInputElement).value)" /> mm
          </label>
          <label class="field">题图最大高：
            <input type="number" min="10" max="240" step="5" style="width:70px"
                   :value="figureCfg().max_h_mm ?? 60"
                   @change="setFigureMaxH(($event.target as HTMLInputElement).value)" /> mm
          </label>
          <label class="field">题号规则：
            <select :value="pad.current.layout.numbering ?? 'auto'"
                    @change="setNumbering(($event.target as HTMLSelectElement).value)">
              <option value="auto">连续编号（1./2.）</option>
              <option value="id">题库题号</option>
            </select>
          </label>
          <label class="field">题号缩进：
            <select :value="pad.current.layout.indent ?? 'none'"
                    @change="setIndent(($event.target as HTMLSelectElement).value)">
              <option value="none">默认（题号紧挨文字）</option>
              <option value="first">首行缩进</option>
              <option value="hanging">悬挂缩进</option>
            </select>
          </label>
        </p>
        <h3>作业纸头部（docs/04 §1）</h3>
        <p>
          <label class="field">id：<input type="text" v-model="pad.current.id" style="width:180px" /></label>
          <label class="field">course：<input type="text" v-model="pad.current.course" style="width:110px" /></label>
          <label class="field">class：<input type="text" v-model="pad.current.class" style="width:110px" placeholder="classA" /></label>
          <label class="field">term：<input type="text" v-model="pad.current.term" style="width:110px" placeholder="2026S1" /></label>
          <label class="field">class_dir：<input type="text" v-model="pad.current.class_dir" :placeholder="settings.defaultClassDir" style="width:230px" /></label>
          <button class="btn small" @click="pad.renewId(); notify('已生成新作业纸 id')">换新 id</button>
        </p>
        <p class="hint">target_tag 标注（变体编排绑定）在②段维护（docs/05-D23）。</p>
      </div>

      <!-- ============ 水印编辑器（不变） ============ -->
      <div class="card" style="flex:0 0 380px; min-width:320px">
        <h2>水印编辑器（命名样式库 / items 列表，0..N 图层）</h2>
        <p>
          <label class="field"><input type="checkbox" v-model="pad.current.watermark.enabled" /> 启用水印（每生唯一标识由 engine 打印时注入）</label>
          <label class="field" title="页角大字页码（engine text_draw 第 n 页）">
            <input type="checkbox" v-model="pageTextOn" /> 页码文字水印
          </label>
        </p>
        <div class="card" style="padding:8px; background:var(--c-bg-soft, #f7f8fa); margin:0 0 8px">
          <div class="hint" style="margin:0 0 4px">
            <b>D87 命名样式库</b>：
            引擎在线时样式与图片落 <code>&lt;ws&gt;/assets/watermark/</code>；离线仅本浏览器预览。
          </div>
          <p style="display:flex; gap:6px; align-items:center; flex-wrap:wrap; margin:0 0 4px">
            <span class="hint" style="margin:0">作业纸引用样式：</span>
            <select v-model="wmStyleRef" title="优先级：作业纸内联 items > 引用样式 > 默认样式 > 引擎内置三槽">
              <option value="">（不引用，用默认样式）</option>
              <option v-for="st in settings.wmStyles" :key="st.name" :value="st.name">
                {{ st.name }}{{ st.default ? '（默认）' : '' }}
              </option>
            </select>
            <span class="hint" style="margin:0" v-if="wmStyleRef">当前引用：{{ wmStyleRef }}</span>
          </p>
          <p style="display:flex; gap:6px; align-items:center; flex-wrap:wrap; margin:0">
            <select v-model="wmEditStyle" @change="wmEditStyle && loadStyle(wmEditStyle)">
              <option value="">— 选择样式编辑 —</option>
              <option v-for="st in settings.wmStyles" :key="st.name" :value="st.name">
                {{ st.name }}{{ st.default ? '（默认）' : '' }}
              </option>
            </select>
            <input v-model="wmStyleName" placeholder="样式名（新建/另存为）" style="width:150px" />
            <button class="btn small" :disabled="wmStylesBusy" @click="saveAsStyle">另存为样式</button>
            <button class="btn small" :disabled="wmStylesBusy || !wmEditStyle" @click="() => copyStyleToPad(wmEditStyle)">复制到本作业纸</button>
            <button class="btn small" :disabled="wmStylesBusy || !wmEditStyle" @click="renameStyle">重命名</button>
            <button class="btn small" :disabled="wmStylesBusy || !wmEditStyle" @click="setDefaultStyle">设为默认</button>
            <button class="btn small" :disabled="wmStylesBusy || !wmEditStyle" @click="deleteStyle">删除</button>
          </p>
          <p class="hint" style="margin:4px 0 0" v-if="!settings.wmStyles.length">
            暂无命名样式：编辑下方图层后「另存为样式」即可新建；不引用样式则引擎用默认/内置三槽。
          </p>
        </div>
        <p class="hint">
          每个图层：上传图片 + 九宫格摆位（3x3 点选）+ 大小/透明度滑条 +
          上下移动/删除。引擎在线时图片落 <code>&lt;ws&gt;/assets/watermark/</code>，
          <code>items[].image</code> 写相对素材目录的 <code>watermark/&lt;文件名&gt;</code>；
          离线时 dataURL 仅存本浏览器预览。作业纸导出同时双写 legacy 三槽。
        </p>
        <div v-for="(it, wi) in pad.current.watermark.items" :key="wi" class="wm-item">
          <div class="wm-head">
            <b>{{ wi + 1 }}.</b>
            <img v-if="settings.wmAssets[it.image.split('/').pop() ?? '']" :src="settings.wmAssets[it.image.split('/').pop() ?? '']" style="height:26px; border:1px solid var(--c-border); border-radius:4px" alt="水印图层预览" />
            <code style="font-size:11px">{{ it.image }}</code>
            <span class="hint" style="margin:0">{{ WATERMARK_POS_LABELS[it.pos] }} · 比例 {{ it.ratio.toFixed(2) }} · 透明度 {{ it.alpha.toFixed(2) }}</span>
            <span style="flex:1"></span>
            <button class="btn small" :disabled="wi === 0" @click="wmMove(wi, -1)">↑上移</button>
            <button class="btn small" :disabled="wi === (pad.current.watermark.items?.length ?? 0) - 1" @click="wmMove(wi, 1)">↓下移</button>
            <button class="btn small" @click="wmRemove(wi)">删除</button>
          </div>
          <div style="display:flex; gap:14px; align-items:flex-start; flex-wrap:wrap; margin-top:6px">
            <div>
              <div class="hint" style="margin:0 0 2px">摆位（九宫格点选）：</div>
              <div class="wm-pos-grid">
                <button v-for="p in wmPosGrid" :key="p" type="button" class="wm-pos-cell" :class="{ on: it.pos === p }" @click="it.pos = p">{{ WATERMARK_POS_LABELS[p] }}</button>
              </div>
            </div>
            <label class="field">大小比例：<input type="range" min="0.05" max="0.9" step="0.05" v-model.number="it.ratio" /> {{ it.ratio.toFixed(2) }}</label>
            <label class="field">透明度：<input type="range" min="0" max="1" step="0.05" v-model.number="it.alpha" /> {{ it.alpha.toFixed(2) }}</label>
          </div>
        </div>
        <p class="hint" v-if="!(pad.current.watermark.items ?? []).length">尚无自定义图层：启用后引擎按默认三槽（university/text/boat）绘制；或添加图层覆盖。</p>
        <p>
          <label class="btn small as-label" for="wm-img-file">+ 上传图片新增图层…（可多选）</label>
          <input type="file" accept="image/*" multiple hidden id="wm-img-file" @change="addWatermarkImage" />
        </p>
      </div>
    </div>
  </section>
</template>

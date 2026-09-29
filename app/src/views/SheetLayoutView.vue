<script setup lang="ts">
/**
 * SheetLayoutView.vue — 作业纸设计的"版式 + 预览清单 + 输出"段（docs/05-D43 重排）。
 *
 * D43-1/2/3/4/6（docs/13 任务单，2026-09-29 拍板）：
 *  - 顶部工具栏 = 新建 / 克隆新建 / 导入 JSON / **仅保存**（保存进新建一栏，D43-2）；
 *  - 卡① 只含 版式 + 页眉页脚 + 作业纸头部（grade/打印/导出全部迁出；
 *    grade 节 UI 归「批阅」选项卡，schema 不变 = D43-5；target_tag 标注归内容页）；
 *  - 卡② 水印编辑器不变；
 *  - 卡③ = 模板预览（CSS 近似删除，改为同一 HTML 模板的 iframe 实时渲染，D43-3；
 *    KaTeX 同源自托管 ./katex/，公式正确显示）+ **作业纸清单合卡**（全页唯一一份清单，D43-4）
 *    + 「内容开关」：☑参考答案 / ☑学生示例（默认**不勾**，D43-6：
 *    未勾答案 → 页面不含答案行；未勾示例 → 页眉学籍三空位、1 份空白；勾选 → 合成 学生A/B 2 份）；
 *  - 「输出与交付」全部沉底（D43-1）：打印浏览器版（模板）/ 下载 HTML（自包含·离线可开）/
 *    打印教程 / 打印级 PDF（需引擎）/ 上传学习通（需引擎）/ 导出作业纸 JSON / 导出全部 zip。
 *  - 预览域分层：本页（含清单行预览/全部连排）一律**模板级**；整班分层预览
 *    （每生按 tag 领包、每生一页）唯一入口在「班级与标签」页（D43-6）。
 */
import PrintGuideModal from '../components/PrintGuideModal.vue'
import { computed, ref, watch } from 'vue'
import { STUDENT_TAG_LABELS, type KbKind } from '../lib/kb'
import { useKbStore } from '../stores/kb'
import { useTaskpadStore } from '../stores/taskpad'
import { useSettingsStore } from '../stores/settings'
import { downloadData, downloadBlob, pickReadFile } from '../lib/fsAccess'
import { serializeTaskpad, parseTaskpad, padInferredTag, WATERMARK_POS_LABELS, type PerPage, type Taskpad } from '../lib/taskpad'
import {
  stringifySheetHtml, printSheetHtml, buildSelfContainedHtml, expandPadItems,
  SYNTHETIC_STUDENTS, BLANK_STUDENT,
  type SheetHtmlItem, type SheetHtmlPadInput,
} from '../lib/sheetHtml'
import SheetHtmlPreviewModal from '../components/SheetHtmlPreviewModal.vue'
import JSZip from 'jszip'

const kb = useKbStore()
const pad = useTaskpadStore()
const settings = useSettingsStore()

const status = ref('')
const showGuide = ref(false)

/* ---------- 运行数据（items 只读展开；题目构成在内容页编辑） ---------- */
const sheetHtmlItems = computed<SheetHtmlItem[]>(() =>
  expandPadItems(pad.current, (kind) => kb.book(kind as KbKind)))

function itemsFor(p: Taskpad): SheetHtmlItem[] {
  return expandPadItems(p, (kind) => kb.book(kind as KbKind))
}

/* ---------- D43-6 内容开关（默认都不勾选 = 空白模板 1 份 + 无答案行） ---------- */
const includeAnswers = ref(false)
const showSamples = ref(false)

/** 学生清单：勾"学生示例" = 合成 学生A/B（2 份；检视页眉/水印摆位）；
 *  未勾 = 空白学籍（1 份；页眉 班级/学号/姓名 手写空位线）。 */
function templateStudents() {
  return showSamples.value ? SYNTHETIC_STUDENTS : [BLANK_STUDENT]
}

/** 预览/打印/下载共用（模板级；KaTeX 同源相对路径，公式离线渲染） */
function templateHtml(inputs: SheetHtmlPadInput[] | SheetHtmlPadInput,
                       studentsOverride?: ReturnType<typeof templateStudents>): string {
  return stringifySheetHtml(inputs, {
    students: studentsOverride ?? templateStudents(),
    includeSolution: includeAnswers.value,
    wmAssets: settings.wmAssets,
    katex: 'relative',
  })
}

/* ---------- 浏览器打印主通道（VB-4：同一模板 HTML，无需引擎） ---------- */
function printBrowserVersion() {
  try {
    printSheetHtml(templateHtml([{ pad: JSON.parse(JSON.stringify(pad.current)), items: sheetHtmlItems.value }]))
    status.value = `已打开浏览器打印对话框（隐藏 iframe 打印模板文档本身）。口径：参考答案=${includeAnswers.value ? '含' : '不含'} · ${showSamples.value ? '学生示例 学生A/B 2 份' : '空白模板 1 份'}；整班分层输出在「班级与标签」页。`
  } catch (e) {
    status.value = `打印浏览器版失败：${(e as Error).message}`
  }
}

/** D43-3：下载 = 自包含 HTML（css+js+woff2 字体内联，file:// 离线打开仍渲染公式） */
async function downloadBrowserVersion() {
  try {
    const html = await buildSelfContainedHtml(
      [{ pad: JSON.parse(JSON.stringify(pad.current)), items: sheetHtmlItems.value }],
      { students: templateStudents(), includeSolution: includeAnswers.value, wmAssets: settings.wmAssets })
    downloadData(html, `${pad.current.id}.html`, 'text/html')
    status.value = `已下载自包含 ${pad.current.id}.html（KaTeX css/js/字体内联）：浏览器打开 → Ctrl/Cmd+P → 另存为 PDF，离线亦可开。口径：参考答案=${includeAnswers.value ? '含' : '不含'} · ${showSamples.value ? '示例 2 份' : '空白 1 份'}。`
  } catch (e) {
    status.value = `下载 HTML 失败：${(e as Error).message}`
  }
}

/* ---------- 弹层预览（同模板；供 "显示为浏览器打印版" 与清单行预览共用） ---------- */
const showHtmlOverlay = ref(false)
const overlayHtml = ref('')
const overlayTitle = ref('')

/** 弹层下载 = 自包含文件（弹层内显示的是 relative 版以保性能） */
async function downloadOverlayHtml() {
  const inputs: SheetHtmlPadInput[] = JSON.parse(overlayInputsKey.value)
  const html = await buildSelfContainedHtml(inputs, {
    students: templateStudents(),
    includeSolution: includeAnswers.value,
    wmAssets: settings.wmAssets,
  })
  downloadData(html, `sheet-preview-${new Date().toISOString().slice(0, 10)}.html`, 'text/html')
}

const overlayInputsKey = ref('[]')

function openPreview(pads: SheetHtmlPadInput[], title: string) {
  if (!pads.length) return
  overlayInputsKey.value = JSON.stringify(pads)
  overlayHtml.value = templateHtml(pads)
  overlayTitle.value = title
  showHtmlOverlay.value = true
}

/** 清单行「预览」（每份作业纸一份模板态预览，受同一对开关控制） */
function previewPad(id: string) {
  const entry = pad.saved.find((s) => s.id === id)
  if (!entry) { status.value = `清单中未找到 ${id}。`; return }
  try {
    const p = parseTaskpad(JSON.parse(entry.json))
    openPreview([{ pad: p, items: itemsFor(p) }], `作业纸预览 · ${id}`)
    status.value = `已打开 ${id} 预览（同一 HTML 模板；口径：参考答案=${includeAnswers.value ? '含' : '不含'} · ${showSamples.value ? '示例 2 份' : '空白 1 份'}）。`
  } catch (e) {
    status.value = `作业纸 ${id} 预览失败（JSON 损坏）：${(e as Error).message}`
  }
}

/** 全部清单作业纸连排预览（多包不分页；模板态，受同一对开关控制） */
function previewAllPads() {
  const sources: SheetHtmlPadInput[] = []
  let bad = 0
  for (const s of pad.saved) {
    try {
      const p = parseTaskpad(JSON.parse(s.json))
      sources.push({ pad: p, items: itemsFor(p) })
    } catch { bad++ }
  }
  if (!sources.length) { status.value = '清单为空或全部 JSON 损坏：无可预览作业纸。'; return }
  openPreview(sources, `全部作业纸连排预览 · ${sources.length} 份`)
  status.value = `已连排预览 ${sources.length} 份作业纸（多包不分页；@page 方向取第一份${bad ? `；${bad} 份 JSON 损坏已跳过` : ''}）。`
}

/* ---------- 实时预览（iframe srcdoc；编辑防抖 180ms；D43-3 单一 HTML 模板渲染） ---------- */
const liveHtml = ref('')
let liveTimer = 0
function buildLiveHtml(): string {
  return templateHtml([{ pad: JSON.parse(JSON.stringify(pad.current)), items: sheetHtmlItems.value }])
}
function scheduleLive() {
  clearTimeout(liveTimer)
  liveTimer = window.setTimeout(() => { liveHtml.value = buildLiveHtml() }, 180)
}
const liveKey = computed(() =>
  JSON.stringify([pad.current, sheetHtmlItems.value, includeAnswers.value, showSamples.value, settings.wmAssets]))
watch(liveKey, scheduleLive, { immediate: true })

/* ---------- 版式编辑（D19：per_page 1–4；竖=上下行、横=左右栏） ---------- */
function setOrientation(o: 'portrait' | 'landscape') {
  pad.setOrientation(o)
}

function setPerPage(v: PerPage) {
  pad.setPerPage(v)
}

/* ---------- 页眉页脚 ---------- */
const headTitle = ref('')
const footerText = ref('')

watch(headTitle, (v) => { pad.current.layout.header.title = v })
watch(footerText, (v) => { pad.current.layout.footer.text = v })

// 从作业纸初始化表单（当前包切换/载入/导入后也同步）
function syncFromPad() {
  headTitle.value = String(pad.current.layout.header.title ?? '')
  footerText.value = String(pad.current.layout.footer.text ?? '')
}
syncFromPad()
watch(() => pad.current.id, () => syncFromPad())

/* ---------- 作业纸清单（多份作业纸管理；D43-4 全页唯一一份，模板态预览） ---------- */
interface PadMeta { id: string; term: string; cls: string; items: number; questions: number; orientation: string; perPage: number; targetTag: string; inferredTag: string | null; json: string }
const library = computed<PadMeta[]>(() =>
  pad.saved.map((s) => {
    try {
      const p = parseTaskpad(JSON.parse(s.json))
      return {
        id: p.id,
        term: p.term || '—',
        cls: p.class || p.class_dir.split('/').pop() || '—',
        items: p.items.length,
        questions: p.items.reduce((n, i) => n + i.ids.length, 0),
        orientation: p.layout.orientation === 'landscape' ? '横版' : '竖版',
        perPage: p.layout.per_page,
        targetTag: p.target_tag ?? '',
        inferredTag: padInferredTag(p.items, p.target_tag),
        json: s.json,
      }
    } catch {
      return { id: s.id, term: '?', cls: '?', items: 0, questions: 0, orientation: '?', perPage: 0, targetTag: '', inferredTag: null, json: s.json }
    }
  }))

function loadFromLibrary(id: string) {
  if (pad.openFromLibrary(id)) {
    syncFromPad()
    status.value = `已载入作业纸 ${id}（可继续编辑；保存会覆盖清单中的同名条目）。`
  } else {
    status.value = `清单中未找到 ${id}。`
  }
}

function removeFromLibrary(id: string) {
  pad.removeFromLibrary(id)
  status.value = `已从清单删除作业纸 ${id}（仅删除清单记录，不影响已导出文件）。`
}

/** 导出全部：多份作业纸 JSON + 题库 xlsx 打包 zip（教师解压放回 workspace：tasks/ + kb/） */
const exportingAll = ref(false)
async function exportAllZip() {
  if (!pad.saved.length) {
    status.value = '作业纸清单为空：先「仅保存」或「导出作业纸 JSON」至少一份。'
    return
  }
  exportingAll.value = true
  try {
    const zip = new JSZip()
    for (const s of pad.savedJsons()) zip.file(`tasks/${s.id}.taskpad.json`, s.json)
    for (const [kind, bin] of Object.entries(kb.exportBinaries())) {
      if (bin) zip.file(`kb/${kind}.xlsx`, bin)
    }
    const readme = [
      '# 作业纸清单导出（assignment-assistant · 作业纸）',
      '',
      '- tasks/<id>.taskpad.json — 已保存的作业纸（schema 同 docs/04 §1）。',
      '  交付引擎执行：assist sheet make --task tasks/<id>.taskpad.json',
      '- kb/<kind>.xlsx — 当前浏览器内题库（source of truth，docs/05-D3）。',
      '',
      'LAN 预览（http://IP）下无法直接写本地目录：请下载本 zip 后解压，',
      '教师手动放回 workspace 的对应目录（tasks/ 与 kb/）。',
      '全部文案为合成占位风格，不含真实学生数据。',
      '',
      `导出时间：${new Date().toISOString()}`,
      `作业纸数量：${pad.saved.length}`,
    ].join('\n')
    zip.file('README-作业纸清单.md', readme)
    const blob = await zip.generateAsync({ type: 'blob' })
    downloadBlob(blob, `taskpads-${new Date().toISOString().slice(0, 10)}.zip`)
    status.value = `已导出 ${pad.saved.length} 份作业纸 + 题库 xlsx（zip）。LAN 预览下请手动放回 workspace 的 tasks/ 与 kb/。`
  } finally {
    exportingAll.value = false
  }
}

/** 新建空作业纸（克隆当前版式/页眉页脚/水印配置可选） */
function newTaskpadClone(cloneStyle: boolean) {
  pad.newPad(cloneStyle)
  syncFromPad()
  status.value = cloneStyle
    ? '已新建空作业纸（克隆了当前版式/页眉页脚/水印配置）。选题请到内容段。'
    : '已新建空作业纸（默认版式）。选题请到内容段。'
}

/* ---------- 导入 / 导出 ---------- */
async function importTaskpadFile() {
  const f = await pickReadFile('application/json,.json')
  if (!f) return
  try {
    const p = pad.importJson(await f.text())
    syncFromPad()
    status.value = `已导入作业纸 ${p.id}（${p.items.length} 组选题），可继续编辑。`
  } catch (e) {
    status.value = `作业纸导入失败：${(e as Error).message}`
  }
}

function exportTaskpadJson() {
  pad.saveToLibrary()
  downloadData(serializeTaskpad(pad.current), `${pad.current.id}.taskpad.json`, 'application/json')
  status.value = `作业纸已导出（schema 同 docs/04 §1）。交付引擎执行：assist sheet make --task ${pad.current.id}.taskpad.json`
}

/* ---------- 水印编辑器（阶段4a：watermark items 列表，兼容 legacy 三槽） ---------- */
const wmPosGrid = ['lt', 'mt', 'rt', 'lm', 'mm', 'rm', 'lb', 'mb', 'rb'] as const

/** 本地上传图片 → dataURL 存 settings.wmAssets（仅浏览器 localStorage，不进作业纸）；
 *  作业纸 items[].image 只写 file 相对路径 hint（如 assets/watermark/<文件名>），
 *  教师把图片放进该路径后引擎即可读取。 */
function addWatermarkImage(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  if (!files.length) return
  for (const f of files) {
    const reader = new FileReader()
    reader.onload = () => {
      const dataUrl = String(reader.result ?? '')
      settings.persistWmAsset(f.name, dataUrl)
      const item = {
        image: `assets/watermark/${f.name}`, // file 相对路径 hint（engine assets/watermark/）
        pos: 'rb' as const,
        ratio: 0.25,
        alpha: 0.5,
      }
      pad.current.watermark.items = [...(pad.current.watermark.items ?? []), item]
      status.value = `已添加水印图层 ${f.name}（图片已存本浏览器；作业纸导出仅含文件路径 hint ${item.image}，教师需把图片放到 workspace 对应路径或 assets/watermark/）。`
    }
    reader.readAsDataURL(f)
  }
  input.value = ''
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

const engineButtonsDisabled = settings.needsSetup
function engineHint(): void {
  status.value = '需引擎在线：去 设置中心 → 环境体检 完成 install.sh / assist serve 配置后启用（阶段4 联调，docs/05-D13）。'
}
</script>

<template>
  <section>
    <!-- ============ 工具栏（D43-2：保存进新建一栏） ============ -->
    <div class="card">
      <h2>作业纸设计段 <small style="font-weight:400;color:var(--c-muted)">头部 / 版式 / 水印 / 预览·清单 / 输出（docs/05-D43）</small></h2>
      <p class="hint">
        作业纸 JSON 交给 engine： <code>assist sheet make --task &lt;file&gt;</code> 即可出打印级 PDF（D1 CLI 超集）。
        grade 批阅配置在「批阅」选项卡（可留空 = 仅出作业纸，schema 不变）。
      </p>
      <div class="notice" v-if="!kb.hasData">题库为空：请先到「题库编辑器」载入 xlsx 或示例数据，再到内容段选题。</div>
      <p>
        <button class="btn" @click="newTaskpadClone(false)">新建作业纸</button>
        <button class="btn" style="margin-left:8px" @click="newTaskpadClone(true)" title="新建空作业纸，克隆当前版式/页眉页脚/水印配置">新建（克隆当前版式）</button>
        <label class="btn as-label btn-file" style="margin-left:8px" for="pad-file">导入作业纸 JSON…</label>
        <input type="file" accept=".json,application/json" hidden id="pad-file" @change="importTaskpadFile" />
        <button class="btn primary" style="margin-left:8px" @click="pad.saveToLibrary(); status = '已保存到作业纸清单'" title="存入本页清单（D43-2：保存与新建同一栏）">仅保存</button>
      </p>
      <p class="hint" v-if="status">{{ status }}</p>
    </div>

    <div style="display:flex; gap:16px; align-items:flex-start; flex-wrap:wrap">
      <!-- ============ ① 版式 / 页眉页脚 / 作业纸头部（grade/打印/导出已迁出） ============ -->
      <div class="card" style="flex:0 0 380px; min-width:320px">
        <h2>① 版式 / 页眉页脚 / 作业纸头部</h2>
        <p>
          <label class="field"><input type="radio" name="orient" :checked="pad.current.layout.orientation === 'portrait'" @change="setOrientation('portrait')" />竖版 A4</label>
          <label class="field"><input type="radio" name="orient" :checked="pad.current.layout.orientation === 'landscape'" @change="setOrientation('landscape')" />横版 A4</label>
          <label class="field">每页题数 per_page：
            <select :value="pad.current.layout.per_page" @change="setPerPage(Number(($event.target as HTMLSelectElement).value) as PerPage)" title="1–4（docs/05-D19：竖版为上下行、横版为左右栏；引擎帧按 per_page 切分，缺省 竖1横2）">
              <option :value="1">1</option>
              <option :value="2">2</option>
              <option :value="3">3</option>
              <option :value="4">4</option>
            </select>
          </label>
        </p>
        <p class="hint">
          per_page 1–4（docs/05-D19）：竖版为上下行、横版为左右栏；缺省 竖1横2。
          预览多题/页的分隔线（横版=栏间竖线、竖版=行间横线）与引擎打印 PDF 同口径（虚线）。
        </p>
        <p>
          <label class="field">页眉标题：<input type="text" v-model="headTitle" style="width:180px" @change="pad.current.layout.header.title = headTitle" /></label>
          <label class="field">页脚：<input type="text" v-model="footerText" style="width:150px" @change="pad.current.layout.footer.text = footerText" /></label>
        </p>
        <h3>作业纸头部（docs/04 §1）</h3>
        <p>
          <label class="field">id：<input type="text" v-model="pad.current.id" style="width:180px" /></label>
          <label class="field">course：<input type="text" v-model="pad.current.course" style="width:110px" /></label>
          <label class="field">class：<input type="text" v-model="pad.current.class" style="width:110px" placeholder="classA" /></label>
          <label class="field">term：<input type="text" v-model="pad.current.term" style="width:110px" placeholder="2026S1" /></label>
          <label class="field">class_dir：<input type="text" v-model="pad.current.class_dir" :placeholder="settings.defaultClassDir" style="width:230px" /></label>
          <button class="btn small" @click="pad.renewId(); status = '已生成新作业纸 id'">换新 id</button>
        </p>
        <p class="hint">target_tag 标注（变体编排绑定）在「作业纸内容」段维护（docs/05-D23）。</p>
        <p class="hint" v-if="status" v-show="false"></p>
      </div>

      <!-- ============ ② 水印编辑器（不变） ============ -->
      <div class="card" style="flex:0 0 380px; min-width:320px">
        <h2>② 水印编辑器（items 列表，0..N 图层）</h2>
        <p>
          <label class="field"><input type="checkbox" v-model="pad.current.watermark.enabled" /> 启用水印（每生唯一标识由 engine 打印时注入）</label>
          <label class="field">样式：</label>
          <select v-model="pad.current.watermark.style"><option value="default">default</option><option value="none">none</option></select>
          <label class="field" title="页角大字页码（engine text_draw 第 n 页）">
            <input type="checkbox" v-model="pageTextOn" /> 页码文字水印
          </label>
        </p>
        <p class="hint">
          每个图层：本地上传图片 + 九宫格摆位（3x3 点选）+ 大小/透明度滑条 +
          上下移动/删除。dataURL 只存本浏览器；作业纸导出仅含
          <code>items[].image</code> 文件相对路径 hint（教师把图片放到 workspace/assets/watermark/），
          并双写 legacy 三槽 university/text/boat（engine 现行 schema 兼容）。
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

      <!-- ============ ③ 预览（iframe · 同一 HTML 模板） + 作业纸清单（合卡 D43-4） ============ -->
      <div class="card" id="preview" style="flex:1 1 520px; min-width:440px">
        <h2>③ 模板预览（同一 HTML 打印模板 · iframe 实时 · D43-3）</h2>
        <p>
          <label class="field" title="D43-6：勾选后预览/打印/下载包含『参考答案：…』行">
            <input type="checkbox" v-model="includeAnswers" /> 显示参考答案
          </label>
          <label class="field" title="D43-6：勾选后按合成 学生A/B 预览 2 份（检视页眉/水印摆位）；不勾 = 页眉学籍三空位、1 份空白模板">
            <input type="checkbox" v-model="showSamples" /> 显示学生示例
          </label>
          <button class="btn" style="margin-left:8px" title="同一 HTML 模板在弹窗 iframe 里再细看（打印/下载按钮在弹层内）" @click="openPreview([{ pad: JSON.parse(JSON.stringify(pad.current)), items: sheetHtmlItems }], `作业纸预览 · ${pad.current.id}`)">🔍 弹窗细看</button>
        </p>
        <p class="hint">
          预览 = 打印产物同源（stringifySheetHtml，与 CLI <code>assist sheet html</code> 同模板）；
          公式用 PWA 内置同源 KaTeX（./katex/）渲染，<b>离线也正确显示</b>，不降级到源码。
          两个开关同时约束 清单行「预览」/「预览全部连排」与底部输出卡的打印/下载（docs/13 D43-6）。
        </p>
        <iframe
          v-if="liveHtml"
          class="live-frame"
          :srcdoc="liveHtml"
          title="作业纸模板实时预览（同一 HTML 打印模板）"
        ></iframe>
        <p class="hint" v-if="!sheetHtmlItems.length">尚未选题（items 为空）：预览只有页眉/页脚/水印骨架；去内容段选题后回来看版式效果。版式/水印/页眉页脚改动实时生效。</p>

        <h3>作业纸清单（多份作业纸管理 · 全页唯一一份）</h3>
        <p>
          <button class="btn" title="每个保存的作业纸各出一连段（模板态，受上方开关约束）" @click="previewAllPads">👁 预览全部作业纸（连排 · 模板态）</button>
        </p>
        <table class="grid" v-if="library.length" style="font-size:12px">
          <thead>
            <tr><th>id</th><th>学期</th><th>班级</th><th>目标 tag</th><th>选题</th><th>题数</th><th>版式</th><th style="width:170px">操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="m in library" :key="m.id">
              <td style="max-width:120px; word-break:break-all">{{ m.id }}</td>
              <td>{{ m.term }}</td>
              <td>{{ m.cls }}</td>
              <td style="white-space:nowrap">
                {{ m.targetTag ? (STUDENT_TAG_LABELS[m.targetTag] ?? m.targetTag) : (m.inferredTag ? `自动推断：${m.inferredTag}` : '⚠ 混合 tag 未绑定') }}
              </td>
              <td style="text-align:center">{{ m.items }}</td>
              <td style="text-align:center">{{ m.questions }}</td>
              <td style="white-space:nowrap">{{ m.orientation }} / {{ m.perPage }}题页</td>
              <td style="white-space:nowrap">
                <button class="btn small" @click="loadFromLibrary(m.id)">载入</button>
                <button class="btn small" style="margin-left:4px" @click="previewPad(m.id)" title="该作业纸的模板态预览（同一 HTML 模板 overlay）">预览</button>
                <button class="btn small" style="margin-left:4px" @click="removeFromLibrary(m.id)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p class="hint" v-else>清单为空：点「仅保存」或「导出作业纸 JSON」后出现在这里。</p>
      </div>
    </div>

    <!-- ============ 输出与交付（D43-1：全部输出动作沉底） ============ -->
    <div class="card" id="output">
      <h2>输出与交付 <small style="font-weight:400;color:var(--c-muted)">模板态输出（受③卡两个开关约束）· docs/05-D43</small></h2>
      <h3>浏览器打印主通道（无需引擎 · docs/14 §VB-4 / 05-D30）</h3>
      <p>
        <button class="btn primary" title="隐藏 iframe 打印模板本身（非本页界面），受「显示参考答案/显示学生示例」开关约束" @click="printBrowserVersion">🖨 打印浏览器版（模板）</button>
        <button class="btn" style="margin-left:8px" title="下载自包含 HTML：KaTeX 资源内联，file:// 离线打开仍渲染公式" @click="downloadBrowserVersion">⬇ 下载 HTML（自包含）</button>
        <button class="btn" style="margin-left:8px" @click="showGuide = true">📖 打印教程</button>
        <PrintGuideModal v-if="showGuide" @close="showGuide = false" />
      </p>
      <p class="hint">
        打印对话框按「打印教程」设置（A4 / 边距=无 / 页眉页脚=关 / 背景图形=开）。
        <b>模板语义（docs/13 D43-6）</b>：{{ showSamples ? '学生示例（学生A/B）2 份' : '空白模板 1 份（页眉学籍三空位）' }}，
        {{ includeAnswers ? '含参考答案行' : '不含参考答案行' }}。
        整班分层（每生一页、按 tag 领包）唯一入口 =「班级与标签」页的「预览整班」。
      </p>
      <h3>引擎依赖按钮（D13 条件式置灰）</h3>
      <p>
        <button class="btn" :disabled="engineButtonsDisabled" title="需引擎在线（assist serve）后启用" @click="engineHint()">🖨 打印级 PDF（模板，需引擎）</button>
        <button class="btn" style="margin-left:8px" :disabled="engineButtonsDisabled" title="需引擎在线（assist serve）后启用" @click="engineHint()">⬆ 上传到学习通（需引擎）</button>
      </p>
      <p class="hint">
        「打印级 PDF（模板）」语义（docs/05-D27）：当前作业纸 × 合成学生 A/B 样例，输出<b>单类型</b>作业纸模板。
        批阅/打分在「批阅」选项卡（grade 节随作业纸 JSON 交付引擎）。
      </p>
      <h3>作业纸 JSON 交付</h3>
      <p>
        <button class="btn primary" @click="exportTaskpadJson">⬇ 导出作业纸 JSON（下载 + 存入清单）</button>
        <button class="btn" style="margin-left:8px" :disabled="!library.length || exportingAll" @click="exportAllZip">📦 导出全部（zip：作业纸 JSON + 题库 xlsx）</button>
      </p>
      <p class="hint" v-if="library.length">清单 {{ library.length }} 份；导出全部 = tasks/*.taskpad.json + 题库 xlsx + README。</p>
      <p class="hint" v-else>清单为空（导出全部不可用）。</p>
    </div>

    <SheetHtmlPreviewModal
      v-if="showHtmlOverlay"
      :html="overlayHtml"
      :title="overlayTitle"
      @close="showHtmlOverlay = false"
      @download="downloadOverlayHtml"
    />
  </section>
</template>

<style scoped>
/* 实时预览 iframe（打印版 HTML 的可视容器；可滚动） */
.live-frame {
  width: 100%; height: 560px; border: 1px solid var(--c-border);
  border-radius: 8px; background: #e8ecf3;
}
</style>

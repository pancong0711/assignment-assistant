<script setup lang="ts">
import PrintGuideModal from '../components/PrintGuideModal.vue'
import { computed, ref, watch } from 'vue'
import { STUDENT_TAG_LABELS, type KbKind } from '../lib/kb'
import { useKbStore } from '../stores/kb'
import { useTaskpadStore } from '../stores/taskpad'
import { useRosterStore } from '../stores/roster'
import { useSettingsStore } from '../stores/settings'
import { downloadData, downloadBlob, pickReadFile } from '../lib/fsAccess'
import { serializeTaskpad, parseTaskpad, padInferredTag, WATERMARK_POS_LABELS, type PerPage } from '../lib/taskpad'
import {
  stringifySheetHtml, downloadSheetHtml, printSheetHtml, SYNTHETIC_STUDENTS,
  type SheetHtmlItem, type SheetHtmlStudent,
} from '../lib/sheetHtml'
import SheetHtmlPreviewModal from '../components/SheetHtmlPreviewModal.vue'
import JSZip from 'jszip'

/** 作业纸版式（M-A S1 拆分，docs/05-D25/D27）：一份模板的"长相"。
 *  orientation / per_page / 页眉页脚 / 水印编辑器 / 模板预览（CSS 近似）/
 *  任务包导出与清单；"打印级 PDF（模板）"语义 = 模板级（当前任务包 × 合成学生
 *  A/B 样例，单类型全班统一场景；docs/05-D27）。整班分层生成入口在「班级与标签」。
 *  题目构成（kind×章选题 / items / target_tag 绑定）在「作业纸内容」页（SheetContentView）。
 *  S2a（docs/14 §VB-4/§VC-1）：+「打印浏览器版」按钮（下载 HTML / window.print，
 *  与 CLI `assist sheet html` 同一模板的 TS 同构实现）+「显示为浏览器打印版」
 *  HTML overlay 预览切换（CSS 预览保留，不依赖引擎）。 */

const kb = useKbStore()
const pad = useTaskpadStore()
const roster = useRosterStore()
const settings = useSettingsStore()

const status = ref('')
const showGuide = ref(false)

/* ---------- 预览数据（items 只读：题目构成在「作业纸内容」页编辑） ---------- */
interface PreItem { kind: KbKind; chap: string; id: string; content: string; solution: string; imgPath: string; tag: string }
const preItems = computed<PreItem[]>(() => {
  const out: PreItem[] = []
  for (const item of pad.current.items) {
    const chap = kb.book(item.kb as KbKind)?.chapters.find((c) => c.name === item.chap)
    if (!chap) continue
    for (const id of item.ids) {
      const r = chap.rows.find((x) => x.id === id)
      if (r) out.push({ kind: item.kb as KbKind, chap: item.chap, id, content: r.content, solution: r.solution, imgPath: r.img_path, tag: item.tag })
    }
  }
  return out
})

/* ---------- 浏览器打印主通道（VB-4：任务包 → 同一模板 HTML；无需引擎） ---------- */
const sheetHtmlItems = computed<SheetHtmlItem[]>(() =>
  preItems.value.map((p) => ({ id: p.id, content: p.content, solution: p.solution, imgPath: p.imgPath, tag: p.tag })))

/** 名单：有名单用名单；否则合成 学生A/B（informational，与引擎 demo 同风格） */
function sheetStudents(): SheetHtmlStudent[] {
  return roster.students.length
    ? roster.students.map((s) => ({ name: s.name, number: s.number, class: s.class, tag: s.tag }))
    : SYNTHETIC_STUDENTS
}

function buildCurrentPadHtml(): string {
  return stringifySheetHtml(
    { pad: pad.current, items: sheetHtmlItems.value },
    { students: sheetStudents(), wmAssets: settings.wmAssets },
  )
}

function printBrowserVersion() {
  try {
    printSheetHtml(buildCurrentPadHtml())
    status.value = `已打开浏览器打印对话框（隐藏 iframe 内打印作业纸文档本身）。名单来源：${roster.students.length ? `本地名单 ${roster.students.length} 人` : '合成 学生A/B（未导入名单）'}；整班 HTML 下载请用旁边按钮。`
  } catch (e) {
    status.value = `打印浏览器版失败：${(e as Error).message}`
  }
}

function downloadBrowserVersion() {
  try {
    const html = buildCurrentPadHtml()
    downloadSheetHtml(html, `${pad.current.id}.html`)
    status.value = `已下载 ${pad.current.id}.html（自包含整班 HTML，与 CLI assist sheet html 同一模板）：浏览器打开 → Ctrl/Cmd+P → 目标「另存为 PDF」。名单：${roster.students.length ? `${roster.students.length} 人` : '合成 学生A/B'}。`
  } catch (e) {
    status.value = `下载 HTML 失败：${(e as Error).message}`
  }
}

/* ---------- VC-1：模板预览切换（CSS 预览保留 + HTML overlay） ---------- */
const showHtmlOverlay = ref(false)
const overlayHtml = ref('')
function openHtmlOverlay() {
  overlayHtml.value = buildCurrentPadHtml()
  showHtmlOverlay.value = true
  status.value = '已在弹窗打开「浏览器打印版」预览（同一 HTML 模板；打印/下载按钮在弹层内）。'
}

const perPage = computed(() => pad.current.layout.per_page)
const orientation = computed(() => pad.current.layout.orientation)
const gridClass = computed(() => {
  const o = orientation.value, n = perPage.value
  if (n === 4) return 'cross'
  if (n === 3) return o === 'portrait' ? 'rows3' : 'cols3'
  return o === 'portrait' ? 'rows2' : 'cols2'
})
/** 预览水印项：items 优先；空则 legacy 默认三槽占位（engine 的同样缺省）。 */
const wmPreviewItems = computed<any[]>(() => {
  const items = pad.current.watermark.items
  if (items && items.length) return items
  return [
    { name: 'university', image: '', pos: 'rt', ratio: 0.125, alpha: 0.5 },
    { name: 'text', image: '', pos: 'lc', ratio: 0.1, alpha: 0.3 },
    { name: 'boat', image: '', pos: 'lb', ratio: 0.3, alpha: 0.5 },
  ]
})
function wmPageTextFor(pi: number) {
  const s = `第 ${pi + 1} 页`
  return s
}
const gridLines = computed<string[]>(() => {
  const n = perPage.value
  if (n === 4) return ['v', 'h']            // 十字
  if (n === 3) return (orientation.value === 'portrait') ? ['h31', 'h32'] : ['v31', 'v32']
  if (n === 2) return (orientation.value === 'portrait') ? ['h'] : ['v']
  return []
})
const demoStudent = { name: '学生A', number: '2026xxxx01' }  // 预览用合成占位（与 engine demo 一致）
const todayStr = new Date().toLocaleDateString('zh-CN')
const pages = computed<PreItem[][]>(() => {
  const chunks: PreItem[][] = []
  for (let i = 0; i < preItems.value.length; i += perPage.value) {
    chunks.push(preItems.value.slice(i, i + perPage.value))
  }
  return chunks.length ? chunks : [[]]
})

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

// 从任务包初始化表单（当前包切换/载入/导入后也同步）
function syncFromPad() {
  headTitle.value = String(pad.current.layout.header.title ?? '')
  footerText.value = String(pad.current.layout.footer.text ?? '')
}
syncFromPad()
watch(() => pad.current.id, () => syncFromPad())

/* ---------- 任务包头（docs/04 §1；target_tag 绑定在「作业纸内容」页，D23/D25） ---------- */

/* ---------- 任务包清单（多份作业纸管理，D19 反馈第 3 项） ---------- */
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
    status.value = `已载入任务包 ${id}（可继续编辑；保存会覆盖清单中的同名条目）。`
  } else {
    status.value = `清单中未找到 ${id}。`
  }
}

function removeFromLibrary(id: string) {
  pad.removeFromLibrary(id)
  status.value = `已从清单删除任务包 ${id}（仅删除清单记录，不影响已导出文件）。`
}

/** 导出全部：多份任务包 JSON + 题库 xlsx 打包 zip（教师解压放回 workspace：tasks/ + kb/） */
const exportingAll = ref(false)
async function exportAllZip() {
  if (!pad.saved.length) {
    status.value = '任务包清单为空：先「仅保存」或「导出任务包 JSON」至少一份。'
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
      '# 任务包清单导出（assignment-assistant · 作业纸）',
      '',
      '- tasks/<id>.taskpad.json — 已保存的任务包（schema 同 docs/04 §1）。',
      '  交付引擎执行：assist sheet make --task tasks/<id>.taskpad.json',
      '- kb/<kind>.xlsx — 当前浏览器内题库（source of truth，docs/05-D3）。',
      '',
      'LAN 预览（http://IP）下无法直接写本地目录：请下载本 zip 后解压，',
      '教师手动放回 workspace 的对应目录（tasks/ 与 kb/）。',
      '全部文案为合成占位风格，不含真实学生数据。',
      '',
      `导出时间：${new Date().toISOString()}`,
      `任务包数量：${pad.saved.length}`,
    ].join('\n')
    zip.file('README-任务包清单.md', readme)
    const blob = await zip.generateAsync({ type: 'blob' })
    downloadBlob(blob, `taskpads-${new Date().toISOString().slice(0, 10)}.zip`)
    status.value = `已导出 ${pad.saved.length} 份任务包 + 题库 xlsx（zip）。LAN 预览下请手动放回 workspace 的 tasks/ 与 kb/。`
  } finally {
    exportingAll.value = false
  }
}

/** 新建空任务包（克隆当前版式/页眉页脚/水印配置可选） */
function newTaskpadClone(cloneStyle: boolean) {
  pad.newPad(cloneStyle)
  syncFromPad()
  status.value = cloneStyle
    ? '已新建空任务包（克隆了当前版式/页眉页脚/水印配置）。选题请到「作业纸内容」页。'
    : '已新建空任务包（默认版式）。选题请到「作业纸内容」页。'
}

/* ---------- 导入 / 导出 ---------- */
async function importTaskpadFile() {
  const f = await pickReadFile('application/json,.json')
  if (!f) return
  try {
    const p = pad.importJson(await f.text())
    syncFromPad()
    status.value = `已导入任务包 ${p.id}（${p.items.length} 组选题），可继续编辑。`
  } catch (e) {
    status.value = `任务包导入失败：${(e as Error).message}`
  }
}

function exportTaskpadJson() {
  pad.saveToLibrary()
  downloadData(serializeTaskpad(pad.current), `${pad.current.id}.taskpad.json`, 'application/json')
  status.value = `任务包已导出（schema 同 docs/04 §1）。交付引擎执行：assist sheet make --task ${pad.current.id}.taskpad.json`
}

/* ---------- 水印编辑器（阶段4a：watermark items 列表，兼容 legacy 三槽） ---------- */
const wmPosGrid = ['lt', 'mt', 'rt', 'lm', 'mm', 'rm', 'lb', 'mb', 'rb'] as const

/** 本地上传图片 → dataURL 存 settings.wmAssets（仅浏览器 localStorage，不进任务包）；
 *  任务包 items[].image 只写 file 相对路径 hint（如 assets/watermark/<文件名>），
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
      status.value = `已添加水印图层 ${f.name}（图片已存本浏览器；任务包导出仅含文件路径 hint ${item.image}，教师需把图片放到 workspace 对应路径或 assets/watermark/）。`
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
    <div class="card">
      <h2>作业纸版式 <small style="font-weight:400;color:var(--c-muted)">一份模板的"长相"：版式 / 页眉页脚 / 水印 / 模板预览（docs/05-D25）</small></h2>
      <p class="hint">
        版式（本页）+ 题目构成（「作业纸内容」页）共同生成一个任务包（schema 不变，仅 UI 分屏）。
        任务包 JSON 交给 engine： assist sheet make --task &lt;file&gt; 即可出打印级 PDF（D1 CLI 超集）。
      </p>
      <div class="notice" v-if="!kb.hasData">题库为空：请先到「题库编辑器」载入 xlsx 或示例数据，再到「作业纸内容」页选题。</div>
      <p>
        <button class="btn" @click="newTaskpadClone(false)">新建任务包</button>
        <button class="btn" style="margin-left:8px" @click="newTaskpadClone(true)" title="新建空任务包，克隆当前版式/页眉页脚/水印配置">新建（克隆当前版式）</button>
        <label class="btn as-label btn-file" style="margin-left:8px" for="pad-file">导入任务包 JSON…</label>
        <input type="file" accept=".json,application/json" hidden id="pad-file" @change="importTaskpadFile" />
      </p>
      <p class="hint" v-if="status">{{ status }}</p>
    </div>

    <div style="display:flex; gap:16px; align-items:flex-start; flex-wrap:wrap">
      <div class="card" style="flex:0 0 380px; min-width:320px">
        <h2>① 版式 / 页眉页脚 / 任务包头</h2>
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
          预览多题/页的分隔线（横版=栏间竖线、竖版=行间横线）与引擎打印 PDF 同口径（实线）。
        </p>
        <p>
          <label class="field">页眉标题：<input type="text" v-model="headTitle" style="width:180px" @change="pad.current.layout.header.title = headTitle" /></label>
          <label class="field">页脚：<input type="text" v-model="footerText" style="width:150px" @change="pad.current.layout.footer.text = footerText" /></label>
        </p>
        <h3>任务包头（docs/04 §1）</h3>
        <p>
          <label class="field">id：<input type="text" v-model="pad.current.id" style="width:180px" /></label>
          <label class="field">course：<input type="text" v-model="pad.current.course" style="width:110px" /></label>
          <label class="field">class：<input type="text" v-model="pad.current.class" style="width:110px" placeholder="classA" /></label>
          <label class="field">term：<input type="text" v-model="pad.current.term" style="width:110px" placeholder="2026S1" /></label>
          <label class="field">class_dir：<input type="text" v-model="pad.current.class_dir" :placeholder="settings.defaultClassDir" style="width:230px" /></label>
          <button class="btn small" @click="pad.renewId(); status = '已生成新任务包 id'">换新 id</button>
        </p>
        <h3>grade（可留空 = 仅出作业纸）</h3>
        <p class="hint">本页仅出作业纸即可用；批阅配置（转录/评阅模型、学生范围）留空交给引擎默认值或阶段3 再细化。</p>
        <p>
          <button class="btn primary" @click="exportTaskpadJson">导出任务包 JSON（下载 + 存入本页清单）</button>
          <button class="btn" style="margin-left:8px" @click="pad.saveToLibrary(); status = '已保存到任务包清单'">仅保存</button>
        </p>
        <h3>浏览器打印主通道（无需引擎 · docs/14 §VB-4 / 05-D30）</h3>
        <p>
          <button class="btn" title="隐藏 iframe 打印作业纸 HTML 本身（非本页界面）；打印对话框按教程设置" @click="printBrowserVersion">🖨 打印浏览器版（window.print）</button>
          <button class="btn" style="margin-left:8px" title="下载自包含整班 HTML：浏览器打开 → Ctrl/Cmd+P → 另存为 PDF" @click="downloadBrowserVersion">⬇ 下载整班 HTML（另存 PDF 用）</button>
        
        <button class="btn" @click="showGuide = true">📖 打印教程</button>
        <PrintGuideModal v-if="showGuide" @close="showGuide = false" /></p>
        <p class="hint">
          任务包 → 与 CLI <code>assist sheet html</code> <b>同一模板</b>的 HTML（每生分页块 · @page A4 横/竖 ·
          per_page 网格 · 水印层 · KaTeX 渲染 $..$ 公式，docs/05-D30 主通道）。纯前端不依赖引擎/未登录可用；
          打印对话框请按「打印教程」设置（A4 / 边距=无 / 页眉页脚=关 / 背景图形=开）。
          名单：{{ roster.students.length ? `本浏览器名单 ${roster.students.length} 人` : '未导入名单 → 合成 学生A/B（informational）' }}。
        </p>
        <h3>引擎依赖按钮（D13 条件式置灰）</h3>
        <p>
          <button class="btn" :disabled="engineButtonsDisabled" title="需引擎在线（assist serve）后启用" @click="engineHint()">🖨 打印级 PDF（模板，需引擎）</button>
          <button class="btn" style="margin-left:8px" :disabled="engineButtonsDisabled" title="需引擎在线（assist serve）后启用" @click="engineHint()">⬆ 上传到学习通（需引擎）</button>
        </p>
        <p class="hint">
          「打印级 PDF（模板）」语义（docs/05-D27）：当前任务包 × 合成学生 A/B 样例，输出<b>单类型</b>作业纸模板，
          适合全班统一场景；产物可直接作为「学习通」公告附件发布。
          整班分层生成（每个学生按 tag 领到不同变体）入口在「班级与标签」页 →「生成全班作业纸」（assist sheet batch）。
        </p>
      </div>

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
          上下移动/删除。dataURL 只存本浏览器；任务包导出仅含
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

      <div class="card" style="flex:1 1 500px; min-width:420px">
        <h2>③ 模板预览（A4 比例 · CSS 容器查询横竖感知）</h2>
        <p>
          <button class="btn" title="用同一 HTML 模板在弹窗 iframe 里预览（VC-1；打印/下载按钮在弹层内，不依赖引擎）" @click="openHtmlOverlay">🔍 显示为浏览器打印版（HTML overlay）</button>
          <span class="hint" style="margin-left:6px">CSS 预览（下方）与打印版预览切换 —— 双视图共用同一任务包与水印配置（docs/14 §VC-1）。</span>
        </p>
        <p class="hint" v-if="!preItems.length">题目构成（items）为空 —— 预览暂无题目框；去「作业纸内容」页选题后回到这里看版式效果。版式/水印/页眉页脚的改动实时生效。</p>
        <div class="viewer">
          <div
            v-for="(pg, pi) in pages"
            :key="pi"
            class="sheet-page"
            :class="{ landscape: pad.current.layout.orientation === 'landscape' }"
            style="position:relative"
          >
            <template v-if="pad.current.watermark.enabled">
              <span v-if="pageTextOn" class="sheet-watermark">{{ wmPageTextFor(pi) }}</span>
              <!-- 预览图层：items 为空时按 legacy 默认三槽占位（rt/lc/lb），与引擎一致 -->
              <div v-for="(it, wi2) in wmPreviewItems" :key="'wm' + pi + '-' + wi2" class="wm-preview-anchor" :class="`wm-${it.pos}`">
                <img v-if="settings.wmAssets[(it.image || '').split('/').pop() ?? '']" class="sheet-wm-img" :src="settings.wmAssets[(it.image || '').split('/').pop() ?? '']" :style="{ width: (it.ratio * 100) + '%', opacity: it.alpha }" alt="水印图层" />
                <span v-else class="sheet-wm-placeholder">[水印：{{ it.image || it.name }}（{{ (WATERMARK_POS_LABELS as any)[it.pos] ?? it.pos }}）]</span>
              </div>
            </template>
            <div class="sheet-header">
              <div class="sh-title">{{ String(pad.current.layout.header.title ?? '') || '作业纸' }}</div>
              <div class="sh-info">
                <span>班级：{{ pad.current.class || 'classA' }}</span>
                <span>学号：{{ demoStudent.number }}</span>
                <span>姓名：{{ demoStudent.name }}</span>
                <span class="sh-assign">作业：{{ pad.current.id }}</span>
              </div>
            </div>
            <div class="sheet-body" :class="{ divided: pg.length > 1 }" :data-grid="gridClass">
              <div v-if="pg.length > 1" class="sf-line" v-for="(line, li) in gridLines" :key="'dl'+pi+'-'+li" :class="line" />
              <div v-for="(item, fi) in pg" :key="fi" class="sheet-frame">
                <div class="q-id">{{ item.id }}</div>
                <div class="q-content">{{ item.content }}</div>
                <div v-if="item.imgPath" class="q-img">[题图：{{ item.imgPath }}]</div>
                <div class="q-solution">参考答案：{{ item.solution || '（题库 solution 为空）' }}</div>
              </div>
            </div>
            <div class="sheet-footer">
              <span>{{ footerText }}{{ footerText ? ' · ' : '' }}第 {{ pi + 1 }} / {{ pages.length }} 页</span>
              <span>签名：</span>
              <span>日期：{{ todayStr }}</span>
            </div>
          </div>
        </div>
        <p class="hint">说明：预览为 HTML/CSS 近似；打印级排版（reportlab 版式、真实题图、每生水印）由 engine 按同一任务包生成。多题/页时预览与打印版统一为**中间虚线**分隔（4题=十字 2×2；横版=栏间竖虚线、竖版=行间横虚线，且不穿页眉页脚；docs/05-D21）。</p>

        <h3>任务包清单（多份作业纸管理）</h3>
        <p class="hint">已保存 {{ library.length }} 份。导出全部 = 多份任务包 JSON + 当前题库 xlsx 打包 zip（LAN 预览下请解压后手动放回 workspace 的 tasks/ 与 kb/）。</p>
        <p>
          <button class="btn" :disabled="!library.length || exportingAll" @click="exportAllZip">导出全部（zip：任务包 JSON + 题库 xlsx）</button>
        </p>
        <table class="grid" v-if="library.length" style="font-size:12px">
          <thead>
            <tr><th>id</th><th>学期</th><th>班级</th><th>目标 tag</th><th>选题</th><th>题数</th><th>版式</th><th style="width:110px">操作</th></tr>
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
                <button class="btn small" style="margin-left:4px" @click="removeFromLibrary(m.id)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p class="hint" v-else>清单为空：点「仅保存」或「导出任务包 JSON」后出现在这里。</p>
        <p class="hint">
          各包的「目标 tag 绑定 / 变体编排」在「作业纸内容」页维护；整班分层生成在「班级与标签」页。
        </p>
      </div>
    </div>

    <SheetHtmlPreviewModal
      v-if="showHtmlOverlay"
      :html="overlayHtml"
      :title="`浏览器打印版 · ${pad.current.id}`"
      @close="showHtmlOverlay = false"
    />
  </section>
</template>

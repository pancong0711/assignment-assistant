<script setup lang="ts">
/**
 * SheetOutputSection.vue — 作业纸设计的「输出与交付」独立段（docs/05-D45）。
 *
 * D45（用户拍板）：预览与输出单独成段——本组件 = ④ 输出与交付（模板级输出，
 * 受预览段两个开关约束：includeAnswers / showSamples 由父级 props 传入）。
 * 动作清单（D43-1 迁入）：🖨 打印浏览器版（模板）/ ⬇ 下载 HTML（自包含·离线可开）/
 * 📖 打印教程 / 🖨 打印级 PDF（需引擎）/ ⬆ 上传学习通（需引擎）/
 * ⬇ 导出作业纸 JSON / 📦 导出全部（zip：作业纸 JSON + 题库 xlsx）。
 *
 * 状态归属：本段自持 status（不与①②③段共享，避免提示文案错位）；
 * 导出全部 zip 的 kb.exportBinaries() 通过 getKbBinaries 回调注入（组件不绑 kb store）。
 */
import { computed, ref } from 'vue'
import PrintGuideModal from './PrintGuideModal.vue'
import { useTaskpadStore } from '../stores/taskpad'
import { useSettingsStore } from '../stores/settings'
import { downloadData, downloadBlob } from '../lib/fsAccess'
import { serializeTaskpad } from '../lib/taskpad'
import {
  printSheetHtml, buildSelfContainedHtml, stringifySheetHtml,
  type SheetHtmlPadInput,
} from '../lib/sheetHtml'
import JSZip from 'jszip'

type PadInput = SheetHtmlPadInput
type Students = NonNullable<PadInput['students']>

const props = defineProps<{
  /** 切到输入 props（对象易失 reactive JSON 深拷）——调用时求值 */
  currentInput: () => PadInput
  /** 模板态学生清单（预览段同一口径：空白 1 份 或 学生A/B 2 份） */
  templateStudents: () => Students
  /** 「显示参考答案」开关（口径回显用） */
  includeAnswers: boolean
  /** 「显示学生示例」开关（口径回显用） */
  showSamples: boolean
  /** D43-7 水印图层开关 */
  includeWatermark: boolean
  /** D43-7 页码大字开关 */
  includePageText: boolean
  /** 题库 xlsx 导出回调（导出全部 zip 用；返回 Record<kind, ArrayBuffer|undefined>） */
  getKbBinaries: () => Record<string, ArrayBuffer | undefined>
  /** 引擎依赖按钮置灰口径（与其它视图同为 settings.needsSetup） */
  engineButtonsDisabled: boolean
}>()

const pad = useTaskpadStore()
const settings = useSettingsStore()
const status = ref('')
const showGuide = ref(false)

const templateNote = computed(() =>
  `${props.showSamples ? '学生示例（学生A/B）2 份' : '空白模板 1 份（页眉学籍三空位）'}，${props.includeAnswers ? '含参考答案行' : '不含参考答案行'}`)

const engineButtonsDisabled = computed(() => props.engineButtonsDisabled)
function engineHint(): void {
  status.value = '需引擎在线：去 设置中心 → 环境体检 完成 install.sh / assist serve 配置后启用（docs/05-D13）。'
}

/** 🖨 打印浏览器版（模板）：同一 HTML 模板隐藏 iframe 打印 */
function printBrowserVersion() {
  try {
    const input = props.currentInput()
    printSheetHtml(stringify(input, props.includeAnswers))
    status.value = `已打开浏览器打印对话框（打印模板文档本身；${templateNote.value}）。整班分层输出在「班级与标签」页。`
  } catch (e) {
    status.value = `打印浏览器版失败：${(e as Error).message}`
  }
}

/** ⬇ 下载 HTML（自包含：KaTeX css/js/woff2 内联；file:// 离线可开） */
async function downloadBrowserVersion() {
  try {
    const input = props.currentInput()
    const html = await buildSelfContainedHtml(input, {
      students: props.templateStudents(),
      includeSolution: props.includeAnswers,
      includeWatermark: props.includeWatermark,
      includePageText: props.includePageText,
      wmAssets: settings.wmAssets,
      figAssets: settings.figAssets,
    })
    downloadData(html, `${pad.current.id}.html`, 'text/html')
    status.value = `已下载自包含 ${pad.current.id}.html：浏览器打开 → Ctrl/Cmd+P → 另存为 PDF，离线亦可开（${templateNote.value}）。`
  } catch (e) {
    status.value = `下载 HTML 失败：${(e as Error).message}`
  }
}

/** ⬇ 导出作业纸 JSON（下载 + 存清单） */
function exportTaskpadJson() {
  pad.saveToLibrary()
  downloadData(serializeTaskpad(pad.current), `${pad.current.id}.taskpad.json`, 'application/json')
  status.value = `作业纸已导出（schema 同 docs/04 §1）。交付引擎执行：assist sheet make --task ${pad.current.id}.taskpad.json`
}

/** 📦 导出全部（zip：tasks/*.taskpad.json + kb/*.xlsx + README） */
const exportingAll = ref(false)
async function exportAllZip() {
  if (!pad.saved.length) {
    status.value = '作业纸清单为空：先在③段清单行或上一栏「仅保存」至少一份。'
    return
  }
  exportingAll.value = true
  try {
    const zip = new JSZip()
    for (const s of pad.savedJsons()) zip.file(`tasks/${s.id}.taskpad.json`, s.json)
    for (const [kind, bin] of Object.entries(props.getKbBinaries())) {
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

/* ---------- 内部：stringify（模板态） ---------- */
function stringify(input: PadInput, includeSolution: boolean): string {
  return stringifySheetHtml(input, {
    students: props.templateStudents(),
    includeSolution,
    includeWatermark: props.includeWatermark,
    includePageText: props.includePageText,
    wmAssets: settings.wmAssets,
    figAssets: settings.figAssets,
    katex: 'relative',
  })
}
</script>

<template>
  <div class="card" id="output">
    <h2>输出与交付 <small style="font-weight:400;color:var(--c-muted)">模板级输出（受③预览段两个开关约束）· docs/05-D45</small></h2>
    <h3>浏览器打印主通道（无需引擎 · docs/14 §VB-4 / 05-D30）</h3>
    <p>
      <button class="btn primary" title="隐藏 iframe 打印模板本身（非本页界面）" @click="printBrowserVersion">🖨 打印浏览器版（模板）</button>
      <button class="btn" style="margin-left:8px" title="下载自包含 HTML：KaTeX 资源内联，file:// 离线打开仍渲染公式" @click="downloadBrowserVersion">⬇ 下载 HTML（自包含）</button>
      <button class="btn" style="margin-left:8px" @click="showGuide = true">📖 打印教程</button>
      <PrintGuideModal v-if="showGuide" @close="showGuide = false" />
    </p>
    <p class="hint">
      打印对话框按「打印教程」设置（A4 / 边距=无 / 页眉页脚=关 / 背景图形=开）。
      <b>模板语义（docs/13 D43-6）</b>：{{ templateNote }}。
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
      <button class="btn" style="margin-left:8px" :disabled="!pad.saved.length || exportingAll" @click="exportAllZip">📦 导出全部（zip：作业纸 JSON + 题库 xlsx）</button>
    </p>
    <p class="hint" v-if="pad.saved.length">清单 {{ pad.saved.length }} 份；导出全部 = tasks/*.taskpad.json + 题库 xlsx + README。</p>
    <p class="hint" v-else>清单为空（导出全部不可用）。</p>
    <p class="hint" v-if="status">{{ status }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { KB_KINDS, KB_KIND_LABELS, STUDENT_TAGS, STUDENT_TAG_LABELS, type KbKind } from '../lib/kb'
import { useKbStore } from '../stores/kb'
import { useTaskpadStore } from '../stores/taskpad'
import { useSettingsStore } from '../stores/settings'
import { downloadData, downloadBlob, pickReadFile } from '../lib/fsAccess'
import { serializeTaskpad, parseTaskpad, type PerPage } from '../lib/taskpad'
import JSZip from 'jszip'

const kb = useKbStore()
const pad = useTaskpadStore()
const settings = useSettingsStore()

const status = ref('')

/* ---------- 选题 ---------- */
const selKind = ref<KbKind>('problems')
const selChap = ref('')
const rowFilter = ref('')
const selectedIds = ref<string[]>([])
const itemTag = ref('')

watch([selKind, selChap], () => { selectedIds.value = [] })

const chapRows = computed(() => {
  const c = kb.book(selKind.value).chapters.find((x) => x.name === selChap.value)
  if (!c) return []
  const f = rowFilter.value.trim().toLowerCase()
  const rows = f ? c.rows.filter((r) => r.content.toLowerCase().includes(f) || r.id.toLowerCase().includes(f)) : c.rows
  return rows
})

function toggleId(id: string) {
  const i = selectedIds.value.indexOf(id)
  if (i >= 0) selectedIds.value.splice(i, 1)
  else selectedIds.value.push(id)
}

function addSelection() {
  if (!selectedIds.value.length) return
  pad.addItem({ kb: selKind.value, chap: selChap.value, ids: [...selectedIds.value], tag: itemTag.value })
  status.value = `已加入 ${selectedIds.value.length} 题（${selKind.value}/${selChap.value}）`
  selectedIds.value = []
}

/* ---------- 版式与页眉页脚 ---------- */
const headTitle = ref('')
const footerText = ref('')

watch(headTitle, (v) => { pad.current.layout.header.title = v })
watch(footerText, (v) => { pad.current.layout.footer.text = v })

// 从任务包初始化表单
function syncFromPad() {
  headTitle.value = String(pad.current.layout.header.title ?? '')
  footerText.value = String(pad.current.layout.footer.text ?? '')
}
syncFromPad()

/* ---------- 预览数据 ---------- */
interface PreItem { kind: KbKind; chap: string; id: string; content: string; solution: string; imgPath: string }
const preItems = computed<PreItem[]>(() => {
  const out: PreItem[] = []
  for (const item of pad.current.items) {
    const chap = kb.book(item.kb as KbKind)?.chapters.find((c) => c.name === item.chap)
    if (!chap) continue
    for (const id of item.ids) {
      const r = chap.rows.find((x) => x.id === id)
      if (r) out.push({ kind: item.kb as KbKind, chap: item.chap, id, content: r.content, solution: r.solution, imgPath: r.img_path })
    }
  }
  return out
})

const perPage = computed(() => pad.current.layout.per_page)
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

/* ---------- 任务包清单（多份作业纸管理，D19 反馈第 3 项） ---------- */
interface PadMeta { id: string; term: string; cls: string; items: number; questions: number; orientation: string; perPage: number; json: string }
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
        json: s.json,
      }
    } catch {
      return { id: s.id, term: '?', cls: '?', items: 0, questions: 0, orientation: '?', perPage: 0, json: s.json }
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
      '# 任务包清单导出（assignment-assistant · 作业纸设计）',
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

/** 新建空任务包（克隆当前版式/叶眉页脚/水印配置可选） */
function newTaskpadClone(cloneStyle: boolean) {
  pad.newPad(cloneStyle)
  syncFromPad()
  selectedIds.value = []
  status.value = cloneStyle
    ? '已新建空任务包（克隆了当前版式/页眉页脚/水印配置）。'
    : '已新建空任务包（默认版式）。'
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
import { WATERMARK_POS_LABELS, type WatermarkItem } from '../lib/taskpad'

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
      const item: WatermarkItem = {
        image: `assets/watermark/${f.name}`, // file 相对路径 hint（engine assets/watermark/）
        pos: 'rb',
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
      <h2>作业纸设计 <small style="font-weight:400;color:var(--c-muted)">复用题库数据 → 所见即所得预览 → 生成任务包</small></h2>
      <p class="hint">数据来自「题库编辑器」载入的 xlsx（或示例数据）。任务包 JSON 交给 engine： assist sheet make --task &lt;file&gt; 即可出打印级 PDF（D1 CLI 超集）。</p>
      <div class="notice" v-if="!kb.hasData">题库为空：请先到「题库编辑器」载入 xlsx 或示例数据，再回来选题。</div>
      <p>
        <button class="btn" @click="newTaskpadClone(false)">新建任务包</button>
        <button class="btn" style="margin-left:8px" @click="newTaskpadClone(true)" title="新建空任务包，克隆当前版式/页眉页脚/水印配置">新建（克隆当前版式）</button>
        <label class="btn as-label btn-file" style="margin-left:8px" for="pad-file">导入任务包 JSON…</label>
        <input type="file" accept=".json,application/json" hidden id="pad-file" @change="importTaskpadFile" />
      </p>
      <p class="hint" v-if="status">{{ status }}</p>
    </div>

    <div style="display:flex; gap:16px; align-items:flex-start; flex-wrap:wrap">
      <div class="card" style="flex:0 0 400px; min-width:340px">
        <h2>① 选题（kind / 章 / 题）</h2>
        <p>
          <label class="field">kind：
            <select v-model="selKind">
              <option v-for="k in KB_KINDS" :key="k" :value="k">{{ KB_KIND_LABELS[k] }}</option>
            </select>
          </label>
          <label class="field">章：
            <select v-model="selChap">
              <option v-for="c in kb.book(selKind).chapters" :key="c.name" :value="c.name">{{ c.name }}</option>
            </select>
          </label>
        </p>
        <p>
          <label class="field">搜索：<input type="text" v-model="rowFilter" style="width:130px" /></label>
          <label class="field">分层标签 tag：<select v-model="itemTag" style="width:170px"><option value="">（无）</option><option v-for="tg in STUDENT_TAGS" :key="tg" :value="tg">{{ STUDENT_TAG_LABELS[tg] }}</option></select></label>
        </p>
        <div v-if="chapRows.length" style="max-height:260px; overflow:auto; border:1px solid var(--c-border); border-radius:8px; padding:6px">
          <label v-for="r in chapRows" :key="r.id" style="display:block; font-size:13px; padding:2px 0">
            <input type="checkbox" :checked="selectedIds.includes(r.id)" @change="toggleId(r.id)" />
            <b>{{ r.id }}</b>：{{ r.content.slice(0, 60) }}{{ r.content.length > 60 ? '…' : '' }}
          </label>
        </div>
        <p class="hint" v-else>该 kind/章暂无题目（或题库为空）。</p>
        <p>
          <button class="btn primary" :disabled="!selectedIds.length" @click="addSelection">加入任务包（{{ selectedIds.length }}）</button>
        </p>

        <h3>② 已选组（items）</h3>
        <ol style="font-size:13px; padding-left:18px; margin:4px 0">
          <li v-for="(it, idx) in pad.current.items" :key="idx" style="margin-bottom:4px">
            {{ it.kb }} / {{ it.chap }} / tag={{ it.tag || '—' }} · {{ it.ids.length }} 题
            <button class="btn small" style="margin-left:6px" @click="pad.removeItem(idx)">移除</button>
          </li>
        </ol>
        <p class="hint" v-if="!pad.current.items.length">尚未选择题目。</p>
      </div>

      <div class="card" style="flex:0 0 380px; min-width:320px">
        <h2>③ 版式 / 页眉页脚 / 任务包</h2>
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
        <h3>水印编辑器（items 列表，0..N 图层）</h3>
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
        <h3>任务包清单（多份作业纸管理）</h3>
        <p class="hint">已保存 {{ library.length }} 份。导出全部 = 多份任务包 JSON + 当前题库 xlsx 打包 zip（LAN 预览下请解压后手动放回 workspace 的 tasks/ 与 kb/）。</p>
        <p>
          <button class="btn" :disabled="!library.length || exportingAll" @click="exportAllZip">导出全部（zip：任务包 JSON + 题库 xlsx）</button>
        </p>
        <table class="grid" v-if="library.length" style="font-size:12px">
          <thead>
            <tr><th>id</th><th>学期</th><th>班级</th><th>选题</th><th>题数</th><th>版式</th><th style="width:110px">操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="m in library" :key="m.id">
              <td style="max-width:120px; word-break:break-all">{{ m.id }}</td>
              <td>{{ m.term }}</td>
              <td>{{ m.cls }}</td>
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
        <h3>引擎依赖按钮（D13 条件式置灰）</h3>
        <p>
          <button class="btn" :disabled="engineButtonsDisabled" title="需引擎在线（assist serve）后启用" @click="engineHint()">🖨 打印级 PDF（需引擎）</button>
          <button class="btn" style="margin-left:8px" :disabled="engineButtonsDisabled" title="需引擎在线（assist serve）后启用" @click="engineHint()">⬆ 上传到学习通（需引擎）</button>
        </p>
      </div>

      <div class="card" style="flex:1 1 500px; min-width:420px">
        <h2>④ 预览（A4 比例 · CSS 容器查询横竖感知）</h2>
        <div class="viewer">
          <div
            v-for="(pg, pi) in pages"
            :key="pi"
            class="sheet-page"
            :class="{ landscape: pad.current.layout.orientation === 'landscape' }"
            style="position:relative"
          >
            <template v-if="pad.current.watermark.enabled">
              <span v-if="pageTextOn" class="sheet-watermark">第 {{ pi + 1 }} 页</span>
              <!-- items 图层预览（按九宫格摆位，dataURL/占位） -->
              <div v-for="(it, wi2) in pad.current.watermark.items" :key="'wm' + pi + '-' + wi2" class="wm-preview-anchor" :class="`wm-${it.pos}`">
                <img v-if="settings.wmAssets[it.image.split('/').pop() ?? '']" class="sheet-wm-img" :src="settings.wmAssets[it.image.split('/').pop() ?? '']" :style="{ width: (it.ratio * 100) + '%', opacity: it.alpha }" alt="水印图层" />
                <span v-else class="sheet-wm-placeholder">[水印：{{ it.image }}（{{ WATERMARK_POS_LABELS[it.pos] }}）]</span>
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
            <div class="sheet-body" :class="{ divided: pg.length > 1 }">
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
        <p class="hint">说明：预览为 HTML/CSS 近似；打印级排版（reportlab 版式、真实题图、每生水印）由 engine 按同一任务包生成。多题/页时预览画出实线分隔（横版=栏间竖线、竖版=行间横线），与引擎 PDF 版式一致（D19）。</p>
      </div>
    </div>
  </section>
</template>

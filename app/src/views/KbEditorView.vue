<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { KB_KINDS, KB_KIND_LABELS, type KbKind } from '../lib/kb'
import { useKbStore, getKbDirHandle } from '../stores/kb'
import { detectCapabilities, fsWriteHint, writeFileInDir } from '../lib/fsAccess'
import { useSettingsStore } from '../stores/settings'

const kb = useKbStore()
const settings = useSettingsStore()
const caps = detectCapabilities()
const writeHint = fsWriteHint()

/* ---------- B3/D46-5：题图上传（kb/fig 素材库，水印 wmAssets 同模式） ----------
 * 行内 📷 按钮 → 选图片 → dataURL 存 settings.figAssets[basename]（预览即时显真图）；
 * 同时把 img_path 写入该行（缺省 fig/<文件名>）；已连接 workspace kb 目录时
 * 尽力写回 <dir>/kb/fig/<文件名>（引擎 CLI 通道 base64 内嵌即可用真图）。 */
async function uploadFig(row: { id: string; content: string; img_path: string; page: string; related: string; type: string; solution: string; note: string }) {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = 'image/*'
  const file = await new Promise<File | null>((res) => {
    input.onchange = () => res(input.files?.[0] ?? null)
    input.click()
  })
  if (!file) return
  const reader = new FileReader()
  const dataUrl = await new Promise<string>((res) => { reader.onload = () => res(String(reader.result ?? '')); reader.readAsDataURL(file) })
  if (!dataUrl.startsWith('data:image')) { status.value = '不是有效的图片文件。'; return }
  settings.persistFigAsset(file.name, dataUrl)
  if (!row.img_path) row.img_path = `fig/${file.name}`
  kb.touch(); kb.persist()
  // 尽力写回 workspace（FSA 可用时）；失败不影响浏览器内预览
  let wrote = ''
  const dir = getKbDirHandle()
  if (dir) {
    try {
      await writeFileInDir(dir, `kb/fig/${file.name}`, dataUrlToBlob(dataUrl))
      wrote = '｜已写回 kb/fig/' + file.name + '（引擎 CLI 出图可用）'
    } catch { wrote = '｜⚠ 写回 kb/fig/ 失败（仅本浏览器预览生效）' }
  } else {
    wrote = '｜未连接 kb 目录：图片仅存本浏览器预览；教师可手动把图放到 workspace 的 kb/fig/ 后由引擎内嵌'
  }
  status.value = `题图 ${file.name} 已入库（img_path=${row?.img_path || '（该行原有路径保留）'}）${wrote}`
}

function dataUrlToBlob(dataUrl: string): Blob {
  const m = /^data:([^;,]+);base64,(.+)$/s.exec(dataUrl)
  if (!m) return new Blob([])
  const bin = atob(m[2])
  const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0))
  return new Blob([bytes], { type: m[1] })
}

function figThumb(imgPath: string): string {
  if (!imgPath) return ''
  const base = imgPath.split('/').pop() ?? imgPath
  return settings.figAssets[base] ?? ''
}

const activeKind = ref<KbKind>('problems')
const activeChap = ref('')
const filter = ref('')
const status = ref('')

onMounted(() => {
  // B4：提前探测引擎在线状态，保证第一次「保存」就有机会走样式保留写回。
  void settings.pingEngine()
  if (kb.restorePersisted()) {
    pickChapter(true)
  }
})

function pickChapter(keepCurrent = false) {
  const chapters = kb.book(activeKind.value).chapters
  if (chapters.length === 0) { activeChap.value = ''; return }
  const keep = keepCurrent && chapters.some((c) => c.name === activeChap.value)
  activeChap.value = keep ? activeChap.value : chapters[0].name
}

function switchKind() {
  pickChapter()
}

const visibleRows = computed(() => {
  const chap = kb.book(activeKind.value).chapters.find((c) => c.name === activeChap.value)
  if (!chap) return []
  const f = filter.value.trim()
  if (!f) return chap.rows
  return chap.rows.filter(
    (r) => Object.values(r).map(String).some((v) => v.toLowerCase().includes(f.toLowerCase())),
  )
})

function selectXlsx(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  void kb.loadXlsxFile(file).then((r) => {
    status.value = r.message
    activeKind.value = kb.book(activeKind.value).chapters.length ? activeKind.value : KB_KINDS[0]
    pickChapter()
  })
}

function connectWorkspace() {
  void kb.connectWorkspaceDir().then((ok) => {
    if (ok) {
      const h = getKbDirHandle()
      if (h) status.value = `已连接目录 ${h.name}（保存时写入 <目录>/kb/<kind>.xlsx，docs/05-D3）`
      else status.value = '连接目录成功，但句柄过期，请重试。'
    } else {
      status.value = caps.full ? '已取消选择目录。' : (caps.insecure ? writeHint : caps.browserHint)
    }
  })
}

function saveOrExport(kind: KbKind) {
  void kb.saveKind(kind).then((msg) => {
    status.value = msg
  })
}

function loadDemoData() {
  kb.loadDemo()
  pickChapter()
  status.value = '已载入合成示例数据（app/src/demo/ 占位题，非真题）。'
}

function addChapter() {
  const name = window.prompt('新章 sheet 名（如 chap10）')
  if (!name) return
  kb.addChapter(activeKind.value, name.replace(/[[\]:*?/\\]/g, '_').slice(0, 31))
  activeChap.value = name
}
</script>

<template>
  <section>
    <div class="card">
      <h2>题库编辑器 <small style="font-weight:400;color:var(--c-muted)">xlsx = source of truth（docs/05-D3）：浏览器内直接读写，kind 多 sheet=章</small></h2>
      <p class="hint">
        列结构与 engine <code>assist kb</code> 兼容：id / content / img_path / page / related / type / solution / note。
        教师既有 xlsx 可直接读入编辑；写回优先由引擎 <code>POST /kb/write</code> 做样式保留写回（openpyxl 只改 cell.value + 自动快照），引擎离线时回退 File System Access API 原地保存或导出文件替换。
      </p>
      <p>
        <label class="btn as-label btn-file" for="kb-file">载入教师 xlsx…</label>
        <input type="file" accept=".xlsx" hidden id="kb-file" @change="selectXlsx" />
        <button class="btn" style="margin-left:8px" @click="loadDemoData">载入示例数据</button>
        <button class="btn" style="margin-left:8px" :disabled="!caps.directoryPicker" @click="connectWorkspace"
          :title="caps.insecure ? writeHint : '需 Chrome/Edge（File System Access API），本机 localhost/https 打开'">
          {{ getKbDirHandle() ? `工作目录：${kb.fsDirName}` : '连接本地题库目录（Chrome/Edge）…' }}
        </button>
      </p>
      <div class="notice" v-if="caps.insecure" style="margin-top:6px">
        当前为局域网预览（http://IP，非安全上下文）：载入/编辑/导出 xlsx 均可用（文件选择方式）；
        "连接本地题库目录 / 原地写回"不可用——请用「导出」下载文件，教师手动放回 workspace 的 kb/。{{ writeHint }}
      </div>
      <div class="notice" v-else-if="!caps.full">{{ caps.browserHint }}</div>
      <p class="hint" v-if="status">{{ status }}</p>
    </div>

    <div class="card">
      <h2>浏览与编辑</h2>
      <p>
        <label class="field">kind：
          <select v-model="activeKind" @change="switchKind">
            <option v-for="k in KB_KINDS" :key="k" :value="k">{{ KB_KIND_LABELS[k] }}</option>
          </select>
        </label>
        <label class="field">章（sheet）：
          <select v-model="activeChap">
            <option v-for="c in kb.book(activeKind).chapters" :key="c.name" :value="c.name">{{ c.name }}（{{ c.rows.length }} 题）</option>
          </select>
        </label>
        <button class="btn small" @click="addChapter">＋新增章</button>
        <button
          class="btn small"
          style="margin-left:6px"
          :disabled="activeChap === ''"
          @click="kb.removeChapter(activeKind, activeChap); pickChapter()"
        >删除本章</button>
        <label class="field" style="margin-left:14px">筛选关键字：<input type="text" v-model="filter" placeholder="id / 题干关键词" /></label>
      </p>

      <div v-if="!kb.hasData" class="notice">题库为空：请「载入教师 xlsx」或点「载入示例数据」先把数据读进内存（数据只在本机浏览器/本地目录，不上传）。</div>

      <table v-else class="grid">
        <thead>
          <tr>
            <th style="width:110px">id</th>
            <th>content</th>
            <th style="width:150px">img_path</th>
            <th style="width:50px">page</th>
            <th style="width:90px">related</th>
            <th style="width:70px">type</th>
            <th>solution</th>
            <th style="width:110px">note</th>
            <th style="width:40px"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(r, idx) in visibleRows" :key="r.id + idx">
            <td v-for="col in (['id','content','img_path','page','related','type','solution','note'] as const)" :key="col"
                :class="col === 'content' ? 'cell-content' : ''">
              <template v-if="col === 'img_path'">
                <div style="display:flex; align-items:center; gap:4px">
                  <input v-model="r.img_path" @change="kb.touch(); kb.persist()" placeholder="fig/xxx.png" style="min-width:70px" />
                  <img v-if="figThumb(r.img_path)" :src="figThumb(r.img_path)" alt="题图缩略"
                    style="height:26px; max-width:60px; object-fit:contain; border:1px solid var(--c-border); border-radius:4px"
                    title="本浏览器素材库命中（B3/D46-5）：预览/打印显示此真图" />
                  <button class="btn small" title="B3/D46-5：上传题图→本浏览器素材库即时预览；已连 kb 目录时写回 kb/fig/（引擎通道 base64 内嵌）"
                    @click="uploadFig(r)">📷</button>
                </div>
              </template>
              <input v-else
                v-model="r[col]"
                @change="kb.touch(); kb.persist()"
              />
            </td>
            <td>
              <button class="btn small" title="删除此题" @click="kb.removeRow(activeKind, activeChap, kb.book(activeKind).chapters.find((c) => c.name === activeChap)!.rows.indexOf(r)); kb.persist()">✕</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p style="margin-top:10px" v-if="activeChap">
        <button class="btn" @click="kb.addRow(activeKind, activeChap); kb.persist()">＋新增一行（题）</button>
        <button class="btn primary" style="margin-left:10px" @click="saveOrExport(activeKind)"
          :title="getKbDirHandle() ? `原地写回 ${kb.fsDirName}/kb/${activeKind}.xlsx` : (caps.insecure ? 'LAN 预览下下载文件，教师手动放回 workspace 的 kb/；原地写回需本机 localhost/https 打开' : '导出 xlsx 文件（可用其替换本地文件）')">
          {{ getKbDirHandle() ? `写回 ${kb.fsDirName}/kb/${activeKind}.xlsx` : (caps.insecure ? `下载 ${activeKind}.xlsx（手动放回 workspace）` : `导出 ${activeKind}.xlsx`) }}
        </button>
        <button class="btn" style="margin-left:8px" @click="kb.downloadKind(activeKind, '.copy')">导出副本（另存）</button>
      </p>
      <p class="hint" v-if="caps.insecure">LAN 预览（非安全上下文）提示：写回按钮已改为"下载文件（教师手动放回 workspace）"；原地写回需本机用 localhost / https 打开。</p>
      <p class="hint">说明：纯浏览不需要引擎；以上操作都在浏览器内完成。</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { KB_KINDS, KB_KIND_LABELS, type KbKind } from '../lib/kb'
import { useKbStore, getKbDirHandle } from '../stores/kb'
import { detectCapabilities } from '../lib/fsAccess'

const kb = useKbStore()
const caps = detectCapabilities()

const activeKind = ref<KbKind>('problems')
const activeChap = ref('')
const filter = ref('')
const status = ref('')

onMounted(() => {
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
      status.value = caps.full ? '已取消选择目录。' : caps.browserHint
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
        教师既有 xlsx 可直接读入编辑；写回优先用 File System Access API 原地保存（Chrome/Edge），否则导出文件替换。
      </p>
      <p>
        <label class="btn as-label btn-file" for="kb-file">载入教师 xlsx…</label>
        <input type="file" accept=".xlsx" hidden id="kb-file" @change="selectXlsx" />
        <button class="btn" style="margin-left:8px" @click="loadDemoData">载入示例数据</button>
        <button class="btn" style="margin-left:8px" :disabled="!caps.directoryPicker" @click="connectWorkspace">
          {{ getKbDirHandle() ? `工作目录：${kb.fsDirName}` : '连接本地题库目录（Chrome/Edge）…' }}
        </button>
      </p>
      <div class="notice" v-if="!caps.full">{{ caps.browserHint }}</div>
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
              <input
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
        <button class="btn primary" style="margin-left:10px" @click="saveOrExport(activeKind)">
          {{ getKbDirHandle() ? `写回 ${kb.fsDirName}/kb/${activeKind}.xlsx` : `导出 ${activeKind}.xlsx` }}
        </button>
        <button class="btn" style="margin-left:8px" @click="kb.downloadKind(activeKind, '.copy')">导出副本（另存）</button>
      </p>
      <p class="hint">说明：纯浏览不需要引擎；以上操作都在浏览器内完成。</p>
    </div>
  </section>
</template>

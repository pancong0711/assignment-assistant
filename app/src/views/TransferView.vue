<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { KB_KINDS, type KbKind } from '../lib/kb'
import { useKbStore, setKbDirHandle, getKbDirHandle } from '../stores/kb'
import { useTaskpadStore } from '../stores/taskpad'
import {
  buildWorkspaceZip, readWorkspaceZip, type ZipEntry,
} from '../lib/workspaceZip'
import {
  detectCapabilities, pickDirectory, writeFileInDir,
  ensurePermission, pickReadFile, downloadBlob, fsWriteHint,
} from '../lib/fsAccess'

const kb = useKbStore()
const pad = useTaskpadStore()
const caps = detectCapabilities()
const writeHint = fsWriteHint()

const status = ref('')
const busy = ref(false)
const PAD_LS_KEY = 'assignment-assistant.taskpads.v1'

onMounted(() => {
  if (!kb.hasData) kb.restorePersisted()
})

/* ---------- 导出 zip ---------- */
async function exportZip() {
  busy.value = true
  try {
    const bin = kb.exportBinaries()
    const taskpads = pad.saved.map((s) => ({ name: `${s.id}.taskpad.json`, json: s.json }))
    // fig/：占位 README 说明目录用途（教师真实题图导出时由目录连接选择性补充）
    const figReadme = new TextEncoder().encode(
      'kb/fig/ 存放题库 img_path 引用的题图文件。\n'
      + '浏览器端仅能打包在页面上传的图片；连接本地目录后建议直接在文件系统内同步。\n'
      + '（assignment-assistant 导出白名单见 docs/05-D14）\n',
    )
    const blob = await buildWorkspaceZip({
      kbXlsx: bin,
      taskpads,
      figFiles: [{ path: 'README.txt', data: figReadme }],
      meta: {
        workspace: kb.fsDirName || '（未连接本地目录，导出的是浏览器内存数据）',
        kb_kinds: Object.keys(bin),
        excludes: ['.runtime/', 'kb/.history/', 'settings.local.json'],
      },
    })
    const name = `assignment-assistant-export-${new Date().toISOString().slice(0, 10)}.zip`
    downloadBlob(blob, name)
    status.value = `已导出 ${name}：题库 xlsx ×${Object.keys(bin).length} + 任务包 ×${taskpads.length} + fig/README。zip 永不包含 .runtime/（docs/05-D14）。`
  } finally {
    busy.value = false
  }
}

/* ---------- 导入 zip（恢复到本地目录 / 内存） ---------- */
async function importZip() {
  const file = await pickReadFile('.zip,application/zip')
  if (!file) return
  busy.value = true
  try {
    const entries: ZipEntry[] = await readWorkspaceZip(file)
    if (!entries.length) {
      status.value = 'zip 内没有白名单内容（.runtime/ 等一律拒绝）。'
      return
    }
    let books = 0
    let pads = 0
    let skipped = 0
    // 1) 内存恢复：题库 xlsx → kb store；任务包 → 任务包清单
    for (const e of entries) {
      if (e.path.startsWith('kb/') && e.path.endsWith('.xlsx')) {
        const stem = e.path.replace(/^kb\//, '').replace(/\.xlsx$/, '') as KbKind
        if ((KB_KINDS as readonly string[]).includes(stem)) {
          const buf = e.data.slice().buffer as ArrayBuffer
          await kb.loadXlsxData(buf, stem, 'zip')
          books++
        } else skipped++
      } else if (e.path.startsWith('tasks/') && e.path.endsWith('.taskpad.json')) {
        const json = new TextDecoder().decode(e.data)
        try {
          const obj = JSON.parse(json) as { id?: string }
          if (obj.id && !pad.saved.some((s) => s.id === obj.id)) {
            pad.saved.push({ id: obj.id, json })
            pads++
          }
        } catch { skipped++ }
      } else skipped++
    }
    localStorage.setItem(PAD_LS_KEY, JSON.stringify(pad.saved))
    kb.persist()
    // 2) 目录写回（Chrome/Edge 可选；降级则止步于内存）
    if (caps.directoryPicker) {
      const dir = getKbDirHandle() ?? (await pickDirectory())
      if (!dir) {
        status.value = `已恢复到浏览器内存：题库 ×${books}、任务包 ×${pads}；跳过目录写回（未选择目录）。忽略条目 ×${skipped}。`
        return
      }
      if (!(await ensurePermission(dir, 'readwrite'))) {
        status.value = '目录写入权限未授予；数据仍在浏览器内存中可用。'
        return
      }
      if (dir.name !== kb.fsDirName) {
        setKbDirHandle(dir)
        kb.fsDirName = dir.name
      }
      for (const e of entries) {
        // 白名单路径直接落盘（.runtime/.history 已在上游过滤）
        await writeFileInDir(dir, e.path, e.data.slice().buffer as ArrayBuffer)
      }
      status.value = `已写回 ${dir.name}/（kb/、tasks/、kb/fig/）：题库 xlsx ×${books}、任务包 ×${pads}；忽略条目 ×${skipped}。.runtime/ 永不写入。`
    } else {
      status.value = `已恢复到浏览器内存（降级模式）：题库 ×${books}、任务包 ×${pads}；忽略条目 ×${skipped}。${caps.browserHint}${caps.insecure ? writeHint : ''}`
    }
  } catch (e) {
    status.value = `zip 导入失败：${(e as Error).message}`
  } finally {
    busy.value = false
  }
}

async function connectDir() {
  const ok = await kb.connectWorkspaceDir()
  status.value = ok
    ? `已连接 ${kb.fsDirName}（导出 zip 将附 workspace 名；保存题库写 <目录>/kb/<kind>.xlsx）`
    : caps.full ? '已取消连接。' : (caps.insecure ? writeHint : caps.browserHint)
}
</script>

<template>
  <section>
    <div class="card">
      <h2>导入 / 导出 zip <small style="font-weight:400;color:var(--c-muted)">白名单：kb 题库 xlsx + fig 题图 + 任务包 JSON；.runtime/ 永不打包（docs/05-D14）</small></h2>
      <p class="hint">
        包结构：<code>kb/&lt;kind&gt;.xlsx</code> × N + <code>kb/fig/</code> +
        <code>tasks/&lt;id&gt;.taskpad.json</code> + <code>manifest.json</code>。
        导入 zip 会恢复题库与任务包到内存，Chrome/Edge 下同时写回所选本地目录。
      </p>
      <p>
        <button class="btn primary" :disabled="busy || !kb.hasData" @click="exportZip">导出 zip（下载）</button>
        <button class="btn" style="margin-left:8px" :disabled="busy" @click="importZip">导入 zip（恢复数据…）</button>
        <button class="btn" style="margin-left:8px" :disabled="!caps.full" @click="connectDir"
          :title="caps.insecure ? writeHint : '需 Chrome/Edge（File System Access API），本机 localhost/https 打开'">连接本地 workspace 目录</button>
      </p>
      <div class="notice info" v-if="caps.insecure">当前为局域网预览（http://IP，非安全上下文）：导出 zip / 导入 zip（恢复到内存）均可用；连接本地目录与写回需本机 localhost / https 打开。{{ writeHint }}</div>
      <div class="notice" v-else-if="!caps.full">{{ caps.browserHint }} 导出为浏览器下载；导入恢复到浏览器内存。</div>
      <div class="notice" v-else-if="!kb.fsDirName">尚未连接本地目录：导入 zip 时会再让您选择目标目录。</div>
      <p class="hint" v-if="status">{{ status }}</p>
    </div>

    <div class="card">
      <h3>zip 白名单规则（D14）</h3>
      <ul style="font-size:13px; line-height:1.9">
        <li>包含：kb/*.xlsx（source of truth 题库）、kb/fig/（题图；当前示例仅 README 占位）、tasks/*.taskpad.json、manifest.json。</li>
        <li>绝不包含：<code>.runtime/</code>（venv / uv 缓存 / Playwright 内核）、<code>kb/.history/</code>、settings.local.json / apikey 等敏感文件；导入端同样按白名单过滤（含 zip-slip / 路径穿越拦截）。</li>
        <li>真实教师数据只存在本地，导出 zip 请自行保管。</li>
      </ul>
    </div>
  </section>
</template>

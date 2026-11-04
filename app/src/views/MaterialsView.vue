<script setup lang="ts">
/** D131：课堂资料页（只读）。
 *
 *  设计取舍（docs/79 §10.4）：**抽取与确认刻意留在 CLI**——
 *  确认动作决定 `summary` 批阅的依据，必须教师亲自执行，
 *  不让 PWA（进而让 AI/脚本）静默改生效清单。本页只做"看清现状"。
 */
import { computed, onMounted, ref } from 'vue'
import { useSettingsStore } from '../stores/settings'
import {
  MATERIALS_UPLOAD_EXTS, fetchMaterialsFiles, fetchMaterialsKnowledge,
  fetchMaterialsList, removeMaterialsFile, uploadMaterialsFiles,
  type MaterialsChap, type MaterialsFile,
} from '../lib/engineClient'

const settings = useSettingsStore()
const loading = ref(false)
const chaps = ref<MaterialsChap[]>([])
const root = ref('')
const msg = ref('')
const active = ref<string>('')
const knowTerms = ref<string[]>([])
const knowMd = ref('')

/* D134-T3e：上传与文件管理（`_source/` 是教师原件，同名不覆盖；移除只进回收站） */
const files = ref<MaterialsFile[]>([])
const showTrash = ref(false)
const uploading = ref(false)
const fileMsg = ref('')
const pendingRemove = ref<MaterialsFile | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

const cur = computed(() => chaps.value.find((c) => c.chap === active.value) || null)

async function refresh() {
  loading.value = true
  msg.value = ''
  try {
    const r = await fetchMaterialsList(settings.engineUrl, settings.engineToken)
    if (!r?.ok) { msg.value = `读取失败：${r?.error || '未知错误'}`; return }
    chaps.value = r.chaps || []
    root.value = r.root || ''
    if (!active.value && chaps.value.length) active.value = chaps.value[0]!.chap
    if (active.value) await showKnowledge(active.value)
  } catch (e) {
    msg.value = `读取失败：${String((e as Error).message || e)}（引擎是否在线？）`
  } finally { loading.value = false }
}

async function showKnowledge(chap: string) {
  active.value = chap
  try {
    const r = await fetchMaterialsKnowledge(settings.engineUrl, settings.engineToken, chap)
    knowTerms.value = r?.terms || []
    knowMd.value = r?.markdown || ''
  } catch {
    knowTerms.value = []
    knowMd.value = ''
  }
  await loadFiles()
}

async function loadFiles() {
  if (!active.value) return
  try {
    const r = await fetchMaterialsFiles(settings.engineUrl, settings.engineToken,
                                        active.value, showTrash.value)
    files.value = r?.files || []
  } catch {
    files.value = []
  }
}

function pickFiles() { fileInput.value?.click() }

function readAsBase64(f: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const fr = new FileReader()
    fr.onerror = () => reject(new Error('读取文件失败'))
    fr.onload = () => {
      const s = String(fr.result || '')
      resolve(s.includes(',') ? s.slice(s.indexOf(',') + 1) : s)
    }
    fr.readAsDataURL(f)
  })
}

async function onFilesPicked(ev: Event) {
  const input = ev.target as HTMLInputElement
  const list = Array.from(input.files || [])
  input.value = ''
  if (!list.length || !active.value) return
  uploading.value = true
  fileMsg.value = ''
  try {
    const items: { name: string; data_b64: string }[] = []
    const rejected: string[] = []
    for (const f of list) {
      const ext = f.name.slice(f.name.lastIndexOf('.')).toLowerCase()
      if (!MATERIALS_UPLOAD_EXTS.includes(ext)) { rejected.push(f.name); continue }
      items.push({ name: f.name, data_b64: await readAsBase64(f) })
    }
    let okN = 0
    let renamed: string[] = []
    if (items.length) {
      const r = await uploadMaterialsFiles(settings.engineUrl, settings.engineToken,
                                           active.value, items)
      if (!r?.ok) { fileMsg.value = `上传失败：${r?.error || '未知错误'}`; return }
      okN = (r.saved || []).length
      renamed = (r.saved || []).filter((x: any) => x.renamed).map((x: any) => x.name)
      const skipped = (r.skipped || []).map((x: any) => `${x.name}（${x.reason}）`)
      fileMsg.value = `已上传 ${okN} 个`
        + (renamed.length ? `；同名已自动改名：${renamed.join('、')}` : '')
        + (rejected.length ? `；已拒绝（扩展名不允许）：${rejected.join('、')}` : '')
        + (skipped.length ? `；跳过：${skipped.join('、')}` : '')
    } else {
      fileMsg.value = `已拒绝（扩展名不允许）：${rejected.join('、')}`
    }
    await refresh()
  } catch (e) {
    fileMsg.value = `上传失败：${String((e as Error).message || e)}`
  } finally {
    uploading.value = false
  }
}

function askRemove(f: MaterialsFile) { pendingRemove.value = f }

async function confirmRemove() {
  const f = pendingRemove.value
  pendingRemove.value = null
  if (!f || !active.value) return
  try {
    // 引擎侧 `materials remove --file` 期望的是**相对 `_source/`** 的名字，
    // 而列表里的 `file` 是相对章节目录的（`_source/plan.md`）→ 这里去掉前缀。
    const rel = f.file.startsWith('_source/') ? f.file.slice('_source/'.length) : f.file
    const r = await removeMaterialsFile(settings.engineUrl, settings.engineToken,
                                        active.value, rel, 'teacher:pwa')
    if (r?.ok) {
      fileMsg.value = `已移入回收站：${f.name}（未删除，可在 _source/_trash/ 找回）`
    } else {
      fileMsg.value = `移除失败：${r?.error || '未知错误'}`
    }
    await loadFiles()
  } catch (e) {
    fileMsg.value = `移除失败：${String((e as Error).message || e)}`
  }
}

function fmtBytes(n: number): string {
  if (!n) return '0'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

/** 章节状态标签：让教师一眼看出"卡在哪一步"。 */
function stateOf(c: MaterialsChap): { text: string; color: string } {
  if (c.hasConfirmed) return { text: '✅ 已生效', color: '#14532d' }
  if (c.hasAiSuggest) return { text: '待确认', color: '#b45309' }
  if (c.extracted > 0) return { text: '已抽取', color: '#1d4ed8' }
  if (c.sources > 0) return { text: '待抽取', color: '#6b7280' }
  return { text: '空章节', color: '#9ca3af' }
}

/** 该章节的下一步该做什么（把 CLI 命令直接给教师，可复制）。 */
function nextStep(c: MaterialsChap): string {
  if (!c.sources) return `把 PPT/PDF 放进 ${root.value}/${c.chap}/_source/`
  if (!c.extracted) return `assist materials extract --chap ${c.chap}`
  if (!c.hasAiSuggest) return `assist materials suggest --chap ${c.chap}`
  if (!c.hasConfirmed) return `assist materials confirm --chap ${c.chap}`
  return '已完成：summary 批阅会以此为依据'
}

onMounted(refresh)
defineExpose({ refresh })
</script>

<template>
  <div class="wrap">
    <h2 style="margin:0 0 6px">课堂资料（章节知识点清单）</h2>
    <p class="hint" style="margin-top:0">
      `summary` 类作业的批阅依据。资料放在
      <code>{{ root || '<workspace>/materials' }}/&lt;章节&gt;/_source/</code>，
      用 CLI 抽取与确认（本页只读，避免误改生效清单）。
    </p>

    <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin:8px 0">
      <button class="btn" :disabled="loading" @click="refresh">刷新</button>
      <span v-if="msg" class="hint" style="margin:0">{{ msg }}</span>
    </div>

    <p v-if="!loading && !chaps.length" class="hint">
      还没有任何课堂资料。在 workspace 下建 <code>materials/&lt;章节&gt;/_source/</code> 并放入
      PPT / PDF / 图片后点「刷新」。
    </p>

    <div v-else class="grid">
      <table class="tbl">
        <thead>
          <tr><th>章节</th><th>原件</th><th>已抽取</th><th>字数</th><th>状态</th></tr>
        </thead>
        <tbody>
          <tr v-for="c in chaps" :key="c.chap"
              :class="{ on: c.chap === active }" @click="showKnowledge(c.chap)">
            <td><b>{{ c.chap }}</b></td>
            <td class="c">{{ c.sources }}</td>
            <td class="c">{{ c.extracted }}</td>
            <td class="c">{{ c.chars }}</td>
            <td class="c"><b :style="{ color: stateOf(c).color }">{{ stateOf(c).text }}</b></td>
          </tr>
        </tbody>
      </table>

      <div v-if="cur" class="detail">
        <!-- D134-T3e：上传与文件管理（同名不覆盖；移除只进回收站） -->
        <h4 style="margin:4px 0">原件（`_source/`）</h4>
        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin:6px 0">
          <button class="btn" :disabled="uploading" @click="pickFiles">
            {{ uploading ? '上传中…' : '⬆️ 上传附件' }}
          </button>
          <input ref="fileInput" type="file" multiple style="display:none"
                 :accept="MATERIALS_UPLOAD_EXTS.join(',')" @change="onFilesPicked" />
          <label class="hint" style="display:flex; gap:4px; align-items:center; margin:0">
            <input v-model="showTrash" type="checkbox" @change="loadFiles" /> 显示回收站
          </label>
          <span v-if="fileMsg" class="hint" style="margin:0">{{ fileMsg }}</span>
        </div>
        <p v-if="!files.length" class="hint" style="margin:0 0 6px">
          还没有原件。可上传 {{ MATERIALS_UPLOAD_EXTS.join(' / ') }}（单个 ≤20MB）。
        </p>
        <table v-else class="tbl" style="margin-bottom:8px">
          <thead>
            <tr><th>文件</th><th>大小</th><th>修改时间</th><th>位置</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="f in files" :key="f.dir + '/' + f.file">
              <td>{{ f.name }}</td>
              <td class="c">{{ fmtBytes(f.bytes) }}</td>
              <td class="c">{{ f.mtime }}</td>
              <td class="c">{{ f.dir === '_source' ? '原件' : '回收站' }}</td>
              <td class="c">
                <button v-if="f.dir === '_source'" class="btn sm" @click="askRemove(f)">
                  移除
                </button>
              </td>
            </tr>
          </tbody>
        </table>

        <h4 style="margin:4px 0">下一步</h4>
        <pre class="cmd">{{ nextStep(cur) }}</pre>

        <h4 style="margin:12px 0 4px">生效知识点清单</h4>
        <p v-if="!knowTerms.length" class="hint">
          尚无生效清单（<code>知识点清单.md</code>）。按上面「下一步」执行后这里会显示。
        </p>
        <template v-else>
          <p class="hint" style="margin:0 0 4px">
            共 {{ knowTerms.length }} 个知识点（summary 批阅以此为核对依据）：
          </p>
          <div class="terms">
            <span v-for="t in knowTerms" :key="t" class="term">{{ t }}</span>
          </div>
          <details style="margin-top:6px">
            <summary class="hint" style="cursor:pointer">查看清单原文</summary>
            <pre class="md">{{ knowMd }}</pre>
          </details>
        </template>
      </div>
    </div>

    <!-- L2 二次确认：把动作原样给教师看，默认不执行 -->
    <div v-if="pendingRemove" class="mask">
      <div class="dlg">
        <h3 style="margin:0 0 8px">确认移除原件？</h3>
        <p class="hint" style="margin:0 0 8px">
          将把 <b>{{ pendingRemove.name }}</b> 移入
          <code>_source/_trash/</code>（<b>不删除</b>，可人工找回）。
          此操作需要你确认后才会执行。
        </p>
        <div style="display:flex; gap:8px; justify-content:flex-end">
          <button class="btn" @click="pendingRemove = null">取消</button>
          <button class="btn danger" @click="confirmRemove">我确认移除</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wrap { padding: 12px 14px; }
.grid { display: grid; grid-template-columns: minmax(320px, 1fr) minmax(320px, 1.2fr);
        gap: 14px; align-items: start; }
.tbl { border-collapse: collapse; font-size: 13px; width: 100%; }
.tbl th, .tbl td { border: 1px solid #e5e7eb; padding: 4px 8px; }
.tbl th { background: #f9fafb; }
.tbl td.c { text-align: center; }
.tbl tbody tr { cursor: pointer; }
.tbl tbody tr:hover { background: #f8fafc; }
.tbl tbody tr.on { background: #eff6ff; outline: 1px solid #bfdbfe; }
.detail { border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px 12px; }
.cmd { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px; padding: 6px 8px;
       font-size: 12px; white-space: pre-wrap; margin: 0; }
.terms { display: flex; gap: 6px; flex-wrap: wrap; }
.term { background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 999px;
        padding: 2px 10px; font-size: 12px; }
.md { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px; padding: 8px;
      font-size: 12px; max-height: 320px; overflow: auto; white-space: pre-wrap; }
.hint { color: #6b7280; font-size: 12px; }
.btn.sm { padding: 1px 8px; font-size: 12px; }
.btn.danger { background: #fee2e2; border-color: #fca5a5; color: #991b1b; }
.mask { position: fixed; inset: 0; background: rgba(15, 23, 42, .45);
        display: flex; align-items: center; justify-content: center; z-index: 50; }
.dlg { background: #fff; border-radius: 10px; padding: 16px 18px; width: min(520px, 92vw);
       box-shadow: 0 12px 40px rgba(0, 0, 0, .25); }
</style>

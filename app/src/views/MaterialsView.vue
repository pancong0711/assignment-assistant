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
  confirmMaterials, extractMaterials, fetchMaterialsList, fetchMaterialsSuggestPreview,
  removeMaterialsFile, restoreMaterialsFile, suggestMaterials, uploadMaterialsFiles,
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
/** D138：按主题分组（`{主题: 术语[]}`）；无主题时全部归「其他」 */
const knowTopics = ref<Record<string, string[]>>({})

/* D134-T3e：上传与文件管理（`_source/` 是教师原件，同名不覆盖；移除只进回收站） */
const files = ref<MaterialsFile[]>([])
const showTrash = ref(false)
const uploading = ref(false)
const fileMsg = ref('')
const pendingRemove = ref<MaterialsFile | null>(null)
const pendingRestore = ref<MaterialsFile | null>(null)

/* D137：抽取 / AI 建议 / 确认生效 */
const stepBusy = ref<'extract' | 'suggest' | 'confirm' | ''>('')
const stepMsg = ref('')
const pendingConfirm = ref<{ preview: string; terms: string[]; hasConfirmed: boolean } | null>(null)
const confirmOverwrite = ref(false)

async function doExtract() {
  if (!active.value) return
  stepBusy.value = 'extract'
  stepMsg.value = ''
  try {
    const r = await extractMaterials(settings.engineUrl, settings.engineToken, active.value)
    stepMsg.value = r?.ok ? '✅ 已抽取（可继续「AI 建议知识点」）' : `❌ ${r?.error || '抽取失败'}`
    await refresh()
  } catch (e) {
    stepMsg.value = `抽取失败：${String((e as Error).message || e)}`
  } finally { stepBusy.value = '' }
}

async function doSuggest() {
  if (!active.value) return
  if (!window.confirm('「AI 建议知识点」会**调用模型**（产生费用），继续？')) return
  stepBusy.value = 'suggest'
  stepMsg.value = '正在让 AI 抽取知识点，请稍候…'
  try {
    const r = await suggestMaterials(settings.engineUrl, settings.engineToken, active.value)
    stepMsg.value = r?.ok
      ? '✅ 已生成 AI 建议（尚未生效，请核对后点「确认生效」）'
      : `❌ ${r?.error || '生成失败'}`
    await refresh()
  } catch (e) {
    stepMsg.value = `生成失败：${String((e as Error).message || e)}`
  } finally { stepBusy.value = '' }
}

/** 确认前**先取全文**：必须让教师看清将生效的内容才允许点确认。 */
async function askConfirm() {
  if (!active.value) return
  stepBusy.value = 'confirm'
  stepMsg.value = ''
  try {
    const r = await fetchMaterialsSuggestPreview(settings.engineUrl, settings.engineToken,
                                                 active.value)
    if (!r?.ok || !r.hasAiSuggest) {
      stepMsg.value = `❌ ${r?.error || '没有待确认的 AI 建议（先点「AI 建议知识点」）'}`
      return
    }
    confirmOverwrite.value = false
    pendingConfirm.value = {
      preview: String(r.preview || ''), terms: r.terms || [],
      hasConfirmed: !!r.hasConfirmed,
    }
  } catch (e) {
    stepMsg.value = `读取建议失败：${String((e as Error).message || e)}`
  } finally { stepBusy.value = '' }
}

async function confirmApply() {
  const p = pendingConfirm.value
  pendingConfirm.value = null
  if (!p || !active.value) return
  if (p.hasConfirmed && !confirmOverwrite.value) {
    stepMsg.value = '已有生效清单：如需覆盖请勾选「覆盖已有清单」'
    return
  }
  stepBusy.value = 'confirm'
  try {
    const r = await confirmMaterials(settings.engineUrl, settings.engineToken, active.value,
                                     { confirm: 'teacher:pwa', force: confirmOverwrite.value })
    stepMsg.value = r?.ok
      ? '✅ 已确认生效：summary 批阅将以此为依据'
      : `❌ ${r?.error || '确认失败'}`
    await refresh()
  } catch (e) {
    stepMsg.value = `确认失败：${String((e as Error).message || e)}`
  } finally { stepBusy.value = '' }
}
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
    knowTopics.value = r?.topics || {}
  } catch {
    knowTerms.value = []
    knowMd.value = ''
    knowTopics.value = {}
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

function askRestore(f: MaterialsFile) { pendingRestore.value = f }

async function confirmRestore() {
  const f = pendingRestore.value
  pendingRestore.value = null
  if (!f || !active.value) return
  try {
    // 回收站里的文件名相对 `_trash/`；引擎接受 `a.pdf` 或 `_trash/a.pdf`
    const rel = f.file.replace(/^_source\/_trash\//, '')
    const r = await restoreMaterialsFile(settings.engineUrl, settings.engineToken,
                                         active.value, rel, 'teacher:pwa')
    if (r?.ok) {
      fileMsg.value = `已从回收站恢复：${f.name}`
    } else {
      fileMsg.value = `恢复失败：${r?.error || '未知错误'}`
    }
    await loadFiles()
  } catch (e) {
    fileMsg.value = `恢复失败：${String((e as Error).message || e)}`
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
                <button v-else class="btn sm" @click="askRestore(f)">
                  恢复
                </button>
              </td>
            </tr>
          </tbody>
        </table>

        <h4 style="margin:4px 0">下一步</h4>
        <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin:4px 0">
          <button class="btn" :disabled="stepBusy !== '' || !cur.sources" @click="doExtract">
            {{ stepBusy === 'extract' ? '抽取中…' : '① 抽取' }}
          </button>
          <button class="btn" :disabled="stepBusy !== '' || !cur.extracted" @click="doSuggest">
            {{ stepBusy === 'suggest' ? '生成中…' : '② AI 建议知识点' }}
          </button>
          <button class="btn primary" :disabled="stepBusy !== '' || !cur.hasAiSuggest"
                  @click="askConfirm">
            {{ stepBusy === 'confirm' ? '处理中…' : '③ 确认生效' }}
          </button>
        </div>
        <p v-if="stepMsg" class="hint" style="margin:2px 0">{{ stepMsg }}</p>
        <p class="hint" style="margin:2px 0">
          {{ nextStep(cur) }}
        </p>

        <h4 style="margin:12px 0 4px">生效知识点清单</h4>
        <p v-if="!knowTerms.length" class="hint">
          尚无生效清单（<code>知识点清单.md</code>）。按上面「下一步」执行后这里会显示。
        </p>
        <template v-else>
          <p class="hint" style="margin:0 0 4px">
            共 {{ knowTerms.length }} 个知识点（summary 批阅以此为核对依据）：
          </p>
          <!-- D138：按主题分组（章 → 主题 → 术语）；无主题时归「其他」 -->
          <div v-for="(ts, topic) in knowTopics" :key="topic" style="margin-bottom:6px">
            <p class="hint" style="margin:0 0 2px">
              📚 <b>{{ topic }}</b>（{{ ts.length }}）
            </p>
            <div class="terms">
              <span v-for="t in ts" :key="t" class="term">{{ t }}</span>
            </div>
          </div>
          <details style="margin-top:6px">
            <summary class="hint" style="cursor:pointer">查看清单原文</summary>
            <pre class="md">{{ knowMd }}</pre>
          </details>
        </template>
      </div>
    </div>

    <!-- D137：确认生效 —— **必须展示全文**，教师看清后才点 -->
    <div v-if="pendingConfirm" class="mask">
      <div class="dlg wide">
        <h3 style="margin:0 0 8px">确认让这份清单成为批阅依据？</h3>
        <p class="hint" style="margin:0 0 6px">
          确认后 <code>summary</code> 类作业会**以此清单核对**学生是否讲到这些知识点。
          共 {{ pendingConfirm.terms.length }} 个知识点：
        </p>
        <pre class="md" style="max-height:300px">{{ pendingConfirm.preview }}</pre>
        <label v-if="pendingConfirm.hasConfirmed" style="display:flex; gap:6px;
               align-items:center; font-size:13px; margin:6px 0">
          <input v-model="confirmOverwrite" type="checkbox" />
          覆盖已有生效清单（<code>知识点清单.md</code>）
        </label>
        <div style="display:flex; gap:8px; justify-content:flex-end; margin-top:6px">
          <button class="btn" @click="pendingConfirm = null">取消</button>
          <button class="btn primary" @click="confirmApply">我确认生效</button>
        </div>
      </div>
    </div>

    <!-- L2 二次确认：恢复 -->
    <div v-if="pendingRestore" class="mask">
      <div class="dlg">
        <h3 style="margin:0 0 8px">确认恢复到原件目录？</h3>
        <p class="hint" style="margin:0 0 8px">
          将把 <b>{{ pendingRestore.name }}</b> 从 <code>_source/_trash/</code>
          移回 <code>_source/</code>（同名会自动改名，不覆盖现有文件）。
        </p>
        <div style="display:flex; gap:8px; justify-content:flex-end">
          <button class="btn" @click="pendingRestore = null">取消</button>
          <button class="btn" @click="confirmRestore">我确认恢复</button>
        </div>
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
.dlg.wide { width: min(720px, 94vw); }
.dlg { background: #fff; border-radius: 10px; padding: 16px 18px; width: min(520px, 92vw);
       box-shadow: 0 12px 40px rgba(0, 0, 0, .25); }
</style>

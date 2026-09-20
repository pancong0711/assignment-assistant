<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { KB_KINDS, KB_KIND_LABELS, type KbKind } from '../lib/kb'
import { useKbStore } from '../stores/kb'
import { useTaskpadStore } from '../stores/taskpad'
import { useSettingsStore } from '../stores/settings'
import { downloadData, pickReadFile } from '../lib/fsAccess'
import { serializeTaskpad } from '../lib/taskpad'

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

function newTaskpad() {
  pad.reset()
  syncFromPad()
  selectedIds.value = []
  status.value = '已新建任务包。'
}

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
        <button class="btn" @click="newTaskpad">新建任务包</button>
        <label class="btn as-label btn-file" style="margin-left:8px" for="pad-file">导入任务包 JSON…</label>
        <input type="file" accept=".json,application/json" hidden id="pad-file" @change="importTaskpadFile" />
      </p>
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
          <label class="field">分层标签 tag：<input type="text" v-model="itemTag" placeholder="copy / distinguish / innovation…" style="width:150px" /></label>
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
          <label class="field"><input type="radio" name="orient" :checked="pad.current.layout.orientation === 'landscape'" @change="setOrientation('landscape')" />横版 A4（两半各一题）</label>
          <label class="field">每页题数：
            <select :value="pad.current.layout.per_page" @change="pad.current.layout.per_page = Number(($event.target as HTMLSelectElement).value) as 1 | 2">
              <option :value="1">1</option>
              <option :value="2">2</option>
            </select>
          </label>
        </p>
        <p>
          <label class="field">页眉标题：<input type="text" v-model="headTitle" style="width:180px" @change="pad.current.layout.header.title = headTitle" /></label>
          <label class="field">页脚：<input type="text" v-model="footerText" style="width:150px" @change="pad.current.layout.footer.text = footerText" /></label>
        </p>
        <p>
          <label class="field">水印：
            <input type="checkbox" v-model="pad.current.watermark.enabled" /> 启用（每生唯一标识由 engine 打印时注入）
          </label>
          <label class="field">样式：
            <select v-model="pad.current.watermark.style"><option value="default">default</option><option value="none">none</option></select>
          </label>
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
        <h3>引擎依赖按钮（D13 条件式置灰）</h3>
        <p>
          <button class="btn" :disabled="engineButtonsDisabled" title="需引擎在线（assist serve）后启用" @click="engineHint()">🖨 打印级 PDF（需引擎）</button>
          <button class="btn" style="margin-left:8px" :disabled="engineButtonsDisabled" title="需引擎在线（assist serve）后启用" @click="engineHint()">⬆ 上传到学习通（需引擎）</button>
        </p>
        <p class="hint" v-if="status">{{ status }}</p>
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
            <span v-if="pad.current.watermark.enabled" class="sheet-watermark">示例水印</span>
            <div class="sheet-header">{{ String(pad.current.layout.header.title ?? '') || '作业纸' }}</div>
            <div class="sheet-body">
              <div v-for="(item, fi) in pg" :key="fi" class="sheet-frame">
                <div class="q-id">{{ item.id }}</div>
                <div class="q-content">{{ item.content }}</div>
                <div v-if="item.imgPath" class="q-img">[题图：{{ item.imgPath }}]</div>
                <div class="q-solution">参考答案：{{ item.solution || '（题库 solution 为空）' }}</div>
              </div>
            </div>
            <div class="sheet-footer">
              <span>{{ footerText }}</span>
              <span>{{ pi + 1 }} / {{ pages.length }}</span>
            </div>
          </div>
        </div>
        <p class="hint">说明：预览为 HTML/CSS 近似；打印级排版（reportlab 版式、真实题图、每生水印）由 engine 按同一任务包生成。</p>
      </div>
    </div>
  </section>
</template>

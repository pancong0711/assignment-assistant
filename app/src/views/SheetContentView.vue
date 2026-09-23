<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { KB_KINDS, KB_KIND_LABELS, STUDENT_TAGS, STUDENT_TAG_LABELS, type KbKind } from '../lib/kb'
import { useKbStore } from '../stores/kb'
import { useTaskpadStore } from '../stores/taskpad'
import { useRosterStore } from '../stores/roster'
import { parseTaskpad, missingBoundTags, padInferredTag, resolveBindTag, type PadBinding, type Taskpad } from '../lib/taskpad'
import { batchCommand, batchPaths, buildVariantBatchZip } from '../lib/variantBatch'
import { buildClassOverlayHtml } from '../lib/classOverlay'
import { downloadBlob, downloadData } from '../lib/fsAccess'
import { useSettingsStore } from '../stores/settings'
import {
  stringifySheetHtml, expandPadItems, SYNTHETIC_STUDENTS,
  type SheetHtmlItem, type SheetHtmlStudent, type SheetHtmlPadInput,
} from '../lib/sheetHtml'
import SheetHtmlPreviewModal from '../components/SheetHtmlPreviewModal.vue'

/* ========== S2b 并行备注（VC-3，docs/14 §VC-3；仅新增内容，未改既有逻辑） ==========
 * 本块为「预览整班」overlay 入口（班级与标签页 RosterView 亦有同款卡；这里放
 * 变体编排卡内的入口按钮，因为 tag→任务包绑定状态在本页维护，所见即所选）。
 * 依赖 lib/classOverlay.buildClassOverlayHtml（fallback 静态生成层，纯前端、不依赖引擎）；
 * 父代理 S2a 的 stringifySheetHtml 模板就位后仅需替换该 lib 内部实现（集成点：与并行 S2a 的 sheetHtml.ts（stringifySheetHtml，模板 assignment.html.j2 同构）互不重名——本模块为 VC-3 整班预览 fallback 静态层，不承载 per-pad stringify）。
 * ========================================================================== */
const classPreviewHtml = ref('')
const classPreviewShow = ref(false)
const classPreviewMsg = ref('')
/** 兜底包（--default 语义）：为"名单里有 tag 但无包绑定"的学生指定兼任变体 */
const classPreviewFallbackId = ref('')

/** tag→包映射（与 batch.json mapping 同口径：显式 target_tag / items 唯一 tag） */
const mappingTag = computed(() => {
  const m: Record<string, string> = {}
  for (const r of padRows.value) {
    const t = resolveBindTag({ id: r.id, binding: r.targetTag, items: r.tagItems })
    if (t) m[t] = r.id
  }
  return m
})

const classTextSource = {
  text(kind: string, chap: string, id: string): string {
    return kb.rowText(kind as never, chap, id)
  },
}

function previewWholeClass() {
  if (!roster.students.length) {
    classPreviewMsg.value = '名单为空：先到「班级与标签」导入/生成带 tag 名单。'
    classPreviewShow.value = false
    return
  }
  if (!padRows.value.length) {
    classPreviewMsg.value = '任务包清单为空：先保存任务包（上方清单）再预览。'
    classPreviewShow.value = false
    return
  }
  try {
    classPreviewHtml.value = buildClassOverlayHtml(roster.students, pad.savedJsons(), classTextSource, {
      title: '整班作业纸预览（VC-3）',
      classDir: classDirName.value,
      fallbackPadId: classPreviewFallbackId.value,
    })
    classPreviewMsg.value = `已按当前 tag→包绑定生成整班预览（${roster.students.length} 名学生）：iframe 内滚动查看 / 「下载 HTML」后浏览器打开 → Ctrl/Cmd+P 打印（每生一页、自动分页；空间不足时该页自动断页）。`
    classPreviewShow.value = true
  } catch (e) {
    classPreviewMsg.value = `整班预览生成失败：${(e as Error).message}`
  }
}

function downloadClassOverlay() {
  if (classPreviewHtml.value) {
    downloadData(classPreviewHtml.value, `class-sheet-preview-${new Date().toISOString().slice(0, 10)}.html`, 'text/html')
  }
}
/* ================== /S2b VC-3 整班预览（新增块结束） ================== */

/* ========== S2a 并行备注（VC-2，docs/14 §VC-2；仅新增内容，未改既有逻辑） ==========
 * 清单里任一任务包「预览」→ 同一 HTML 模板（engine/templates/assignment.html.j2 的
 * TS 同构 = lib/sheetHtml.ts stringifySheetHtml）在弹窗 iframe overlay 预览
 * （版式/水印/内容全量，不依赖引擎）；「预览全部」把清单所有任务包连排在同一
 * HTML（多包不分页）。与上方 S2b 整班预览（VC-3，classOverlay fallback 层）
 * 互不占用命名/状态；名单缺省合成 学生A/B（informational）。 */
const settings = useSettingsStore()
const showHtmlOverlay = ref(false)
const overlayHtml = ref('')
const overlayTitle = ref('')

function sheetStudents(): SheetHtmlStudent[] {
  return roster.students.length
    ? roster.students.map((s) => ({ name: s.name, number: s.number, class: s.class, tag: s.tag }))
    : SYNTHETIC_STUDENTS
}

/** 任务包 → 题帧（kb store 取 content/solution/img_path；未命中的题跳过） */
function padItemsOf(p: Taskpad): SheetHtmlItem[] {
  return expandPadItems(p, (kind) => kb.book(kind))
}

function openPreview(pads: SheetHtmlPadInput[], title: string) {
  if (!pads.length) return
  overlayHtml.value = stringifySheetHtml(pads, {
    students: sheetStudents(),
    wmAssets: settings.wmAssets,
  })
  overlayTitle.value = title
  showHtmlOverlay.value = true
}

/** 清单里单个任务包的预览（版式/水印/内容全量；docs/14 §VC-2） */
function previewPad(id: string) {
  const entry = pad.saved.find((s) => s.id === id)
  if (!entry) { status.value = `清单中未找到 ${id}。`; return }
  try {
    const p = parseTaskpad(JSON.parse(entry.json))
    openPreview([{ pad: p, items: padItemsOf(p) }], `任务包预览 · ${id}`)
    status.value = `已打开 ${id} 的浏览器打印版预览（同一 HTML 模板；名单：${roster.students.length ? `${roster.students.length} 人` : '合成 学生A/B'}）。`
  } catch (e) {
    status.value = `任务包 ${id} 预览失败（JSON 损坏）：${(e as Error).message}`
  }
}

/** 全部清单任务包连排预览（多包不分页：不加封面/额外分页，页块仍每生分页） */
function previewAllPads() {
  const sources: SheetHtmlPadInput[] = []
  let bad = 0
  for (const s of pad.saved) {
    try {
      const p = parseTaskpad(JSON.parse(s.json))
      sources.push({ pad: p, items: padItemsOf(p) })
    } catch { bad++ }
  }
  if (!sources.length) { status.value = '清单为空或全部 JSON 损坏：无可预览任务包。'; return }
  openPreview(sources, `全部任务包连排预览 · ${sources.length} 份`)
  status.value = `已连排预览 ${sources.length} 份任务包（多包不分页；@page 方向取第一份${bad ? `；${bad} 份 JSON 损坏已跳过` : ''}）。`
}
/* ================== /S2a VC-2 任务包预览（新增块结束） ================== */

/** 作业纸内容（M-A S1 拆分，docs/05-D25）：一份模板的"题目构成"。
 *  kind×章题选篮（含跨 kind/tag 提示文）→ items 列表编辑 → target_tag 标注；
 *  任务包清单列表与 D23 变体编排绑定面板（原 RosterView「变体编排」卡整体迁入，
 *  绑定 store（taskpad.setSavedTargetTag）不动；RosterView 仅留指向本页的提示链接，
 *  避免同一功能双入口）。整班 batch zip 生成也随编排面板迁到本页（打完 tag 后一步到位）。 */

const kb = useKbStore()
const pad = useTaskpadStore()
const roster = useRosterStore()

const status = ref('')

/* ---------- 选题（kind / 章 / 题） ---------- */
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

/** 当前选篮的 tag 组成（跨 kind/tag 提示用） */
const selCrossKinds = computed(() => {
  const kinds = new Set<string>()
  for (const it of pad.current.items) kinds.add(it.kb)
  return [...kinds]
})
const selCrossTags = computed(() => {
  const tags = new Set<string>()
  for (const it of pad.current.items) if (it.tag) tags.add(it.tag)
  return [...tags]
})
const curInferredTag = computed(() => padInferredTag(pad.current.items, pad.current.target_tag))
const mixedTagWarn = computed(() => !pad.current.target_tag && pad.current.items.length > 0 && !curInferredTag.value)

function addSelection() {
  if (!selectedIds.value.length) return
  pad.addItem({ kb: selKind.value, chap: selChap.value, ids: [...selectedIds.value], tag: itemTag.value })
  status.value = `已加入 ${selectedIds.value.length} 题（${selKind.value}/${selChap.value}${itemTag.value ? ` · tag=${itemTag.value}` : ''}）`
  selectedIds.value = []
}

/* ---------- 当前任务包 target_tag 标注 ---------- */
const targetTagOn = computed({
  get: () => pad.current.target_tag ?? '',
  set: (v: string) => { pad.current.target_tag = v || undefined },
})

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
    status.value = `已载入任务包 ${id}（题目构成可继续编辑；保存会覆盖清单中的同名条目）。`
  } else {
    status.value = `清单中未找到 ${id}。`
  }
}

function removeFromLibrary(id: string) {
  pad.removeFromLibrary(id)
  status.value = `已从清单删除任务包 ${id}（仅删除清单记录，不影响已导出文件）。`
}

/* ---------- D23 变体编排（docs/05-D23 / 12-B3.5）：tag→任务包绑定 + 一键 batch zip ---------- */
/** 绑定下拉选项：STUDENT_TAGS + 名单里出现但不在表内的 tag（容错） */
const tagOptions = computed<string[]>(() => {
  const set = new Set<string>(STUDENT_TAGS)
  for (const t of Object.keys(roster.tagCounts)) set.add(t)
  return [...set]
})

/** 各已保存任务包的绑定明细（target_tag + 有效性推断） */
const padRows = computed(() => pads_savedRows())
function pads_savedRows() {
  return pad.saved.flatMap((s) => {
    try {
      const p = parseTaskpad(JSON.parse(s.json))
      return [{
        id: s.id,
        title: String(p.layout.header.title ?? '') || '—',
        targetTag: p.target_tag ?? '',
        tagItems: p.items,
        items: p.items.length,
        questions: p.items.reduce((n, i) => n + i.ids.length, 0),
        layout: `${p.layout.orientation === 'landscape' ? '横版' : '竖版'}·${p.layout.per_page}题页`,
        inferred: padInferredTag(p.items, p.target_tag),
      }]
    } catch {
      return []
    }
  })
}
const bindings = computed<PadBinding[]>(() =>
  padRows.value.map((r) => ({ id: r.id, binding: r.targetTag, items: r.tagItems })))

/** 名单里有 tag 但没有绑定包 → 黄色提示（可加 --default 兜底 / 回本页补变体） */
const missingTags = computed(() => missingBoundTags(roster.tagCounts, bindings.value))
/** 多个包推向同一 tag 的冲突（引擎会拒绝后进映射） */
const dupTags = computed(() => {
  const seen = new Map<string, number>()
  for (const b of bindings.value) {
    const t = resolveBindTag(b)
    if (t) seen.set(t, (seen.get(t) ?? 0) + 1)
  }
  return [...seen.entries()].filter(([, n]) => n > 1).map(([t]) => t)
})

const classDirName = computed(() => roster.students[0]?.class || 'classA')
const bp = computed(() => batchPaths(classDirName.value))
const batchCmdPreview = computed(() =>
  batchCommand(bp.value.roster, padRows.value.map((r) => bp.value.task(r.id)), bp.value.classDir, missingTags.value))

function setBinding(id: string, ev: Event) {
  const ok = pad.setSavedTargetTag(id, (ev.target as HTMLSelectElement).value)
  status.value = ok ? `已把任务包 ${id} 绑定到目标 tag（target_tag 同步进任务包 JSON）。` : `任务包 ${id} 绑定失败（JSON 损坏）。`
}

const exportingBatch = ref(false)
async function downloadBatchZip() {
  if (!roster.students.length) {
    status.value = '名单为空：先到「班级与标签」导入/生成带 tag 名单，再一键生成 batch 包。'
    return
  }
  if (!padRows.value.length) {
    status.value = '任务包清单为空：先在本页保存任务包（每份可绑 target_tag）。'
    return
  }
  exportingBatch.value = true
  try {
    const { blob, cd, padCount } = await buildVariantBatchZip(roster.students, pad.savedJsons())
    downloadBlob(blob, `batch-package-${new Date().toISOString().slice(0, 10)}.zip`)
    status.value = `已生成整班 batch 交付包（班级 ${cd}）：${padCount} 份任务包 + roster.xlsx + batch.json + README。解压到引擎 workspace 根目录后按 README 执行 assist sheet batch 即可。`
  } catch (e) {
    status.value = `batch 包生成失败：${(e as Error).message}`
  } finally {
    exportingBatch.value = false
  }
}
</script>

<template>
  <section>
    <div class="card">
      <h2>作业纸内容 <small style="font-weight:400;color:var(--c-muted)">一份模板的"题目构成"：kind×章选题 → items → target_tag 标注（docs/05-D25）</small></h2>
      <p class="hint">
        版式（「作业纸版式」页）+ 题目构成（本页）共同生成一个任务包（schema 不变，仅 UI 分屏）。
        数据来自「题库编辑器」载入的 xlsx（或示例数据）。任务包 JSON 交给 engine：
        assist sheet make --task &lt;file&gt; 即可出打印级 PDF（D1 CLI 超集）。
      </p>
      <div class="notice" v-if="!kb.hasData">题库为空：请先到「题库编辑器」载入 xlsx 或示例数据，再回来选题。</div>
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
        <p class="hint" v-if="selCrossKinds.length">
          当前包已含 kind：<code>{{ selCrossKinds.join('、') }}</code><template v-if="selCrossTags.length">；分层 tag：<code>{{ selCrossTags.map((t) => STUDENT_TAG_LABELS[t] ?? t).join('、') }}</code></template>。
          同一份作业纸可跨 kind 混编；分层 tag 用于变体编排（每个 tag 需一份对应任务包）。
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

        <h3>③ 目标 tag 标注（target_tag，docs/05-D23）</h3>
        <p>
          <label class="field" title="D23 变体编排：该任务包面向的学生分层 tag；留空则引擎按 items 的唯一 tag 自动绑定（mixed-tag 包需显式指定）。">
            目标 tag (target_tag)：
            <select v-model="targetTagOn" style="max-width:190px">
              <option value="">（自动：由 items 唯一 tag 推断）</option>
              <option v-for="t in STUDENT_TAGS" :key="t" :value="t">{{ STUDENT_TAG_LABELS[t] }}</option>
            </select>
          </label>
        </p>
        <p class="hint" v-if="curInferredTag">
          引擎 batch 绑定口径（pad_tag）：本包将面向 tag=<code>{{ curInferredTag }}</code>{{ pad.current.target_tag ? '（target_tag 显式绑定）' : '（items 唯一 tag 自动推断）' }}。
        </p>
        <p class="hint" v-else-if="mixedTagWarn">⚠ 本包 items 混合多个 tag 且未显式绑定 target_tag：引擎 <code>sheet batch</code> 将拒收（需上方绑定目标 tag，或 CLI --map）。</p>
        <p class="hint" v-else>尚未选题：选完题（或绑定显式 target_tag）后这里显示引擎绑定的 tag。</p>
      </div>

      <div class="card" style="flex:1 1 500px; min-width:420px">
        <h2>④ 任务包清单（多份作业纸管理）</h2>
        <p class="hint">
          已保存 {{ library.length }} 份。导出/新建在「作业纸版式」页；本页负责题目构成与
          <b>变体编排绑定</b>（每份包绑定一个目标 tag，整班分层生成时引擎按学生 tag 选用对应包）。
        </p>
        <p v-if="library.length">
          <button class="btn" title="VC-2：清单所有任务包连排在同一 HTML overlay（多包不分页；同一模板，不依赖引擎）" @click="previewAllPads">👁 预览全部任务包（连排，同一 HTML 模板）</button>
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
                <button class="btn small" @click="loadFromLibrary(m.id)">载入编辑</button>
                <button class="btn small" style="margin-left:4px" @click="previewPad(m.id)" title="VC-2：该任务包的浏览器打印版预览（同一 HTML 模板 overlay）">预览</button>
                <button class="btn small" style="margin-left:4px" @click="removeFromLibrary(m.id)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p class="hint" v-else>清单为空：到「作业纸版式」页点「仅保存」或「导出任务包 JSON」后出现在这里。</p>

        <h3>变体编排（D23 · 整班分层作业纸，docs/05-D23 / 12-B3.5）</h3>
        <p class="hint">
          每个学生按其 tag 领到<b>不同的任务包</b>变体（同 tag 内题目顺序引擎可轮换防抄袭）。
          下方清单即上方任务包清单；"绑定到 tag" 与包的 <code>target_tag</code> 双向同步
          （引擎 <code>assist sheet batch</code> 按 tag 自动选用对应包）。
          名单/tag 切分在「班级与标签」页完成。
        </p>
        <p class="hint" v-if="Object.keys(roster.tagCounts).length">
          名单 tag 分布（roster.tagCounts，来自「班级与标签」）：<template v-for="(c, t, i) in roster.tagCounts" :key="t"><code>{{ STUDENT_TAG_LABELS[t] ?? t }}</code>×{{ c }}<template v-if="i < Object.keys(roster.tagCounts).length - 1">；</template></template>
        </p>
        <div class="notice" v-if="missingTags.length" style="border-color:#c9a227;color:#7a5c00">
          ⚠ 缺包 tag：<code>{{ missingTags.join('、') }}</code> —— 名单里这些 tag 有学生，但没有任何任务包绑定到它，
          引擎 <code>sheet batch</code> 会跳过这部分人。
          处理：在本页为这些 tag 补建变体任务包（选题时给对应 tag），或临时用 CLI <code>--default &lt;兜底任务包&gt;</code> 为未覆盖学生兜底。
        </div>
        <p class="hint" v-if="dupTags.length">⚠ 同一 tag 被多个任务包绑定（{{ dupTags.join('、') }}）：引擎仅认先到的一份，请去重。</p>
        <table class="grid" v-if="padRows.length" style="font-size:12px">
          <thead>
            <tr><th>id</th><th>标题</th><th>题组/题数</th><th>版式</th><th>目标 tag 推断</th><th style="width:190px">绑定到 tag（target_tag）</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in padRows" :key="r.id">
              <td style="max-width:150px; word-break:break-all">{{ r.id }}</td>
              <td>{{ r.title }}</td>
              <td style="text-align:center">{{ r.items }} 组 / {{ r.questions }} 题</td>
              <td style="white-space:nowrap">{{ r.layout }}</td>
              <td style="white-space:nowrap">
                {{ r.inferred ? (STUDENT_TAG_LABELS[r.inferred] ?? r.inferred) + (r.targetTag ? '（显式）' : '（自动）') : '⚠ 混合 tag，需显式绑定' }}
              </td>
              <td>
                <select :value="r.targetTag" @change="setBinding(r.id, $event)" style="max-width:160px">
                  <option value="">（未绑定：按 items 推断）</option>
                  <option v-for="t in tagOptions" :key="t" :value="t">{{ STUDENT_TAG_LABELS[t] ?? t }}</option>
                </select>
              </td>
            </tr>
          </tbody>
        </table>
        <p class="hint" v-else>任务包清单为空：先在本页保存任务包后回到这里绑定。</p>
        <p>
          <button class="btn primary" :disabled="exportingBatch || !roster.students.length || !padRows.length" @click="downloadBatchZip">📦 一键生成整班 batch 交付包（zip：roster.xlsx + tasks/*.taskpad.json + batch.json + README）</button>
          <button class="btn" style="margin-left:8px" :disabled="!roster.students.length || !padRows.length" @click="previewWholeClass" title="VC-3：按当前 tag→包映射生成整班多页 HTML overlay（纯前端，不依赖引擎；与「班级与标签」页的「预览整班」同款）">👁 预览整班（HTML overlay，不依赖引擎）</button>
        </p>
        <p class="hint" v-if="classPreviewMsg">{{ classPreviewMsg }}</p>
        <p class="hint" v-if="Object.keys(mappingTag).length && roster.students.length">
          兜底变体（--default 语义，预览用）：
          <select v-model="classPreviewFallbackId" style="max-width:220px">
            <option value="">（不兜底：未覆盖 tag 的学生页显示占位说明）</option>
            <option v-for="r in padRows" :key="r.id" :value="r.id">{{ r.id }}（{{ mappingTag[r.id] ?? '未绑定' }}）</option>
          </select>
        </p>
        <p v-if="classPreviewShow && classPreviewHtml">
          <button class="btn small" @click="downloadClassOverlay">⬇ 下载整班预览 HTML（浏览器打开→Ctrl/Cmd+P 打印）</button>
        </p>
        <iframe v-if="classPreviewShow && classPreviewHtml"
          :srcdoc="classPreviewHtml" title="整班作业纸预览（VC-3）"
          sandbox="allow-same-origin"
          style="width:100%; height:560px; border:1px solid var(--c-border); border-radius:8px; background:#fff"></iframe>
        <p class="hint">README 内含整条命令示例（教师本机执行即出整班分层作业纸）：</p>
        <pre class="hint" style="white-space:pre-wrap; font-size:11px; background:var(--c-bg,#f7f7f9); padding:8px; border-radius:6px"><code>{{ batchCmdPreview }}</code></pre>
        <p class="hint">
          zip 目录结构对齐 docs/04 §1（<code>classes/&lt;班级&gt;/roster/roster.xlsx</code>、<code>tasks/&lt;id&gt;.taskpad.json</code>、
          <code>batch.json</code> 仅元数据）。不依赖引擎在线/LLM/学习通；FSA 降级照 D11（浏览器下载，教师手动解压）。
        </p>
      </div>
    </div>

    <SheetHtmlPreviewModal
      v-if="showHtmlOverlay && overlayHtml"
      :html="overlayHtml"
      :title="overlayTitle"
      @close="showHtmlOverlay = false"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { STUDENT_TAGS, STUDENT_TAG_LABELS } from '../lib/kb'
import {
  SCORE_FAMILY_PRESETS, isFixedFamily, scoreFamilyDesc, scoreFamilyLabel,
  sourceScoreMatrix,
  type ScoreFamily,
} from '../lib/roster'
import type { PreviewTable } from '../lib/rosterXlsx'
import { useRosterStore } from '../stores/roster'
import { useTaskpadStore } from '../stores/taskpad'
import { getKbDirHandle } from '../stores/kb'
import { buildBatchManifest, buildClassOverlayHtml } from '../lib/classOverlay'
import { parseTaskpad, padInferredTag } from '../lib/taskpad'
import { downloadData, detectCapabilities, fsWriteHint, pickReadFileFsa } from '../lib/fsAccess'
import { useKbStore } from '../stores/kb'
import PreviewTableCard from '../components/PreviewTableCard.vue'

/** 班级与标签（M5 成绩管理，docs/05-D18；M-A S1 由"班级与成绩"更名，docs/05-D26）：
 *  名单/成绩导入 + 综合得分 + 自动打 tag + 导出。
 *  成绩源格式预设（docs/05-D19）：固定四类（教务点名册/教务期末/学习通作业统计/
 *  学习通章节测验/雨课堂汇总）按列名 family 语义自动定位分数列，无需用户选列；
 *  custom 保留手动选列。纯前端闭环（不依赖学习通/引擎）。
 *  S2b（docs/14 §VC-3/4/5/6、M-C R3.2/3.3/3.5 收口）：
 *  - VC-4/VC-6 导入预览卡（表头+前3行+列映射说明，PreviewTableCard 复用）；
 *  - VC-5 成绩源宽表（行=学生，列=各源分数列，横向滚动）+ 默认勾选/取消勾选
 *    （score excluding，includeInAggregation）+ 按勾选源重算 + 按单列切分（一列即排）；
 *  - VC-3 整班作业纸预览：tag→任务包映射生成自包含多页 HTML overlay（纯前端，
 *    不依赖引擎；lib/classOverlay.ts 为 fallback 静态层，S2a 模板就位后切同一模板交付）。
 *  变体编排（tag→任务包绑定 + 整班 batch zip）在「作业纸内容」页（单入口，D25）。 */

const roster = useRosterStore()
const pad = useTaskpadStore()
const kbStore = useKbStore()
const caps = detectCapabilities()
const status = ref('')
/** 成绩源添加时的格式预设选择（默认 custom = 旧行为） */
const presetFamily = ref<ScoreFamily>('custom')
const presetDesc = computed(() => scoreFamilyDesc(presetFamily.value))
const presetIsFixed = computed(() => isFixedFamily(presetFamily.value))

onMounted(() => {
  if (roster.students.length) roster.touch()
})

function pickXlsx(): Promise<File | null> {
  // LAN（http://IP）/Firefox/Safari 下静默降级为 file input（fsAccess 内部处理）
  return pickReadFileFsa('.xlsx')
}

/* ---------- VC-4/VC-6 导入预览（表头+前 3 行+列映射说明） ---------- */
const rosterPreview = ref<PreviewTable | null>(null)
const rosterPreviewFile = ref('')
const sourcePreview = ref<PreviewTable | null>(null)
const sourcePreviewFile = ref('')

async function importRoster() {
  const file = await pickXlsx()
  if (!file) return
  try {
    const { message, preview } = await roster.loadRosterFile(file)
    status.value = message
    rosterPreview.value = preview
    rosterPreviewFile.value = file.name
  } catch (e) {
    status.value = `名单读入失败：${(e as Error).message}`
    rosterPreview.value = null
  }
}

async function addSource() {
  const file = await pickXlsx()
  if (!file) return
  try {
    const { message, preview } = await roster.addScoreSource(file, presetFamily.value)
    status.value = message
    sourcePreview.value = preview
    sourcePreviewFile.value = file.name
  } catch (e) {
    status.value = `成绩源读入失败：${(e as Error).message}`
    sourcePreview.value = null
  }
}

/** 源内切换格式预设：需要原始 xlsx 重新解析（固定四类按 family 语义重新定位） */
async function reparseSource(idx: number) {
  const file = await pickXlsx()
  if (!file) return
  try {
    const family = roster.sources[idx]?.family ?? 'custom'
    await roster.rescoreWithFamily(idx, file, family)
    status.value = `已按 ${scoreFamilyLabel(family)} 重新解析成绩源「${roster.sources[idx]?.name ?? ''}」。`
  } catch (e) {
    status.value = `成绩源重新解析失败：${(e as Error).message}`
  }
}

function recompute() {
  if (!roster.students.length) {
    status.value = '请先导入/手动建立名单。'
    return
  }
  status.value = roster.recomputeFromChecked()
}

/* ---------- VC-5 成绩源宽表：行=学生，列=各源分数列（横向滚动） ---------- */
/** 宽表行：学生 + 每个源该生的分数（'' = 该源无此生分数） */
interface WideRow { name: string; number: string; cells: string[] }
const scoreSources = computed(() => roster.sources)
const wideHeaders = computed(() => scoreSources.value.map((s, i) => ({
  idx: i,
  label: s.name || s.fileName || `源${i + 1}`,
  title: `${s.fileName} · family=${s.family} · 分数列：${s.scoreColumn} · 权重 ${s.weight} · ${isFixedFamily(s.family) ? '固定格式' : 'custom'}`,
  included: s.includeInAggregation !== false,
  excluded: s.family === 'roster',
})))
const wideRows = computed<WideRow[]>(() => {
  // 列取数：源.scores（family 解析结果）优先，legacy 无 scores 时回退按所选列
  const matrices = scoreSources.value.map((s) => sourceScoreMatrix(s))
  return roster.students.map((stu) => ({
    name: stu.name,
    number: stu.number,
    cells: matrices.map((m) => {
      const v = m[stu.name]
      return typeof v === 'number' && Number.isFinite(v) ? String(v) : ''
    }),
  }))
})
/** 勾选状态摘要（显示在宽表上方） */
const checkedSummary = computed(() => {
  const inc = scoreSources.value.filter((s) => s.includeInAggregation !== false && s.family !== 'roster')
  const exc = scoreSources.value.filter((s) => s.includeInAggregation === false)
  const parts: string[] = []
  if (inc.length) parts.push(`勾选参与综合得分 ${inc.length} 列（${inc.map((s) => s.name).join('、')}）`)
  if (exc.length) parts.push(`已排除 ${exc.length} 列（${exc.map((s) => s.name).join('、')}）`)
  return parts.join('；') || '尚无计分成绩源（roster 接表源不计分）。'
})
/** 多列加权语义提示（宽表下方的操作说明） */
const wideHint = computed(() =>
  `多列加权口径：综合得分 = Σ(勾选源归一化分数 × 源权重 / 勾选源权重和) × 100（源内按该源最大值归一）。`)

/** 单列切分按钮（一列即排） */
function tagBySingleColumn(idx: number) {
  if (!roster.students.length) { status.value = '请先导入/手动建立名单。'; return }
  status.value = roster.tagByColumn(idx)
}

/** 供模板使用的勾选切换（checkbox 直接绑 includeInAggregation） */
function toggleInclude(idx: number, ev: Event) {
  roster.setSourceIncluded(idx, (ev.target as HTMLInputElement).checked)
}

/* ---------- VC-3 整班作业纸预览（HTML overlay，纯前端不依赖引擎） ---------- */
const showClassPreview = ref(false)
const classPreviewHtml = ref('')
const classPreviewMsg = ref('')
const classPreviewManifest = ref('')
const previewingClass = ref(false)

/** 题库文本取数（与 SheetContentView 同一 store；未载入题库时返回空 → 页内占位说明） */
const classTextSource = {
  text(kind: string, chap: string, id: string): string {
    const book = kbStore.books[kind as keyof typeof kbStore.books]
    const ch = book?.chapters.find((c) => c.name === chap)
    return ch?.rows.find((r) => r.id === id)?.content ?? ''
  },
}

/** 预览整班：按当前 tag→任务包映射生成完整多页 HTML overlay。
 *  fallback：lib/classOverlay.ts 静态生成层（每生页块 + @page A4 + @media print，
 *  数据装配已按 S2a 模板的 pages/frames 形状预留）；同时生成 batch manifest
 *  文本（README/绑定核对，无引擎也可用）。 */
function previewWholeClass() {
  if (!roster.students.length) { classPreviewMsg.value = '名单为空：先导入/生成带 tag 名单。'; return }
  if (!pad.saved.length) { classPreviewMsg.value = '任务包清单为空：到「作业纸内容」页保存任务包后再预览。'; return }
  previewingClass.value = true
  try {
    const padJsons = pad.savedJsons()
    classPreviewHtml.value = buildClassOverlayHtml(roster.students, padJsons, classTextSource, {
      title: '整班作业纸预览（VC-3）',
      classDir: roster.students[0]?.class ?? 'classA',
    })
    classPreviewManifest.value = buildBatchManifest(roster.students, padJsons)
    classPreviewMsg.value = `已生成整班预览（${roster.students.length} 名学生 / ${pad.saved.length} 份任务包映射）：下方 iframe 内可滚动查看；「下载 HTML」后浏览器打开 → Ctrl/Cmd+P 打印/存 PDF（每生一页，自动分页）。`
    showClassPreview.value = true
  } catch (e) {
    classPreviewMsg.value = `整班预览生成失败：${(e as Error).message}`
  } finally {
    previewingClass.value = false
  }
}

function downloadClassPreviewHtml() {
  if (!classPreviewHtml.value) return
  downloadData(classPreviewHtml.value, `class-sheet-preview-${new Date().toISOString().slice(0, 10)}.html`, 'text/html')
}

/** 未绑定 tag 的学生提示（预览/引擎 batch 都会跳过这部分人） */
const missingTagWarn = computed(() => {
  if (!roster.students.length || !pad.saved.length) return ''
  const bound = new Set<string>()
  for (const s of pad.saved) {
    try {
      const p = parseTaskpad(JSON.parse(s.json))
      const t = padInferredTag(p.items, p.target_tag)
      if (t) bound.add(t)
    } catch { /* JSON 损坏包忽略 */ }
  }
  const missing = [...new Set(roster.students.map((s) => s.tag).filter((t) => t && !bound.has(t)))]
  if (!missing.length) return ''
  return `⚠ 以下 tag 没有任何任务包绑定（预览中这些学生页会显示"未匹配变体"占位，引擎 batch 也会跳过）：${missing.map((t) => STUDENT_TAG_LABELS[t] ?? t).join('、')}——去「作业纸内容」页补绑定，或生成 batch 包时指定 --default 兜底。`
})

/** 宽表列数（预览按钮文案用） */
const pageCount = computed(() => roster.students.length)

const warnRatio = computed(() => roster.ratioSum > 1.0001)
const warnRatioOff = computed(() => Math.abs(roster.ratioSum - 1) > 0.0001 && roster.ratioSum <= 1.0001)

function setTag(stuIdx: number, ev: Event) {
  const val = (ev.target as HTMLSelectElement).value
  roster.setManualTag(roster.students[stuIdx], val)
}

const batchNames = ref('')
const batchTag = ref('copy')
const batchCreateIfAbsent = ref(true)
const batchMsg = ref('')

function applyBatchTag() {
  const names = batchNames.value.split(/[，,、/；;]+/).map((s2: string) => s2.trim()).filter(Boolean)
  if (!names.length || !batchTag.value) return
  let hit = 0; let added = 0
  for (const nm of names) {
    let idx = roster.students.findIndex((s) => s.name === nm)
    if (idx < 0 && batchCreateIfAbsent.value) {
      roster.addStudent()
      idx = roster.students.length - 1
      roster.students[idx].name = nm
      added++
    }
    if (idx >= 0) { roster.students[idx].tag = batchTag.value; hit++ }
  }
  roster.touch()
  batchMsg.value = `已给 ${hit} 人打上 ${batchTag.value}（新增 ${added} 人）`
}

function setPunish(stuIdx: number, ev: Event) {
  const stu = roster.students[stuIdx]
  if ((ev.target as HTMLInputElement).checked) roster.setManualTag(stu, 'punish')
  else roster.setManualTag(stu, '')
}

// punish 快捷勾选：见下面名单表操作说明（tag 选择即覆盖，punish 在下拉中）

function downloadRosterJsonAndXlsx() {
  roster.downloadRosterXlsx()
  roster.downloadRosterJson()
}

async function downloadTaskPackage() {
  try {
    status.value = await roster.downloadTaskPackage()
  } catch (e) {
    status.value = `任务包导出失败：${(e as Error).message}`
  }
}

/** 与 kb 编辑器共用已连接的 workspace 目录句柄（原地写回 roster/；TODO(阶段4) 换 roster 自己的句柄） */
const dirHandle = computed(() => getKbDirHandle())
const writeHint = fsWriteHint()

async function saveToWorkspace() {
  if (!dirHandle.value) {
    status.value = '未连接 workspace 目录（在「题库编辑器」连接后可原地写回；当前用下载导出即可）。'
    return
  }
  try {
    status.value = await roster.saveToDir(dirHandle.value)
  } catch (e) {
    status.value = `写回失败：${(e as Error).message}`
  }
}

const exportDisabled = computed(() => roster.students.length === 0)

/** 导出前统计（显示在按钮下的提示） */
const summaryText = computed(() => {
  if (!roster.students.length) return '名单为空。'
  const parts: string[] = []
  for (const [tag, cnt] of Object.entries(roster.tagCounts)) {
    parts.push(`${STUDENT_TAG_LABELS[tag] ?? tag}：${cnt}`)
  }
  return `共 ${roster.students.length} 人。${parts.join('；')}`
})

const fixedSourceCount = computed(() => roster.sources.filter((s) => isFixedFamily(s.family)).length)
/** 比例合计不含 translation（D24：translation 是独立"随机拨给"，不占 100%）。 */
const nonTranslationRatios = computed(() => roster.ratios.filter((g) => g.tag !== 'translation'))

/** D23 变体编排（绑定面板 + 一键 batch zip）已迁「作业纸内容」页（SheetContentView，
 *  M-A S1 单入口，docs/05-D25）；本页保留指向链接 + VC-3「预览整班」
 *  （S2b：纯前端 HTML overlay，不依赖引擎；编排绑定本身仍单入口在内容页）。 */
</script>

<template>
  <section>
    <p class="hint" style="margin-top:0">
      名单列自适应（姓名|name、学号|number、班级|class、tag|tag）；成绩源支持<b>格式预设</b>
      （docs/05-D19：固定四类教务/学习通/雨课堂 + custom）；综合得分 = 多源加权归一均值；
      分组比例自动切分 tag；「特殊标签」栏随时人工覆盖（special_tag_cfg）。
      S2b 预览整合（docs/14 §VC）：名单/成绩导入预览卡 + 成绩源宽表（勾选=分层依据，默认全勾）
      + 整班作业纸预览（纯前端 overlay，不依赖引擎）。
    </p>
    <div class="notice" v-if="!caps.full && caps.browserHint">{{ caps.browserHint }}</div>
    <div class="notice info" v-if="caps.insecure" style="margin-top:6px">
      当前为局域网预览（http://IP，非安全上下文）：导入名单/成绩/题库均可用（文件选择方式）；
      "写回 workspace 目录"不可用——请用下方导出按钮下载文件，教师手动放回 workspace。
      {{ writeHint }}
    </div>
    <PreviewTableCard
      title="成绩源解析状态预览（表头 + 前 3 行，VC-6）"
      :preview="sourcePreview"
      :file-name="sourcePreviewFile"
      tone="ok"
    />

    <div class="card">
      <h2>成绩源（格式预设 + 任意 xlsx，docs/05-D19）</h2>
      <p class="hint">
        先选<b>格式预设</b>再选文件：固定四类无需选列（自动按该格式的列名语义定位）；
        custom（自定义）需手动指定"分数来源列" + 权重（雨课堂签到次数、作业完成度、考试分数等均可）。
        列值在其源内按最大值归一到 0~100；综合得分 = weighted mean
        （ <b>VC-5</b>：只聚合下方宽表中<b>勾选中</b>的源；取消勾选 = score excluding）。
      </p>
      <p>
        <label class="field">格式预设：
          <select v-model="presetFamily" style="min-width:230px">
            <option v-for="p in SCORE_FAMILY_PRESETS" :key="p.value" :value="p.value">{{ p.label }}</option>
          </select>
        </label>
        <button class="btn primary" style="margin-left:8px" @click="addSource">＋添加成绩源（选 xlsx）</button>
      </p>
      <p class="hint" :class="{ notice: presetIsFixed }" style="margin-top:2px">
        <template v-if="presetIsFixed">这是固定格式（来自{{ presetFamily === 'rainclass' ? '雨课堂' : presetFamily.startsWith('xuexitong') ? '学习通' : '教务' }}导出）——无需选列，自动按列名语义解析。说明：{{ presetDesc }}</template>
        <template v-else>{{ presetDesc }}</template>
      </p>
      <div v-if="!roster.sources.length" class="notice">尚无成绩源：可只导名单不打 tag（tag 列留空），或添加若干成绩源后「重算并打 tag」。</div>
      <p v-for="(s, i) in roster.sources" :key="i" class="hint" style="border-bottom:1px dashed var(--c-border);padding:6px 0">
        <label class="field">源名：<input type="text" v-model="s.name" style="width:150px" @change="roster.touch()" /></label>
        <label class="field" :title="scoreFamilyDesc(s.family)">格式预设：
          <select :value="s.family" @change="roster.setSourceFamily(i, (($event.target as HTMLSelectElement).value) as ScoreFamily, null)" style="max-width:190px">
            <option v-for="p in SCORE_FAMILY_PRESETS" :key="p.value" :value="p.value">{{ p.label }}</option>
          </select>
        </label>
        <template v-if="isFixedFamily(s.family)">
          <span class="hint" style="color:var(--c-ok)">
            固定格式（来自{{ s.family === 'rainclass' ? '雨课堂' : s.family.startsWith('xuexitong') ? '学习通' : '教务' }}导出）·
            {{ s.family === 'roster' ? '仅接表，不计分' : `分数列：${s.scoreColumn}` }}
            <button class="btn small" style="margin-left:4px" title="固定四类按原始表重新按 family 语义解析" @click="reparseSource(i)">重选文件解析</button>
          </span>
        </template>
        <template v-else>
          <label class="field">分数来源列：
            <select v-model="s.scoreColumn" @change="roster.touch()">
              <option v-for="h in Object.keys(s.rows[0] ?? {})" :key="h" :value="h">{{ h }}</option>
            </select>
          </label>
          <label class="field">姓名列：
            <select v-model="s.nameColumn" @change="roster.touch()">
              <option v-for="h in Object.keys(s.rows[0] ?? {})" :key="h" :value="h">{{ h }}</option>
            </select>
          </label>
        </template>
        <label class="field" v-if="s.family !== 'roster'">权重：<input type="number" v-model.number="s.weight" min="0.1" step="0.1" style="width:70px" @change="roster.touch()" /></label>
        <span class="hint">{{ s.rows.length }} 行 · {{ s.fileName }}</span>
        <button class="btn small" @click="roster.removeSource(i)">移除</button>
      </p>
      <p class="hint" v-if="fixedSourceCount">已按固定格式解析的成绩源 ×{{ fixedSourceCount }}（score_sources[].family 将随任务包导出，与 engine CLI <code>--score family:file[:col[:weight]]</code> 同口径）。</p>
      <p class="hint" v-if="scoreSources.length">{{ checkedSummary }}</p>
      <p class="hint" v-if="scoreSources.length">{{ wideHint }}</p>
    </div>

    <div class="card" v-if="scoreSources.length">
      <h2>成绩源宽表（VC-5：每生一行 × 各源分数列 · 勾选 = 是否参与综合得分）</h2>
      <p class="hint">
        每行 = 一名学生，每列 = 一个已添加成绩源（<b>分数列</b>）——可以看到每个人名下哪个成绩源有分数；可横向滚动。
        每列<b>默认勾选 ✅</b>（includeInAggregation=true，等价"此列作为分层依据"多选叠加）；
        取消勾选的源<b>被排除出综合得分</b>（score excluding，重算时跳过），其分数值仍灰显可见（排除≠删除）；
        roster 接表源仅接表不计分（列头"—"不可勾）。
      </p>
      <div style="overflow:auto; max-height:420px; border:1px solid var(--c-border); border-radius:8px">
        <table class="grid score-wide-table">
          <thead>
            <tr>
              <th class="sticky-col">姓名</th>
              <th class="sticky-col">学号</th>
              <th v-for="h in wideHeaders" :key="h.idx" :title="h.title" :class="{ 'col-excluded': h.excluded }">
                <div class="col-head">
                  <label class="inc" v-if="!h.excluded"
                    :title="h.included ? '取消勾选：该源被排除出综合得分（score excluding）' : '重新勾选：该源重新参与综合得分加权'">
                    <input type="checkbox" :checked="h.included" @change="toggleInclude(h.idx, $event)" />✅
                  </label>
                  <span v-else title="教务点名册仅接表不计分（不可勾选）" style="color:var(--c-muted)">—</span>
                  <span class="col-name">{{ h.label }}</span>
                  <button class="btn small" style="margin-top:2px" :disabled="h.excluded || !roster.students.length"
                    title="VC-5：按该源的分数列单独切分打 tag（一列即排，其余源不参与加权）"
                    @click="tagBySingleColumn(h.idx)">按此列切分</button>
                </div>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in wideRows" :key="row.name + '\u0000' + row.number">
              <td class="sticky-col">{{ row.name || '（未命名）' }}</td>
              <td class="sticky-col">{{ row.number || '—' }}</td>
              <td v-for="(c, j) in row.cells" :key="j" :class="{ 'muted-cell': c === '' }"
                :title="c === '' ? '该源无此生分数（重算时跳过该源）' : ''">
                <span :class="{ 'excluded-val': !wideHeaders[j].included }">{{ c === '' ? '—' : c }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="hint" :class="{ notice: checkedSummary.includes('已排除') }" style="margin-top:6px">{{ checkedSummary }}</p>
      <p class="hint">
        「按此列切分」= 只用该源计算综合得分并按比例自动打 tag（<b>一列即排</b>）；
        「重算综合得分并自动切分打 tag」（下方分组比例卡）= 按<b>当前勾选集合</b>加权重算（多列加权语义：权重/权重和）。
        两者均不清除手动覆盖与 punish。
      </p>
    </div>

    <div class="card">
      <h2>分组比例 + 自动切分打 tag</h2>
      <p class="hint">
        2603 默认比例模板可改（punish 不参与比例，仅手动勾选覆盖；docs/05-D17/D18）。
        切分：不含 translation 的比例合计 ≤100% 之间依次切档（_translation 不参与_，等价 _legacy）；
        translation 沿用 _legacy 的"随机散布"语义。已手动覆盖的学生不参与切分且不被覆盖。
      </p>
      <p>
        <label class="field" v-for="g in nonTranslationRatios" :key="g.tag">
          {{ STUDENT_TAG_LABELS[g.tag] ?? g.tag }}
          <input type="number" :value="Math.round(g.ratio * 100)" min="0" max="100" step="1" style="width:60px"
            @change="(e) => { g.ratio = Number((e.target as HTMLInputElement).value) / 100 || 0; roster.touch(); }" />%
        </label>
        <span class="hint" :class="{ notice: warnRatio }">
          合计（不含 translation）{{ (roster.ratioSum * 100).toFixed(1) }}%
          <template v-if="warnRatio">（&gt;100%：余数为负，按名单实际人数封顶切分）</template>
          <template v-else-if="warnRatioOff">（&lt;100%：剩余学生补到最后一个非 translation 档）</template>
        </span>
      </p>
      <p>
        <button class="btn primary" @click="recompute">重算综合得分并自动切分打 tag</button>
        <button class="btn" style="margin-left:8px" :disabled="exportDisabled" @click="saveToWorkspace" v-if="dirHandle">写回 workspace roster/</button>
      </p>
      <p class="hint" v-if="dirHandle && writeHint">{{ writeHint }}</p>
      <p class="hint">{{ summaryText }}</p>
    </div>

    <PreviewTableCard
      title="名单预览（表头 + 前 3 行 + 列映射，VC-4）"
      :preview="rosterPreview"
      :file-name="rosterPreviewFile"
      tone="ok"
    />

    <div class="card">
      <h2>特殊标签（手动覆盖 special_tag_cfg，批量打 tag）</h2>
      <p>
        <button class="btn primary" @click="importRoster">导入名单 xlsx…</button>
        <button class="btn" style="margin-left:8px" @click="roster.addStudent()">＋手动添加学生</button>
        <button class="btn" style="margin-left:8px" @click="roster.clearAll()" v-if="roster.students.length">清空全部</button>
      </p>
      <p class="hint" v-if="!roster.students.length">尚无学生：先"导入名单 xlsx"（教务导出固定格式，列自动识别）或手动添加，再配分组比例/成绩源即可自动分层；也可直接手动点选本表的 tag（=special_tag_cfg 覆盖）。</p>
      <p>
        <label class="field">批量打 tag：姓名（逗号/顿号分隔多个学生）
          <input type="text" v-model="batchNames" placeholder="学生A, 学生B, 学生C" style="width:min(420px, 60%)" />
        </label>
        <label class="field">tag：
          <select v-model="batchTag">
            <option v-for="t2 in STUDENT_TAGS" :key="t2" :value="t2">{{ STUDENT_TAG_LABELS[t2] }}</option>
          </select>
        </label>
        <label class="field" style="white-space:nowrap"><input type="checkbox" v-model="batchCreateIfAbsent" /> 缺失者自动新增</label>
        <button class="btn" style="margin-left:8px" @click="applyBatchTag" :disabled="!batchNames.trim()">应用到多个学生</button>
        <span class="hint" v-if="batchMsg"> {{ batchMsg }}</span>
      </p>
      <table class="grid">
        <thead>
          <tr><th style="width:120px">姓名</th><th style="width:150px">学号</th><th style="width:150px">班级</th><th style="width:180px">tag</th><th style="width:60px">punish</th><th style="width:40px"></th></tr>
        </thead>
        <tbody>
          <tr v-for="(s, i) in roster.students" :key="i">
            <td><input v-model="s.name" @change="roster.touch()" /></td>
            <td><input v-model="s.number" @change="roster.touch()" /></td>
            <td><input v-model="s.class" @change="roster.touch()" /></td>
            <td>
              <select :value="s.tag" @change="setTag(i, $event)">
                <option value="">（未打）</option>
                <option v-for="t in STUDENT_TAGS" :key="t" :value="t">{{ STUDENT_TAG_LABELS[t] }}</option>
              </select>
            </td>
            <td style="text-align:center"><input type="checkbox" :checked="s.punish" @change="setPunish(i, $event)" title="punish：期末补作业统一题集（不参与比例）" /></td>
            <td><button class="btn small" @click="roster.removeStudent(i)">✕</button></td>
          </tr>
        </tbody>
      </table>
      <p class="hint" style="margin-top:8px">
        手动改 tag = special_tag 覆盖（等价 _legacy special_tag_cfg）；重算自动切分时手动覆盖不被冲掉。
      </p>
    </div>

    <div class="card">
      <h2>产出（名单带 tag → 引擎可直接用）</h2>
      <p class="hint">
        roster.xlsx 列 = name/number/class/tag（恒英文值），<code>uv run assist sheet make &lt;task&gt; --roster roster.xlsx</code> 直接可用；
        roster.json 供 CLI/AI；任务包 zip 内含 roster.xlsx + roster.json + task-package.json
        （group_cfg + special_tag_cfg + punish + score_sources[].family，docs/05-D19）+ 附带切分规则说明 md。
      </p>
      <p>
        <button class="btn primary" :disabled="exportDisabled" @click="downloadRosterJsonAndXlsx">导出 tag 名单（xlsx + JSON）</button>
        <button class="btn" style="margin-left:8px" :disabled="exportDisabled" @click="downloadTaskPackage">下载任务包（zip，附带说明）</button>
      </p>
      <p class="hint" :style="{ marginTop: '4px' }">
        punish 名单（期末补交统一题集，不按层）：
        <template v-if="roster.tagCounts.punish">
          <code>{{ roster.students.filter((s) => s.tag === 'punish').map((s) => s.name).join('、') }}</code>
        </template>
        <template v-else>（未勾选）</template>
      </p>
      <p class="hint" v-if="caps.insecure">LAN 预览提示：导出为浏览器下载，教师手动放回 workspace 的 <code>classes/&lt;班级&gt;/roster/</code> 即可（写回目录能力需本机 localhost/https 打开）。</p>
    </div>
    <div class="card">
      <h2>整班作业纸预览（VC-3：按 tag→任务包映射的多页 HTML overlay，纯前端不依赖引擎）</h2>
      <p class="hint">
        变体编排绑定（tag→任务包 target_tag）在「作业纸内容」页维护（单入口，D25）；
        本卡按当前映射 + 名单 tag 即时生成<b>完整多页 HTML overlay</b>（每生一页块、@page A4、
        @media print 自动分页，lib/classOverlay.ts）——名单里所有人按其 tag 领到对应变体（与引擎 batch 同口径）。
        S2a 的 HTML 打印模板（assignment.html.j2 / stringifySheetHtml）就位后，本预览切换为同一模板交付
        （数据装配已按其 pages/frames 形状预留，见 lib/classOverlay.ts 头注释）；当前为 fallback 静态层，无引擎也可用。
      </p>
      <p>
        <button class="btn primary" :disabled="previewingClass || !roster.students.length || !pad.saved.length" @click="previewWholeClass">👁 预览整班（HTML overlay：{{ roster.students.length }} 名学生 × {{ pad.saved.length }} 份任务包映射）</button>
        <button class="btn" style="margin-left:8px" :disabled="!classPreviewHtml" @click="downloadClassPreviewHtml">⬇ 下载 HTML（浏览器打开→Ctrl+P 打印）</button>
        <span class="hint" v-if="!pad.saved.length">（任务包清单为空：没有可映射的任务包；先去内容页保存）.</span>
        <span class="hint" v-else-if="!pageCount">（名单为空，先导入名单。）</span>
      </p>
      <p class="hint notice warning" v-if="missingTagWarn">{{ missingTagWarn }}</p>
      <p class="hint" v-if="classPreviewMsg">{{ classPreviewMsg }}</p>
      <details open v-if="classPreviewManifest" style="margin:6px 0">
        <summary style="cursor:pointer; font-size:13px">fallback manifest（README：tag→包绑定核对，无引擎可用）</summary>
        <pre class="hint" style="white-space:pre-wrap; font-size:11px; background:var(--c-bg,#f7f7f9); padding:8px; border-radius:6px"><code>{{ classPreviewManifest }}</code></pre>
      </details>
      <iframe v-if="showClassPreview && classPreviewHtml"
        class="class-overlay-frame"
        :srcdoc="classPreviewHtml"
        title="整班作业纸预览"
        sandbox="allow-same-origin"
      ></iframe>
    </div>

  </section>
</template>

<style scoped>
/* VC-5 宽表：粘性首列 + 横向滚动（外层 overflow:auto 已在模板内联设置） */
.score-wide-table { min-width: max-content; }
.score-wide-table th, .score-wide-table td { text-align: left; }
.score-wide-table th.sticky-col, .score-wide-table td.sticky-col {
  position: sticky; left: 0; background: var(--c-card);
  border-right: 1px solid var(--c-border); z-index: 1;
}
.score-wide-table th.sticky-col { background: var(--c-primary-soft); }
.score-wide-table .col-head { display: flex; flex-direction: column; gap: 2px; min-width: 130px; }
.score-wide-table .col-head .inc { display: flex; align-items: center; gap: 4px; font-size: 12px; cursor: pointer; }
.score-wide-table .col-head .col-name { font-size: 12px; word-break: break-all; }
.score-wide-table th.col-excluded { color: var(--c-muted); }
.score-wide-table td.muted-cell { color: var(--c-muted); }
.score-wide-table td .excluded-val { color: var(--c-muted); text-decoration: line-through; }
/* VC-3 整班预览 iframe：多页 overlay 的可视容器（可滚动，页块自身 A4 尺寸） */
.class-overlay-frame { width: 100%; height: 560px; border: 1px solid var(--c-border); border-radius: 8px; background: white; }
.hint.warning { color: var(--c-warn-text); }
</style>

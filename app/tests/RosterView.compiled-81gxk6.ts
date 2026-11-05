import { defineComponent as _defineComponent } from 'vue'
import { computed, onMounted, ref, watch } from 'vue'
import { STUDENT_TAGS, STUDENT_TAG_LABELS } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/kb'
import {
  SCORE_FAMILY_PRESETS, isIncluded, isFixedFamily, scoreFamilyDesc, scoreFamilyLabel,
  type ScoreFamily,
} from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/roster'
import { columnScoreOf, scoreColumnsOf } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/rosterXlsx'
import { computeScoresFiltered } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/roster'
import type { PreviewTable } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/rosterXlsx'
import { useRosterStore } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/stores/roster'
import { useTaskpadStore } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/stores/taskpad'
import { usePackStore } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/stores/packs'
import { getKbDirHandle } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/stores/kb'
import { buildBatchManifest, partitionStudentsByTag } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/classOverlay'
import { parseTaskpad, padInferredTag } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/taskpad'
import { downloadData, detectCapabilities, fsWriteHint, pickReadFileFsa } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/fsAccess'
import { useKbStore } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/stores/kb'
import { useSettingsStore } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/stores/settings'
import { fetchGradingPacks, fetchGradingScores, saveTagsSnapshot } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/engineClient'
import { buildSheetSidecar, sidecarFileName, type SheetSidecar } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/sheetSidecar'
import { stringifyClassHtml, printSheetHtml, expandPadItems,
  type SheetHtmlPadInput, type SheetHtmlStudent } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/sheetHtml'
import type { KbKind } from '/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/kb'
import PreviewTableCard from '/home/bot2603/Projects/2609-assignment-assistant/app/tests/PreviewTableCard.compiled-1ilsba.ts'

/** 班级与标签（M5 成绩管理，docs/05-D18；M-A S1 由"班级与成绩"更名，docs/05-D26）：
 *  名单/成绩导入 + 综合得分 + 自动打 tag + 导出。
 *  成绩源格式预设（docs/05-D19）：固定四类（教务点名册/教务期末/学习通作业统计/
 *  学习通章节测验/雨课堂汇总）按列名 family 语义自动定位分数列，无需用户选列；
 *  custom 保留手动选列。纯前端闭环（不依赖学习通/引擎）。
 *  S2b（docs/14 §VC-3/4/5/6、M-C R3.2/3.3/3.5 收口）：
 *  - VC-4/VC-6 导入预览卡（表头+前3行+列映射说明，PreviewTableCard 复用）；
 *  - VC-5 成绩源宽表（行=学生，列=各源分数列，横向滚动）+ 默认勾选/取消勾选
 *    （score excluding，includeInAggregation）+ 按勾选源重算 + 按单列切分（一列即排）；
 *  - VC-3 整班作业纸预览（docs/13 D43-3/6）：同一打印模板（lib/sheetHtml.ts）渲染；
 *    本页 = 全站唯一整班分层预览入口；lib/classOverlay.ts 只承担 tag→包分段 + manifest。
 *  变体编排（tag→作业纸绑定 + 整班 batch zip）在「作业纸内容」页（单入口，D25）。 */

interface WideRow { name: string; number: string; cells: string[]; composite: string }
interface WideHeader {
  si: number; ci: number
  label: string; title: string
  included: boolean; excluded: boolean
  col: { name: string; index: number; weight: number } | null
}

const __sfc_main = /*@__PURE__*/_defineComponent({
  __name: 'RosterView',
  setup(__props, { expose: __expose }) {
  __expose();

const roster = useRosterStore()
const pad = useTaskpadStore()
const kbStore = useKbStore()
const settingsStore = useSettingsStore()
const caps = detectCapabilities()
const status = ref('')
/** D149：AI 批阅成绩（一次作业包 = 一列） */
/** 当前班级的 workspace 目录：按 D124「目录名 = 班级真名」推断。 */
const activeClassDir = computed(() => {
  const nm = String(roster.activeMeta?.name || '').trim()
  return nm ? `classes/${nm}` : ''
})

const gradingPicker = ref(false)
const gradingPacks = ref<Array<{ packId: string; name: string; graded: number; at: string }>>([])

async function openGradingPicker() {
  const cd = activeClassDir.value
  if (!cd) { status.value = '请先选择班级（需有班级名称才能定位 workspace 目录）。'; return }
  try {
    const r = await fetchGradingPacks(settingsStore.engineUrl, settingsStore.engineToken, cd)
    if (!r?.ok) { status.value = `读取批阅结果失败：${r?.error || ''}`; return }
    gradingPacks.value = r.packs || []
    gradingPicker.value = true
    if (!gradingPacks.value.length) {
      status.value = '该班级还没有批阅结果：先在「AI 辅助批阅」跑一次批阅。'
    }
  } catch (e) {
    status.value = `读取失败：${String((e as Error).message || e)}（引擎是否在线？）`
  }
}

async function pickGradingPack(g: { packId: string; name: string }) {
  const cd = activeClassDir.value
  const names = roster.students.map((s) => s.name)
  try {
    const r = await fetchGradingScores(settingsStore.engineUrl, settingsStore.engineToken,
                                       cd, g.packId, names)
    if (!r?.ok) { status.value = `读取批阅成绩失败：${r?.error || ''}`; return }
    status.value = roster.addGradingSource({
      packId: g.packId, name: g.name, rows: r.rows || [],
    })
    gradingPicker.value = false
  } catch (e) {
    status.value = `加入失败：${String((e as Error).message || e)}`
  }
}

/** 成绩源添加时的格式预设选择（默认 custom = 旧行为） */
const presetFamily = ref<ScoreFamily>('custom')
// D49-F1：成绩源下拉已移除 roster 预设（名单=「导入名单 xlsx…」专用按钮的唯一入口）；
// addScoreSource 收到 family='roster' 时走单写路径（见 store）
const presetDesc = computed(() => scoreFamilyDesc(presetFamily.value))
const presetIsFixed = computed(() => isFixedFamily(presetFamily.value))

onMounted(() => {
  if (roster.students.length) roster.touch()
})

function pickXlsx(): Promise<File | null> {
  // LAN（http://IP）/Firefox/Safari 下静默降级为 file input（fsAccess 内部处理）
  // D49-F1：accept 扩 .xls/.csv（教务点名册=.xls、成绩 custom 可 .csv——此前只认 .xlsx 是教师导入失败链的一环）
  return pickReadFileFsa('.xlsx,.xls,.csv')
}

/* ---------- VC-4/VC-6 导入预览（表头+前 3 行+列映射说明） ---------- */
const rosterPreview = ref<PreviewTable | null>(null)
const rosterPreviewFile = ref('')

const rosterFailNotice = ref(false)

/** D56-I4：清空当前班级的名单+成绩源+比例（破坏性操作，二次确认）。 */
function clearAllAction() {
  if (!window.confirm(`确认清空当前班级「${roster.activeMeta?.name ?? ''}」的全部名单、成绩源与分组比例？（不可恢复）`)) return
  roster.clearAll()
  status.value = '已清空当前班级的名单/成绩源/分组比例。'
}

async function importRoster() {
  const file = await pickXlsx()
  if (!file) return
  try {
    const { message, preview } = await roster.loadRosterFile(file)
    status.value = message
    rosterPreview.value = preview
    rosterPreviewFile.value = file.name
    rosterFailNotice.value = false
    // D46-2：成功即滚到宽表并 flash 人数 chip（所见即所导）
    requestAnimationFrame(() => {
      document.getElementById('wide-table')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      wideFlash.value = true
      setTimeout(() => { wideFlash.value = false }, 1600)
    })
  } catch (e) {
    const err = e as { message?: string; reason?: string; firstRows?: string[][]; sheetNames?: string[] }
    const hint = err.reason === 'no-name-column' && err.firstRows?.length
      ? `｜文件前 3 行原文：${err.firstRows.map((r) => r.filter((c) => c).slice(0, 6).join(' | ') || '（空行）').join(' ／ ')}` +
        `｜sheets：${(err.sheetNames ?? []).join(', ') || '无'}。如为教务名册且表头缺失，删至仅剩表头行后重试。`
      : ''
    status.value = `名单读入失败：${err.message ?? String(e)}${hint}`
    rosterFailNotice.value = true
    rosterPreview.value = null
  }
}

const wideFlash = ref(false)

/* ---------- D49-F2：班级配置栏 handlers ---------- */
function renameCurrent(name: string) {
  if (!roster.activeMeta) return
  roster.renameClass(roster.activeMeta.id, name || roster.activeMeta.name)
  status.value = `班级名已更新为「${name}」。`
}
function renameCurrentTerm(term: string) {
  if (!roster.activeMeta) return
  roster.renameClass(roster.activeMeta.id, roster.activeMeta.name, term)
  status.value = `学期已更新为「${term}」。`
}
function loadClassAction(cid: string) {
  if (roster.switchClass(cid)) {
    status.value = `已载入班级「${roster.activeMeta?.name ?? cid}」（名单/成绩/标签/产出全部切换）。`
  }
}
async function deleteClassAction(cid: string, name: string) {
  if (!window.confirm(`确认删除班级「${name}」？（其名单/成绩源/产出登记一并清除，IndexedDB 原始文件同步删除；不可恢复）`)) return
  const ok = await roster.deleteClass(cid)
  status.value = ok ? `已删除班级「${name}」。` : '删除失败（班级不存在）。'
}
function rosterTagCountsOf(cid: string): Record<string, number> {
  const out: Record<string, number> = {}
  for (const stu of roster.classes[cid]?.students ?? []) {
    if (stu.tag) out[stu.tag] = (out[stu.tag] ?? 0) + 1
  }
  return out
}
function createClassAction() {
  const name = window.prompt('新班级名称（如：化工251-2026S1）：', `班级${roster.classOrder.length + 1}`)
  if (name === null) return
  const cid = roster.createClass(name.trim() || undefined)
  status.value = `已新建并切换到班级「${name}」（名单/成绩从零开始；分组比例沿用上一班级配置）。`
  void cid
}

async function addSource() {
  const file = await pickXlsx()
  if (!file) return
  try {
    const { message } = await roster.addScoreSource(file, presetFamily.value)
    status.value = message
  } catch (e) {
    status.value = `成绩源读入失败：${(e as Error).message}`
    
  }
}

/** 源内切换格式预设：需要原始 xlsx 重新解析（固定四类按 family 语义重新定位） */
async function reparseSource(idx: number) {
  // D46-3：IndexedDB 有原始文件 → 直接重解析（免二次选文件）；无 → 回退旧流程选文件
  try {
    if (roster.sources[idx]?.uid) {
      const msg = await roster.reparseFromRaw(idx)
      status.value = msg
      if (!msg.startsWith('已按')) {
        // 无 raw（旧数据/IDB 丢失）→ 走手动选文件
        const file = await pickXlsx()
        if (!file) return
        const family = roster.sources[idx]?.family ?? 'custom'
        await roster.rescoreWithFamily(idx, file, family)
        status.value = `已按 ${scoreFamilyLabel(family)} 重新解析成绩源「${roster.sources[idx]?.name ?? ''}」。`
      }
      return
    }
    const file = await pickXlsx()
    if (!file) return
    const family = roster.sources[idx]?.family ?? 'custom'
    await roster.rescoreWithFamily(idx, file, family)
    status.value = `已按 ${scoreFamilyLabel(family)} 重新解析成绩源「${roster.sources[idx]?.name ?? ''}」。`
  } catch (e) {
    status.value = `成绩源重新解析失败：${(e as Error).message}`
  }
}

/** D47-5：列勾选（store toggle + 即时状态回显） */
async function colToggleMsg(idx: number, name: string) {
  status.value = roster.toggleSourceColumn(idx, name)
}

/* ---------- D46-3：成绩源行内👁预览（IndexedDB raw 即时重建 PreviewTable） ---------- */
const sourceRowPreview = ref<PreviewTable | null>(null)
const sourceRowPreviewFile = ref('')

/* ---------- B1：多 sheet 源的行内 sheet 切换（raw 留存时列出全部 sheet） ---------- */
const sheetChoices = ref<Record<number, string[]>>({})

async function toggleSheetPicker(idx: number) {
  if (sheetChoices.value[idx]) { delete sheetChoices.value[idx]; return }
  const names = await roster.listSourceSheets(idx)
  if (names.length <= 1) {
    status.value = names.length === 1 ? '该文件只有 1 张 sheet，无需切换。' : '无留存原始文件：「重解析」重新选文件后可用。'
    return
  }
  sheetChoices.value = { ...sheetChoices.value, [idx]: names }
}

async function switchSourceSheet(idx: number, ev: Event) {
  const name = (ev.target as HTMLSelectElement).value
  const msg = await roster.setSourceSheet(idx, name)
  status.value = msg
  const next = { ...sheetChoices.value }
  delete next[idx]
  sheetChoices.value = next
}

async function previewSourceRow(idx: number) {
  try {
    const pv = await roster.previewSource(idx)
    if (!pv) {
      status.value = '该源暂无原始文件留存（早期导入的数据）：点「重选文件解析」一次即可启用回看。'
      return
    }
    sourceRowPreview.value = pv
    sourceRowPreviewFile.value = roster.sources[idx]?.fileName ?? ''
  } catch (e) {
    status.value = `预览失败：${(e as Error).message}`
  }
}

/* ---------- D168：把本次 tag 结果冻结成某作业包的快照 ----------
 * 教师使用习惯（docs/112-D168 §3.3）：预览整班作业纸后**打印 PDF**，
 * 不生成 batch/json —— 元数据会丢。所以在「重算并打 tag」时把 roster 固化下来。
 * 不选作业包 = 只更新班级 roster（旧行为不变）。 */
const snapshotPackId = ref('')
const snapshotMsg = ref('')
const snapshotBusy = ref(false)

const snapshotPackOptions = computed(() =>
  (packStore.packs || []).map((p) => ({ id: p.id, name: (p as any).name || p.id })))

async function freezeSnapshotIfChosen() {
  const pid = String(snapshotPackId.value || '').trim()
  const cd = activeClassDir.value
  if (!pid || !cd) return
  snapshotBusy.value = true
  try {
    const r = await saveTagsSnapshot(settingsStore.engineUrl, settingsStore.engineToken, {
      classDir: cd, packId: pid,
      students: roster.students.map((x) => ({
        number: x.number, name: x.name, tag: x.tag })),
      source: 'recompute-tags',
    })
    snapshotMsg.value = r?.ok
      ? (r.created
          ? `✅ 已冻结「${pid}」的学生→tag 快照（${r.count} 人）`
          : `ℹ 「${pid}」快照已存在，未覆盖（${r.skipped || ''}）。如需更新请用「刷新快照」`)
      : `❌ 快照写入失败：${r?.error || '未知错误'}`
  } catch (e) {
    snapshotMsg.value = `快照写入失败：${String((e as Error).message || e)}`
  } finally { snapshotBusy.value = false }
}

function recompute() {
  if (!roster.students.length) {
    status.value = '请先导入/手动建立名单。'
    return
  }
  status.value = roster.recomputeFromChecked()
  void freezeSnapshotIfChosen()
}

/* ---------- D46-4 总览导出 xlsx（SheetJS aoa；未勾选源列保留、表头加"[未参与]"标注） ---------- */
const overviewMsg = ref('')
async function exportOverviewXlsx() {
  try {
    const XLSX = (await import('xlsx')).default ?? await import('xlsx')
    const headers = ['姓名', '学号', '班级', ...wideHeaders.value.map((h) => `${h.label}${h.excluded ? '' : (h.included ? '' : '[未参与]')}`), '综合得分', 'tag', 'punish']
    const rows: (string | number)[][] = [headers]
    for (const r of wideRows.value) {
      const stu = roster.students.find((s) => s.name === r.name && s.number === r.number)
      rows.push([r.name, r.number, stu?.class ?? '', ...r.cells.map((c) => c === '' ? '' : Number(c)), r.composite === '' ? '' : Number(r.composite), stu?.tag ?? '', stu?.punish ? '是' : ''])
    }
    const wb = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(rows), '全部成绩总览')
    const out = XLSX.write(wb, { type: 'array', bookType: 'xlsx' })
    downloadData(new Blob([out], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }),
      `成绩总览-${new Date().toISOString().slice(0, 10)}.xlsx`)
    overviewMsg.value = `已导出 ${roster.students.length} 生 × ${wideHeaders.value.length} 源总览（未勾选源列标"[未参与]"）。`
  } catch (e) {
    overviewMsg.value = `导出失败：${(e as Error).message}`
  }
}

/* ---------- VC-5 成绩源宽表：行=学生，列=各源分数列（横向滚动） ---------- */
/** 宽表行：学生 + 每个源该生的分数（'' = 该源无此生分数） */
const scoreSources = computed(() => roster.sources)
/** D55-H3：总览列 = 每源 × 每勾选列（一个源可多列）；列头带权重输入与单列切分。 */
const wideHeaders = computed<WideHeader[]>(() =>
  scoreSources.value.flatMap((s, si): WideHeader[] => {
    if (s.family === 'roster') {
      return [{ si, ci: -1, label: s.name || s.fileName || '点名册', title: '教务点名册：仅接表不计分',
                included: false, excluded: true, col: null }]
    }
    const cols = scoreColumnsOf(s)
    return cols.map((col, ci): WideHeader => ({
      si, ci,
      col,
      label: s.name ? `${s.name}·${col.name}` : col.name,
      title: `${s.fileName} · family=${s.family} · 列：${col.name} · 权重 ${col.weight ?? 1}`,
      included: isIncluded(s) && Number(col.weight ?? 1) > 0,
      excluded: false,
    }))
  }))
/** D94-T3：总览显示顺序（默认点名册；可选按加权成绩 升/降）。 */
const orderedWideRows = computed<WideRow[]>(() => {
  const rows = wideRows.value
  const idx = sortedIdx(roster.students, overviewSort.value)
  return idx.map((i) => rows[i]).filter(Boolean)
})
const wideRows = computed<WideRow[]>(() => {
  const headers = wideHeaders.value
  // D46-4/D55-H3 综合得分列：按当前勾选源×列"干跑"原始分加权平均（不落库；正式写入走「重算并打 tag」）
  const shadow = roster.students.map((s) => ({ ...s }))
  try { computeScoresFiltered(shadow, scoreSources.value.filter(isIncluded)) } catch { /* noop */ }
  const compMap = new Map(shadow.map((s) => [`${s.name}\u0000${s.number}`, s.score]))
  return roster.students.map((stu) => ({
    name: stu.name,
    number: stu.number,
    cells: headers.map((h) => {
      if (!h.col || h.excluded) return ''
      const v = columnScoreOf(scoreSources.value[h.si], h.col, stu.name, stu.number)
      return typeof v === 'number' && Number.isFinite(v) ? String(v) : ''
    }),
    composite: (() => {
      const c = compMap.get(`${stu.name}\u0000${stu.number}`)
      return typeof c === 'number' && Number.isFinite(c) ? c.toFixed(2) : ''
    })(),
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
  `多列加权口径：综合得分 = Σ(原始分 × 列权重) / Σ列权重（D55-H3；不再做班内最高分归一）。`)

/** 单列切分按钮（一列即排） */
function tagBySingleColumn(si: number, colName?: string) {
  if (!roster.students.length) { status.value = '请先导入/手动建立名单。'; return }
  status.value = roster.tagByColumn(si, colName)
}
function toggleColumnInclude(si: number, colName: string, on: boolean) {
  status.value = roster.toggleColumnInclude(si, colName, on)
}
function setColumnWeight(si: number, colName: string, raw: string) {
  const w = Number(raw)
  status.value = roster.setColumnWeight(si, colName, Number.isFinite(w) ? w : 1)
}


/* ---------- VC-3 整班作业纸预览（HTML overlay，纯前端不依赖引擎） ---------- */
const showClassPreview = ref(false)
const classPreviewHtml = ref('')
const classPreviewMsg = ref('')
const classPreviewManifest = ref('')
const previewingClass = ref(false)

/** D57-1：整班输出内容开关（默认=学生版：不含答案；水印/页码保持现状勾选）。 */
const classIncludeAnswers = ref(false)
const classIncludeWatermark = ref(true)
const classIncludePageText = ref(true)

/** 兜底包（--default 语义，预览用）：名单里有 tag 但无包绑定的学生指定兼任变体 */
const classPreviewFallbackId = ref('')
/** D88-b：未出页学生（tag 未绑定任何作业纸且未选兜底变体） */
const classPreviewUnmatched = ref<string[]>([])

/** D43-3/D43-6 收口：整班预览改用 stringifySheetHtml（与 CLI assignment.html.j2 同一模板）。
 *  数组分段 = lib/classOverlay.partitionStudentsByTag（tag→包，--default 兜底同口径）；
 *  每包段内学生 → expandPadItems 取题帧；KaTeX 相对路径（同源 ./katex/，离线也渲染）。 */
const packStore = usePackStore()

/** D127：整班预览**跟随当前选中的作业包**。
 *
 *  此前用 `pad.savedJsons()`（全库）按 tag 反推 → 同一 tag 在多个批次都有作业纸时，
 *  会串到**别的作业**的题目。现在只取当前包内的作业纸。
 *  没有选中包时返回空并给出明确提示（不再静默回退全库）。
 */
const classPackPads = computed(() => packStore.packPadJsons(pad.savedJsons()))

/** 整班预览的取题来源（当前包）；无包 → 空数组。 */
function classPadJsons(): Array<{ id: string; json: string }> {
  return classPackPads.value.pads.map((x) => ({ id: x.id, json: x.json }))
}

function buildClassInputs(): { inputs: SheetHtmlPadInput[]; unmatched: number; unmatchedNames: string[]; total: number } {
  const { groups, unmatched } = partitionStudentsByTag(
    roster.students, classPadJsons(), classPreviewFallbackId.value)
  const inputs: SheetHtmlPadInput[] = groups.map((g) => ({
    pad: g.pad,
    // D100-T7：参考答案走生效版（版本库置顶/最新版 → 回落 xlsx 列）
    items: expandPadItems(g.pad, (kind) => kbStore.book(kind as KbKind), kbStore.effectiveSolution),
    // D93-fix：按**学号升序**排序（= 教务处点名册顺序）；学号空缺者排末尾、保持稳定。
    // 说明：成绩/雨课堂源常按分数降序，故必须显式按学号重排，才能得到教务处名单顺序。
    students: [...g.students]
      .map((st, i) => ({ st, i }))
      .sort((A, B) => {
        const na = String(A.st.number || '').trim(), nb = String(B.st.number || '').trim()
        const ha = na !== '', hb = nb !== ''
        if (ha && hb) {
          const c = na.localeCompare(nb, undefined, { numeric: true })
          return c !== 0 ? c : A.i - B.i
        }
        if (ha !== hb) return ha ? -1 : 1   // 有学号在前
        return A.i - B.i                    // 都空 → 稳定原序
      })
      .map(({ st }) => ({ name: st.name, number: st.number, class: st.class, tag: st.tag })),
  }))
  return { inputs, unmatched: unmatched.length,
           unmatchedNames: unmatched.map((s) => s.name), total: roster.students.length }
}

/** 预览整班：同一打印模板多页 HTML；同时生成 batch manifest 文本（README/绑定核对）。 */
/** D57-1：按当前开关构建整班 HTML（含答案/水印/页码三开关；与设计页同语义）。 */
/** D94-T2：整班渲染输入 —— 学生→作业纸映射（由 tag 决定），顺序用 roster.students（点名册顺序）。 */
function classOrderResolver(): (stu: SheetHtmlStudent) => { pad: any; items: any[] } | null {
  const { groups } = partitionStudentsByTag(roster.students, classPadJsons(), classPreviewFallbackId.value)
  const padByTag = new Map<string, { pad: any; items: any[] }>()
  const itemsOf = (p: any) => expandPadItems(p, (k) => kbStore.book(k as KbKind), kbStore.effectiveSolution)
  for (const g of groups) {
    const tag = padInferredTag(g.pad.items, g.pad.target_tag) || ''
    if (tag) padByTag.set(tag, { pad: g.pad, items: itemsOf(g.pad) })
  }
  const fallbackPadId = classPreviewFallbackId.value
  return (stu: SheetHtmlStudent) => {
    const tag = String((stu as any).tag || '')
    let hit = padByTag.get(tag)
    if (!hit && fallbackPadId) {
      const fp = groups.find((g) => g.pad.id === fallbackPadId)
      if (fp) hit = { pad: fp.pad, items: itemsOf(fp.pad) }
    }
    return hit || null
  }
}

/** D94-T2：整班预览**按点名册顺序逐人**输出。 */
function buildClassPreviewHtml(): string {
  const { html } = stringifyClassHtml(roster.students as SheetHtmlStudent[], classOrderResolver(), {
    groupName: '',
    includeSolution: classIncludeAnswers.value,
    includeWatermark: classIncludeWatermark.value,
    includePageText: classIncludePageText.value,
    wmAssets: settingsStore.wmAssets,
    wmStyles: settingsStore.wmStyles,
    figAssets: settingsStore.figAssets,
    katex: 'relative',
  })
  return html
}

function previewWholeClass() {
  if (!roster.students.length) { classPreviewMsg.value = '名单为空：先导入/生成带 tag 名单。'; return }
  if (!pad.saved.length) { classPreviewMsg.value = '作业纸清单为空：到「作业纸内容」页保存作业纸后再预览。'; return }
  // D127：整班预览**只出当前作业包内的作业纸**（不再按 tag 从全库反推）
  if (!packStore.currentId) {
    classPreviewMsg.value = '未选择作业包：请先到「作业纸设计」页选择当前作业包（整班预览只出该包内的作业纸，'
      + '避免同一 tag 串到别的批次）。'
    return
  }
  const pk = classPackPads.value
  if (!pk.pads.length) {
    classPreviewMsg.value = `当前作业包「${packStore.currentId}」内没有可用的作业纸`
      + (pk.dangling.length ? `（包内引用的 ${pk.dangling.join('、')} 找不到，可能已删除）` : '')
      + '：请先在「作业纸设计」页把作业纸加入该包。'
    return
  }
  previewingClass.value = true
  try {
    const padJsons = classPadJsons()
    const { unmatchedNames, total } = buildClassInputs()
    classPreviewHtml.value = buildClassPreviewHtml()
    classPreviewManifest.value = buildBatchManifest(roster.students, padJsons)
    classPreviewUnmatched.value = unmatchedNames
    const unNames = unmatchedNames
    const unBrief = unNames.length
      ? `；未出页 ${unNames.length} 人（tag 未绑定或未选兜底变体）：${unNames.slice(0, 12).join('、')}${unNames.length > 12 ? ` 等 ${unNames.length} 人` : ''}`
      : ''
    // D93：学号缺失告警（无学号则无法按教务处名单排序）
    const noNum = roster.students.filter((x) => !String(x.number || '').trim()).length
    const numWarn = noNum
      ? `；⚠ ${noNum} 人无学号：整班顺序按学号排序将不完整，请在名单/成绩源补齐「学号」列`
      : ''
    const danglingWarn = pk.dangling.length
      ? `；⚠ 包内引用的 ${pk.dangling.join('、')} 找不到（可能已删除）` : ''
    classPreviewMsg.value = `已按当前作业包「${packStore.currentId}」内的 tag→作业纸绑定生成整班预览（同一打印模板：${total} 名学生 / ${pk.pads.length} 份作业纸映射${unBrief}${danglingWarn}；口径：${classIncludeAnswers.value ? '教师版（含答案）' : '学生版（不含答案）'}${numWarn}）：iframe 内可滚动查看，「🖨 打印」直接出整班文档。`
    showClassPreview.value = true
  } catch (e) {
    classPreviewMsg.value = `整班预览生成失败：${(e as Error).message}`
  } finally {
    previewingClass.value = false
  }
}

/** 打印当前整班 HTML（隐藏 iframe → contentWindow.print，与打印主通道同语义） */
/** D168-T13：整班输出的追溯 sidecar（打印/下载时同步产出）。
 *  教师习惯是"打印 PDF 保存"，PDF 本身零元数据；这份 JSON 记录
 *  「哪个包、哪些作业纸、发给哪些学生、谁什么 tag、用了哪些开关」。 */
function currentPackPadsBound(): Array<{ padId: string; tag: string }> {
  const out: Array<{ padId: string; tag: string }> = []
  for (const s of pad.saved) {
    try {
      const p = parseTaskpad(JSON.parse(s.json))
      out.push({ padId: s.id, tag: padInferredTag(p.items, p.target_tag) || '' })
    } catch { /* 损坏包忽略 */ }
  }
  return out
}

function makeClassSidecar(purpose: 'print' | 'download'): SheetSidecar | null {
  if (!roster.students.length) return null
  try {
    const pk = packStore.currentId
      ? { id: packStore.currentId, name: String(packStore.current?.name || '') }
      : { id: '', name: '' }
    const boundPads = currentPackPadsBound()
    const padByStudent: Record<string, string> = {}
    for (const st of roster.students) {
      const hit = boundPads.find((b) => b.tag && b.tag === (st.tag || ''))
      if (hit) padByStudent[st.name] = hit.padId
    }
    return buildSheetSidecar({
      packId: pk.id, packName: pk.name, purpose,
      pads: boundPads,
      students: roster.students.map((x) => ({
        name: x.name, number: x.number, tag: x.tag })),
      padByStudent,
      options: {
        includeAnswers: classIncludeAnswers.value,
        includeWatermark: classIncludeWatermark.value,
        includePageText: classIncludePageText.value,
      },
    })
  } catch {
    return null
  }
}

/** 写入 sidecar：已连目录则写同目录，否则下载（与 HTML 同批产出）。 */
function emitClassSidecar(purpose: 'print' | 'download') {
  const sc = makeClassSidecar(purpose)
  if (!sc) return
  const stamp = new Date().toISOString().slice(0, 10)
  const name = sidecarFileName(`class-sheet-${stamp}.html`)
  try {
    downloadData(JSON.stringify(sc, null, 1), name, 'application/json')
  } catch { /* 下载失败不阻断打印 */ }
}

function printClassPreview() {
  if (!classPreviewHtml.value) return
  emitClassSidecar('print')          // 先产出 sidecar，再打开打印对话框
  printSheetHtml(classPreviewHtml.value)
}

/** 下载 = 自包含 HTML（KaTeX 内联；资源拉取失败回退同源 relative 版） */
/** D57-1：开关变化时，已打开的预览实时重建（未打开则不动作）。 */
watch([classIncludeAnswers, classIncludeWatermark, classIncludePageText], () => {
  if (!showClassPreview.value || !roster.students.length || !pad.saved.length) return
  try {
    classPreviewHtml.value = buildClassPreviewHtml()
    classPreviewMsg.value = `已按新开关重建整班预览（口径：${classIncludeAnswers.value ? '教师版（含答案）' : '学生版（不含答案）'}）。`
  } catch { /* 保持原预览 */ }
})

async function downloadClassPreviewHtml() {
  if (!classPreviewHtml.value) return
  try {
    // D94-T2：下载同样按点名册顺序；自包含 KaTeX 内联（file:// 离线可开）
    const { fetchSelfContainedKatex } = await import('/home/bot2603/Projects/2609-assignment-assistant/app/src/lib/sheetHtml')
    const raw = await fetchSelfContainedKatex()
    const { html } = stringifyClassHtml(roster.students as SheetHtmlStudent[], classOrderResolver(), {
      includeSolution: classIncludeAnswers.value,
      includeWatermark: classIncludeWatermark.value,
      includePageText: classIncludePageText.value,
      wmAssets: settingsStore.wmAssets,
      wmStyles: settingsStore.wmStyles,
      figAssets: settingsStore.figAssets,
      katex: 'raw', katexRaw: raw,
    })
    downloadData(html, `class-sheet-preview-${new Date().toISOString().slice(0, 10)}.html`, 'text/html')
    emitClassSidecar('download')     // D168-T13：与 HTML 同批产出追溯 JSON
  } catch {
    downloadData(classPreviewHtml.value, `class-sheet-preview-${new Date().toISOString().slice(0, 10)}.html`, 'text/html')
    emitClassSidecar('download')
  }
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
  return `⚠ 以下 tag 没有任何作业纸绑定（预览中这些学生页会显示"未匹配变体"占位，引擎 batch 也会跳过）：${missing.map((t) => STUDENT_TAG_LABELS[t] ?? t).join('、')}——去「作业纸内容」页补绑定，或生成 batch 包时指定 --default 兜底。`
})

/** 宽表列数（预览按钮文案用） */
const pageCount = computed(() => roster.students.length)

const warnRatio = computed(() => roster.ratioSum > 1.0001)
const warnRatioOff = computed(() => Math.abs(roster.ratioSum - 1) > 0.0001 && roster.ratioSum <= 1.0001)

/* ---------- D94-T3：按加权成绩排序（仅视图；默认点名册顺序；无成绩者末尾） ---------- */
const overviewSort = ref<'roster' | 'desc' | 'asc'>('roster')
const labelSort = ref<'roster' | 'desc' | 'asc'>('roster')

/** 综合得分（干跑，不落库）：与总览"综合得分*"同口径；无成绩 = null。 */
function compositeScores(): Map<string, number | null> {
  const shadow = roster.students.map((s) => ({ ...s }))
  try { computeScoresFiltered(shadow, scoreSources.value.filter(isIncluded)) } catch { /* noop */ }
  return new Map(shadow.map((s) => [`${s.name}\u0000${s.number}`, s.score]))
}
/** 按 sort 生成索引顺序（保留原索引，供编辑回调）。 */
function sortedIdx<T extends { name: string; number: string }>(arr: T[], sort: 'roster' | 'desc' | 'asc'): number[] {
  const idx = arr.map((_, i) => i)
  if (sort === 'roster') return idx
  const comp = compositeScores()
  const scoreOf = (i: number) => comp.get(`${arr[i].name}\u0000${arr[i].number}`) ?? null
  return idx.slice().sort((a, b) => {
    const sa = scoreOf(a), sb = scoreOf(b)
    const ha = typeof sa === 'number', hb = typeof sb === 'number'
    if (ha && hb) { const d = (sa as number) - (sb as number); return sort === 'desc' ? -d : d }
    if (ha !== hb) return ha ? -1 : 1      // 有成绩者在前
    return a - b                            // 稳定
  })
}

function setTag(stuIdx: number, ev: Event) {
  const val = (ev.target as HTMLSelectElement).value
  roster.setManualTag(roster.students[stuIdx], val)
}

/** D94-T3：标签预览显示行（原索引 + 学生），按 labelSort。 */
const labelRows = computed<{ s: (typeof roster.students)[number]; i: number }[]>(() =>
  sortedIdx(roster.students, labelSort.value).map((i) => ({ s: roster.students[i], i })))
const batchNames = ref('')
const batchTag = ref('copy')
const batchCreateIfAbsent = ref(true)
const batchMsg = ref('')

// D40/D53-G1：translation 仅存两处入口——分组比例卡的随机拨给%（setTranslationRatio）+ 标签预览批量打 tag/学生表下拉（手动点名旧卡已删，与批量打 tag 同构）
const translationRatioPct = computed(() =>
  Math.round((roster.ratios.find((r) => r.tag === 'translation')?.ratio ?? 0) * 100)
)

function setTranslationRatio(v: string) {
  const g = roster.ratios.find((r) => r.tag === 'translation')
  if (g) g.ratio = Number(v) / 100 || 0
  roster.touch()
}


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
  if ((ev.target as HTMLInputElement).checked) {
    roster.setManualTag(stu, 'punish')
    return
  }
  // D56-I3：取消 punish 仅在"当前 tag 就是 punish"时清空；否则保留学生原有 tag（此前会误清）
  if (stu.tag === 'punish') roster.setManualTag(stu, '')
  else roster.touch()
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
    status.value = `作业纸导出失败：${(e as Error).message}`
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
    // D124：目录名用班级名（RosterClass.name），不再从 students[0].class 推断
    const curCls = roster.classes[roster.activeClassId]
    status.value = await roster.saveToDir(dirHandle.value, String(curCls?.name || ''))
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

const __returned__ = { roster, pad, kbStore, settingsStore, caps, status, activeClassDir, gradingPicker, gradingPacks, openGradingPicker, pickGradingPack, presetFamily, presetDesc, presetIsFixed, pickXlsx, rosterPreview, rosterPreviewFile, rosterFailNotice, clearAllAction, importRoster, wideFlash, renameCurrent, renameCurrentTerm, loadClassAction, deleteClassAction, rosterTagCountsOf, createClassAction, addSource, reparseSource, colToggleMsg, sourceRowPreview, sourceRowPreviewFile, sheetChoices, toggleSheetPicker, switchSourceSheet, previewSourceRow, snapshotPackId, snapshotMsg, snapshotBusy, snapshotPackOptions, freezeSnapshotIfChosen, recompute, overviewMsg, exportOverviewXlsx, scoreSources, wideHeaders, orderedWideRows, wideRows, checkedSummary, wideHint, tagBySingleColumn, toggleColumnInclude, setColumnWeight, showClassPreview, classPreviewHtml, classPreviewMsg, classPreviewManifest, previewingClass, classIncludeAnswers, classIncludeWatermark, classIncludePageText, classPreviewFallbackId, classPreviewUnmatched, packStore, classPackPads, classPadJsons, buildClassInputs, classOrderResolver, buildClassPreviewHtml, previewWholeClass, currentPackPadsBound, makeClassSidecar, emitClassSidecar, printClassPreview, downloadClassPreviewHtml, missingTagWarn, pageCount, warnRatio, warnRatioOff, overviewSort, labelSort, compositeScores, sortedIdx, setTag, labelRows, batchNames, batchTag, batchCreateIfAbsent, batchMsg, translationRatioPct, setTranslationRatio, applyBatchTag, setPunish, downloadRosterJsonAndXlsx, downloadTaskPackage, dirHandle, writeHint, saveToWorkspace, exportDisabled, summaryText, fixedSourceCount, nonTranslationRatios, get STUDENT_TAGS() { return STUDENT_TAGS }, get STUDENT_TAG_LABELS() { return STUDENT_TAG_LABELS }, get SCORE_FAMILY_PRESETS() { return SCORE_FAMILY_PRESETS }, get isFixedFamily() { return isFixedFamily }, get scoreFamilyDesc() { return scoreFamilyDesc }, PreviewTableCard }
Object.defineProperty(__returned__, '__isScriptSetup', { enumerable: false, value: true })
return __returned__
}

})
import { createCommentVNode as _createCommentVNode, createElementVNode as _createElementVNode, createTextVNode as _createTextVNode, toDisplayString as _toDisplayString, normalizeClass as _normalizeClass, openBlock as _openBlock, createElementBlock as _createElementBlock, renderList as _renderList, Fragment as _Fragment, vModelText as _vModelText, withDirectives as _withDirectives, createVNode as _createVNode, vModelSelect as _vModelSelect, createBlock as _createBlock, vModelCheckbox as _vModelCheckbox, normalizeStyle as _normalizeStyle, createStaticVNode as _createStaticVNode } from "vue"

const _hoisted_1 = { class: "roster-topbar" }
const _hoisted_2 = {
  key: 1,
  class: "hint",
  style: {"margin":"2px 0"}
}
const _hoisted_3 = {
  class: "card",
  id: "class-config"
}
const _hoisted_4 = { class: "field" }
const _hoisted_5 = ["value"]
const _hoisted_6 = { class: "field" }
const _hoisted_7 = ["value"]
const _hoisted_8 = {
  class: "hint",
  style: {"margin-left":"8px"}
}
const _hoisted_9 = {
  key: 0,
  class: "notice"
}
const _hoisted_10 = {
  key: 1,
  class: "notice info",
  style: {"margin-top":"6px"}
}
const _hoisted_11 = {
  class: "card",
  id: "roster-module"
}
const _hoisted_12 = {
  class: "hint",
  style: {"margin-left":"8px"}
}
const _hoisted_13 = {
  key: 0,
  class: "hint"
}
const _hoisted_14 = {
  key: 1,
  class: "table-scroll h320"
}
const _hoisted_15 = { class: "grid" }
const _hoisted_16 = ["onUpdate:modelValue"]
const _hoisted_17 = ["onUpdate:modelValue"]
const _hoisted_18 = ["onUpdate:modelValue"]
const _hoisted_19 = ["onClick"]
const _hoisted_20 = {
  key: 2,
  style: {"margin-top":"8px"}
}
const _hoisted_21 = { style: {"cursor":"pointer","font-size":"13px"} }
const _hoisted_22 = {
  class: "card",
  id: "score-module"
}
const _hoisted_23 = { class: "field" }
const _hoisted_24 = ["value"]
const _hoisted_25 = {
  key: 0,
  class: "notice",
  style: {"margin":"6px 0"}
}
const _hoisted_26 = {
  key: 0,
  class: "hint"
}
const _hoisted_27 = ["onClick"]
const _hoisted_28 = { class: "hint" }
const _hoisted_29 = {
  key: 1,
  class: "notice"
}
const _hoisted_30 = { class: "field" }
const _hoisted_31 = ["onUpdate:modelValue"]
const _hoisted_32 = ["title"]
const _hoisted_33 = ["value", "onChange"]
const _hoisted_34 = ["value"]
const _hoisted_35 = {
  key: 0,
  class: "hint",
  style: {"color":"var(--c-ok)"}
}
const _hoisted_36 = ["onClick"]
const _hoisted_37 = { class: "field" }
const _hoisted_38 = ["onUpdate:modelValue"]
const _hoisted_39 = ["value"]
const _hoisted_40 = { class: "field" }
const _hoisted_41 = ["onUpdate:modelValue"]
const _hoisted_42 = ["value"]
const _hoisted_43 = {
  key: 2,
  class: "field"
}
const _hoisted_44 = ["onUpdate:modelValue"]
const _hoisted_45 = { class: "hint" }
const _hoisted_46 = {
  key: 0,
  style: {"margin":"2px 0"}
}
const _hoisted_47 = { style: {"cursor":"pointer","font-size":"12px"} }
const _hoisted_48 = ["title"]
const _hoisted_49 = ["checked", "onChange"]
const _hoisted_50 = ["title"]
const _hoisted_51 = ["checked", "onChange"]
const _hoisted_52 = {
  key: 4,
  class: "hint"
}
const _hoisted_53 = ["onClick"]
const _hoisted_54 = ["value", "onChange"]
const _hoisted_55 = ["value"]
const _hoisted_56 = ["onClick"]
const _hoisted_57 = ["onClick"]
const _hoisted_58 = {
  key: 3,
  class: "hint"
}
const _hoisted_59 = {
  key: 4,
  class: "hint"
}
const _hoisted_60 = {
  key: 5,
  class: "hint"
}
const _hoisted_61 = {
  key: 0,
  class: "notice",
  style: {"border-color":"#c9a227","color":"#7a5c00"}
}
const _hoisted_62 = { style: {"display":"flex","gap":"6px","align-items":"center","flex-wrap":"wrap","margin":"0 0 6px"} }
const _hoisted_63 = { style: {"overflow":"auto","max-height":"420px","border":"1px solid var(--c-border)","border-radius":"8px"} }
const _hoisted_64 = { class: "grid score-wide-table" }
const _hoisted_65 = ["title"]
const _hoisted_66 = { class: "col-head" }
const _hoisted_67 = ["title"]
const _hoisted_68 = ["checked", "onChange"]
const _hoisted_69 = {
  key: 1,
  title: "教务点名册仅接表不计分（不可勾选）",
  style: {"color":"var(--c-muted)"}
}
const _hoisted_70 = { class: "col-name" }
const _hoisted_71 = {
  key: 2,
  class: "field",
  style: {"margin":"2px 0","font-size":"11px"},
  title: "D55-H3：该列权重（默认 1；综合分 = Σ原始分×权重 / Σ权重）"
}
const _hoisted_72 = ["value", "onChange"]
const _hoisted_73 = ["disabled", "onClick"]
const _hoisted_74 = { class: "sticky-col" }
const _hoisted_75 = { class: "sticky-col" }
const _hoisted_76 = ["title"]
const _hoisted_77 = ["title"]
const _hoisted_78 = { class: "hint" }
const _hoisted_79 = ["disabled"]
const _hoisted_80 = {
  key: 0,
  class: "hint",
  style: {"margin-left":"8px"}
}
const _hoisted_81 = {
  class: "card",
  id: "ratio-module"
}
const _hoisted_82 = ["value", "onChange"]
const _hoisted_83 = {
  class: "field",
  title: "D50b：translation 独立随机拨给比例（不占上行合计，docs/05-D24）"
}
const _hoisted_84 = ["value"]
const _hoisted_85 = { class: "hint" }
const _hoisted_86 = ["disabled"]
const _hoisted_87 = {
  class: "field",
  title: "D168：选中作业包后，本次 tag 结果会冻结成该包的「学生→tag」快照，批阅与统计都以快照为准（保证历史可复现）"
}
const _hoisted_88 = ["value"]
const _hoisted_89 = {
  key: 0,
  class: "hint",
  style: {"margin":"0"}
}
const _hoisted_90 = {
  key: 1,
  class: "hint",
  style: {"margin":"0"}
}
const _hoisted_91 = {
  key: 0,
  class: "hint"
}
const _hoisted_92 = { class: "hint" }
const _hoisted_93 = {
  class: "card",
  id: "tag-preview"
}
const _hoisted_94 = { style: {"display":"flex","gap":"6px","align-items":"center","flex-wrap":"wrap","margin":"0 0 6px"} }
const _hoisted_95 = {
  key: 0,
  class: "hint"
}
const _hoisted_96 = { class: "hint" }
const _hoisted_97 = {
  key: 1,
  class: "hint"
}
const _hoisted_98 = { class: "field" }
const _hoisted_99 = { class: "field" }
const _hoisted_100 = ["value"]
const _hoisted_101 = {
  class: "field",
  style: {"white-space":"nowrap"}
}
const _hoisted_102 = ["disabled"]
const _hoisted_103 = {
  key: 0,
  class: "hint"
}
const _hoisted_104 = {
  key: 2,
  open: "",
  style: {"margin-top":"6px"}
}
const _hoisted_105 = { style: {"cursor":"pointer","font-size":"13px"} }
const _hoisted_106 = { class: "table-scroll h360" }
const _hoisted_107 = {
  class: "grid",
  style: {"font-size":"12px"}
}
const _hoisted_108 = ["value", "onChange"]
const _hoisted_109 = ["value"]
const _hoisted_110 = { style: {"text-align":"center"} }
const _hoisted_111 = ["checked", "onChange"]
const _hoisted_112 = {
  key: 3,
  class: "notice"
}
const _hoisted_113 = {
  key: 4,
  class: "notice info",
  style: {"margin-top":"6px"}
}
const _hoisted_114 = {
  class: "card",
  id: "output-module"
}
const _hoisted_115 = ["disabled"]
const _hoisted_116 = ["disabled"]
const _hoisted_117 = {
  class: "hint",
  style: { marginTop: '4px' }
}
const _hoisted_118 = { key: 0 }
const _hoisted_119 = {
  key: 0,
  class: "hint"
}
const _hoisted_120 = { class: "card" }
const _hoisted_121 = {
  class: "hint",
  style: {"margin":"4px 0"}
}
const _hoisted_122 = {
  class: "field",
  title: "D57-1：不勾=学生版（预览/打印/下载均不含『参考答案：』行）；勾选=教师版"
}
const _hoisted_123 = {
  class: "field",
  title: "D57-1：整班输出的水印图层开关（默认勾选=现状）"
}
const _hoisted_124 = {
  class: "field",
  title: "D57-1：整班输出的页码大字开关（默认勾选=现状）"
}
const _hoisted_125 = { class: "hint" }
const _hoisted_126 = ["disabled"]
const _hoisted_127 = ["disabled"]
const _hoisted_128 = ["disabled"]
const _hoisted_129 = {
  key: 0,
  class: "hint"
}
const _hoisted_130 = {
  key: 1,
  class: "hint"
}
const _hoisted_131 = {
  key: 0,
  class: "hint"
}
const _hoisted_132 = ["value"]
const _hoisted_133 = {
  key: 1,
  class: "hint notice warning"
}
const _hoisted_134 = {
  key: 2,
  class: "hint"
}
const _hoisted_135 = {
  key: 3,
  open: "",
  style: {"margin":"6px 0"}
}
const _hoisted_136 = {
  class: "hint",
  style: {"white-space":"pre-wrap","font-size":"11px","background":"var(--c-bg,#f7f7f9)","padding":"8px","border-radius":"6px"}
}
const _hoisted_137 = ["srcdoc"]
const _hoisted_138 = {
  class: "card",
  id: "class-list"
}
const _hoisted_139 = {
  key: 0,
  class: "grid",
  style: {"font-size":"12px"}
}
const _hoisted_140 = {
  key: 0,
  class: "hint"
}
const _hoisted_141 = { style: {"text-align":"center"} }
const _hoisted_142 = { style: {"font-size":"11px"} }
const _hoisted_143 = { style: {"text-align":"center"} }
const _hoisted_144 = { style: {"font-size":"11px","max-width":"180px","word-break":"break-all"} }
const _hoisted_145 = { style: {"white-space":"nowrap"} }
const _hoisted_146 = ["disabled", "onClick"]
const _hoisted_147 = ["disabled", "onClick"]
const _hoisted_148 = {
  key: 1,
  class: "hint"
}
const _hoisted_149 = {
  key: 2,
  class: "hint"
}

export function render(_ctx, _cache, $props, $setup, $data, $options) {
  return (_openBlock(), _createElementBlock("section", null, [
    _createCommentVNode(" D50b 段内锚点导航（与作业纸设计页 D45 同风格） "),
    _createElementVNode("div", _hoisted_1, [
      _cache[28] || (_cache[28] = _createStaticVNode("<p class=\"design-anchors\"><a href=\"#class-config\">班级配置</a> · <a href=\"#roster-module\">① 名单</a> · <a href=\"#score-module\">② 成绩源/总览</a> · <a href=\"#ratio-module\">③ 比例→标签预览</a> · <a href=\"#output-module\">④ 产出</a> · <a href=\"#class-list\">班级清单</a></p>", 1)),
      ($setup.status)
        ? (_openBlock(), _createElementBlock("p", {
            key: 0,
            class: _normalizeClass(["roster-status", { 'status-fail': $setup.rosterFailNotice }])
          }, _toDisplayString($setup.status), 3 /* TEXT, CLASS */))
        : _createCommentVNode("v-if", true),
      _createCommentVNode(" D120：自动写盘结果（保存即落盘到 <ws>/<班级>/roster/roster.xlsx；失败不静默） "),
      ($setup.roster.persistMsg)
        ? (_openBlock(), _createElementBlock("p", _hoisted_2, " 名单落盘：" + _toDisplayString($setup.roster.persistMsg), 1 /* TEXT */))
        : _createCommentVNode("v-if", true)
    ]),
    _cache[100] || (_cache[100] = _createElementVNode("p", {
      class: "hint",
      style: {"margin-top":"0"}
    }, [
      _createTextVNode(" 名单列自适应（姓名|name、学号|number、班级|class、tag|tag）；成绩源支持"),
      _createElementVNode("b", null, "格式预设"),
      _createTextVNode(" （docs/05-D19：固定四类教务/学习通/雨课堂 + custom）；综合得分 = 多源加权归一均值； 分组比例自动切分 tag；「标签预览」卡随时人工覆盖（special_tag_cfg，D50b 更名）。 "),
      _createElementVNode("b", null, "D50b 卡序"),
      _createTextVNode("：班级配置 → ①名单 → ②成绩源+总览 → ③分组比例(含 translation 随机拨给%)→标签预览 → ④产出 → 整班作业纸预览 → 班级清单。 S2b 预览整合（docs/14 §VC）：名单/成绩导入预览卡 + 成绩源宽表（勾选=分层依据，默认全勾） + 整班作业纸预览（纯前端 overlay，不依赖引擎）。 ")
    ], -1 /* CACHED */)),
    _createCommentVNode(" ============ D49-F2 班级配置栏（班级为中心重设计） ============ "),
    _createElementVNode("div", _hoisted_3, [
      _cache[31] || (_cache[31] = _createElementVNode("h2", null, [
        _createTextVNode("班级配置 "),
        _createElementVNode("small", { style: {"font-weight":"400","color":"var(--c-muted)"} }, "当前工作区 = 载入的班级（docs/13 D49）")
      ], -1 /* CACHED */)),
      _createElementVNode("p", null, [
        _createElementVNode("label", _hoisted_4, [
          _cache[29] || (_cache[29] = _createTextVNode("班级名称：", -1 /* CACHED */)),
          _createElementVNode("input", {
            type: "text",
            value: $setup.roster.activeMeta?.name ?? '',
            onChange: _cache[0] || (_cache[0] = $event => ($setup.renameCurrent(($event.target as HTMLInputElement).value))),
            style: {"width":"180px"}
          }, null, 40 /* PROPS, NEED_HYDRATION */, _hoisted_5)
        ]),
        _createElementVNode("label", _hoisted_6, [
          _cache[30] || (_cache[30] = _createTextVNode("学期：", -1 /* CACHED */)),
          _createElementVNode("input", {
            type: "text",
            value: $setup.roster.activeMeta?.term ?? '',
            placeholder: "2026S1",
            onChange: _cache[1] || (_cache[1] = $event => ($setup.renameCurrentTerm(($event.target as HTMLInputElement).value))),
            style: {"width":"110px"}
          }, null, 40 /* PROPS, NEED_HYDRATION */, _hoisted_7)
        ]),
        _createElementVNode("button", {
          class: "btn",
          onClick: $setup.createClassAction
        }, "＋新建班级"),
        _createElementVNode("button", {
          class: "btn primary",
          style: {"margin-left":"8px"},
          onClick: _cache[2] || (_cache[2] = $event => {$setup.roster.persist(); $setup.status = '已保存当前班级'})
        }, "💾 保存班级"),
        _createElementVNode("span", _hoisted_8, "人数 " + _toDisplayString($setup.roster.students.length) + " · 源 " + _toDisplayString($setup.roster.sources.length) + " · 产出 " + _toDisplayString($setup.roster.activeMeta?.artifacts.length ?? 0), 1 /* TEXT */)
      ]),
      _cache[32] || (_cache[32] = _createElementVNode("p", { class: "hint" }, "名单/成绩/标签/产出各模块都作用于当前班级；切换班级用页面底部「班级清单」。数据自动保存在本浏览器（D49 v2 多班级存储，老数据已自动迁入\"默认班级\"）。", -1 /* CACHED */))
    ]),
    (!$setup.caps.full && $setup.caps.browserHint)
      ? (_openBlock(), _createElementBlock("div", _hoisted_9, _toDisplayString($setup.caps.browserHint), 1 /* TEXT */))
      : _createCommentVNode("v-if", true),
    ($setup.caps.insecure)
      ? (_openBlock(), _createElementBlock("div", _hoisted_10, " 当前为局域网预览（http://IP，非安全上下文）：导入名单/成绩/题库均可用（文件选择方式）； \"写回 workspace 目录\"不可用——请用下方导出按钮下载文件，教师手动放回 workspace。 " + _toDisplayString($setup.writeHint), 1 /* TEXT */))
      : _createCommentVNode("v-if", true),
    _createCommentVNode(" ============ D50b ① 名单模块（导入/手动/基本表 + 名单预览） ============ "),
    _createElementVNode("div", _hoisted_11, [
      _cache[34] || (_cache[34] = _createElementVNode("h2", null, [
        _createTextVNode("名单 "),
        _createElementVNode("small", { style: {"font-weight":"400","color":"var(--c-muted)"} }, "教务点名册 / 姓名列表 / 手动输入（docs/13 D50b：名单模块独立成卡）")
      ], -1 /* CACHED */)),
      _createElementVNode("p", null, [
        _createElementVNode("button", {
          class: "btn primary",
          onClick: $setup.importRoster
        }, "📥 导入名单 xlsx/xls/csv…"),
        _createElementVNode("button", {
          class: "btn",
          style: {"margin-left":"8px"},
          onClick: _cache[3] || (_cache[3] = $event => ($setup.roster.addStudent()))
        }, "＋手动添加学生"),
        ($setup.roster.students.length)
          ? (_openBlock(), _createElementBlock("button", {
              key: 0,
              class: "btn",
              style: {"margin-left":"8px"},
              onClick: $setup.clearAllAction
            }, "清空全部"))
          : _createCommentVNode("v-if", true),
        _createElementVNode("span", _hoisted_12, "当前 " + _toDisplayString($setup.roster.students.length) + " 人", 1 /* TEXT */)
      ]),
      (!$setup.roster.students.length)
        ? (_openBlock(), _createElementBlock("p", _hoisted_13, "尚无学生：导入教务点名册（表头自适应→关键词找表头行两级回退，zjxu 名册/无表头说明文字形态均可读，docs/13 D46-1/E5）或手动添加。"))
        : _createCommentVNode("v-if", true),
      ($setup.roster.students.length)
        ? (_openBlock(), _createElementBlock("div", _hoisted_14, [
            _createElementVNode("table", _hoisted_15, [
              _cache[33] || (_cache[33] = _createElementVNode("thead", null, [
                _createElementVNode("tr", null, [
                  _createElementVNode("th", { style: {"width":"140px"} }, "姓名"),
                  _createElementVNode("th", { style: {"width":"170px"} }, "学号"),
                  _createElementVNode("th", { style: {"width":"170px"} }, "班级"),
                  _createElementVNode("th", { style: {"width":"40px"} })
                ])
              ], -1 /* CACHED */)),
              _createElementVNode("tbody", null, [
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.roster.students, (s, i) => {
                  return (_openBlock(), _createElementBlock("tr", { key: i }, [
                    _createElementVNode("td", null, [
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": $event => ((s.name) = $event),
                        onChange: _cache[4] || (_cache[4] = $event => ($setup.roster.touch()))
                      }, null, 40 /* PROPS, NEED_HYDRATION */, _hoisted_16), [
                        [_vModelText, s.name]
                      ])
                    ]),
                    _createElementVNode("td", null, [
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": $event => ((s.number) = $event),
                        onChange: _cache[5] || (_cache[5] = $event => ($setup.roster.touch()))
                      }, null, 40 /* PROPS, NEED_HYDRATION */, _hoisted_17), [
                        [_vModelText, s.number]
                      ])
                    ]),
                    _createElementVNode("td", null, [
                      _withDirectives(_createElementVNode("input", {
                        "onUpdate:modelValue": $event => ((s.class) = $event),
                        onChange: _cache[6] || (_cache[6] = $event => ($setup.roster.touch()))
                      }, null, 40 /* PROPS, NEED_HYDRATION */, _hoisted_18), [
                        [_vModelText, s.class]
                      ])
                    ]),
                    _createElementVNode("td", null, [
                      _createElementVNode("button", {
                        class: "btn small",
                        onClick: $event => ($setup.roster.removeStudent(i)),
                        title: "移除此学生"
                      }, "✕", 8 /* PROPS */, _hoisted_19)
                    ])
                  ]))
                }), 128 /* KEYED_FRAGMENT */))
              ])
            ])
          ]))
        : _createCommentVNode("v-if", true),
      _cache[35] || (_cache[35] = _createElementVNode("p", {
        class: "hint",
        style: {"margin-top":"6px"}
      }, " 提示：改名/改学号后，各成绩源按姓名匹配的分数不会自动重映射——改动后请到对应成绩源行点「重解析」并核对列映射。 ", -1 /* CACHED */)),
      ($setup.rosterPreview)
        ? (_openBlock(), _createElementBlock("details", _hoisted_20, [
            _createElementVNode("summary", _hoisted_21, "查看导入文件原文预览（" + _toDisplayString($setup.rosterPreview.rowCount) + " 行 · 点击展开，表内滚轮查看）", 1 /* TEXT */),
            _createVNode($setup["PreviewTableCard"], {
              title: "名单原始文件预览",
              preview: $setup.rosterPreview,
              "file-name": $setup.rosterPreviewFile,
              tone: "ok"
            }, null, 8 /* PROPS */, ["preview", "file-name"])
          ]))
        : _createCommentVNode("v-if", true)
    ]),
    _createElementVNode("div", _hoisted_22, [
      _cache[45] || (_cache[45] = _createStaticVNode("<h2>成绩源（格式预设 + 任意 xlsx，docs/05-D19）</h2><p class=\"hint\"> 先选<b>格式预设</b>再选文件：固定四类按格式语义自动定位列；custom（自定义）可手动多选列。 <b>D55-H3 口径</b>：每源可勾选<b>多列</b>，综合得分 = <code>Σ(列原始分 × 列权重) / Σ列权重</code> （<b>不做班内最高分归一</b>；单列/等权即原始分；列权重在下方总览表头逐列可调，默认 1）。 <b>VC-5</b>：取消勾选源/列 = 该源/列不进总览与加权（score excluding）。 </p>", 2)),
      _createElementVNode("p", null, [
        _createElementVNode("label", _hoisted_23, [
          _cache[36] || (_cache[36] = _createTextVNode("格式预设： ", -1 /* CACHED */)),
          _withDirectives(_createElementVNode("select", {
            "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => (($setup.presetFamily) = $event)),
            style: {"min-width":"230px"}
          }, [
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.SCORE_FAMILY_PRESETS.filter((x) => x.value !== 'roster'), (p) => {
              return (_openBlock(), _createElementBlock("option", {
                key: p.value,
                value: p.value
              }, _toDisplayString(p.label), 9 /* TEXT, PROPS */, _hoisted_24))
            }), 128 /* KEYED_FRAGMENT */))
          ], 512 /* NEED_PATCH */), [
            [_vModelSelect, $setup.presetFamily]
          ])
        ]),
        _createElementVNode("button", {
          class: "btn primary",
          style: {"margin-left":"8px"},
          onClick: $setup.addSource
        }, "＋添加成绩源（选 xlsx）"),
        _createElementVNode("button", {
          class: "btn",
          style: {"margin-left":"8px"},
          onClick: $setup.openGradingPicker
        }, " ＋加入 AI 批阅成绩 ")
      ]),
      _createCommentVNode(" D149：选一次作业包 → 作为一列成绩（未批阅/未提交记 0 分） "),
      ($setup.gradingPicker)
        ? (_openBlock(), _createElementBlock("div", _hoisted_25, [
            _cache[37] || (_cache[37] = _createElementVNode("p", {
              class: "hint",
              style: {"margin":"0 0 4px"}
            }, " 选择要作为成绩的作业包（该班级下有评阅结果的）： ", -1 /* CACHED */)),
            (!$setup.gradingPacks.length)
              ? (_openBlock(), _createElementBlock("p", _hoisted_26, "（该班级还没有任何批阅结果。）"))
              : _createCommentVNode("v-if", true),
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.gradingPacks, (g) => {
              return (_openBlock(), _createElementBlock("p", {
                key: g.packId,
                style: {"margin":"2px 0"}
              }, [
                _createElementVNode("button", {
                  class: "btn small",
                  onClick: $event => ($setup.pickGradingPack(g))
                }, " ＋ " + _toDisplayString(g.name), 9 /* TEXT, PROPS */, _hoisted_27),
                _createElementVNode("span", _hoisted_28, _toDisplayString(g.graded) + " 人已评阅" + _toDisplayString(g.at ? ' · ' + g.at : ''), 1 /* TEXT */)
              ]))
            }), 128 /* KEYED_FRAGMENT */)),
            _createElementVNode("button", {
              class: "btn small",
              style: {"margin-top":"4px"},
              onClick: _cache[8] || (_cache[8] = $event => ($setup.gradingPicker = false))
            }, "取消")
          ]))
        : _createCommentVNode("v-if", true),
      _createElementVNode("p", {
        class: _normalizeClass(["hint", { notice: $setup.presetIsFixed }]),
        style: {"margin-top":"2px"}
      }, [
        ($setup.presetIsFixed)
          ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
              _createTextVNode("这是固定格式（来自" + _toDisplayString($setup.presetFamily === 'rainclass' ? '雨课堂' : $setup.presetFamily.startsWith('xuexitong') ? '学习通' : '教务') + "导出）——无需选列，自动按列名语义解析。说明：" + _toDisplayString($setup.presetDesc), 1 /* TEXT */)
            ], 64 /* STABLE_FRAGMENT */))
          : (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
              _createTextVNode(_toDisplayString($setup.presetDesc), 1 /* TEXT */)
            ], 64 /* STABLE_FRAGMENT */))
      ], 2 /* CLASS */),
      (!$setup.roster.sources.length)
        ? (_openBlock(), _createElementBlock("div", _hoisted_29, "尚无成绩源：可只导名单不打 tag（tag 列留空），或添加若干成绩源后「重算并打 tag」。"))
        : _createCommentVNode("v-if", true),
      _cache[46] || (_cache[46] = _createElementVNode("p", {
        class: "hint",
        style: {"margin-top":"2px"}
      }, [
        _createTextVNode(" D55-H3：每源可勾选"),
        _createElementVNode("b", null, "多列"),
        _createTextVNode("（勾选框见各行）——每勾一列即成为总览的一列并参与加权； "),
        _createElementVNode("b", null, "每列权重在总览表头逐列可调"),
        _createTextVNode("（默认 1）。综合 = Σ(原始分×权重)/Σ权重，不做班内最高分归一。 ")
      ], -1 /* CACHED */)),
      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.roster.sources, (s, i) => {
        return (_openBlock(), _createElementBlock("p", {
          key: i,
          class: "hint",
          style: {"border-bottom":"1px dashed var(--c-border)","padding":"6px 0"}
        }, [
          _createElementVNode("label", _hoisted_30, [
            _cache[38] || (_cache[38] = _createTextVNode("源名：", -1 /* CACHED */)),
            _withDirectives(_createElementVNode("input", {
              type: "text",
              "onUpdate:modelValue": $event => ((s.name) = $event),
              style: {"width":"150px"},
              onChange: _cache[9] || (_cache[9] = $event => ($setup.roster.touch()))
            }, null, 40 /* PROPS, NEED_HYDRATION */, _hoisted_31), [
              [_vModelText, s.name]
            ])
          ]),
          _createElementVNode("label", {
            class: "field",
            title: $setup.scoreFamilyDesc(s.family)
          }, [
            _cache[39] || (_cache[39] = _createTextVNode("格式预设： ", -1 /* CACHED */)),
            _createElementVNode("select", {
              value: s.family,
              onChange: $event => ($setup.roster.setSourceFamily(i, (($event.target as HTMLSelectElement).value) as ScoreFamily, null)),
              style: {"max-width":"190px"}
            }, [
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.SCORE_FAMILY_PRESETS.filter((x) => x.value !== 'roster'), (p) => {
                return (_openBlock(), _createElementBlock("option", {
                  key: p.value,
                  value: p.value
                }, _toDisplayString(p.label), 9 /* TEXT, PROPS */, _hoisted_34))
              }), 128 /* KEYED_FRAGMENT */))
            ], 40 /* PROPS, NEED_HYDRATION */, _hoisted_33)
          ], 8 /* PROPS */, _hoisted_32),
          ($setup.isFixedFamily(s.family))
            ? (_openBlock(), _createElementBlock("span", _hoisted_35, [
                _createTextVNode(" 固定格式（来自" + _toDisplayString(s.family === 'rainclass' ? '雨课堂' : s.family.startsWith('xuexitong') ? '学习通' : '教务') + "导出）· " + _toDisplayString(s.family === 'roster' ? '仅接表，不计分' : `分数列：${s.scoreColumn}`) + " ", 1 /* TEXT */),
                _createElementVNode("button", {
                  class: "btn small",
                  style: {"margin-left":"4px"},
                  title: "用 IndexedDB 原始文件按当前格式预设重新解析（D46-3，免二次选文件；无留存时回退为选文件）",
                  onClick: $event => ($setup.reparseSource(i))
                }, "重解析", 8 /* PROPS */, _hoisted_36)
              ]))
            : (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                _createElementVNode("label", _hoisted_37, [
                  _cache[40] || (_cache[40] = _createTextVNode("分数来源列： ", -1 /* CACHED */)),
                  _withDirectives(_createElementVNode("select", {
                    "onUpdate:modelValue": $event => ((s.scoreColumn) = $event),
                    onChange: _cache[10] || (_cache[10] = $event => ($setup.roster.touch()))
                  }, [
                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(Object.keys(s.rows[0] ?? {}), (h) => {
                      return (_openBlock(), _createElementBlock("option", {
                        key: h,
                        value: h
                      }, _toDisplayString(h), 9 /* TEXT, PROPS */, _hoisted_39))
                    }), 128 /* KEYED_FRAGMENT */))
                  ], 40 /* PROPS, NEED_HYDRATION */, _hoisted_38), [
                    [_vModelSelect, s.scoreColumn]
                  ])
                ]),
                _createElementVNode("label", _hoisted_40, [
                  _cache[41] || (_cache[41] = _createTextVNode("姓名列： ", -1 /* CACHED */)),
                  _withDirectives(_createElementVNode("select", {
                    "onUpdate:modelValue": $event => ((s.nameColumn) = $event),
                    onChange: _cache[11] || (_cache[11] = $event => ($setup.roster.touch()))
                  }, [
                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(Object.keys(s.rows[0] ?? {}), (h) => {
                      return (_openBlock(), _createElementBlock("option", {
                        key: h,
                        value: h
                      }, _toDisplayString(h), 9 /* TEXT, PROPS */, _hoisted_42))
                    }), 128 /* KEYED_FRAGMENT */))
                  ], 40 /* PROPS, NEED_HYDRATION */, _hoisted_41), [
                    [_vModelSelect, s.nameColumn]
                  ])
                ])
              ], 64 /* STABLE_FRAGMENT */)),
          (s.family !== 'roster')
            ? (_openBlock(), _createElementBlock("label", _hoisted_43, [
                _cache[42] || (_cache[42] = _createTextVNode("权重：", -1 /* CACHED */)),
                _withDirectives(_createElementVNode("input", {
                  type: "number",
                  "onUpdate:modelValue": $event => ((s.weight) = $event),
                  min: "0.1",
                  step: "0.1",
                  style: {"width":"70px"},
                  onChange: _cache[12] || (_cache[12] = $event => ($setup.roster.touch()))
                }, null, 40 /* PROPS, NEED_HYDRATION */, _hoisted_44), [
                  [
                    _vModelText,
                    s.weight,
                    void 0,
                    { number: true }
                  ]
                ])
              ]))
            : _createCommentVNode("v-if", true),
          _createElementVNode("span", _hoisted_45, [
            _createTextVNode(_toDisplayString(s.rows.length) + " 行 · " + _toDisplayString(s.fileName), 1 /* TEXT */),
            (s.sheetName)
              ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                  _createTextVNode(" · sheet=" + _toDisplayString(s.sheetName), 1 /* TEXT */)
                ], 64 /* STABLE_FRAGMENT */))
              : _createCommentVNode("v-if", true)
          ]),
          ((s.allNumericColumns ?? []).length)
            ? (_openBlock(), _createElementBlock(_Fragment, { key: 3 }, [
                ((s.allNumericColumns ?? []).length > 6)
                  ? (_openBlock(), _createElementBlock("details", _hoisted_46, [
                      _createElementVNode("summary", _hoisted_47, " 列勾选（共 " + _toDisplayString(s.allNumericColumns!.length) + " 列，已勾 " + _toDisplayString((s.includedColumns ?? []).length) + " 列；点击展开逐列选择） ", 1 /* TEXT */),
                      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList((s.allNumericColumns ?? []), (c) => {
                        return (_openBlock(), _createElementBlock("label", {
                          key: c.name,
                          class: "field",
                          style: {"margin-right":"8px","font-size":"12px"},
                          title: `D55-H3：${(s.includedColumns ?? []).some((ic) => ic.name === c.name) ? '已勾选（进总览与加权，权重见总览表头）' : '未勾选（不出现在总览）'}`
                        }, [
                          _createElementVNode("input", {
                            type: "checkbox",
                            checked: (s.includedColumns ?? []).some((ic) => ic.name === c.name),
                            onChange: $event => ($setup.colToggleMsg(i, c.name))
                          }, null, 40 /* PROPS, NEED_HYDRATION */, _hoisted_49),
                          _createTextVNode(" " + _toDisplayString(c.name), 1 /* TEXT */)
                        ], 8 /* PROPS */, _hoisted_48))
                      }), 128 /* KEYED_FRAGMENT */))
                    ]))
                  : (_openBlock(true), _createElementBlock(_Fragment, { key: 1 }, _renderList((s.allNumericColumns ?? []), (c) => {
                      return (_openBlock(), _createElementBlock("label", {
                        key: c.name,
                        class: "field",
                        style: {"margin-right":"8px"},
                        title: `D55-H3：${(s.includedColumns ?? []).some((ic) => ic.name === c.name) ? '已勾选（进总览与加权，权重见总览表头）' : '未勾选（不出现在总览）'}`
                      }, [
                        _createElementVNode("input", {
                          type: "checkbox",
                          checked: (s.includedColumns ?? []).some((ic) => ic.name === c.name),
                          onChange: $event => ($setup.colToggleMsg(i, c.name))
                        }, null, 40 /* PROPS, NEED_HYDRATION */, _hoisted_51),
                        _createTextVNode(" " + _toDisplayString(c.name), 1 /* TEXT */)
                      ], 8 /* PROPS */, _hoisted_50))
                    }), 128 /* KEYED_FRAGMENT */))
              ], 64 /* STABLE_FRAGMENT */))
            : (_openBlock(), _createElementBlock("span", _hoisted_52, "（旧数据源：点「重解析」一次即可启用多列勾选与逐列权重）")),
          _createElementVNode("button", {
            class: "btn small",
            style: {"margin-left":"4px"},
            title: "D46-3：用留存原始文件即时重建解析预览（表头+前3行+定位说明）",
            onClick: $event => ($setup.previewSourceRow(i))
          }, "👁 预览", 8 /* PROPS */, _hoisted_53),
          ($setup.sheetChoices[i])
            ? (_openBlock(), _createElementBlock("select", {
                key: 5,
                style: {"margin-left":"4px"},
                value: s.sheetName,
                onChange: $event => ($setup.switchSourceSheet(i, $event)),
                title: "B1：该源原始文件含多张 sheet——切换后按当前格式预设重新解析"
              }, [
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.sheetChoices[i], (n) => {
                  return (_openBlock(), _createElementBlock("option", {
                    key: n,
                    value: n
                  }, _toDisplayString(n), 9 /* TEXT, PROPS */, _hoisted_55))
                }), 128 /* KEYED_FRAGMENT */))
              ], 40 /* PROPS, NEED_HYDRATION */, _hoisted_54))
            : (_openBlock(), _createElementBlock("button", {
                key: 6,
                class: "btn small",
                style: {"margin-left":"4px"},
                title: "B1：多 sheet 文件切换数据表（需原始文件留存；单 sheet/无留存时给出提示）",
                onClick: $event => ($setup.toggleSheetPicker(i))
              }, "⇄ sheet", 8 /* PROPS */, _hoisted_56)),
          _createElementVNode("button", {
            class: "btn small",
            style: {"margin-left":"4px"},
            onClick: $event => ($setup.roster.removeSource(i))
          }, "移除", 8 /* PROPS */, _hoisted_57)
        ]))
      }), 128 /* KEYED_FRAGMENT */)),
      ($setup.sourceRowPreview)
        ? (_openBlock(), _createBlock($setup["PreviewTableCard"], {
            key: 2,
            title: "成绩源解析预览（D47 全文件模式：可滚动到最大 500 行；sheet 切换见 ⇄）",
            preview: $setup.sourceRowPreview,
            "file-name": $setup.sourceRowPreviewFile,
            tone: "ok"
          }, null, 8 /* PROPS */, ["preview", "file-name"]))
        : _createCommentVNode("v-if", true),
      ($setup.fixedSourceCount)
        ? (_openBlock(), _createElementBlock("p", _hoisted_58, [
            _createTextVNode("已按固定格式解析的成绩源 ×" + _toDisplayString($setup.fixedSourceCount) + "（score_sources[].family 将随作业纸导出，与 engine CLI ", 1 /* TEXT */),
            _cache[43] || (_cache[43] = _createElementVNode("code", null, "--score family:file[:col[:weight]]", -1 /* CACHED */)),
            _cache[44] || (_cache[44] = _createTextVNode(" 同口径）。", -1 /* CACHED */))
          ]))
        : _createCommentVNode("v-if", true),
      ($setup.scoreSources.length)
        ? (_openBlock(), _createElementBlock("p", _hoisted_59, _toDisplayString($setup.checkedSummary), 1 /* TEXT */))
        : _createCommentVNode("v-if", true),
      ($setup.scoreSources.length)
        ? (_openBlock(), _createElementBlock("p", _hoisted_60, _toDisplayString($setup.wideHint), 1 /* TEXT */))
        : _createCommentVNode("v-if", true)
    ]),
    ($setup.scoreSources.length)
      ? (_openBlock(), _createElementBlock("div", {
          key: 2,
          class: _normalizeClass(["card", { 'wide-flash': $setup.wideFlash }]),
          id: "wide-table"
        }, [
          (!$setup.roster.students.length)
            ? (_openBlock(), _createElementBlock("div", _hoisted_61, " ⚠ 名单尚未导入（总览无行可显示）——请点上方「导入名单 xlsx…」导入教务点名册/姓名列表（docs/13 D48 单写路径： 无论从哪个入口导入，名单都会写入）。 "))
            : _createCommentVNode("v-if", true),
          _cache[57] || (_cache[57] = _createElementVNode("h2", null, "全部成绩总览（D46-4：每生一行 × 各源分数列 × 综合得分 · 勾选 = 是否参与综合）", -1 /* CACHED */)),
          _createElementVNode("p", _hoisted_62, [
            _cache[47] || (_cache[47] = _createElementVNode("span", {
              class: "hint",
              style: {"margin":"0"}
            }, "显示顺序：", -1 /* CACHED */)),
            _createElementVNode("button", {
              class: _normalizeClass(["btn small", { primary: $setup.overviewSort === 'roster' }]),
              onClick: _cache[13] || (_cache[13] = $event => ($setup.overviewSort = 'roster'))
            }, "点名册顺序", 2 /* CLASS */),
            _createElementVNode("button", {
              class: _normalizeClass(["btn small", { primary: $setup.overviewSort === 'desc' }]),
              onClick: _cache[14] || (_cache[14] = $event => ($setup.overviewSort = 'desc'))
            }, "加权成绩 ↓ 降序", 2 /* CLASS */),
            _createElementVNode("button", {
              class: _normalizeClass(["btn small", { primary: $setup.overviewSort === 'asc' }]),
              onClick: _cache[15] || (_cache[15] = $event => ($setup.overviewSort = 'asc'))
            }, "加权成绩 ↑ 升序", 2 /* CLASS */),
            _cache[48] || (_cache[48] = _createElementVNode("span", {
              class: "hint",
              style: {"margin":"0"}
            }, "（仅影响显示，不改名单顺序；无成绩者排末尾）", -1 /* CACHED */))
          ]),
          _cache[58] || (_cache[58] = _createStaticVNode("<p class=\"notice info\" style=\"margin:0 0 6px;\"><b>综合得分算法（D55-H3 拍板）</b>：<code>综合 = Σ(列原始分 × 列权重) / Σ列权重</code> —— 只统计「已勾选」的列；<b>不做班内最高分归一</b>；单列（或全权重=1）时即该列原始分。 与引擎 <code>assist roster tag</code>（merge_scores 原始分加权平均）同口径；列权重在每列表头可调（默认 1）。 </p><p class=\"hint\"> 每行 = 一名学生，每列 = 一个已添加成绩源（<b>分数列</b>）+ 末列<b>综合得分</b>（随勾选即时重算预览， 正式写入需点「重算并打 tag」）；可横向滚动。 每列<b>默认勾选 ✅</b>（includeInAggregation=true，等价&quot;此列作为分层依据&quot;多选叠加）； 取消勾选的源<b>被排除出综合得分</b>（score excluding，重算时跳过），其分数值仍灰显可见（排除≠删除）； roster 接表源仅接表不计分（列头&quot;—&quot;不可勾）。 </p>", 2)),
          _createElementVNode("div", _hoisted_63, [
            _createElementVNode("table", _hoisted_64, [
              _createElementVNode("thead", null, [
                _createElementVNode("tr", null, [
                  _cache[51] || (_cache[51] = _createElementVNode("th", { class: "sticky-col" }, "姓名", -1 /* CACHED */)),
                  _cache[52] || (_cache[52] = _createElementVNode("th", { class: "sticky-col" }, "学号", -1 /* CACHED */)),
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.wideHeaders, (h) => {
                    return (_openBlock(), _createElementBlock("th", {
                      key: h.si + '-' + h.ci,
                      title: h.title,
                      class: _normalizeClass({ 'col-excluded': h.excluded })
                    }, [
                      _createElementVNode("div", _hoisted_66, [
                        (!h.excluded && h.col)
                          ? (_openBlock(), _createElementBlock("label", {
                              key: 0,
                              class: "inc",
                              title: h.included ? '取消勾选：该列不进总览/加权' : '勾选：该列进入总览与加权'
                            }, [
                              _createElementVNode("input", {
                                type: "checkbox",
                                checked: h.included,
                                onChange: $event => ($setup.toggleColumnInclude(h.si, h.col!.name, ($event.target as HTMLInputElement).checked))
                              }, null, 40 /* PROPS, NEED_HYDRATION */, _hoisted_68),
                              _cache[49] || (_cache[49] = _createTextVNode("✅ ", -1 /* CACHED */))
                            ], 8 /* PROPS */, _hoisted_67))
                          : (_openBlock(), _createElementBlock("span", _hoisted_69, "—")),
                        _createElementVNode("span", _hoisted_70, _toDisplayString(h.label), 1 /* TEXT */),
                        (!h.excluded && h.col)
                          ? (_openBlock(), _createElementBlock("label", _hoisted_71, [
                              _cache[50] || (_cache[50] = _createTextVNode(" 权重 ", -1 /* CACHED */)),
                              _createElementVNode("input", {
                                type: "number",
                                min: "0",
                                step: "0.1",
                                style: {"width":"52px"},
                                value: h.col!.weight ?? 1,
                                onChange: $event => ($setup.setColumnWeight(h.si, h.col!.name, ($event.target as HTMLInputElement).value))
                              }, null, 40 /* PROPS, NEED_HYDRATION */, _hoisted_72)
                            ]))
                          : _createCommentVNode("v-if", true),
                        _createElementVNode("button", {
                          class: "btn small",
                          style: {"margin-top":"2px"},
                          disabled: h.excluded || !h.col || !$setup.roster.students.length,
                          title: "D55-H3：按该列原始分单独切分打 tag（一列即排，其余列/源不参与）",
                          onClick: $event => ($setup.tagBySingleColumn(h.si, h.col ? h.col.name : undefined))
                        }, "按此列切分", 8 /* PROPS */, _hoisted_73)
                      ])
                    ], 10 /* CLASS, PROPS */, _hoisted_65))
                  }), 128 /* KEYED_FRAGMENT */)),
                  _cache[53] || (_cache[53] = _createElementVNode("th", {
                    class: "composite-col",
                    title: "D46-4：按当前勾选源加权即时预览（未点「重算并打 tag」前不写库）"
                  }, "综合得分*", -1 /* CACHED */))
                ])
              ]),
              _createElementVNode("tbody", null, [
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.orderedWideRows, (row) => {
                  return (_openBlock(), _createElementBlock("tr", {
                    key: row.name + '\u0000' + row.number
                  }, [
                    _createElementVNode("td", _hoisted_74, _toDisplayString(row.name || '（未命名）'), 1 /* TEXT */),
                    _createElementVNode("td", _hoisted_75, _toDisplayString(row.number || '—'), 1 /* TEXT */),
                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(row.cells, (c, j) => {
                      return (_openBlock(), _createElementBlock("td", {
                        key: j,
                        class: _normalizeClass({ 'muted-cell': c === '' }),
                        title: c === '' ? '该源无此生分数（重算时跳过该源）' : ''
                      }, [
                        _createElementVNode("span", {
                          class: _normalizeClass({ 'excluded-val': !$setup.wideHeaders[j].included })
                        }, _toDisplayString(c === '' ? '—' : c), 3 /* TEXT, CLASS */)
                      ], 10 /* CLASS, PROPS */, _hoisted_76))
                    }), 128 /* KEYED_FRAGMENT */)),
                    _createElementVNode("td", {
                      class: "composite-col",
                      title: row.composite === '' ? '勾选集合为空或该生无任何勾选源分数' : '综合得分预览（点「重算并打 tag」正式写入并切分）'
                    }, _toDisplayString(row.composite || '—'), 9 /* TEXT, PROPS */, _hoisted_77)
                  ]))
                }), 128 /* KEYED_FRAGMENT */))
              ])
            ])
          ]),
          _createElementVNode("p", {
            class: _normalizeClass(["hint", { notice: $setup.checkedSummary.includes('已排除') }]),
            style: {"margin-top":"6px"}
          }, _toDisplayString($setup.checkedSummary), 3 /* TEXT, CLASS */),
          _createElementVNode("p", _hoisted_78, [
            _cache[54] || (_cache[54] = _createTextVNode(" * 综合得分列为", -1 /* CACHED */)),
            _cache[55] || (_cache[55] = _createElementVNode("b", null, "预览口径", -1 /* CACHED */)),
            _cache[56] || (_cache[56] = _createTextVNode("（随勾选即时重算，不写库；点「重算并打 tag」正式生效）。 ", -1 /* CACHED */)),
            _createElementVNode("button", {
              class: "btn small",
              style: {"margin-left":"6px"},
              disabled: !$setup.roster.students.length,
              title: "D46-4：全部成绩总览导出 xlsx（名单+各源分数列[未勾选列保留并标注]+tag/punish/综合分）",
              onClick: $setup.exportOverviewXlsx
            }, "⬇ 导出总览 xlsx", 8 /* PROPS */, _hoisted_79),
            ($setup.overviewMsg)
              ? (_openBlock(), _createElementBlock("span", _hoisted_80, _toDisplayString($setup.overviewMsg), 1 /* TEXT */))
              : _createCommentVNode("v-if", true)
          ]),
          _cache[59] || (_cache[59] = _createElementVNode("p", { class: "hint" }, [
            _createTextVNode(" 「按此列切分」= 只用该源计算综合得分并按比例自动打 tag（"),
            _createElementVNode("b", null, "一列即排"),
            _createTextVNode("）； 「重算综合得分并自动切分打 tag」（下方分组比例卡）= 按"),
            _createElementVNode("b", null, "当前勾选集合"),
            _createTextVNode("加权重算（多列加权语义：权重/权重和）。 两者均不清除手动覆盖与 punish。 ")
          ], -1 /* CACHED */))
        ], 2 /* CLASS */))
      : _createCommentVNode("v-if", true),
    _createElementVNode("div", _hoisted_81, [
      _cache[65] || (_cache[65] = _createElementVNode("h2", null, "分组比例 + 自动切分打 tag", -1 /* CACHED */)),
      _cache[66] || (_cache[66] = _createElementVNode("p", { class: "hint" }, " 2603 默认比例模板可改（punish 不参与比例，仅手动勾选覆盖；docs/05-D17/D18）。 切分：不含 translation 的比例合计 ≤100% 之间依次切档（_translation 不参与_，等价 _legacy）； translation 沿用 _legacy 的\"随机散布\"语义。已手动覆盖的学生不参与切分且不被覆盖。 ", -1 /* CACHED */)),
      _createElementVNode("p", null, [
        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.nonTranslationRatios, (g) => {
          return (_openBlock(), _createElementBlock("label", {
            class: "field",
            key: g.tag
          }, [
            _createTextVNode(_toDisplayString($setup.STUDENT_TAG_LABELS[g.tag] ?? g.tag) + " ", 1 /* TEXT */),
            _createElementVNode("input", {
              type: "number",
              value: Math.round(g.ratio * 100),
              min: "0",
              max: "100",
              step: "1",
              style: {"width":"60px"},
              onChange: (e) => { g.ratio = Number((e.target as HTMLInputElement).value) / 100 || 0; $setup.roster.touch(); }
            }, null, 40 /* PROPS, NEED_HYDRATION */, _hoisted_82),
            _cache[60] || (_cache[60] = _createTextVNode("% ", -1 /* CACHED */))
          ]))
        }), 128 /* KEYED_FRAGMENT */)),
        _createElementVNode("span", {
          class: _normalizeClass(["hint", { notice: $setup.warnRatio }])
        }, [
          _createTextVNode(" 合计（不含 translation）" + _toDisplayString(($setup.roster.ratioSum * 100).toFixed(1)) + "% ", 1 /* TEXT */),
          ($setup.warnRatio)
            ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                _createTextVNode("（>100%：余数为负，按名单实际人数封顶切分）")
              ], 64 /* STABLE_FRAGMENT */))
            : ($setup.warnRatioOff)
              ? (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                  _createTextVNode("（<100%：剩余学生补到最后一个非 translation 档）")
                ], 64 /* STABLE_FRAGMENT */))
              : _createCommentVNode("v-if", true)
        ], 2 /* CLASS */)
      ]),
      _createElementVNode("p", null, [
        _createElementVNode("label", _hoisted_83, [
          _cache[61] || (_cache[61] = _createElementVNode("b", null, "translation（随机拨给，独立）", -1 /* CACHED */)),
          _createElementVNode("input", {
            type: "number",
            value: Math.round($setup.translationRatioPct),
            min: "0",
            max: "100",
            step: "1",
            style: {"width":"60px"},
            onChange: _cache[16] || (_cache[16] = $event => ($setup.setTranslationRatio(($event.target as HTMLInputElement).value)))
          }, null, 40 /* PROPS, NEED_HYDRATION */, _hoisted_84),
          _cache[62] || (_cache[62] = _createTextVNode("% ", -1 /* CACHED */))
        ]),
        _createElementVNode("span", _hoisted_85, "其他档合计 " + _toDisplayString(($setup.roster.ratioSum * 100).toFixed(1)) + "% + translation " + _toDisplayString(Math.round($setup.translationRatioPct)) + "%（translation 随机散布、与档位切分正交）", 1 /* TEXT */)
      ]),
      _createElementVNode("p", null, [
        _createElementVNode("button", {
          class: "btn primary",
          onClick: $setup.recompute
        }, "⚙ 重算综合得分并自动切分打 tag（调比例后必点）"),
        ($setup.dirHandle)
          ? (_openBlock(), _createElementBlock("button", {
              key: 0,
              class: "btn",
              style: {"margin-left":"8px"},
              disabled: $setup.exportDisabled,
              onClick: $setup.saveToWorkspace
            }, "写回 workspace roster/", 8 /* PROPS */, _hoisted_86))
          : _createCommentVNode("v-if", true)
      ]),
      _createElementVNode("p", null, [
        _createElementVNode("label", _hoisted_87, [
          _cache[64] || (_cache[64] = _createTextVNode(" 本次结果关联到作业包 ", -1 /* CACHED */)),
          _withDirectives(_createElementVNode("select", {
            "onUpdate:modelValue": _cache[17] || (_cache[17] = $event => (($setup.snapshotPackId) = $event)),
            style: {"min-width":"180px"}
          }, [
            _cache[63] || (_cache[63] = _createElementVNode("option", { value: "" }, "（不关联，只更新班级名单）", -1 /* CACHED */)),
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.snapshotPackOptions, (p) => {
              return (_openBlock(), _createElementBlock("option", {
                key: p.id,
                value: p.id
              }, _toDisplayString(p.name), 9 /* TEXT, PROPS */, _hoisted_88))
            }), 128 /* KEYED_FRAGMENT */))
          ], 512 /* NEED_PATCH */), [
            [_vModelSelect, $setup.snapshotPackId]
          ])
        ]),
        ($setup.snapshotBusy)
          ? (_openBlock(), _createElementBlock("span", _hoisted_89, "正在冻结快照…"))
          : _createCommentVNode("v-if", true),
        ($setup.snapshotMsg)
          ? (_openBlock(), _createElementBlock("span", _hoisted_90, _toDisplayString($setup.snapshotMsg), 1 /* TEXT */))
          : _createCommentVNode("v-if", true)
      ]),
      ($setup.dirHandle && $setup.writeHint)
        ? (_openBlock(), _createElementBlock("p", _hoisted_91, _toDisplayString($setup.writeHint), 1 /* TEXT */))
        : _createCommentVNode("v-if", true),
      _createElementVNode("p", _hoisted_92, _toDisplayString($setup.summaryText), 1 /* TEXT */)
    ]),
    _createVNode($setup["PreviewTableCard"], {
      title: "名单预览（表头 + 前 3 行 + 列映射，VC-4）",
      preview: $setup.rosterPreview,
      "file-name": $setup.rosterPreviewFile,
      tone: "ok"
    }, null, 8 /* PROPS */, ["preview", "file-name"]),
    _createCommentVNode(" ============ D50b ③ 标签预览（分布统计 + 每生 tag/punish + 批量打 tag） ============ "),
    _createElementVNode("div", _hoisted_93, [
      _cache[74] || (_cache[74] = _createElementVNode("h2", null, [
        _createTextVNode("标签预览 "),
        _createElementVNode("small", { style: {"font-weight":"400","color":"var(--c-muted)"} }, "比例切分结果 + 手动覆盖（special_tag_cfg；docs/13 D50b：原\"特殊标签\"卡更名）")
      ], -1 /* CACHED */)),
      _createElementVNode("p", _hoisted_94, [
        _cache[67] || (_cache[67] = _createElementVNode("span", {
          class: "hint",
          style: {"margin":"0"}
        }, "显示顺序：", -1 /* CACHED */)),
        _createElementVNode("button", {
          class: _normalizeClass(["btn small", { primary: $setup.labelSort === 'roster' }]),
          onClick: _cache[18] || (_cache[18] = $event => ($setup.labelSort = 'roster'))
        }, "点名册顺序", 2 /* CLASS */),
        _createElementVNode("button", {
          class: _normalizeClass(["btn small", { primary: $setup.labelSort === 'desc' }]),
          onClick: _cache[19] || (_cache[19] = $event => ($setup.labelSort = 'desc'))
        }, "加权成绩 ↓ 降序", 2 /* CLASS */),
        _createElementVNode("button", {
          class: _normalizeClass(["btn small", { primary: $setup.labelSort === 'asc' }]),
          onClick: _cache[20] || (_cache[20] = $event => ($setup.labelSort = 'asc'))
        }, "加权成绩 ↑ 升序", 2 /* CLASS */)
      ]),
      _cache[75] || (_cache[75] = _createElementVNode("p", { class: "hint" }, "调整任何比例 → 在上方「分组比例」卡点「重算并自动切分打 tag」→ 本预览即时变化。手动改 tag = special_tag 覆盖（重算不被冲掉）。", -1 /* CACHED */)),
      ($setup.roster.students.length)
        ? (_openBlock(), _createElementBlock("p", _hoisted_95, [
            _cache[68] || (_cache[68] = _createTextVNode(" 分布：", -1 /* CACHED */)),
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.roster.tagCounts, (n, t) => {
              return (_openBlock(), _createElementBlock("code", {
                key: t,
                style: {"margin-right":"6px"}
              }, _toDisplayString($setup.STUDENT_TAG_LABELS[t] ?? t) + "×" + _toDisplayString(n), 1 /* TEXT */))
            }), 128 /* KEYED_FRAGMENT */)),
            _createElementVNode("span", _hoisted_96, "未打 " + _toDisplayString($setup.roster.students.filter((x) => !x.tag).length) + " 人", 1 /* TEXT */)
          ]))
        : (_openBlock(), _createElementBlock("p", _hoisted_97, "名单为空时本卡无内容。")),
      _createElementVNode("p", null, [
        _createElementVNode("label", _hoisted_98, [
          _cache[69] || (_cache[69] = _createTextVNode("批量打 tag：姓名（逗号/顿号分隔多个学生） ", -1 /* CACHED */)),
          _withDirectives(_createElementVNode("input", {
            type: "text",
            "onUpdate:modelValue": _cache[21] || (_cache[21] = $event => (($setup.batchNames) = $event)),
            placeholder: "学生A, 学生B, 学生C",
            style: {"width":"min(420px, 60%)"}
          }, null, 512 /* NEED_PATCH */), [
            [_vModelText, $setup.batchNames]
          ])
        ]),
        _createElementVNode("label", _hoisted_99, [
          _cache[70] || (_cache[70] = _createTextVNode("tag： ", -1 /* CACHED */)),
          _withDirectives(_createElementVNode("select", {
            "onUpdate:modelValue": _cache[22] || (_cache[22] = $event => (($setup.batchTag) = $event)),
            title: "批量打 tag（punish 请用每生行内勾选框）"
          }, [
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.STUDENT_TAGS.filter((x) => x !== 'punish'), (t2) => {
              return (_openBlock(), _createElementBlock("option", {
                key: t2,
                value: t2
              }, _toDisplayString($setup.STUDENT_TAG_LABELS[t2] ?? t2), 9 /* TEXT, PROPS */, _hoisted_100))
            }), 128 /* KEYED_FRAGMENT */))
          ], 512 /* NEED_PATCH */), [
            [_vModelSelect, $setup.batchTag]
          ])
        ]),
        _createElementVNode("label", _hoisted_101, [
          _withDirectives(_createElementVNode("input", {
            type: "checkbox",
            "onUpdate:modelValue": _cache[23] || (_cache[23] = $event => (($setup.batchCreateIfAbsent) = $event))
          }, null, 512 /* NEED_PATCH */), [
            [_vModelCheckbox, $setup.batchCreateIfAbsent]
          ]),
          _cache[71] || (_cache[71] = _createTextVNode(" 缺失者自动新增", -1 /* CACHED */))
        ]),
        _createElementVNode("button", {
          class: "btn",
          style: {"margin-left":"8px"},
          onClick: $setup.applyBatchTag,
          disabled: !$setup.batchNames.trim()
        }, "应用到多个学生", 8 /* PROPS */, _hoisted_102),
        ($setup.batchMsg)
          ? (_openBlock(), _createElementBlock("span", _hoisted_103, _toDisplayString($setup.batchMsg), 1 /* TEXT */))
          : _createCommentVNode("v-if", true)
      ]),
      ($setup.roster.students.length)
        ? (_openBlock(), _createElementBlock("details", _hoisted_104, [
            _createElementVNode("summary", _hoisted_105, "每生 tag / punish 一览（" + _toDisplayString($setup.roster.students.length) + " 人 · 点击折叠，表内滚轮查看）", 1 /* TEXT */),
            _createElementVNode("div", _hoisted_106, [
              _createElementVNode("table", _hoisted_107, [
                _cache[73] || (_cache[73] = _createElementVNode("thead", null, [
                  _createElementVNode("tr", null, [
                    _createElementVNode("th", null, "姓名"),
                    _createElementVNode("th", null, "学号"),
                    _createElementVNode("th", null, "tag（下拉=手动覆盖）"),
                    _createElementVNode("th", { style: {"width":"70px"} }, "punish")
                  ])
                ], -1 /* CACHED */)),
                _createElementVNode("tbody", null, [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.labelRows, ({ s, i }) => {
                    return (_openBlock(), _createElementBlock("tr", { key: i }, [
                      _createElementVNode("td", null, _toDisplayString(s.name || '（未命名）'), 1 /* TEXT */),
                      _createElementVNode("td", null, _toDisplayString(s.number || '—'), 1 /* TEXT */),
                      _createElementVNode("td", null, [
                        _createElementVNode("select", {
                          value: s.tag,
                          onChange: $event => ($setup.setTag(i, $event)),
                          title: "tag 下拉=手动覆盖（punish 请用右侧勾选框）"
                        }, [
                          _cache[72] || (_cache[72] = _createElementVNode("option", { value: "" }, "（未打）", -1 /* CACHED */)),
                          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.STUDENT_TAGS.filter((x) => x !== 'punish'), (t) => {
                            return (_openBlock(), _createElementBlock("option", {
                              key: t,
                              value: t
                            }, _toDisplayString($setup.STUDENT_TAG_LABELS[t] ?? t), 9 /* TEXT, PROPS */, _hoisted_109))
                          }), 128 /* KEYED_FRAGMENT */))
                        ], 40 /* PROPS, NEED_HYDRATION */, _hoisted_108)
                      ]),
                      _createElementVNode("td", _hoisted_110, [
                        _createElementVNode("input", {
                          type: "checkbox",
                          checked: s.punish,
                          onChange: $event => ($setup.setPunish(i, $event)),
                          title: "punish：期末补作业统一题集（不参与比例）"
                        }, null, 40 /* PROPS, NEED_HYDRATION */, _hoisted_111)
                      ])
                    ]))
                  }), 128 /* KEYED_FRAGMENT */))
                ])
              ])
            ])
          ]))
        : _createCommentVNode("v-if", true)
    ]),
    (!$setup.caps.full && $setup.caps.browserHint)
      ? (_openBlock(), _createElementBlock("div", _hoisted_112, _toDisplayString($setup.caps.browserHint), 1 /* TEXT */))
      : _createCommentVNode("v-if", true),
    ($setup.caps.insecure)
      ? (_openBlock(), _createElementBlock("div", _hoisted_113, " 当前为局域网预览（http://IP，非安全上下文）：导入名单/成绩/题库均可用（文件选择方式）； \"写回 workspace 目录\"不可用——请用下方导出按钮下载文件，教师手动放回 workspace。 " + _toDisplayString($setup.writeHint), 1 /* TEXT */))
      : _createCommentVNode("v-if", true),
    _createElementVNode("div", _hoisted_114, [
      _cache[78] || (_cache[78] = _createElementVNode("h2", null, [
        _createTextVNode("产出 "),
        _createElementVNode("small", { style: {"font-weight":"400","color":"var(--c-muted)"} }, "名单带 tag → 引擎可直接用（docs/13 D50b ④产出段）")
      ], -1 /* CACHED */)),
      _cache[79] || (_cache[79] = _createElementVNode("p", { class: "hint" }, [
        _createTextVNode(" roster.xlsx 列 = name/number/class/tag（恒英文值），"),
        _createElementVNode("code", null, "uv run assist sheet make <task> --roster roster.xlsx"),
        _createTextVNode(" 直接可用； roster.json 供 CLI/AI；作业纸 zip 内含 roster.xlsx + roster.json + task-package.json （group_cfg + special_tag_cfg + punish + score_sources[].family，docs/05-D19）+ 附带切分规则说明 md。 "),
        _createElementVNode("b", null, "D49-F4"),
        _createTextVNode("：本卡 = 当前班级的产出集中入口（导出即登记进班级产出簿，见下方清单/班级清单栏）； 整班分层作业纸的 batch 交付包在「作业纸设计→内容/变体绑定」卡生成（也会登记）。 FSA 已连接 workspace 时：导出走 "),
        _createElementVNode("code", null, "classes/<班级>/roster/"),
        _createTextVNode(" 原地写回（产出簿记 fsa-write 路径）。 ")
      ], -1 /* CACHED */)),
      _createElementVNode("p", null, [
        _createElementVNode("button", {
          class: "btn primary",
          disabled: $setup.exportDisabled,
          onClick: $setup.downloadRosterJsonAndXlsx
        }, "导出 tag 名单（xlsx + JSON）", 8 /* PROPS */, _hoisted_115),
        _createElementVNode("button", {
          class: "btn",
          style: {"margin-left":"8px"},
          disabled: $setup.exportDisabled,
          onClick: $setup.downloadTaskPackage
        }, "下载作业纸（zip，附带说明）", 8 /* PROPS */, _hoisted_116)
      ]),
      _createElementVNode("p", _hoisted_117, [
        _cache[76] || (_cache[76] = _createTextVNode(" punish 名单（期末补交统一题集，不按层）： ", -1 /* CACHED */)),
        ($setup.roster.tagCounts.punish)
          ? (_openBlock(), _createElementBlock("code", _hoisted_118, _toDisplayString($setup.roster.students.filter((s) => s.tag === 'punish').map((s) => s.name).join('、')), 1 /* TEXT */))
          : (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
              _createTextVNode("（未勾选）")
            ], 64 /* STABLE_FRAGMENT */))
      ]),
      ($setup.caps.insecure)
        ? (_openBlock(), _createElementBlock("p", _hoisted_119, [...(_cache[77] || (_cache[77] = [
            _createTextVNode("LAN 预览提示：导出为浏览器下载，教师手动放回 workspace 的 ", -1 /* CACHED */),
            _createElementVNode("code", null, "classes/<班级>/roster/", -1 /* CACHED */),
            _createTextVNode(" 即可（写回目录能力需本机 localhost/https 打开）。", -1 /* CACHED */)
          ]))]))
        : _createCommentVNode("v-if", true)
    ]),
    _createElementVNode("div", _hoisted_120, [
      _cache[94] || (_cache[94] = _createElementVNode("h2", null, "整班作业纸预览（VC-3：按 tag→作业纸映射，同一打印模板 · 全站唯一整班预览入口）", -1 /* CACHED */)),
      _cache[95] || (_cache[95] = _createElementVNode("p", { class: "hint" }, [
        _createTextVNode(" 变体编排绑定（tag→作业纸 target_tag）在「作业纸内容」页维护（单入口，D25）； 本卡 = **整班分层预览/打印的唯一入口**（docs/13 D43-6 域分层：作业纸设计页只做模板级预览）。 渲染与 CLI "),
        _createElementVNode("code", null, "assist sheet html"),
        _createTextVNode(),
        _createElementVNode("b", null, "同一模板"),
        _createTextVNode("（lib/sheetHtml.ts）：名单里所有人按其 tag 领到对应变体（引擎 batch 同口径）， KaTeX 同源渲染（离线也可）。 ")
      ], -1 /* CACHED */)),
      _createElementVNode("p", _hoisted_121, [
        _cache[84] || (_cache[84] = _createElementVNode("b", null, "D127 · 取题来源", -1 /* CACHED */)),
        _cache[85] || (_cache[85] = _createTextVNode("：整班预览", -1 /* CACHED */)),
        _cache[86] || (_cache[86] = _createElementVNode("b", null, "跟随当前选中的作业包", -1 /* CACHED */)),
        _cache[87] || (_cache[87] = _createTextVNode(" —— ", -1 /* CACHED */)),
        ($setup.packStore.currentId)
          ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
              _cache[80] || (_cache[80] = _createTextVNode(" 当前包：", -1 /* CACHED */)),
              _createElementVNode("code", null, _toDisplayString($setup.packStore.currentId), 1 /* TEXT */),
              _createTextVNode(" （" + _toDisplayString($setup.classPackPads.pads.length) + " 张作业纸", 1 /* TEXT */),
              ($setup.classPackPads.dangling.length)
                ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                    _createTextVNode("， ⚠ " + _toDisplayString($setup.classPackPads.dangling.length) + " 个引用找不到", 1 /* TEXT */)
                  ], 64 /* STABLE_FRAGMENT */))
                : _createCommentVNode("v-if", true),
              _cache[81] || (_cache[81] = _createTextVNode("） ", -1 /* CACHED */))
            ], 64 /* STABLE_FRAGMENT */))
          : (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
              _cache[82] || (_cache[82] = _createElementVNode("b", { style: {"color":"#b91c1c"} }, "尚未选择作业包", -1 /* CACHED */)),
              _cache[83] || (_cache[83] = _createTextVNode("——请到「作业纸设计」页选择/新建作业包后再预览 （只出当前包内的作业纸，避免同一 tag 串到别的批次）。 ", -1 /* CACHED */))
            ], 64 /* STABLE_FRAGMENT */))
      ]),
      _createElementVNode("p", null, [
        _createElementVNode("label", _hoisted_122, [
          _withDirectives(_createElementVNode("input", {
            type: "checkbox",
            "onUpdate:modelValue": _cache[24] || (_cache[24] = $event => (($setup.classIncludeAnswers) = $event))
          }, null, 512 /* NEED_PATCH */), [
            [_vModelCheckbox, $setup.classIncludeAnswers]
          ]),
          _cache[88] || (_cache[88] = _createTextVNode(" 显示参考答案 ", -1 /* CACHED */))
        ]),
        _createElementVNode("label", _hoisted_123, [
          _withDirectives(_createElementVNode("input", {
            type: "checkbox",
            "onUpdate:modelValue": _cache[25] || (_cache[25] = $event => (($setup.classIncludeWatermark) = $event))
          }, null, 512 /* NEED_PATCH */), [
            [_vModelCheckbox, $setup.classIncludeWatermark]
          ]),
          _cache[89] || (_cache[89] = _createTextVNode(" 显示水印图层 ", -1 /* CACHED */))
        ]),
        _createElementVNode("label", _hoisted_124, [
          _withDirectives(_createElementVNode("input", {
            type: "checkbox",
            "onUpdate:modelValue": _cache[26] || (_cache[26] = $event => (($setup.classIncludePageText) = $event))
          }, null, 512 /* NEED_PATCH */), [
            [_vModelCheckbox, $setup.classIncludePageText]
          ]),
          _cache[90] || (_cache[90] = _createTextVNode(" 显示页码大字 ", -1 /* CACHED */))
        ]),
        _createElementVNode("span", _hoisted_125, "当前口径：" + _toDisplayString($setup.classIncludeAnswers ? '教师版（含答案）' : '学生版（不含答案）'), 1 /* TEXT */)
      ]),
      _createElementVNode("p", null, [
        _createElementVNode("button", {
          class: "btn primary",
          disabled: $setup.previewingClass || !$setup.roster.students.length || !$setup.pad.saved.length,
          onClick: $setup.previewWholeClass
        }, "👁 预览整班（" + _toDisplayString($setup.roster.students.length) + " 名学生 × " + _toDisplayString($setup.pad.saved.length) + " 份作业纸映射）", 9 /* TEXT, PROPS */, _hoisted_126),
        _createElementVNode("button", {
          class: "btn",
          style: {"margin-left":"8px"},
          disabled: !$setup.classPreviewHtml,
          onClick: $setup.printClassPreview
        }, "🖨 打印整班", 8 /* PROPS */, _hoisted_127),
        _createElementVNode("button", {
          class: "btn",
          style: {"margin-left":"8px"},
          disabled: !$setup.classPreviewHtml,
          onClick: $setup.downloadClassPreviewHtml
        }, "⬇ 下载 HTML（自包含）", 8 /* PROPS */, _hoisted_128),
        (!$setup.pad.saved.length)
          ? (_openBlock(), _createElementBlock("span", _hoisted_129, "（作业纸清单为空：没有可映射的作业纸；先去内容页保存）."))
          : (!$setup.pageCount)
            ? (_openBlock(), _createElementBlock("span", _hoisted_130, "（名单为空，先导入名单。）"))
            : _createCommentVNode("v-if", true)
      ]),
      ($setup.pad.saved.length)
        ? (_openBlock(), _createElementBlock("p", _hoisted_131, [
            _cache[92] || (_cache[92] = _createTextVNode(" 兜底变体（--default 语义，预览用）： ", -1 /* CACHED */)),
            _withDirectives(_createElementVNode("select", {
              "onUpdate:modelValue": _cache[27] || (_cache[27] = $event => (($setup.classPreviewFallbackId) = $event)),
              style: {"max-width":"220px"}
            }, [
              _cache[91] || (_cache[91] = _createElementVNode("option", { value: "" }, "（不兜底：未覆盖 tag 的学生不出页，见 manifest 与提示）", -1 /* CACHED */)),
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.pad.saved, (sv) => {
                return (_openBlock(), _createElementBlock("option", {
                  key: sv.id,
                  value: sv.id
                }, _toDisplayString(sv.id), 9 /* TEXT, PROPS */, _hoisted_132))
              }), 128 /* KEYED_FRAGMENT */))
            ], 512 /* NEED_PATCH */), [
              [_vModelSelect, $setup.classPreviewFallbackId]
            ])
          ]))
        : _createCommentVNode("v-if", true),
      ($setup.missingTagWarn)
        ? (_openBlock(), _createElementBlock("p", _hoisted_133, _toDisplayString($setup.missingTagWarn), 1 /* TEXT */))
        : _createCommentVNode("v-if", true),
      ($setup.classPreviewMsg)
        ? (_openBlock(), _createElementBlock("p", _hoisted_134, _toDisplayString($setup.classPreviewMsg), 1 /* TEXT */))
        : _createCommentVNode("v-if", true),
      ($setup.classPreviewManifest)
        ? (_openBlock(), _createElementBlock("details", _hoisted_135, [
            _cache[93] || (_cache[93] = _createElementVNode("summary", { style: {"cursor":"pointer","font-size":"13px"} }, "manifest（README：tag→包绑定核对，无引擎可用）", -1 /* CACHED */)),
            _createElementVNode("pre", _hoisted_136, [
              _createElementVNode("code", null, _toDisplayString($setup.classPreviewManifest), 1 /* TEXT */)
            ])
          ]))
        : _createCommentVNode("v-if", true),
      ($setup.showClassPreview && $setup.classPreviewHtml)
        ? (_openBlock(), _createElementBlock("iframe", {
            key: 4,
            class: "class-overlay-frame",
            srcdoc: $setup.classPreviewHtml,
            "aria-label": "整班作业纸预览：Tab 聚焦后可用方向键滚动",
            tabindex: "0",
            title: "整班作业纸预览",
            sandbox: "allow-same-origin allow-scripts"
          }, null, 8 /* PROPS */, _hoisted_137))
        : _createCommentVNode("v-if", true)
    ]),
    _createCommentVNode(" ============ D49-F2 班级清单栏（汇总 + 载入/删除） ============ "),
    _createElementVNode("div", _hoisted_138, [
      _cache[98] || (_cache[98] = _createElementVNode("h2", null, [
        _createTextVNode("班级清单 "),
        _createElementVNode("small", { style: {"font-weight":"400","color":"var(--c-muted)"} }, "已添加班级汇总 · 载入/删除（docs/13 D49）")
      ], -1 /* CACHED */)),
      _cache[99] || (_cache[99] = _createElementVNode("p", { class: "hint" }, "新学年归档旧班级、或删除误操作的班级；载入后上方所有模块切换为该班级的工作区。", -1 /* CACHED */)),
      ($setup.roster.classList.length)
        ? (_openBlock(), _createElementBlock("table", _hoisted_139, [
            _cache[96] || (_cache[96] = _createElementVNode("thead", null, [
              _createElementVNode("tr", null, [
                _createElementVNode("th", null, "班级"),
                _createElementVNode("th", null, "学期"),
                _createElementVNode("th", null, "人数"),
                _createElementVNode("th", null, "tag 分布"),
                _createElementVNode("th", null, "成绩源"),
                _createElementVNode("th", null, "状态"),
                _createElementVNode("th", null, "最近产出"),
                _createElementVNode("th", null, "更新时间"),
                _createElementVNode("th", { style: {"width":"120px"} }, "操作")
              ])
            ], -1 /* CACHED */)),
            _createElementVNode("tbody", null, [
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.roster.classList, (c) => {
                return (_openBlock(), _createElementBlock("tr", {
                  key: c.id,
                  style: _normalizeStyle(c.id === $setup.roster.activeClassId ? 'background:var(--c-primary-soft)' : '')
                }, [
                  _createElementVNode("td", null, [
                    _createElementVNode("b", null, _toDisplayString(c.name), 1 /* TEXT */),
                    (c.id === $setup.roster.activeClassId)
                      ? (_openBlock(), _createElementBlock("span", _hoisted_140, "（当前）"))
                      : _createCommentVNode("v-if", true)
                  ]),
                  _createElementVNode("td", null, _toDisplayString(c.term || '—'), 1 /* TEXT */),
                  _createElementVNode("td", _hoisted_141, _toDisplayString(c.studentsCount), 1 /* TEXT */),
                  _createElementVNode("td", _hoisted_142, _toDisplayString(Object.entries($setup.rosterTagCountsOf(c.id)).map(([t, n]) => `${t}×${n}`).join('，') || '—'), 1 /* TEXT */),
                  _createElementVNode("td", _hoisted_143, _toDisplayString(c.sourceCount), 1 /* TEXT */),
                  _createElementVNode("td", null, _toDisplayString(c.status), 1 /* TEXT */),
                  _createElementVNode("td", _hoisted_144, _toDisplayString(c.artifacts[0] ? `${c.artifacts[0].name}（${new Date(c.artifacts[0].at).toLocaleDateString()}）` : '—'), 1 /* TEXT */),
                  _createElementVNode("td", null, _toDisplayString(new Date(c.updatedAt).toLocaleDateString()), 1 /* TEXT */),
                  _createElementVNode("td", _hoisted_145, [
                    _createElementVNode("button", {
                      class: "btn small",
                      disabled: c.id === $setup.roster.activeClassId,
                      onClick: $event => ($setup.loadClassAction(c.id))
                    }, "载入", 8 /* PROPS */, _hoisted_146),
                    _createElementVNode("button", {
                      class: "btn small",
                      style: {"margin-left":"4px"},
                      disabled: $setup.roster.classList.length <= 1,
                      onClick: $event => ($setup.deleteClassAction(c.id, c.name))
                    }, "删除", 8 /* PROPS */, _hoisted_147)
                  ])
                ], 4 /* STYLE */))
              }), 128 /* KEYED_FRAGMENT */))
            ])
          ]))
        : (_openBlock(), _createElementBlock("p", _hoisted_148, "尚无班级。")),
      ($setup.roster.activeMeta?.artifacts.length)
        ? (_openBlock(), _createElementBlock("p", _hoisted_149, [
            _cache[97] || (_cache[97] = _createTextVNode(" 当前班级产出登记：", -1 /* CACHED */)),
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList($setup.roster.activeMeta.artifacts.slice(0, 5), (a) => {
              return (_openBlock(), _createElementBlock("code", {
                key: a.name + a.at,
                style: {"display":"inline-block","margin":"1px 4px 1px 0"}
              }, _toDisplayString(a.name) + "（" + _toDisplayString(a.kind) + "）", 1 /* TEXT */))
            }), 128 /* KEYED_FRAGMENT */))
          ]))
        : _createCommentVNode("v-if", true)
    ])
  ]))
}
__sfc_main.render = render
export default __sfc_main

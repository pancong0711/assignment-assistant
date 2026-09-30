import { defineStore } from 'pinia'
import {
  DEFAULT_GROUP_RATIOS, applyAutoTagging, computeScores, computeScoresFiltered, emptyStudent,
  isIncluded, normalizeSource,
  type GroupRatio, type RosterStudent, type ScoreFamily, type ScoreSource,
} from '../lib/roster'
import {
  buildRosterPreview, buildScoreSourcePreview, buildTaskPackage, newUid, readRosterXlsx,
  readScoreSourceXlsx, taskPackageReadme, writeRosterXlsx,
  type PreviewTable,
} from '../lib/rosterXlsx'
import { downloadData, writeFileInDir } from '../lib/fsAccess'
import { idbPut, idbGet, idbDel } from '../lib/idbRaw'
import JSZip from 'jszip'

/** 班级与成绩 store（M5 成绩管理，docs/05-D18；成绩源格式预设 docs/05-D19）。
 *  纯前端闭环：名单导入/编辑、成绩源导入（格式预设：固定四类自动按列名 family
 *  语义定位分数列；custom 手动选分数列+权重）、
 *  综合得分 → 自上而下按比例切分打 tag、special 覆盖；
 *  VC-4/VC-6（docs/14 §VC）：导入后返回 PreviewTable（表头+前3行+列映射说明）
 *  供预览卡展示；VC-5：成绩源默认勾选（includeInAggregation），取消勾选 =
 *  score excluding，重算/切分只用勾选集合（computeScores 内部按 isIncluded 过滤，
 *  所见即所选，等价 D30 已有的 sources 设置列勾选）。
 *  持久化 localStorage（同 kb store 模式，key: assignment-assistant.roster.v1）；
 *  导出 roster xlsx（engine `assist sheet make --roster` 直接可用）+ JSON + 作业纸。 */

interface PersistedRoster {
  students: RosterStudent[]
  sources: ScoreSource[]
  ratios: GroupRatio[]
  savedAt: string
}

const LS_KEY = 'assignment-assistant.roster.v1'

function fromPersisted(raw: string): PersistedRoster | null {
  try {
    const obj = JSON.parse(raw) as PersistedRoster
    if (!Array.isArray(obj.students)) return null
    return {
      students: obj.students,
      // legacy 存量源（无 family/scores/includeInAggregation 字段）规范化为 custom + 默认勾选
      sources: Array.isArray(obj.sources) ? obj.sources.map((s) => normalizeSource(s)) : [],
      ratios: Array.isArray(obj.ratios) && obj.ratios.length ? obj.ratios : [...DEFAULT_GROUP_RATIOS],
      savedAt: obj.savedAt ?? '',
    }
  } catch {
    return null
  }
}

/* ---------- D49：多班级 store（班级为中心重设计，F2） ----------
 *  班级清单 = classes: Record<cid, RosterClass>；activeClassId = 当前工作区指针。
 *  持久化键 roster-classes.v2；首启一次性迁移 roster.v1 → 默认班级（meta.name='默认班级'）。
 *  产出登记簿 artifacts[] 挂每班级（F3）；载入=切 activeClassId；删除=从 classes 移除。 */

export interface ClassArtifact {
  /** 文件名（含扩展名） */
  name: string
  /** 类型：tagged-roster / overview-xlsx / batch-zip / sheet-html / other */
  kind: 'tagged-roster' | 'overview-xlsx' | 'batch-zip' | 'sheet-html' | 'other'
  /** 产出方式：fsa-write（FSA 写回）或 browser-download */
  via: 'fsa-write' | 'browser-download'
  /** FSA 写回时的目标相对路径（workspace 相对） */
  path?: string
  bytes: number
  at: string
}

export interface RosterClassMeta {
  id: string
  name: string
  term?: string
  createdAt: string
  updatedAt: string
  /** 产出登记簿（F3） */
  artifacts: ClassArtifact[]
}

export interface RosterClass extends RosterClassMeta {
  students: RosterStudent[]
  sources: ScoreSource[]
  ratios: GroupRatio[]
}

const LS_CLASSES_KEY = 'assignment-assistant.roster-classes.v2'

function nowIso(): string { return new Date().toISOString() }
function emptyClass(name = '新班级'): RosterClass {
  return {
    id: newUid(), name, term: '',
    createdAt: nowIso(), updatedAt: nowIso(), artifacts: [],
    students: [], sources: [], ratios: [...DEFAULT_GROUP_RATIOS],
  }
}

function loadClasses(): { classes: Record<string, RosterClass>; order: string[]; activeId: string } {
  try {
    const raw = localStorage.getItem(LS_CLASSES_KEY)
    if (raw) {
      const obj = JSON.parse(raw) as { classes: Record<string, RosterClass>; order?: string[]; activeId?: string }
      const order = obj.order ?? Object.keys(obj.classes)
      return { classes: obj.classes ?? {}, order, activeId: obj.activeId ?? order[0] ?? '' }
    }
  } catch { /* fallthrough 迁移 */ }
  // 一次性迁移：roster.v1 → 默认班级
  const legacy = fromPersisted(localStorage.getItem(LS_KEY) ?? '')
  const c: RosterClass = legacy
    ? { id: newUid(), name: '默认班级', term: '', createdAt: legacy.savedAt || nowIso(), updatedAt: nowIso(),
        artifacts: [], students: legacy.students, sources: legacy.sources, ratios: legacy.ratios }
    : emptyClass('默认班级')
  return { classes: { [c.id]: c }, order: [c.id], activeId: c.id }
}

export const useRosterStore = defineStore('roster', {
  state: () => {
    const loaded = loadClasses()
    const cur = loaded.classes[loaded.activeId]
    return {
      // —— D49 多班级 ——
      classes: loaded.classes as Record<string, RosterClass>,
      classOrder: loaded.order as string[],
      activeClassId: loaded.activeId as string,
      // —— 当前工作区代理（兼容旧视图代码：读写这些字段 = 读写 active 班级） ——
      students: (cur?.students ?? []) as RosterStudent[],
      sources: (cur?.sources ?? []) as ScoreSource[],
      ratios: (cur?.ratios ?? [...DEFAULT_GROUP_RATIOS]) as GroupRatio[],
      savedAt: cur?.updatedAt ?? '',
      dirty: false,
    }
  },
  getters: {
    /** D49：班级清单（供清单栏渲染） */
    classList(state): Array<RosterClassMeta & { studentsCount: number; taggedCount: number; sourceCount: number; status: '仅名单' | '已打tag' | '已产出' }> {
      return state.classOrder
        .map((cid) => state.classes[cid])
        .filter(Boolean)
        .map((c) => {
          const tagged = c.students.filter((x) => x.tag).length
          const status: '仅名单' | '已打tag' | '已产出' = c.artifacts.length ? '已产出' : (tagged > 0 ? '已打tag' : '仅名单')
          return { id: c.id, name: c.name, term: c.term, createdAt: c.createdAt, updatedAt: c.updatedAt, artifacts: c.artifacts,
                   studentsCount: c.students.length, taggedCount: tagged, sourceCount: c.sources.length, status }
        })
    },
    activeMeta(state): RosterClassMeta | null {
      return state.classes[state.activeClassId]
        ? { id: state.classes[state.activeClassId].id, name: state.classes[state.activeClassId].name, term: state.classes[state.activeClassId].term,
            createdAt: state.classes[state.activeClassId].createdAt, updatedAt: state.classes[state.activeClassId].updatedAt,
            artifacts: state.classes[state.activeClassId].artifacts }
        : null
    },
    hasData: (s) => s.students.length > 0,
    /** 每档 tag 人数统计（含手动覆盖与 punish） */
    tagCounts(state): Record<string, number> {
      const out: Record<string, number> = {}
      for (const stu of state.students) {
        if (!stu.tag) continue
        out[stu.tag] = (out[stu.tag] ?? 0) + 1
      }
      return out
    },
    /** 比例合计**不含 translation**（D24：translation 为独立"随机拨给"，不占 100%） */
    ratioSum(state): number {
      return state.ratios.filter((r) => r.tag !== 'translation')
        .reduce((sum, r) => sum + (Number(r.ratio) || 0), 0)
    },
    translationRatio(state): number {
      return state.ratios.find((r) => r.tag === 'translation')?.ratio ?? 0
    },
  },
  actions: {
    persist() {
      // D49：写回 active 班级 + v2 键（兼容字段 students/sources/ratios 直接来自 state 代理）
      const cur = this.classes[this.activeClassId]
      if (cur) {
        cur.students = this.students
        cur.sources = this.sources
        cur.ratios = this.ratios
        cur.updatedAt = nowIso()
      }
      try {
        localStorage.setItem(LS_CLASSES_KEY, JSON.stringify({
          classes: this.classes, order: this.classOrder, activeId: this.activeClassId,
        }))
        this.savedAt = cur?.updatedAt ?? nowIso()
      } catch {
        // 超出 localStorage 配额时静默跳过（内存中仍可编辑/导出）
      }
    },
    /** D49：新建班级（可选从当前班级克隆配置/比例；名单与源不复制=全新开始） */
    createClass(name?: string, cloneRatios = true): string {
      const c = emptyClass(name || `班级${this.classOrder.length + 1}`)
      if (cloneRatios) c.ratios = this.ratios.map((r) => ({ ...r }))
      this.classes[c.id] = c
      this.classOrder.push(c.id)
      this.switchClass(c.id)
      return c.id
    },
    /** D49：载入班级（切 activeClassId；当前工作区状态先回写） */
    switchClass(cid: string): boolean {
      const c = this.classes[cid]
      if (!c) return false
      // 回写当前
      const cur = this.classes[this.activeClassId]
      if (cur) { cur.students = this.students; cur.sources = this.sources; cur.ratios = this.ratios }
      this.activeClassId = cid
      this.students = c.students
      this.sources = c.sources
      this.ratios = c.ratios
      this.savedAt = c.updatedAt
      this.dirty = false
      this.persist()
      return true
    },
    /** D49：删除班级（新学年归档/误操作清除；IndexedDB raw 随源 uid 清理） */
    async deleteClass(cid: string): Promise<boolean> {
      const c = this.classes[cid]
      if (!c) return false
      for (const src of c.sources) { if (src.uid) { try { const { idbDel } = await import('../lib/idbRaw'); void idbDel(src.uid) } catch { /* noop */ } } }
      delete this.classes[cid]
      this.classOrder = this.classOrder.filter((x) => x !== cid)
      if (this.activeClassId === cid) {
        const next = this.classOrder[0]
        if (next) { this.switchClass(next) } else {
          const fresh = emptyClass('默认班级')
          this.classes[fresh.id] = fresh
          this.classOrder.push(fresh.id)
          this.switchClass(fresh.id)
        }
      } else {
        this.persist()
      }
      return true
    },
    /** D49：重命名/改学期 */
    renameClass(cid: string, name: string, term?: string): boolean {
      const c = this.classes[cid]
      if (!c) return false
      c.name = name
      if (term !== undefined) c.term = term
      c.updatedAt = nowIso()
      this.persist()
      return true
    },
    /** F3：产出登记簿（按拍板=只记产出） */
    registerArtifact(a: Omit<ClassArtifact, 'at'>): void {
      const cur = this.classes[this.activeClassId]
      if (!cur) return
      cur.artifacts.unshift({ ...a, at: nowIso() })
      if (cur.artifacts.length > 30) cur.artifacts.length = 30
      this.persist()
    },
    clearAll() {
      this.students = []
      this.sources = []
      this.ratios = [...DEFAULT_GROUP_RATIOS]
      this.dirty = false
      this.persist()
      // v1 键清除（迁移已完成）
      localStorage.removeItem(LS_KEY)
    },
    async loadRosterFile(file: File): Promise<{ message: string; preview: PreviewTable }> {
      const preview = await buildRosterPreview(file) // VC-4：先出预览（宽松列名 rule 同引擎）
      const list = await readRosterXlsx(file)
      if (list.length === 0) {
        this.dirty = true
        return { message: `未从 ${file.name} 读到学生行（需含 姓名/name 列）。`, preview }
      }
      this.students = list
      this.dirty = true
      this.persist()
      return {
        message: `已读入名单 ${list.length} 人（${file.name}）。`,
        preview,
      }
    },
    /** 添加成绩源（D19：family 格式预设决定解析方式；固定四类自动按列名/表结构
     *  family 语义定位分数列，无需用户选列；custom 走手动选列）。
     *  VC-5：新源默认勾选（includeInAggregation=true，参与综合得分）；
     *  VC-6：返回 PreviewTable（表头+前 3 行+family 定位说明）。 */
    async addScoreSource(file: File, family: ScoreFamily = 'custom'): Promise<{ message: string; preview: PreviewTable }> {
      const preview = await buildScoreSourcePreview(file, family)
      const src = await readScoreSourceXlsx(file, file.name, family)
      // D49-F1 单写路径：roster 源同时写回 students[]（双入口语义合一——教师无论从哪个入口导入点名册，
      // 名单都会进来；已存在 students 时按学号 merge 补齐姓名/班级，无 students 时全量填充）。
      if (family === 'roster') {
        const byNumber = new Map(this.students.map((x) => [x.number, x] as const))
        const merged: RosterStudent[] = src.rows.map((r) => {
          const name = String(r[src.nameColumn] ?? '').trim()
          const number = String(r['学号'] ?? r['number'] ?? '').trim()
          const cls = String(r['班级'] ?? r['class'] ?? '').trim()
          const existing = byNumber.get(number) ?? byNumber.get(name)
          if (existing) {
            if (!existing.number && number) existing.number = number
            if (!existing.class && cls) existing.class = cls
            return existing
          }
          return { name, number, class: cls, tag: '', score: null, manualTag: false, punish: false }
        }).filter((x) => x.name)
        if (merged.length) {
          this.students = merged
          this.dirty = true
        }
      }
      // D46-3：原始 ArrayBuffer 入 IndexedDB（👁回看/reparse/rescore 免二次选文件；失败静默降级）
      if (src.uid) void idbPut(src.uid, await file.arrayBuffer())
      this.sources.push(src)
      this.dirty = true
      this.persist()
      const msg = src.family === 'custom'
        ? `已加入成绩源「${src.name}」（${src.rows.length} 行，默认勾选参与综合得分；请在宽表中确认勾选/姓名列/分数列与权重）。`
        : `已加入成绩源「${src.name}」（固定格式 ${src.family}：已按该格式的列名语义自动定位，${src.rows.length} 行，默认勾选；只需确认权重）。`
      return { message: msg, preview }
    },
    /** 切换某成绩源的格式预设：固定四类需重新按 family 语义解析原始表。
     *  legacy 源没有原始矩阵（只有选列后的行），提示教师重新选择文件。 */
    setSourceFamily(idx: number, family: ScoreFamily, file: File | null): string {
      const s = this.sources[idx]
      if (!s) return '未找到该成绩源。'
      if (!file) {
        s.family = family
        this.touch()
        return `已把「${s.name}」标记为 ${family}（未重新解析；如需按固定格式自动定位分数列，请移除后重新选择该 xlsx）。`
      }
      void this.rescoreWithFamily(idx, file, family)
      return ''
    },
    async rescoreWithFamily(idx: number, file: File, family: ScoreFamily, sheetName?: string): Promise<void> {
      const oldUid = this.sources[idx]?.uid
      const src = await readScoreSourceXlsx(file, file.name, family, sheetName)
      if (oldUid) src.uid = oldUid   // 沿用原 uid（raw 覆盖写，不产生孤儿键）
      void idbPut(src.uid ?? '', await file.arrayBuffer())
      this.sources.splice(idx, 1, src)
      this.dirty = true
      this.persist()
    },
    /** D46-3：用 IndexedDB 里的原始文件按当前 family 重新解析（免二次选文件）。 */
    async reparseFromRaw(idx: number): Promise<string> {
      const src = this.sources[idx]
      if (!src?.uid) return '该源无留存原始文件（旧数据）：请「重选文件解析」。'
      const buf = await idbGet(src.uid)
      if (!buf) return 'IndexedDB 中原始文件缺失：请「重选文件解析」重建留存。'
      const fresh = await readScoreSourceXlsx(new File([buf], src.fileName), src.fileName, src.family, src.sheetName)
      fresh.uid = src.uid
      fresh.name = src.name          // 教师改过的源名保留
      this.sources.splice(idx, 1, fresh)
      this.dirty = true
      this.persist()
      return `已按原始文件重新解析「${src.name}」（family=${src.family}）。`
    },
    /** D46-3：行内👁预览——优先用 IndexedDB raw 即时重建 PreviewTable。返回 null=无 raw。 */
    async previewSource(idx: number): Promise<PreviewTable | null> {
      const src = this.sources[idx]
      if (!src?.uid) return null
      const buf = await idbGet(src.uid)
      if (!buf) return null
      return buildScoreSourcePreview(buf, src.family, src.sheetName)
    },
    /** B1：列出该源原始文件全部 sheet（UI 切换用；无 raw 返回空数组）。 */
    async listSourceSheets(idx: number): Promise<string[]> {
      const src = this.sources[idx]
      if (!src?.uid) return []
      const buf = await idbGet(src.uid)
      if (!buf) return []
      try {
        const XLSX = await import('xlsx')
        return XLSX.read(buf, { type: 'array' }).SheetNames
      } catch { return [] }
    },
    /** B1：切换该源使用的 sheet 并按当前 family 重解析（raw 留存时免选文件）。 */
    /** D47-5：勾选/取消某源某列（perColumn——总览显示与综合加权口径随教师管理） */
    toggleSourceColumn(idx: number, colName: string): string {
      const src = this.sources[idx]
      if (!src?.includedColumns || !src?.allNumericColumns) return '该源无限定数值列（旧数据或不支持）。'
      const has = src.includedColumns.some((c) => c.name === colName)
      src.includedColumns = has
        ? src.includedColumns.filter((c) => c.name !== colName)
        : [...src.includedColumns, { name: colName, index: src.allNumericColumns.find((a) => a.name === colName)?.index ?? -1 }]
      this.touch()
      return has ? `已取消「${colName}」列（不进该源聚合/总览）` : `已勾选「${colName}」列`
    },
    async setSourceSheet(idx: number, sheetName: string): Promise<string> {
      const src = this.sources[idx]
      if (!src?.uid) return '该源无留存原始文件，无法切换 sheet：请「重解析」重新选文件。'
      const buf = await idbGet(src.uid)
      if (!buf) return 'IndexedDB 原始文件缺失：请「重解析」重新选文件。'
      const fresh = await readScoreSourceXlsx(new File([buf], src.fileName), src.fileName, src.family, sheetName)
      fresh.uid = src.uid
      fresh.name = src.name
      this.sources.splice(idx, 1, fresh)
      this.dirty = true
      this.persist()
      return `已把「${src.name}」切到 sheet「${sheetName}」重新解析（${fresh.rows.length} 行）。`
    },
    removeSource(idx: number) {
      const uid = this.sources[idx]?.uid
      if (uid) void idbDel(uid)
      this.sources.splice(idx, 1)
      this.dirty = true
      this.persist()
    },
    touch() {
      this.dirty = true
      this.persist()
    },
    addStudent() {
      const s = emptyStudent()
      s.name = `学生${String.fromCharCode(65 + (this.students.length % 26))}` // 合成占位风格
      this.students.push(s)
      this.dirty = true
      this.persist()
    },
    removeStudent(idx: number) {
      this.students.splice(idx, 1)
      this.dirty = true
      this.persist()
    },
    /** 重算：综合得分 + 自动切分（手动覆盖/punish 不被冲掉）。
     *  VC-5：computeScores 内部只聚合"勾选中"的源（isIncluded 过滤）——
     *  所见即所选：取消勾选的源被排除出综合得分（score excluding）。 */
    recompute(): string {
      computeScores(this.students, this.sources)
      applyAutoTagging(this.students, this.ratios)
      this.dirty = true
      this.persist()
      const used = this.sources.filter(isIncluded)
      const excluded = this.sources.length - used.length
      return used.length
        ? `已按勾选的 ${used.length} 个成绩源加权重算${excluded ? `（已排除 ${excluded} 个未勾选源）` : ''}。`
        : '⚠ 当前没有勾选任何计分成绩源：综合得分为空，切分保持名单顺序（手动覆盖/punish 不受影响）。'
    },
    /** VC-5"按勾选源重算 scoring 并自动切 tag"（与 recompute 同口径的显式入口，
     *  数据源 = 宽表中可见且勾选的集合；返回提示文案）。 */
    recomputeFromChecked(): string {
      return this.recompute()
    },
    /** VC-5"按某单一列切分打 tag"（一列即排）：只用该源计算综合得分
     *  （该源权重 100%，等价"此列作为分层依据"），再按比例自动切分。
     *  手动覆盖/punish 语义与 recompute 完全一致（不被冲掉）。 */
    tagByColumn(idx: number): string {
      const src = this.sources[idx]
      if (!src) return '未找到该成绩源。'
      if (src.family === 'roster') return '「教务点名册」仅接表不计分，不能作为分层依据。'
      computeScoresFiltered(this.students, [src])
      applyAutoTagging(this.students, this.ratios)
      this.dirty = true
      this.persist()
      return `已按「${src.name}」单列（${src.scoreColumn}）切分打 tag（一列即排；其余源未参与）。`
    },
    /** VC-5 勾选/取消勾选某成绩源（false = score excluding，重算时排除）。 */
    setSourceIncluded(idx: number, included: boolean) {
      const s = this.sources[idx]
      if (!s) return
      s.includeInAggregation = included
      this.touch()
    },
    /** 手动覆盖 tag（special_tag_cfg 等价功能入口） */
    setManualTag(stu: RosterStudent, tag: string) {
      stu.tag = tag
      stu.manualTag = tag !== ''
      if (tag === 'punish') stu.punish = true
      this.dirty = true
      this.persist()
    },
    /** 导出 roster xlsx（带 tag 列；engine `assist sheet make --roster` 直接可用） */
    downloadRosterXlsx() {
      const buf = writeRosterXlsx(this.students)
      downloadData(buf, 'roster.xlsx',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
      this.registerArtifact({ name: 'roster.xlsx', kind: 'tagged-roster', via: 'browser-download', bytes: buf.byteLength })
    },
    /** 导出 roster.json（CLI/AI 用） */
    downloadRosterJson() {
      const list = this.students.map((s) => ({ name: s.name, number: s.number, class: s.class, tag: s.tag }))
      downloadData(JSON.stringify(list, null, 2), 'roster.json', 'application/json')
      this.registerArtifact({ name: 'roster.json', kind: 'other', via: 'browser-download', bytes: JSON.stringify(list).length })
    },
    /** 导出"分组比例+special_tag 参数"作业纸 zip（xlsx + json + 附带说明 md）。
     *  D19：score_sources[].family 与 engine CLI --score family:file[:col:w] 对齐。 */
    async downloadTaskPackage(): Promise<string> {
      const zip = new JSZip()
      zip.file('roster.xlsx', writeRosterXlsx(this.students))
      zip.file('roster.json', JSON.stringify(
        this.students.map((s) => ({ name: s.name, number: s.number, class: s.class, tag: s.tag })), null, 2))
      zip.file('task-package.json', buildTaskPackage(this.students, this.sources, this.ratios))
      zip.file('README-切分规则说明.md', taskPackageReadme())
      const blob = await zip.generateAsync({ type: 'blob' })
      downloadData(blob, 'roster-task-package.zip')
      this.registerArtifact({ name: 'roster-task-package.zip', kind: 'other', via: 'browser-download', bytes: blob.size })
      return '已导出 roster-task-package.zip（roster.xlsx + roster.json + task-package.json（含成绩源 family）+ 附带说明）。'
    },
    /** 已连接 workspace 目录时原地写入 classes/<班级>/roster/（Chrome/Edge） */
    async saveToDir(dirHandle: FileSystemDirectoryHandle): Promise<string> {
      const cls = this.students[0]?.class ?? 'classA'
      const dir = `classes/${cls}/roster`
      await writeFileInDir(dirHandle, `${dir}/roster.xlsx`, writeRosterXlsx(this.students))
      await writeFileInDir(dirHandle, `${dir}/roster.json`, JSON.stringify(
        this.students.map((s) => ({ name: s.name, number: s.number, class: s.class, tag: s.tag })), null, 2))
      await writeFileInDir(dirHandle, `${dir}/task-package.json`,
        buildTaskPackage(this.students, this.sources, this.ratios))
      this.registerArtifact({ name: 'roster.xlsx', kind: 'tagged-roster', via: 'fsa-write', path: `${dir}/roster.xlsx`, bytes: writeRosterXlsx(this.students).byteLength })
      return `已写回 ${dirHandle.name}/${dir}/（roster.xlsx + roster.json + task-package.json）。`
    },
  },
})

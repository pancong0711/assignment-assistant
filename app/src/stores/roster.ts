import { defineStore } from 'pinia'
import {
  DEFAULT_GROUP_RATIOS, applyAutoTagging, computeScores, computeScoresFiltered, emptyStudent,
  isIncluded, normalizeSource,
  type GroupRatio, type RosterStudent, type ScoreFamily, type ScoreSource,
} from '../lib/roster'
import {
  buildRosterPreview, buildScoreSourcePreview, buildTaskPackage, readRosterXlsx,
  readScoreSourceXlsx, taskPackageReadme, writeRosterXlsx,
  type PreviewTable,
} from '../lib/rosterXlsx'
import { downloadData, writeFileInDir } from '../lib/fsAccess'
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
 *  导出 roster xlsx（engine `assist sheet make --roster` 直接可用）+ JSON + 任务包。 */

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

export const useRosterStore = defineStore('roster', {
  state: () => {
    const p = fromPersisted(localStorage.getItem(LS_KEY) ?? '')
    return {
      students: p?.students ?? [],
      sources: p?.sources ?? [],
      ratios: p?.ratios ?? [...DEFAULT_GROUP_RATIOS],
      savedAt: p?.savedAt ?? '',
      dirty: false,
    }
  },
  getters: {
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
      const data: PersistedRoster = {
        students: this.students, sources: this.sources, ratios: this.ratios,
        savedAt: new Date().toISOString(),
      }
      try {
        localStorage.setItem(LS_KEY, JSON.stringify(data))
        this.savedAt = data.savedAt
      } catch {
        // 超出 localStorage 配额时静默跳过（内存中仍可编辑/导出）
      }
    },
    clearAll() {
      this.students = []
      this.sources = []
      this.ratios = [...DEFAULT_GROUP_RATIOS]
      this.dirty = false
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
    async rescoreWithFamily(idx: number, file: File, family: ScoreFamily): Promise<void> {
      const src = await readScoreSourceXlsx(file, file.name, family)
      this.sources.splice(idx, 1, src)
      this.dirty = true
      this.persist()
    },
    removeSource(idx: number) {
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
      downloadData(writeRosterXlsx(this.students), 'roster.xlsx',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    },
    /** 导出 roster.json（CLI/AI 用） */
    downloadRosterJson() {
      const list = this.students.map((s) => ({ name: s.name, number: s.number, class: s.class, tag: s.tag }))
      downloadData(JSON.stringify(list, null, 2), 'roster.json', 'application/json')
    },
    /** 导出"分组比例+special_tag 参数"任务包 zip（xlsx + json + 附带说明 md）。
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
      return `已写回 ${dirHandle.name}/${dir}/（roster.xlsx + roster.json + task-package.json）。`
    },
  },
})

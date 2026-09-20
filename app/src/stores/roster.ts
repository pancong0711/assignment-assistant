import { defineStore } from 'pinia'
import {
  DEFAULT_GROUP_RATIOS, applyAutoTagging, computeScores, emptyStudent,
  type GroupRatio, type RosterStudent, type ScoreSource,
} from '../lib/roster'
import { buildTaskPackage, readRosterXlsx, readScoreSourceXlsx, taskPackageReadme, writeRosterXlsx } from '../lib/rosterXlsx'
import { downloadData, writeFileInDir } from '../lib/fsAccess'
import JSZip from 'jszip'

/** 班级与成绩 store（M5 成绩管理，docs/05-D18）。
 *  纯前端闭环：名单导入/编辑、成绩源导入（手动选分数列+权重）、
 *  综合得分 → 自上而下按比例切分打 tag、special 覆盖；
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
      sources: Array.isArray(obj.sources) ? obj.sources : [],
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
    ratioSum(state): number {
      return state.ratios.reduce((sum, r) => sum + (Number(r.ratio) || 0), 0)
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
    async loadRosterFile(file: File): Promise<string> {
      const list = await readRosterXlsx(file)
      if (list.length === 0) return `未从 ${file.name} 读到学生行（需含 姓名/name 列）。`
      this.students = list
      this.dirty = true
      this.persist()
      return `已读入名单 ${list.length} 人（${file.name}）。`
    },
    async addScoreSource(file: File): Promise<string> {
      const src = await readScoreSourceXlsx(file, file.name)
      this.sources.push(src)
      this.dirty = true
      this.persist()
      return `已加入成绩源「${src.name}」（${src.rows.length} 行；请在表中确认姓名列/分数来源列与权重）。`
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
    /** 重算：综合得分 + 自动切分（手动覆盖/punish 不被冲掉） */
    recompute() {
      computeScores(this.students, this.sources)
      applyAutoTagging(this.students, this.ratios)
      this.dirty = true
      this.persist()
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
    /** 导出"分组比例+special_tag 参数"任务包 zip（xlsx + json + 附带说明 md） */
    async downloadTaskPackage(): Promise<string> {
      const zip = new JSZip()
      zip.file('roster.xlsx', writeRosterXlsx(this.students))
      zip.file('task-package.json', buildTaskPackage(this.students, this.sources, this.ratios))
      zip.file('README-切分规则说明.md', taskPackageReadme())
      const blob = await zip.generateAsync({ type: 'blob' })
      downloadData(blob, 'roster-task-package.zip')
      return '已导出 roster-task-package.zip（roster.xlsx + task-package.json + 附带说明）。'
    },
    /** 已连接 workspace 目录时原地写入 classes/<班级>/roster/（Chrome/Edge） */
    async saveToDir(dirHandle: FileSystemDirectoryHandle): Promise<string> {
      const cls = this.students[0]?.class ?? 'classA'
      const dir = `classes/${cls}/roster`
      await writeFileInDir(dirHandle, `${dir}/roster.xlsx`, writeRosterXlsx(this.students))
      await writeFileInDir(dirHandle, `${dir}/task-package.json`,
        buildTaskPackage(this.students, this.sources, this.ratios))
      return `已写回 ${dirHandle.name}/${dir}/（roster.xlsx + task-package.json）。`
    },
  },
})

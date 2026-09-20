/** 班级与成绩（M5 成绩管理，docs/05-D18）数据模型与打 tag 纯前端计算。
 *  纯本地闭环：不依赖学习通/引擎（老师要求"不依赖学习通也能用"）。
 *  名单列结构保持与 engine `assist roster` / files/roster.py 兼容：
 *  name / number / class / tag（中文表头 姓名/学号/班级 由 xlsx 层自适应映射）。
 *  分层标签 9 项固定保留（docs/05-D17），tag 恒用英文值（导出后引擎直接可用）。
 *  打 tag 切分规则对齐 _legacy student.py：按综合得分降序 → 逐比例自上而下切分，
 *  translation 随机散布（沿用 legacy 的"最后一段随机挑选"语义）；punish 不参与
 *  比例，仅手动勾选覆盖；special_tag_cfg 等价功能 = 表内手动指定 tag 覆盖。 */

import { STUDENT_TAGS } from './kb'

export type StudentTag = (typeof STUDENT_TAGS)[number]

/** 一行 = 一名学生（导出 xlsx 列：姓名/学号/班级/tag） */
export interface RosterStudent {
  name: string
  number: string
  class: string
  /** 自动切分 / 手动覆盖结果（英文 tag 值；空 = 未打） */
  tag: string
  /** 综合得分（按比例加权归一后 0~100；无成绩源时为 null） */
  score: number | null
  /** 该生 tag 是否被手动覆盖过（special_tag_cfg 等价；重算自动切分时保留） */
  manualTag: boolean
  /** punish 勾选（惩罚作业：不参与比例，单独覆盖） */
  punish: boolean
}

/** 一个成绩源文件（任意 xlsx，教师手动指定"分数来源列"与权重） */
export interface ScoreSource {
  /** 源名称（如"雨课堂-第3章签到"），教师起名 */
  name: string
  /** 原始文件名（提示用） */
  fileName: string
  /** 分数来源列（xlsx 原始表头名） */
  scoreColumn: string
  /** 学生姓名列（xlsx 原始表头名） */
  nameColumn: string
  /** 权重（任意正数，最终按权重总和归一） */
  weight: number
  /** 该源各行的数据（key: 姓名, value: { [列名]: 值 }），供切源/换列时复用 */
  rows: Array<Record<string, string>>
}

/** 2603 默认分组比例模板（docs/05-D18；punish 不参与比例） */
export interface GroupRatio {
  tag: string
  /** 0~1；全部之和应 ≤ 1，余数补到最后一个比例项 */
  ratio: number
}

export const DEFAULT_GROUP_RATIOS: GroupRatio[] = [
  { tag: 'distinguish', ratio: 0.05 },
  { tag: 'innovation', ratio: 0.10 },
  { tag: 'summary', ratio: 0.10 },
  { tag: 'qa', ratio: 0.25 },
  { tag: 'copy', ratio: 0.35 },
  { tag: 'copyOnly', ratio: 0.15 },
  { tag: 'translation', ratio: 0.10 },
]

/** 综合得分 = Σ(源归一化分数 × 源权重 / 权重和) × 100（每个源内部按该列最大值归一到 0~1）。 */
export function computeScores(students: RosterStudent[], sources: ScoreSource[]): void {
  const valid = sources.filter((s) => s.weight > 0 && s.scoreColumn !== '' && s.rows.length > 0)
  const totalWeight = valid.reduce((sum, s) => sum + s.weight, 0)
  for (const stu of students) {
    if (valid.length === 0 || totalWeight <= 0) {
      stu.score = null
      continue
    }
    let acc = 0
    for (const src of valid) {
      const row = src.rows.find((r) => str(r[src.nameColumn]) === stu.name)
      if (!row) continue
      const nums = src.rows
        .map((r) => num(r[src.scoreColumn]))
        .filter((v) => v !== null) as number[]
      const max = nums.length ? Math.max(...nums) : 0
      const raw = num(row[src.scoreColumn])
      if (raw === null) continue
      acc += (max > 0 ? raw / max : 0) * (src.weight / totalWeight)
    }
    stu.score = Math.round(acc * 1000) / 10 // 0~100，保留 1 位小数
  }
}

/** 切分打 tag（重算入口）：
 *  1) 综合得分降序排序（并列保持原序）；无成绩源时保持名单顺序；
 *  2) 自上而下逐比例切分（legacy：int(n*ratio)，余数补到最后一个比例项）；
 *  3) translation 特殊：随机散布到名单中（legacy 同款语义）；
 *  4) 手动覆盖（manualTag / punish）不被自动重算冲掉。 */
export function applyAutoTagging(students: RosterStudent[], ratios: GroupRatio[]): void {
  const auto = students.filter((s) => !s.manualTag && !s.punish)
  const sorted = [...auto].sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
  const n = sorted.length
  if (n === 0) return

  // 逐比例自上而下切分；translation 先留空位，最后随机散布
  const tags: string[] = new Array(n).fill('')
  let cursor = 0
  const translationCount = takeRatio('translation', ratios)
  for (const g of ratios) {
    if (g.tag === 'translation') continue
    const cnt = Math.min(Math.floor(n * g.ratio), n - cursor)
    for (let i = 0; i < cnt; i++) tags[cursor + i] = g.tag
    cursor += cnt
  }
  const rest = n - cursor
  for (let i = 0; i < rest; i++) {
    // 余数补到最后一个非 translation 比例项（legacy：tag_list[-1]，copyOnly 殿后）
    tags[cursor + i] = lastNonTranslation(ratios)?.tag ?? 'copy'
  }
  const pool = tags.flatMap((t, i) => (t === '' ? [] : [i]))
  const shuffled = shuffle(pool)
  for (let i = 0; i < Math.min(translationCount, shuffled.length); i++) {
    tags[shuffled[i]] = 'translation'
  }

  for (let i = 0; i < n; i++) {
    const stu = sorted[i]
    stu.tag = tags[i] || 'copy'
  }

  function takeRatio(tag: string, list: GroupRatio[]): number {
    return Math.floor(n * (list.find((g) => g.tag === tag)?.ratio ?? 0))
  }
  function lastNonTranslation(list: GroupRatio[]): GroupRatio | undefined {
    const usable = list.filter((g) => g.tag !== 'translation' && g.ratio > 0)
    return usable[usable.length - 1]
  }
}

/** 手动覆盖某学生 tag（special_tag_cfg 等价功能） */
export function setManualTag(stu: RosterStudent, tag: string) {
  stu.tag = tag
  stu.manualTag = tag !== ''
}

function str(v: unknown): string {
  if (v == null) return ''
  return String(v).trim()
}

function num(v: unknown): number | null {
  if (v == null || v === '') return null
  const f = Number(String(v).replace(/[^\d.eE+-]/g, ''))
  return Number.isFinite(f) ? f : null
}

function shuffle<T>(arr: T[]): T[] {
  const out = [...arr]
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[out[i], out[j]] = [out[j], out[i]]
  }
  return out
}

export function emptyStudent(): RosterStudent {
  return { name: '', number: '', class: '', tag: '', score: null, manualTag: false, punish: false }
}

export function tagLabel(tag: string): string {
  return tag || '（未打）'
}

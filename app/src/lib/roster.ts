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

/** 一个成绩源文件（任意 xlsx，教师手动指定"分数来源列"与权重）。
 *  D19：新增格式预设 family —— 固定四类（engine scores.py ADAPTERS 同名）按
 *  列名/表结构 family 语义自动定位分数列，无需用户选列；custom = 手动选列。 */
export type ScoreFamily = 'roster' | 'exam' | 'xuexitong_assignment' | 'xuexitong_stat' | 'rainclass' | 'custom'

export interface ScoreSource {
  /** 源名称（如"雨课堂-第3章签到"），教师起名 */
  name: string
  /** 原始文件名（提示用） */
  fileName: string
  /** 格式预设（docs/05-D19）：固定四类 + custom（默认） */
  family: ScoreFamily
  /** 分数来源列（xlsx 原始表头名；custom 用，固定四类为解析结果说明） */
  scoreColumn: string
  /** 学生姓名列（xlsx 原始表头名；custom 用，固定四类自动定位） */
  nameColumn: string
  /** 权重（任意正数，最终按权重总和归一） */
  weight: number
  /** 该源各行的数据（key: 姓名, value: { [列名]: 值 }），供切源/换列时复用 */
  rows: Array<Record<string, string>>
  /** 每生解析出的分数（固定四类由 family 语义解析；custom 按所选列）。
   *  key: 姓名。供 computeScores 直接取用。 */
  scores: Record<string, number>
}

/** 格式预设元数据（界面下拉 + 说明文字；与 engine scores.py ADAPTERS 注释同口径） */
export const SCORE_FAMILY_PRESETS: Array<{
  value: ScoreFamily
  label: string
  desc: string
  fixed: boolean
}> = [
  { value: 'roster', label: '教务点名册（仅接表，不计分）', desc: '固定格式（来自教务系统导出）：姓名/学号/班级列，作为名单接表用，不参与加权计分。', fixed: true },
  { value: 'exam', label: '教务期末成绩表', desc: '固定格式（来自教务系统导出）：表头含"期末(必填)"列，直接取该列分数。', fixed: true },
  { value: 'xuexitong_assignment', label: '学习通·作业统计', desc: '固定格式（来自学习通导出）：前 8 行内含"成绩"行，其上一行为作业标题，数据行在下方；每生取各作业均分。', fixed: true },
  { value: 'xuexitong_stat', label: '学习通·章节测验（统计文件）', desc: '固定格式（来自学习通导出）：按 sheet 名含"章节测验"匹配，第 4 行为表头找"成绩"列，非 0 计入取均分。', fixed: true },
  { value: 'rainclass', label: '雨课堂汇总表', desc: '固定格式（来自雨课堂导出）：无表头，第 2 行为列标题，前 3 列为学号/姓名/汇总，其后每课 2 列（方式+得分），取每课得分均值。', fixed: true },
  { value: 'custom', label: '自定义（手动选列）', desc: '其他成绩（高考数学/大一高数等）：手动指定姓名列与分数来源列 + 权重。', fixed: false },
]

export function scoreFamilyLabel(family: ScoreFamily): string {
  return SCORE_FAMILY_PRESETS.find((p) => p.value === family)?.label ?? family
}

export function scoreFamilyDesc(family: ScoreFamily): string {
  return SCORE_FAMILY_PRESETS.find((p) => p.value === family)?.desc ?? ''
}

/** 固定四类 = 界面上标注"固定格式（来自教务/学习通/雨课堂导出）"，无需选列。 */
export function isFixedFamily(family: ScoreFamily): boolean {
  return SCORE_FAMILY_PRESETS.find((p) => p.value === family)?.fixed ?? false
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

/** 综合得分 = Σ(源归一化分数 × 源权重 / 权重和) × 100（每个源内部按该源分数最大值归一到 0~1）。
 *  分数来源：源.scores（由 xlsx 层按 family 语义解析好：固定四类自动按列名/表结构定位，
 *  custom 按教师所选列）；legacy 存量源无 scores 时回退按 scoreColumn 取值。 */
export function computeScores(students: RosterStudent[], sources: ScoreSource[]): void {
  const valid = sources.filter((s) => s.weight > 0 && s.rows.length > 0
    && (Object.keys(s.scores ?? {}).length > 0 || s.scoreColumn !== ''))
  const totalWeight = valid.reduce((sum, s) => sum + s.weight, 0)
  for (const stu of students) {
    if (valid.length === 0 || totalWeight <= 0) {
      stu.score = null
      continue
    }
    let acc = 0
    for (const src of valid) {
      const raw = srcScoreOf(src, stu.name)
      if (raw === null) continue
      const nums = Object.values(srcScores(src)).filter((v) => v !== null) as number[]
      const max = nums.length ? Math.max(...nums) : 0
      acc += (max > 0 ? raw / max : 0) * (src.weight / totalWeight)
    }
    stu.score = Math.round(acc * 1000) / 10 // 0~100，保留 1 位小数
  }
}

/** 源内某个学生的分数（scores 表优先；legacy 无 scores 时按 scoreColumn 回退）。 */
export function srcScoreOf(src: ScoreSource, name: string): number | null {
  if (src.scores && Object.keys(src.scores).length > 0) {
    const v = src.scores[name]
    return typeof v === 'number' && Number.isFinite(v) ? v : null
  }
  const row = src.rows.find((r) => str(r[src.nameColumn]) === name)
  return row ? num(row[src.scoreColumn]) : null
}

function srcScores(src: ScoreSource): Record<string, number> {
  return src.scores ?? {}
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

/** legacy 存量源（无 family/scores 字段）的规范化：补 family='custom' + scores={}。 */
export function normalizeSource(s: Partial<ScoreSource>): ScoreSource {
  const family = (SCORE_FAMILY_PRESETS.some((p) => p.value === s.family) ? s.family : 'custom') as ScoreSource['family']
  return {
    name: String(s.name ?? ''),
    fileName: String(s.fileName ?? ''),
    family,
    scoreColumn: String(s.scoreColumn ?? ''),
    nameColumn: String(s.nameColumn ?? ''),
    weight: Number(s.weight ?? 1) || 1,
    rows: Array.isArray(s.rows) ? s.rows : [],
    scores: (s.scores && typeof s.scores === 'object' ? s.scores : {}) as Record<string, number>,
  }
}

export function tagLabel(tag: string): string {
  return tag || '（未打）'
}

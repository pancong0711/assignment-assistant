/** D221：题库 xlsx 写回路径解析 + 写前备份命名（纯函数，便于单测）。
 *
 * 现场问题：连接目录后写回，文件落到了 `kb/kb/problems.xlsx`。
 * 原因：按钮文案是“连接本地题库目录”，教师自然选了 `kb/` 本身；
 * 而写入代码固定拼 `kb/<kind>.xlsx`，于是多出一层。
 *
 * 规则（按“已连接目录”判断）：
 *  - 目录名就是 `kb`，或根目录下已存在 `<kind>.xlsx` → 认为连的是 **kb 目录本身**
 *    → 写 `<kind>.xlsx`
 *  - 否则认为连的是 **workspace 根** → 写 `kb/<kind>.xlsx`
 */

export const KB_KINDS = [
  'problems', 'qa', 'copy', 'distinguish', 'innovation', 'translation', 'summary',
] as const

export type KbKindName = (typeof KB_KINDS)[number]

export type KbDirMode = 'kb-dir' | 'workspace'

export interface KbWriteTarget {
  /** 相对“已连接目录”的写入路径 */
  path: string
  /** 该路径下的 kb 目录相对路径（用于 .history 备份） */
  kbDir: string
  mode: KbDirMode
  /** 人类可读说明（界面展示） */
  note: string
}

function lower(s: string): string {
  return String(s || '').trim().toLowerCase()
}

/** 判断已连接目录是不是 kb 目录本身。 */
export function looksLikeKbDir(dirName: string, rootEntries: string[]): boolean {
  if (lower(dirName) === 'kb') return true
  const names = new Set((rootEntries || []).map(lower))
  return KB_KINDS.some((k) => names.has(`${k}.xlsx`))
}

/** 已连接目录下，kb 相对前缀：连的是 kb 目录本身 → ''，workspace 根 → 'kb'。
 *  写 xlsx（D221）与写 fig（D223）必须用同一口径，否则又会出现 kb/kb。 */
export function resolveKbDirPrefix(dirName: string, rootEntries: string[]): '' | 'kb' {
  return looksLikeKbDir(dirName, rootEntries) ? '' : 'kb'
}

/** 解析某 kind 的写回目标。 */
export function resolveKbWriteTarget(
  dirName: string,
  rootEntries: string[],
  kind: string,
): KbWriteTarget {
  const k = String(kind || '').trim()
  if (resolveKbDirPrefix(dirName, rootEntries) === '') {
    return { path: `${k}.xlsx`, kbDir: '', mode: 'kb-dir',
             note: `已识别为 kb 目录，写入 ${k}.xlsx` }
  }
  return { path: `kb/${k}.xlsx`, kbDir: 'kb', mode: 'workspace',
           note: `已识别为 workspace 根目录，写入 kb/${k}.xlsx` }
}

/** 写前备份的相对路径：`<kbDir>/.history/<ts>/<kind>.xlsx`。 */
export function historyBackupPath(kbDir: string, kind: string, ts: string): string {
  const dir = String(kbDir || '').replace(/^\/+|\/+$/g, '')
  const stamp = String(ts || '').trim() || 'snapshot'
  const name = `${String(kind || '').replace(/[^\w.-]+/g, '_')}.xlsx`
  return (dir ? `${dir}/` : '') + `.history/${stamp}/${name}`
}

/** `YYYYMMDD-HHMMSS`（与引擎 `kb/.history/<ts>/` 同口径）。 */
export function historyStamp(d: Date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}` +
         `-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
}

/** 嵌套目录检测：已连接目录下若存在 `<dir>/kb/kb`，多半是历史误写。
 *  返回提示文案（无问题返回空串）。 */
export function nestedKbWarning(hasNestedKbKb: boolean, mode: KbDirMode): string {
  if (!hasNestedKbKb) return ''
  return mode === 'kb-dir'
    ? '检测到当前 kb 目录下还有一个多余的 kb/ 子目录（历史误写），可确认内容后删除。'
    : '检测到 kb/kb 嵌套目录（历史误写）：本次会写入 kb/；请确认后把 kb/kb 里的文件合并到 kb/ 再删除该子目录。'
}

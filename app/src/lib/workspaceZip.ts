import JSZip from 'jszip'
import type { KbKind } from './kb'
import { KB_KINDS } from './kb'

/** 导入导出 zip（docs/06 阶段2 / docs/05-D14 导出白名单）：
 *  内容 = 题库 xlsx 文件们 + fig/ 题图 + 任务包 JSON；
 *  绝不包含 .runtime/（引擎环境永不打包）。 */

/** 白名单内的 zip 成员路径（防 zip-slip，且排除 .runtime 与隐藏历史） */
function isAllowedEntry(path: string): boolean {
  const p = path.replace(/\\/g, '/')
  if (p.startsWith('/') || p.includes('..')) return false
  if (/(^|\/)\.runtime(\/|$)/.test(p)) return false
  if (/(^|\/)\.history(\/|$)/.test(p)) return false
  return true
}

export interface ExportZipInput {
  /** kind → xlsx 二进制 */
  kbXlsx: Partial<Record<KbKind, ArrayBuffer>>
  /** 相对 fig/ 的路径 → 文件 */
  figFiles?: Array<{ path: string; data: Blob | ArrayBuffer }>
  /** 任务包 JSON 文本（可多个） */
  taskpads?: Array<{ name: string; json: string }>
  meta?: Record<string, unknown>
}

export async function buildWorkspaceZip(input: ExportZipInput): Promise<Blob> {
  const zip = new JSZip()
  for (const kind of KB_KINDS) {
    const data = input.kbXlsx[kind]
    if (data) zip.file(`kb/${kind}.xlsx`, data)
  }
  for (const f of input.figFiles ?? []) {
    zip.file(`kb/fig/${f.path.replace(/^\/+/, '')}`, f.data)
  }
  for (const t of input.taskpads ?? []) {
    zip.file(`tasks/${t.name.replace(/^\/+/, '')}`, t.json)
  }
  zip.file('manifest.json', JSON.stringify({
    app: 'assignment-assistant',
    exported_at: new Date().toISOString(),
    note: '白名单导出：kb 题库 xlsx + fig 题图 + 任务包；不含 .runtime/（docs/05-D14）',
    ...input.meta,
  }, null, 2))
  return zip.generateAsync({ type: 'blob', compression: 'DEFLATE' })
}

export interface ZipEntry {
  path: string
  data: Uint8Array
}

export async function readWorkspaceZip(file: Blob): Promise<ZipEntry[]> {
  const zip = await JSZip.loadAsync(file)
  const out: ZipEntry[] = []
  const jobs: Promise<void>[] = []
  zip.forEach((path, entry) => {
    if (entry.dir) return
    if (!isAllowedEntry(path)) return
    jobs.push(entry.async('uint8array').then((data) => { out.push({ path, data }) }))
  })
  await Promise.all(jobs)
  return out
}

export { isAllowedEntry }

/** File System Access API 能力检测与封装（docs/05-D11：Firefox/Safari 降级提示）。
 *  Chrome/Edge 可用 → 可选目录直接写回；不可用 → 导出文件/上传文件交互。 */

export interface FsCapabilities {
  /** showDirectoryPicker 存在（目录读写能力） */
  directoryPicker: boolean
  /** showOpenFilePicker / showSaveFilePicker 存在 */
  filePicker: boolean
  /** 完整体验（题库 xlsx 原地写回、zip 导入恢复目录） */
  full: boolean
  /** 是否 Firefox / Safari 系（用于精确降级提示文案） */
  browserHint: string
}

export function detectCapabilities(): FsCapabilities {
  const ua = navigator.userAgent
  const isFirefox = /firefox/i.test(ua)
  const isSafari = /^((?!chrome|android|crios|fxios).)*safari/i.test(ua)
  const directoryPicker = typeof window.showDirectoryPicker === 'function'
  const filePicker =
    typeof window.showOpenFilePicker === 'function' &&
    typeof window.showSaveFilePicker === 'function'
  const full = directoryPicker && filePicker
  const browserHint = full
    ? ''
    : isFirefox
      ? '当前浏览器为 Firefox：不支持 File System Access API，已启用降级模式（下载文件 / 选择文件上传）。如需原地写回题库 xlsx、导入 zip 到本地目录，请改用 Chrome / Edge。'
      : isSafari
        ? '当前浏览器为 Safari：不支持 File System Access API，已启用降级模式（下载文件 / 选择文件上传）。如需原地写回题库 xlsx、导入 zip 到本地目录，请改用 Chrome / Edge。'
        : '当前浏览器不完整支持 File System Access API，已启用降级模式（下载文件 / 选择文件上传）。建议改用 Chrome / Edge 获得完整体验。'
  return { directoryPicker, filePicker, full, browserHint }
}

/** 请求一个目录句柄（readwrite）。用户拒绝/不支持时返回 null。 */
export async function pickDirectory(): Promise<FileSystemDirectoryHandle | null> {
  if (!window.showDirectoryPicker) return null
  try {
    return await window.showDirectoryPicker({ mode: 'readwrite', id: 'assignment-assistant' })
  } catch {
    return null // 用户取消
  }
}

type PermissionHandle = FileSystemHandle & {
  queryPermission?: (descriptor: { mode: 'read' | 'readwrite' }) => Promise<PermissionState>
  requestPermission?: (descriptor: { mode: 'read' | 'readwrite' }) => Promise<PermissionState>
}

export async function ensurePermission(handle: PermissionHandle, mode: 'read' | 'readwrite'): Promise<boolean> {
  if (!handle.queryPermission) return true
  if ((await handle.queryPermission({ mode })) === 'granted') return true
  if (!handle.requestPermission) return false
  return (await handle.requestPermission({ mode })) === 'granted'
}

/** 在目录句柄下写入文件（自动创建父目录）。 */
export async function writeFileInDir(
  dir: FileSystemDirectoryHandle,
  path: string,
  data: BlobPart | ArrayBuffer,
): Promise<void> {
  const parts = path.split('/').filter(Boolean)
  const name = parts.pop()!
  let cur = dir
  for (const seg of parts) {
    cur = await cur.getDirectoryHandle(seg, { create: true })
  }
  const fh = await cur.getFileHandle(name, { create: true })
  const writable = fh.createWritable
    ? await fh.createWritable()
    : await (fh as unknown as { createWritable: () => Promise<FileSystemWritableFileStream> }).createWritable()
  await writable.write(data instanceof Blob ? data : new Blob([data as BlobPart]))
  await writable.close()
}

/** 兜底：浏览器下载一个文件（降级路径，所有浏览器可用）。 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

/** 下载文本/二进制为文件。 */
export function downloadData(data: BlobPart | ArrayBuffer, filename: string, mime = 'application/octet-stream'): void {
  const blob = data instanceof Blob ? data : new Blob([data as BlobPart], { type: mime })
  downloadBlob(blob, filename)
}

/** 选择并读取一个本地文件（input 兜底，所有浏览器可用）。 */
export function pickReadFile(accept: string): Promise<File | null> {
  return new Promise((resolve) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = accept
    input.onchange = () => resolve(input.files?.[0] ?? null)
    input.oncancel = () => resolve(null)
    input.click()
  })
}

/** 选择并读取一个本地文件：File System Access API 优先（Chrome/Edge），
 *  不可用/用户取消 → input 兜底（同 pickReadFile），返回 null 表示未选。 */
export async function pickReadFileFsa(accept: string): Promise<File | null> {
  if (typeof window.showOpenFilePicker === 'function') {
    try {
      const [handle] = await window.showOpenFilePicker({
        multiple: false,
        types: [{ description: accept, accept: { 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'] } }],
      })
      return await handle.getFile()
    } catch {
      return null // 用户取消
    }
  }
  return pickReadFile(accept)
}

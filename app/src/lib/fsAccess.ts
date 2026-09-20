/** File System Access API 能力检测与封装（docs/05-D11；D19 反馈：LAN 场景修复）。
 *
 * 关键点（D19 检测反馈第 1 项）：
 * - File System Access API 仅在**安全上下文**（isSecureContext：https / localhost）
 *   下可用。通过 http://<LAN IP>:8602/ 访问时 window.showOpenFilePicker 不存在，
 *   这是平台限制而非浏览器不支持。
 * - 因此能力检测必须同时看 `window.isSecureContext`；不满足时**静默降级**：
 *   文件导入走 <input type=file>（所有浏览器/场景可用），不弹
 *   "当前浏览器不支持" 错误横幅 —— LAN 预览下用 file input 即可完成
 *   名单/成绩/题库 xlsx 与任务包 JSON 的导入。
 * - "写回/另存/连接目录"等真正的写能力入口在 LAN 下不可用：界面把按钮改为
 *   "下载文件（教师手动放回 workspace）"，并通过 fsWriteHint() 说明原因
 *   （需本机打开：localhost 或 https）。
 */

export interface FsCapabilities {
  /** showDirectoryPicker 存在（目录读写能力；安全上下文限定） */
  directoryPicker: boolean
  /** showOpenFilePicker / showSaveFilePicker 存在（安全上下文限定） */
  filePicker: boolean
  /** 完整体验（题库 xlsx 原地写回、zip 导入恢复目录）= 安全上下文 + 目录/文件 picker */
  full: boolean
  /** 是否因非安全上下文降级（http://<LAN IP> 场景；用于写能力入口的提示） */
  insecure: boolean
  /** 是否 Firefox / Safari 系（用于精确降级提示文案） */
  browserHint: string
}

export function detectCapabilities(): FsCapabilities {
  const ua = navigator.userAgent
  const isFirefox = /firefox/i.test(ua)
  const isSafari = /^((?!chrome|android|crios|fxios).)*safari/i.test(ua)
  const insecure = !window.isSecureContext
  const directoryPicker = insecure ? false : typeof window.showDirectoryPicker === 'function'
  const filePicker = insecure
    ? false
    : typeof window.showOpenFilePicker === 'function' &&
      typeof window.showSaveFilePicker === 'function'
  const full = directoryPicker && filePicker
  const browserHint = full
    ? ''
    : insecure
      // LAN（http://IP）场景：不是浏览器问题，不要求换浏览器；写回能力入口单独提示。
      ? ''
      : isFirefox
        ? '当前浏览器为 Firefox：不支持 File System Access API，已启用降级模式（下载文件 / 选择文件上传）。如需原地写回题库 xlsx、导入 zip 到本地目录，请改用 Chrome / Edge。'
        : isSafari
          ? '当前浏览器为 Safari：不支持 File System Access API，已启用降级模式（下载文件 / 选择文件上传）。如需原地写回题库 xlsx、导入 zip 到本地目录，请改用 Chrome / Edge。'
          : '当前浏览器不完整支持 File System Access API，已启用降级模式（下载文件 / 选择文件上传）。建议改用 Chrome / Edge 获得完整体验。'
  return { directoryPicker, filePicker, full, insecure, browserHint }
}

/** 写能力（连接目录/原地写回/另存到目录）入口在当前环境是否可用。 */
export function canWriteFs(): boolean {
  return detectCapabilities().directoryPicker
}

/** 写能力入口的提示文案（按钮 title / 提示行用）。
 *  LAN（http://IP）下说明原因：非安全上下文，需本机打开（localhost / https）。 */
export function fsWriteHint(): string {
  if (window.isSecureContext) return ''
  return '当前通过局域网 IP（http://…）访问，浏览器在非安全上下文下不提供"直接写本地目录"能力；请在本机用 localhost（或 https）打开后使用。局域网预览下请用"下载文件"，教师手动放回 workspace 即可。'
}

/** 请求一个目录句柄（readwrite）。不支持/用户拒绝时返回 null。 */
export async function pickDirectory(): Promise<FileSystemDirectoryHandle | null> {
  if (!canWriteFs() || !window.showDirectoryPicker) return null
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

/** 兜底：浏览器下载一个文件（降级路径，所有浏览器/场景可用，含 LAN）。 */
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

/** 选择并读取一个本地文件（input 兜底，所有浏览器/场景可用，含 LAN）。 */
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

/** 选择并读取一个本地文件：File System Access API 优先（本机安全上下文的 Chrome/Edge），
 *  不可用（LAN http / Firefox / Safari）/用户取消 → input 兜底（同 pickReadFile，静默降级，
 *  不弹"浏览器不支持"提示），返回 null 表示未选。 */
export async function pickReadFileFsa(accept: string): Promise<File | null> {
  if (window.isSecureContext && typeof window.showOpenFilePicker === 'function') {
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

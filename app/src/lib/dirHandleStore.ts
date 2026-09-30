/** dirHandleStore.ts — D55/H1：workspace 目录句柄的 IndexedDB 持久化（零依赖）。
 *  动机：FileSystemDirectoryHandle 此前只存内存，刷新即"未连接"；教师"设置好 workspace"后
 *  KaTeX 直装/写回全部失效。方案：句柄入 IDB（Chrome/Edge 支持结构化克隆句柄），
 *  启动时读回 + queryPermission/requestPermission 恢复授权。IDB 不可用=静默降级（会话内仍可用）。 */

const DB = 'assist-dir-handles'
const STORE = 'handles'
const KEY = 'workspace'

function openDb(): Promise<IDBDatabase | null> {
  return new Promise((resolve) => {
    try {
      const req = indexedDB.open(DB, 1)
      req.onupgradeneeded = () => {
        const db = req.result
        if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE)
      }
      req.onsuccess = () => resolve(req.result)
      req.onerror = () => resolve(null)
    } catch { resolve(null) }
  })
}

export async function saveDirHandle(handle: FileSystemDirectoryHandle): Promise<void> {
  const db = await openDb(); if (!db) return
  await new Promise<void>((resolve) => {
    try {
      const tx = db.transaction(STORE, 'readwrite')
      tx.objectStore(STORE).put(handle, KEY)
      tx.oncomplete = () => { db.close(); resolve() }
      tx.onerror = () => { db.close(); resolve() }
    } catch { db.close(); resolve() }
  })
}

export async function loadDirHandle(): Promise<FileSystemDirectoryHandle | null> {
  const db = await openDb(); if (!db) return null
  return new Promise((resolve) => {
    try {
      const tx = db.transaction(STORE, 'readonly')
      const req = tx.objectStore(STORE).get(KEY)
      req.onsuccess = () => { db.close(); resolve((req.result as FileSystemDirectoryHandle) ?? null) }
      req.onerror = () => { db.close(); resolve(null) }
    } catch { db.close(); resolve(null) }
  })
}

export async function clearDirHandle(): Promise<void> {
  const db = await openDb(); if (!db) return
  await new Promise<void>((resolve) => {
    try {
      const tx = db.transaction(STORE, 'readwrite')
      tx.objectStore(STORE).delete(KEY)
      tx.oncomplete = () => { db.close(); resolve() }
      tx.onerror = () => { db.close(); resolve() }
    } catch { db.close(); resolve() }
  })
}

/** 权限恢复：queryPermission 已有 → 直接可用；prompt → requestPermission（需用户手势的浏览器可能拒绝，静默降级）。 */
export async function ensureDirPermission(handle: FileSystemDirectoryHandle): Promise<boolean> {
  const h = handle as unknown as {
    queryPermission?: (d: { mode: 'readwrite' }) => Promise<PermissionState>
    requestPermission?: (d: { mode: 'readwrite' }) => Promise<PermissionState>
  }
  try {
    if (!h.queryPermission) return true
    const q = await h.queryPermission({ mode: 'readwrite' })
    if (q === 'granted') return true
    if (q === 'prompt' && h.requestPermission) {
      return (await h.requestPermission({ mode: 'readwrite' })) === 'granted'
    }
    return false
  } catch { return false }
}

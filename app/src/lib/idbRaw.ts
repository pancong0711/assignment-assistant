/** idbRaw.ts — D46-3：成绩源原始 xlsx 的 IndexedDB 留存（轻量封装，零依赖）。
 *  动机：VC-6 导入预览只显示"当次"；刷新后无法回看某源的解析口径，reparse/rescore 还要二次选文件。
 *  方案：每源存整份 ArrayBuffer（数 MB 量级可接受），key = roster store 分配的 source uid；
 *  提供 get/put/del + clearAll；IndexedDB 不可用（老浏览器/隐私模式）时全部静默降级为 no-op，
 *  UI 侧据 hasRaw 决定 👁 按钮可用性（降级=按钮置灰提示"重新选文件查看"）。 */

const DB_NAME = 'assist-roster-raw'
const STORE = 'sources'
const VERSION = 1

function openDb(): Promise<IDBDatabase | null> {
  return new Promise((resolve) => {
    try {
      const req = indexedDB.open(DB_NAME, VERSION)
      req.onupgradeneeded = () => {
        const db = req.result
        if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE)
      }
      req.onsuccess = () => resolve(req.result)
      req.onerror = () => resolve(null)
    } catch {
      resolve(null)
    }
  })
}

export async function idbPut(key: string, buf: ArrayBuffer): Promise<boolean> {
  const db = await openDb()
  if (!db) return false
  return new Promise((resolve) => {
    try {
      const tx = db.transaction(STORE, 'readwrite')
      tx.objectStore(STORE).put(buf, key)
      tx.oncomplete = () => { db.close(); resolve(true) }
      tx.onerror = () => { db.close(); resolve(false) }
    } catch { db.close(); resolve(false) }
  })
}

export async function idbGet(key: string): Promise<ArrayBuffer | null> {
  const db = await openDb()
  if (!db) return null
  return new Promise((resolve) => {
    try {
      const tx = db.transaction(STORE, 'readonly')
      const req = tx.objectStore(STORE).get(key)
      req.onsuccess = () => { db.close(); resolve((req.result as ArrayBuffer) ?? null) }
      req.onerror = () => { db.close(); resolve(null) }
    } catch { db.close(); resolve(null) }
  })
}

export async function idbDel(key: string): Promise<void> {
  const db = await openDb()
  if (!db) return
  try {
    const tx = db.transaction(STORE, 'readwrite')
    tx.objectStore(STORE).delete(key)
    tx.oncomplete = () => db.close()
  } catch { db.close() }
}

export async function idbClearAll(): Promise<void> {
  const db = await openDb()
  if (!db) return
  try {
    const tx = db.transaction(STORE, 'readwrite')
    tx.objectStore(STORE).clear()
    tx.oncomplete = () => db.close()
  } catch { db.close() }
}

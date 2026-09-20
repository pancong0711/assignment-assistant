import { defineStore } from 'pinia'
import {
  KB_KINDS, emptyRow,
  type KbBook, type KbKind, type KbRow,
} from '../lib/kb'
import { readKbXlsx, writeKbXlsx } from '../lib/kbXlsx'
import { downloadData, pickDirectory, writeFileInDir } from '../lib/fsAccess'
import { demoBooks } from '../demo/demoData'

/** 题库 store：浏览器内存中的 kb（xlsx = source of truth，docs/05-D3）。
 *  读：教师上传 xlsx / 加载合成示例 / zip 导入；
 *  写：File System Access API 原地写回（Chrome/Edge），不可用时导出文件（D11 降级）。
 *  TODO(阶段3+)：companion 模式下可委托 engine `assist kb` 写回并自动 .history/ 快照。 */

interface PersistedKb {
  books: KbBook[]
  savedAt: string
}

const LS_KEY = 'assignment-assistant.kb.v1'

function emptyBooks(): Record<KbKind, KbBook> {
  const out = {} as Record<KbKind, KbBook>
  for (const k of KB_KINDS) out[k] = { kind: k, chapters: [] }
  return out
}

function fromPersisted(raw: string): Record<KbKind, KbBook> | null {
  try {
    const obj = JSON.parse(raw) as PersistedKb
    if (!Array.isArray(obj.books)) return null
    const books = emptyBooks()
    for (const b of obj.books) {
      if ((KB_KINDS as readonly string[]).includes(b.kind)) books[b.kind] = b
    }
    return books
  } catch {
    return null
  }
}

export const useKbStore = defineStore('kb', {
  state: () => ({
    books: emptyBooks(),
    /** 数据来源标记（用于界面提示） */
    origin: 'none' as 'none' | 'demo' | 'file' | 'zip' | 'fs',
    savedAt: '',
    /** 已连接的 kb 所在目录句柄名字（句柄本体存内存，不序列化） */
    fsDirName: '' as string,
    dirty: false,
  }),
  getters: {
    allBooks(state): KbBook[] {
      return KB_KINDS.map((k) => state.books[k])
    },
    book(state): (kind: KbKind) => KbBook {
      return (kind) => state.books[kind]
    },
    hasData(state): boolean {
      return KB_KINDS.some((k) => state.books[k].chapters.length > 0)
    },
    /** 全库题目的扁平索引（供设计器选题） */
    allRows(state): Array<{ kind: KbKind; chap: string; row: KbRow }> {
      const out: Array<{ kind: KbKind; chap: string; row: KbRow }> = []
      for (const k of KB_KINDS) {
        for (const ch of state.books[k].chapters) {
          for (const row of ch.rows) out.push({ kind: k, chap: ch.name, row })
        }
      }
      return out
    },
  },
  actions: {
    /** 载入合成示例（占位合成题，不含任何真实数据） */
    loadDemo() {
      const books = emptyBooks()
      for (const b of demoBooks) books[b.kind] = b
      this.books = books
      this.origin = 'demo'
      this.dirty = true
    },
    clearAll() {
      this.books = emptyBooks()
      this.origin = 'none'
      this.dirty = false
      localStorage.removeItem(LS_KEY)
    },
    /** 读取教师选择的 xlsx 文件（File input 方式，Firefox/Safari 亦可） */
    async loadXlsxFile(file: File): Promise<{ ok: boolean; message: string }> {
      const stem = file.name.replace(/\.xlsx$/i, '')
      const kind = (KB_KINDS as readonly string[]).includes(stem)
        ? (stem as KbKind)
        : null
      if (!kind) {
        return { ok: false, message: `无法从文件名识别 kind（${file.name}）。请使用 problems.xlsx / copy.xlsx / qa.xlsx / distinguish.xlsx / innovation.xlsx / translation.xlsx 命名。` }
      }
      const book = await readKbXlsx(file, kind)
      this.books[kind] = book
      this.origin = 'file'
      this.dirty = true
      this.persist()
      return { ok: true, message: `已读入 ${kind}：${book.chapters.length} 个 sheet（章），共 ${book.chapters.reduce((n, c) => n + c.rows.length, 0)} 题。` }
    },
    async loadXlsxData(data: ArrayBuffer, kind: KbKind, origin: 'file' | 'zip' = 'file') {
      this.books[kind] = await readKbXlsx(data, kind)
      this.origin = origin
      this.dirty = true
      this.persist()
    },
    connectWorkspaceDir(): Promise<boolean> {
      return pickDirectory().then((dir) => {
        if (!dir) return false
        setKbDirHandle(dir)
        this.fsDirName = dir.name
        this.origin = this.origin === 'none' ? 'fs' : this.origin
        return true
      })
    },
    /** 章级操作 */
    addChapter(kind: KbKind, name: string) {
      const n = name.trim()
      if (!n) return
      if (this.books[kind].chapters.some((c) => c.name === n)) return
      this.books[kind].chapters.push({ name: n, rows: [] })
      this.dirty = true
    },
    removeChapter(kind: KbKind, name: string) {
      const b = this.books[kind]
      b.chapters = b.chapters.filter((c) => c.name !== name)
      this.dirty = true
    },
    renameChapter(kind: KbKind, oldName: string, newName: string) {
      const c = this.books[kind].chapters.find((x) => x.name === oldName)
      if (!c) return
      c.name = newName
      this.dirty = true
    },
    addRow(kind: KbKind, chap: string) {
      const c = this.books[kind].chapters.find((x) => x.name === chap)
      if (!c) return
      c.rows.push({ ...emptyRow(`NEW-${c.rows.length + 1}`) })
      this.dirty = true
    },
    removeRow(kind: KbKind, chap: string, idx: number) {
      const c = this.books[kind].chapters.find((x) => x.name === chap)
      if (!c) return
      c.rows.splice(idx, 1)
      this.dirty = true
    },
    touch() {
      this.dirty = true
    },
    rowText(kind: KbKind, chap: string, id: string): string {
      const c = this.books[kind]?.chapters.find((x) => x.name === chap)
      const r = c?.rows.find((x) => x.id === id)
      return r ? r.content : ''
    },
    /** 内存 → xlsx 二进制（zip 导出用） */
    exportBinaries(): Partial<Record<KbKind, ArrayBuffer>> {
      const out: Partial<Record<KbKind, ArrayBuffer>> = {}
      for (const k of KB_KINDS) {
        if (this.books[k].chapters.length) out[k] = writeKbXlsx(this.books[k])
      }
      return out
    },
    downloadKind(kind: KbKind, suffix = '') {
      const bin = writeKbXlsx(this.books[kind])
      downloadData(bin, `${kind}${suffix}.xlsx`,
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    },
    /** 写回：已连接本地目录（Chrome/Edge）→ 写到 <目录>/kb/<kind>.xlsx；
     *  否则下载文件（D11 降级）。 */
    async saveKind(kind: KbKind): Promise<string> {
      const bin = writeKbXlsx(this.books[kind])
      const dirHandle = getKbDirHandle()
      if (dirHandle) {
        await writeFileInDir(dirHandle, `kb/${kind}.xlsx`, bin)
        this.savedAt = new Date().toLocaleTimeString()
        // TODO(阶段1 engine 已具备)：真实快照由 engine `assist kb snapshot` 负责
        this.dirty = false
        return `已写回 ${this.fsDirName}/kb/${kind}.xlsx`
      }
      this.downloadKind(kind)
      return `当前浏览器不支持原地写回，已导出 ${kind}.xlsx（可用其替换本地文件；或改用 Chrome/Edge 获得直接写回）`
    },
    persist() {
      const data: PersistedKb = { books: this.allBooks, savedAt: new Date().toISOString() }
      try {
        localStorage.setItem(LS_KEY, JSON.stringify(data))
        this.savedAt = data.savedAt
      } catch {
        // 题库过大超出 localStorage 配额时静默跳过（内存中仍可编辑/导出）
      }
    },
    restorePersisted(): boolean {
      const raw = localStorage.getItem(LS_KEY)
      if (!raw) return false
      const books = fromPersisted(raw)
      if (!books) return false
      this.books = books
      this.origin = 'file'
      return this.hasData
    },
  },
})

// 目录句柄不进 reactive 序列化（handle 无法结构化克隆），挂在 store 外部
const moduleAny = useKbStore as unknown as { _dirHandle?: FileSystemDirectoryHandle }
export function setKbDirHandle(handle: FileSystemDirectoryHandle | undefined) {
  moduleAny._dirHandle = handle
}
export function getKbDirHandle(): FileSystemDirectoryHandle | undefined {
  return moduleAny._dirHandle
}

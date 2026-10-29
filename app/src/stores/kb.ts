import { defineStore } from 'pinia'
import {
  KB_KINDS, emptyRow,
  type KbBook, type KbKind, type KbRow,
} from '../lib/kb'
import { readKbXlsx, writeKbXlsx } from '../lib/kbXlsx'
import { downloadData, pickDirectory, writeFileInDir } from '../lib/fsAccess'
import { demoBooks } from '../demo/demoData'
import { fetchKbSolutionIndex, solutionScopeKey, type KbSolutionEntry } from '../lib/engineClient'
import { pickEffectiveSolution, type SolutionLike } from '../lib/sheetHtml'

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

function demoBooksFactory(): Record<KbKind, KbBook> {
  const out = emptyBooks()
  for (const b of demoBooks) out[b.kind] = b
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

function kindFromXlsxName(fname: string): KbKind | null {
  const stem = fname.replace(/\.xlsx$/i, '')
  const kinds = KB_KINDS as readonly string[]
  if (kinds.includes(stem)) return stem as KbKind
  for (const k of kinds) {
    if (stem === `${k}-example` || stem === `example-${k}`) return k as KbKind
  }
  return null
}

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(String(r.result ?? ''))
    r.onerror = () => reject(r.error)
    r.readAsDataURL(file)
  })
}

const FIG_EXTS = /[.](png|jpe?g|webp|gif|bmp)$/i

async function collectFigFiles(dir: FileSystemDirectoryHandle, acc: File[], limit = 500, depth = 0): Promise<void> {
  if (depth > 4 || acc.length >= limit) return
  // @ts-expect-error values() 在部分 TS lib 中缺失
  for await (const entry of dir.values()) {
    if (acc.length >= limit) return
    if (entry.kind === 'file') {
      if (FIG_EXTS.test(entry.name)) {
        try { acc.push(await (entry as FileSystemFileHandle).getFile()) } catch { /* skip */ }
      }
    } else if (depth < 4) {
      await collectFigFiles(entry as FileSystemDirectoryHandle, acc, limit, depth + 1)
    }
  }
}

export const useKbStore = defineStore('kb', {
  state: () => ({
    // 初始：无任何本地记录时自动载入合成示例（快速上手体验；载入教师数据后即被替换）
    books: fromPersisted(localStorage.getItem(LS_KEY) ?? '') ?? demoBooksFactory(),
    /** 数据来源标记（用于界面提示） */
    origin: 'none' as 'none' | 'demo' | 'file' | 'zip' | 'fs',
    savedAt: '',
    /** 已连接的 kb 所在目录句柄名字（句柄本体存内存，不序列化） */
    fsDirName: '' as string,
    dirty: false,
    /** D100-T6：题库 solution 版本库「生效答案」索引（qid → {text, from, version, ...}）。
     *  来源 = 引擎 `GET /kb/solutions`（批量）；引擎离线时为空 → 全部回落 xlsx `solution` 列。
     *  不持久化（每次刷新重拉，避免 xlsx 与版本库长期漂移）。 */
    solIndex: {} as Record<string, KbSolutionEntry>,
    /** D110：按 `kb__chap__qid` 精确索引（跨章同号题的正确答案；优先于 solIndex）。 */
    solIndexByKey: {} as Record<string, KbSolutionEntry>,
    /** D100-T6：索引刷新次数（预览 computed 依赖它 → AI 作答完成后能立即重算）。 */
    solutionsRev: 0,
    /** 索引最近一次成功/失败的状态文案（供设置/题库页展示）。 */
    solutionsMsg: '' as string,
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
    /** D100-T6：生效答案解析器（供 `expandPadItems` 注入）。
     *  pinned 版 > 最新版 > xlsx `solution` 列 fallback，语义同引擎 `effective_solution`。 */
    effectiveSolution(state): (qid: string, fallback: string,
                                scope?: { kb?: string; chap?: string }) => SolutionLike {
      return (qid, fallback, scope) => {
        // 批量索引条目本身已是"生效版"（引擎 effective_solution 同语义）；
        // pickEffectiveSolution 对扁平条目会补全 version（field=id）并保留 from/pinned。
        // D110：先按 (kb, chap, qid) 精确命中，再回落按 qid 的旧索引
        // （旧索引在跨章同号时带 ambiguous 标记，此时不应盲用）。
        const key = solutionScopeKey(qid, scope?.kb, scope?.chap)
        const scoped = state.solIndexByKey[key]
        if (scoped && String(scoped.text ?? '').trim()) return pickEffectiveSolution(scoped, fallback)
        const hit = state.solIndex[String(qid)]
        if (hit && String(hit.text ?? '').trim() && !hit.ambiguous) {
          return pickEffectiveSolution(hit, fallback)
        }
        return pickEffectiveSolution(null, fallback)
      }
    },
    /** 某题是否已有版本库记录（题库表格摘要用）。D110：可按作用域精确查。 */
    solutionOf(state): (qid: string, scope?: { kb?: string; chap?: string }) => KbSolutionEntry | undefined {
      return (qid, scope) => {
        const key = solutionScopeKey(qid, scope?.kb, scope?.chap)
        return state.solIndexByKey[key] ?? state.solIndex[String(qid)]
      }
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
      const kind = kindFromXlsxName(file.name)
      if (!kind) {
        return { ok: false, message: `无法从文件名识别 kind（${file.name}）。请使用 problems.xlsx / problems-example.xlsx 等命名。` }
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
    /** D83-1：启动/刷新时恢复 workspace —— 恢复句柄 + 权限，成功后自动重扫 kb/*.xlsx 与 kb/fig。
     *  返回 { restored, needPermission, loaded } 供设置页展示状态。 */
    async restoreWorkspace(): Promise<{ restored: boolean; needPermission: boolean; loaded: string[] }> {
      const empty = { restored: false, needPermission: false, loaded: [] as string[] }
      try {
        const { loadDirHandle, ensureDirPermission } = await import('../lib/dirHandleStore')
        const h = await loadDirHandle()
        if (!h) return empty
        const ok = await ensureDirPermission(h)
        if (!ok) return { restored: false, needPermission: true, loaded: [] }
        setKbDirHandle(h)
        this.fsDirName = h.name
        const r = await this.loadWorkspaceKbFiles(h)
        return { restored: true, needPermission: false, loaded: r.loaded }
      } catch { return empty }
    },
    async connectWorkspaceDir(): Promise<boolean> {
      const dir = await pickDirectory()
      if (!dir) return false
      // D120-Q1：必须是 **workspace 根**（内含 kb/）。
      // 旧实现把「题库目录」和「workspace 根」当同一个句柄用，
      // 导致 roster 被写进 <ws>/kb/classes/（引擎读不到 → AI 批阅报"名单 0 人"）。
      const hasKb = await dirHasSubdir(dir, 'kb')
      if (!hasKb) {
        this.savedAt = ''
        this.origin = this.origin === 'none' ? 'none' : this.origin
        // 用 fsDirName 传递错误提示（视图层会读它展示）
        this.fsDirName = ''
        throw new Error(
          `所选目录不是 workspace 根（未找到 kb/ 子目录）：${dir.name}。` +
          '请选择包含 kb/、classes/ 的上级目录，而不是 kb/ 本身。',
        )
      }
      await connectKbDir(dir)
      this.fsDirName = dir.name
      this.origin = this.origin === 'none' ? 'fs' : this.origin
      await this.loadWorkspaceKbFiles(dir)
      return true
    },
    /** D82：从 workspace/kb 目录读取所有可识别的 xlsx（支持多个 xlsx）。 */
    async loadWorkspaceKbFiles(dirHandle: FileSystemDirectoryHandle): Promise<{ ok: boolean; loaded: string[]; skipped: string[] }> {
      const loaded: string[] = []
      const skipped: string[] = []
      let kbDir: FileSystemDirectoryHandle | null = null
      try { kbDir = await dirHandle.getDirectoryHandle('kb') } catch { kbDir = null }
      const roots = kbDir ? [kbDir] : [dirHandle]
      const files: File[] = []
      for (const root of roots) {
        // @ts-expect-error FileSystemDirectoryHandle.values 在部分 TS lib 中缺失
        for await (const entry of root.values()) {
          const e = entry as FileSystemFileHandle
          if (e.kind !== 'file' || !/\.xlsx$/i.test(e.name)) continue
          const kind = kindFromXlsxName(e.name)
          if (!kind) { skipped.push(e.name); continue }
          try { files.push(await e.getFile()) } catch { skipped.push(e.name) }
        }
      }
      // exact 文件名优先于 -example
      files.sort((a, b) => {
        const ae = /-example\.xlsx$/i.test(a.name) || /^example-/.test(a.name)
        const be = /-example\.xlsx$/i.test(b.name) || /^example-/.test(b.name)
        return Number(ae) - Number(be)
      })
      for (const f of files) {
        const kind = kindFromXlsxName(f.name)
        if (!kind) continue
        this.books[kind] = await readKbXlsx(f, kind)
        loaded.push(`${kind}(${f.name})`)
      }
      this.origin = loaded.length ? 'fs' : this.origin
      if (loaded.length) this.persist()
      // D82：自动扫描 kb/fig（或根 fig）图片 → settings.figAssets，用于缩略图/预览
      try {
        const figDirs: FileSystemDirectoryHandle[] = []
        for (const base of [kbDir, dirHandle]) {
          if (!base) continue
          for (const name of ['fig', 'figs']) {
            try { figDirs.push(await base.getDirectoryHandle(name)) } catch { /* continue */ }
          }
        }
        const figFiles: File[] = []
        for (const d of figDirs) await collectFigFiles(d, figFiles, 500)
        if (figFiles.length) {
          const { useSettingsStore } = await import('./settings')
          const settings = useSettingsStore()
          for (const f of figFiles) {
            if (f.size > 5 * 1024 * 1024) continue
            try { settings.persistFigAsset(f.name, await fileToDataUrl(f)) } catch { /* skip */ }
          }
          loaded.push(`fig×${figFiles.length}`)
        }
      } catch { /* 图库扫描失败不影响 xlsx 读取 */ }
      return { ok: loaded.length > 0, loaded, skipped }
    },
    /** D82：示例数据导出为 <kind>-example.xlsx。 */
    downloadExample(kind: KbKind) {
      const bin = writeKbXlsx(this.books[kind])
      downloadData(bin, `${kind}-example.xlsx`,
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
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
    /** D100-T6：从引擎拉全库生效答案索引（幂等；引擎离线 → 清空索引并回落 xlsx 列）。 */
    async refreshSolutions(): Promise<{ ok: boolean; count: number; message: string }> {
      const { useSettingsStore } = await import('./settings')
      const settings = useSettingsStore()
      const r = await fetchKbSolutionIndex(settings.engineUrl, settings.engineToken)
      const eff = r.effective ?? {}
      this.solIndex = eff
      this.solIndexByKey = r.effectiveByKey ?? {}
      this.solutionsRev += 1
      const ok = r.ok !== false && !!r.effective
      this.solutionsMsg = ok
        ? `已载入 ${Object.keys(eff).length} 题生效答案（引擎版本库）`
        : '引擎离线或未启用版本库：参考答案回落题库 solution 列'
      return { ok, count: Object.keys(eff).length, message: this.solutionsMsg }
    },
    /** D100-T6：本地已知变更（AI 作答完成 / 手动追加·置顶·删除版本）后刷新索引。 */
    async bumpSolutions(): Promise<void> {
      try { await this.refreshSolutions() } catch { /* 引擎离线：保持旧索引/xlsx 回落 */ }
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
    /** 写回顺序（B4）：
     *  ① 引擎在线 → POST /kb/write，openpyxl 原位改值保留样式 + .history 快照；
     *  ② 否则回退 File System Access 原地写（SheetJS 纯数据，会丢样式）；
     *  ③ 再不行下载文件（D11 降级）。
     *  translation 是中文例外表，PWA 读到的是合成后的通用 KbBook，暂不走样式写回。 */
    async saveKind(kind: KbKind): Promise<string> {
      let engineNote = ''
      if (kind !== 'translation') {
        try {
          const { useSettingsStore } = await import('./settings')
          const settings = useSettingsStore()
          if (settings.engineOnline) {
            const { writeKbViaEngine } = await import('../lib/engineClient')
            const path = await writeKbViaEngine(
              settings.engineUrl, settings.engineToken, kind, this.books[kind].chapters,
            )
            this.savedAt = new Date().toLocaleTimeString()
            this.dirty = false
            return `已通过引擎样式保留写回 ${path}（写前自动 .history 快照）`
          }
        } catch (e) {
          engineNote = `；引擎样式写回失败：${(e as Error).message}`
        }
      }
      const bin = writeKbXlsx(this.books[kind])
      const dirHandle = getKbDirHandle()
      if (dirHandle) {
        await writeFileInDir(dirHandle, `kb/${kind}.xlsx`, bin)
        this.savedAt = new Date().toLocaleTimeString()
        // TODO(阶段1 engine 已具备)：真实快照由 engine `assist kb snapshot` 负责
        this.dirty = false
        return `已写回 ${this.fsDirName}/kb/${kind}.xlsx${engineNote}`
      }
      this.downloadKind(kind)
      return `当前浏览器不支持原地写回，已导出 ${kind}.xlsx（可用其替换本地文件；或改用 Chrome/Edge 获得直接写回）${engineNote}`
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

/** D55/H1：连接 workspace 目录（设置句柄 + IndexedDB 持久化，刷新后自动恢复）。 */
export async function connectKbDir(handle: FileSystemDirectoryHandle): Promise<void> {
  setKbDirHandle(handle)
  try {
    const { saveDirHandle } = await import('../lib/dirHandleStore')
    await saveDirHandle(handle)
  } catch { /* 降级：仅会话内有效 */ }
}

/** D55/H1：启动时恢复 workspace 句柄（IDB → 权限检查/请求）；返回是否恢复成功。 */
export async function restoreKbDir(): Promise<boolean> {
  try {
    const { loadDirHandle, ensureDirPermission } = await import('../lib/dirHandleStore')
    const h = await loadDirHandle()
    if (!h) return false
    if (await ensureDirPermission(h)) { setKbDirHandle(h); return true }
    return false
  } catch { return false }
}
/** D120：目录下是否存在指定子目录（workspace 根校验用）。 */
async function dirHasSubdir(dir: FileSystemDirectoryHandle, name: string): Promise<boolean> {
  try {
    await dir.getDirectoryHandle(name)
    return true
  } catch {
    return false
  }
}

export function getKbDirHandle(): FileSystemDirectoryHandle | undefined {
  return moduleAny._dirHandle
}

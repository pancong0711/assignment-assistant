import { defineStore } from 'pinia'
import { fetchPacks, savePack, type Pack } from '../lib/engineClient'
import { useSettingsStore } from './settings'

/** D89-N1：作业包 store —— 当前包 + 包列表。
 *  作业包 = 一次分层作业全部作业纸的集合（引用 padId，作业纸是唯一真源）。
 *  在线：读写引擎 <ws>/packs/；离线：退回 localStorage（仅本浏览器，界面提示）。 */

const LS_KEY = 'assignment-assistant.packs.v1'

function loadLocal(): Pack[] {
  try { return JSON.parse(localStorage.getItem(LS_KEY) ?? '[]') as Pack[] } catch { return [] }
}

export const usePackStore = defineStore('packs', {
  state: () => ({
    packs: loadLocal() as Pack[],
    currentId: '' as string,
    loaded: false as boolean,
    online: false as boolean,
    error: '' as string,
  }),
  getters: {
    current(state): Pack | null {
      return state.packs.find((p) => p.id === state.currentId) || null
    },
    /** 当前包内的作业纸引用（seq）；无包 → 空。 */
    currentPadRefs(state): { padId: string; tag: string }[] {
      const p = state.packs.find((x) => x.id === state.currentId)
      return (p?.pads ?? []).map((r) => ({ padId: r.padId, tag: r.tag ?? '' }))
    },
  },
  actions: {
    persistLocal() {
      try { localStorage.setItem(LS_KEY, JSON.stringify(this.packs)) } catch { /* 容量/隐私降级 */ }
    },
    async refresh(): Promise<Pack[]> {
      const settings = useSettingsStore()
      this.error = ''
      try {
        const r = await fetchPacks(settings.engineUrl, settings.engineToken)
        if (r && Array.isArray(r.packs)) {
          this.packs = r.packs
          this.loaded = true
          this.online = true
          this.persistLocal()
        }
        return this.packs
      } catch (e) {
        this.loaded = true
        this.online = false
        this.error = String((e as Error)?.message ?? e)
        return this.packs
      }
    },
    /** 保存/删除/重命名（在线写引擎；离线写本地）。 */
    async mutate(payload: {
      action?: 'save' | 'delete' | 'rename'; id: string; new_id?: string; pack?: Partial<Pack>
    }): Promise<{ ok: boolean; error?: string }> {
      const settings = useSettingsStore()
      // 乐观本地更新（离线也能用；在线随后以引擎为准覆盖）
      const applyLocal = () => {
        if (payload.action === 'delete') {
          this.packs = this.packs.filter((p) => p.id !== payload.id)
          if (this.currentId === payload.id) this.currentId = ''
        } else if (payload.action === 'rename') {
          const hit = this.packs.find((p) => p.id === payload.id)
          if (hit && payload.new_id) {
            hit.id = payload.new_id
            if (this.currentId === payload.id) this.currentId = payload.new_id
          }
        } else {
          const idx = this.packs.findIndex((p) => p.id === payload.id)
          const merged: Pack = { ...(payload.pack ?? {}), id: payload.id }
          if (idx >= 0) this.packs[idx] = { ...this.packs[idx], ...merged }
          else this.packs.push(merged)
        }
        this.persistLocal()
      }
      try {
        const r = await savePack(settings.engineUrl, settings.engineToken, payload)
        if (r && Array.isArray(r.packs)) {
          this.packs = r.packs
          this.online = true
          this.persistLocal()
          if (!this.currentId && this.packs.length === 1) this.currentId = this.packs[0].id
          return { ok: !!r.ok, error: r.error }
        }
        applyLocal()
        return { ok: true }
      } catch {
        applyLocal()
        this.online = false
        return { ok: true }
      }
    },
    newPack(id: string): boolean {
      if (!id.trim()) return false
      if (!this.packs.some((p) => p.id === id)) {
        this.packs.push({ id, name: id, pads: [] })
        this.persistLocal()
      }
      this.currentId = id
      return true
    },
    select(id: string) {
      this.currentId = id
    },
    addPad(padId: string, tag: string) {
      const p = this.packs.find((x) => x.id === this.currentId)
      if (!p) return
      if (!p.pads) p.pads = []
      if (!p.pads.some((r) => r.padId === padId)) p.pads.push({ padId, tag })
      this.persistLocal()
    },
    removePad(padId: string) {
      const p = this.packs.find((x) => x.id === this.currentId)
      if (!p || !p.pads) return
      p.pads = p.pads.filter((r) => r.padId !== padId)
      this.persistLocal()
    },
    setPadTag(padId: string, tag: string) {
      const p = this.packs.find((x) => x.id === this.currentId)
      const ref = p?.pads?.find((r) => r.padId === padId)
      if (ref) { ref.tag = tag; this.persistLocal() }
    },
    /** D91-M1：把某作业纸从当前包**移动**到目标包（从当前包移除引用 + 目标包加入引用）。 */
    async movePadToPack(padId: string, toPackId: string, tag = ''): Promise<{ ok: boolean; error?: string }> {
      const from = this.currentId
      if (!from || !toPackId || from === toPackId) return { ok: false, error: '目标包无效' }
      const src = this.packs.find((x) => x.id === from)
      const dst = this.packs.find((x) => x.id === toPackId)
      if (!src || !dst) return { ok: false, error: '作业包不存在' }
      src.pads = (src.pads ?? []).filter((r) => r.padId !== padId)
      if (!dst.pads) dst.pads = []
      if (!dst.pads.some((r) => r.padId === padId)) dst.pads.push({ padId, tag })
      this.persistLocal()
      const r1 = await this.mutate({ action: 'save', id: from, pack: src })
      const r2 = await this.mutate({ action: 'save', id: toPackId, pack: dst })
      return { ok: r1.ok && r2.ok, error: r1.error || r2.error }
    },
    /** D91-M1：**复制引用** —— 当前包保留，目标包加入同一 padId（改一处两包同步）。 */
    async copyPadRefToPack(padId: string, toPackId: string, tag = ''): Promise<{ ok: boolean; error?: string }> {
      const dst = this.packs.find((x) => x.id === toPackId)
      if (!dst || !toPackId) return { ok: false, error: '目标包无效' }
      if (!dst.pads) dst.pads = []
      if (!dst.pads.some((r) => r.padId === padId)) dst.pads.push({ padId, tag })
      this.persistLocal()
      const r = await this.mutate({ action: 'save', id: toPackId, pack: dst })
      return { ok: r.ok, error: r.error }
    },
  },
})

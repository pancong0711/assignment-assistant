import { defineStore } from 'pinia'
import {
  emptyTaskpad, parseTaskpad, serializeTaskpad, makeTaskpadId,
  type Taskpad, type TaskpadItem,
} from '../lib/taskpad'

/** 任务包 store：当前正在设计的任务包 + 已保存任务包列表（localStorage）。 */

const LS_KEY = 'assignment-assistant.taskpads.v1'

interface PersistedPad { id: string; json: string }

function loadSaved(): PersistedPad[] {
  try {
    const raw = localStorage.getItem(LS_KEY)
    return raw ? (JSON.parse(raw) as PersistedPad[]) : []
  } catch {
    return []
  }
}

export const useTaskpadStore = defineStore('taskpad', {
  state: () => ({
    current: emptyTaskpad() as Taskpad,
    saved: loadSaved() as PersistedPad[],
  }),
  actions: {
    reset() {
      this.current = emptyTaskpad()
    },
    /** 作业纸设计器：添加一个选题分组（kind+章+若干题号） */
    addItem(item: TaskpadItem) {
      const same = this.current.items.find(
        (i) => i.kb === item.kb && i.chap === item.chap && i.tag === item.tag,
      )
      if (same) {
        const ids = new Set([...same.ids, ...item.ids])
        same.ids = [...ids]
      } else {
        this.current.items.push({ ...item, ids: [...item.ids] })
      }
    },
    removeItem(idx: number) {
      this.current.items.splice(idx, 1)
    },
    setOrientation(orientation: 'portrait' | 'landscape') {
      this.current.layout.orientation = orientation
      this.current.layout.per_page = orientation === 'landscape' ? 2 : 1
    },
    toJson(): string {
      return serializeTaskpad(this.current)
    },
    saveToLibrary(): string {
      const entry: PersistedPad = { id: this.current.id, json: this.toJson() }
      const exist = this.saved.findIndex((s) => s.id === entry.id)
      if (exist >= 0) this.saved[exist] = entry
      else this.saved.push(entry)
      localStorage.setItem(LS_KEY, JSON.stringify(this.saved))
      return entry.id
    },
    removeFromLibrary(id: string) {
      this.saved = this.saved.filter((s) => s.id !== id)
      localStorage.setItem(LS_KEY, JSON.stringify(this.saved))
    },
    openFromLibrary(id: string): boolean {
      const found = this.saved.find((s) => s.id === id)
      if (!found) return false
      this.current = parseTaskpad(JSON.parse(found.json))
      return true
    },
    importJson(text: string): Taskpad {
      const pad = parseTaskpad(JSON.parse(text))
      this.current = pad
      return pad
    },
    /** 生成新的任务包 id（重复导出时避免互相覆盖） */
    renewId() {
      this.current.id = makeTaskpadId()
    },
  },
})

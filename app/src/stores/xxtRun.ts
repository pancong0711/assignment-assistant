import { defineStore } from 'pinia'

/** D83-6：「当前 run」跨页共享 + 持久化。
 *
 *  动机：作业预览-学习通（XxetongView）有 curRun（默认 runs[0]），但发布作业
 *  （PublishView）此前写死 runs[0]，两页无共享概念；若两处不一致，白名单/班级列表
 *  会看错批次。这里做单一来源：选中写入 localStorage，各页读取；为空回落最新 run。
 */
const LS_KEY = 'assignment-assistant.xxt-current-run.v1'

function load(): string {
  try { return String(localStorage.getItem(LS_KEY) || '') } catch { return '' }
}

export const useXxtRunStore = defineStore('xxtRun', {
  state: () => ({ currentRunId: load() }),
  actions: {
    setCurrentRun(id: string) {
      this.currentRunId = String(id || '')
      try { localStorage.setItem(LS_KEY, this.currentRunId) } catch { /* noop */ }
    },
    clear() {
      this.currentRunId = ''
      try { localStorage.removeItem(LS_KEY) } catch { /* noop */ }
    },
  },
})

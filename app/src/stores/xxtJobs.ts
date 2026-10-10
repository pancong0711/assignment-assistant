import { defineStore } from 'pinia'

/** D73：学习通长任务状态跨组件卸载持久化（提取 job 切换 tab 后恢复）。 */
const LS_KEY = 'assignment-assistant.xxt-extract-job.v1'

interface PersistedJob {
  jobId: string
  startedAt: number
  msg: string
}

function load(): PersistedJob {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (!raw) return { jobId: '', startedAt: 0, msg: '' }
    const o = JSON.parse(raw) as Partial<PersistedJob>
    return {
      jobId: String(o.jobId || ''),
      startedAt: Number(o.startedAt || 0),
      msg: String(o.msg || ''),
    }
  } catch {
    return { jobId: '', startedAt: 0, msg: '' }
  }
}

export const useXxtJobsStore = defineStore('xxtJobs', {
  state: () => {
    const p = load()
    return {
      extractJobId: p.jobId,
      extractStartedAt: p.startedAt,
      extractMsg: p.msg,
    }
  },
  actions: {
    persistExtract() {
      try {
        localStorage.setItem(LS_KEY, JSON.stringify({
          jobId: this.extractJobId,
          startedAt: this.extractStartedAt,
          msg: this.extractMsg,
        }))
      } catch { /* localStorage 不可用时仅内存态 */ }
    },
    startExtractJob(jobId: string) {
      this.extractJobId = jobId
      this.extractStartedAt = Date.now()
      this.extractMsg = '已提交提取任务，等待 engine 执行……'
      this.persistExtract()
    },
    setExtractMsg(msg: string) {
      this.extractMsg = msg
      this.persistExtract()
    },
    finishExtractJob() {
      this.extractJobId = ''
      this.extractStartedAt = 0
      this.extractMsg = ''
      this.persistExtract()
    },
  },
})

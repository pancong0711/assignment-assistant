import { defineStore } from 'pinia'
import {
  DEFAULT_ENGINE_ADDR, fetchDoctor, fetchEngineStatus, normalizeEngineAddr,
  startInstall, streamInstall,
  statusClass, type DoctorCheck,
} from '../lib/engineClient'

/** 设置中心状态（docs/05-D13：设置中心 + 首次运行向导 + 条件式置灰）。
 *  这些设置只存教师本地浏览器（localStorage），不入库、不外发；
 *  真正落盘的 settings.local.json 由引擎侧管理（阶段4 assist serve），
 *  本页的 engine_addr 为其同名前端镜像（PWA 内可改，docs/05-D5）。 */

export interface EnvCheckItem {
  key: string
  label: string
  /** ok=绿 warn=黄(占位/注意) fail=红 */
  status: 'pending' | 'ok' | 'warn' | 'fail'
  note: string
}

export interface WizardState {
  visible: boolean
  step: 1 | 2 | 3
}

const LS_KEY = 'assignment-assistant.settings.v1'
/** 首次运行向导独立存储 key：完成/跳过后重开不再弹（阶段4a）。 */
const LS_ONBOARDING_KEY = 'assignment-assistant.onboarding.v1'
/** 水印素材库 key（name → dataURL，阶段4a 水印编辑器）。 */
const LS_WM_ASSETS_KEY = 'assignment-assistant.watermark.assets.v1'

interface PersistedSettings {
  wizardDone: boolean
  preferredEngineCommand: 'sh' | 'ps1'
  workspaceLabel: string
  workspaceConnected: boolean
  engineUrl: string
  engineToken: string
  engineApiKey: string
  defaultClassDir: string
  confirmBeforeUpload: boolean
}

function defaultSettings(): PersistedSettings {
  return {
    wizardDone: false,
    preferredEngineCommand: 'sh',
    workspaceLabel: '',
    workspaceConnected: false,
    // 引擎默认地址：与 engine bootstrap 写入 settings.local.json 的
    // engine_addr 同名同值（http://127.0.0.1:8601，PWA 内可改）。
    engineUrl: DEFAULT_ENGINE_ADDR,
    engineToken: '',
    engineApiKey: '',
    defaultClassDir: 'classes/2026S1-大学物理-classA',
    confirmBeforeUpload: true,
  }
}

function loadSettings(): PersistedSettings {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (!raw) return defaultSettings()
    const merged = { ...defaultSettings(), ...(JSON.parse(raw) as Partial<PersistedSettings>) }
    // 一次性迁移：阶段2 默认地址 8765 → 阶段4a 契约端口 8601（仅当用户未改过）
    if (merged.engineUrl === 'http://127.0.0.1:8765') merged.engineUrl = DEFAULT_ENGINE_ADDR
    return merged
  } catch {
    return defaultSettings()
  }
}

/** 向导完成/跳过状态（独立 key：assignment-assistant.onboarding.v1）。
 *  兼容阶段2 的旧值：settings.v1 里 wizardDone=true 也视为已完成。 */
function loadOnboardingDone(): boolean {
  try {
    if (localStorage.getItem(LS_ONBOARDING_KEY) === 'done') return true
    const raw = localStorage.getItem(LS_KEY)
    if (!raw) return false
    return Boolean((JSON.parse(raw) as Partial<PersistedSettings>).wizardDone)
  } catch {
    return false
  }
}

/** 水印素材库（name → dataURL）。 */
function loadWmAssets(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(LS_WM_ASSETS_KEY) ?? '{}') as Record<string, string>
  } catch {
    return {}
  }
}

function placeholderChecks(): EnvCheckItem[] {
  // 引擎未在线时的黄色占位（降级观感保留，docs/05-D13）；接入 assist serve
  // 后由 runDoctor() 逐项替换为真实绿黄红。
  return [
    { key: 'uv', label: 'uv', status: 'pending', note: '占位：引擎未在线，接入 assist serve 后真实检测' },
    { key: 'deps', label: '引擎依赖（.runtime/venv）', status: 'pending', note: '占位：引擎未在线，接入 assist doctor 后真实检测' },
    { key: 'fonts', label: '字体（开源 fallback 链，D15）', status: 'pending', note: '占位：缺失时引擎自动降级' },
    { key: 'tex', label: 'TeX（可选，样题渲染）', status: 'pending', note: '占位：缺失时引擎自动降级（黄）' },
    { key: 'kb', label: 'kb/ 题库存在', status: 'pending', note: '占位：引擎未在线' },
    { key: 'settings', label: 'settings.local.json 存在', status: 'pending', note: '占位：引擎未在线' },
  ]
}

/** /doctor 检查项 name → 本地表格 key（引擎 CLI doctor 检查项的子集）。 */
function doctorKey(c: DoctorCheck): string {
  const n = c.name.toLowerCase()
  if (n.includes('uv')) return 'uv'
  if (n.includes('依赖') || n.includes('dep') || n.includes('venv')) return 'deps'
  if (n.includes('字体') || n.includes('font')) return 'fonts'
  if (n.includes('tex') || n.includes('latex')) return 'tex'
  if (n.includes('kb') || n.includes('题库')) return 'kb'
  if (n.includes('settings')) return 'settings'
  return n.replace(/\s+/g, '-') || 'misc'
}

export const useSettingsStore = defineStore('settings', {
  state: () => ({
    ...loadSettings(),
    // 向导完成状态以独立 key（assignment-assistant.onboarding.v1）为准，
    // 兼容阶段2 写在 settings.v1 里的 wizardDone。
    wizardDone: loadOnboardingDone(),
    installing: '' as string,
    installLog: '',
    checks:placeholderChecks() as EnvCheckItem[],
    /** 是否做过任何一次体检动作（用于横幅/向导第二步文案） */
    checkRunAt: '' as string,
    wizard: { visible: true, step: 1 as 1 | 2 | 3 } as WizardState,
    /** 引擎在线检测 chip（/status）：online + 版本 */
    engineOnline: false as boolean,
    engineVersion: '' as string,
    engineStatusError: '' as string,
    /** 引擎未在线时的体检降级态标记（true=上次体检走的是占位/降级路径）。 */
    doctorDegraded: false as boolean,
    /** 最近一次 /doctor 结果（含未在线降级信息） */
    lastDoctorError: '' as string,
    doctorOk: false as boolean,
    doctorWorkspace: '' as string,
    /** 水印素材库（name → dataURL；任务包仅引用文件路径 hint） */
    wmAssets: loadWmAssets() as Record<string, string>,
  }),
  getters: {
    /** 向导未完成或跳过 → 引擎类按钮灰 + 黄色横幅（D13：不整体置灰） */
    needsSetup: (s) => !s.wizardDone,
    engineLikelyOnline: (s) => s.engineOnline,
    allChecks(state): EnvCheckItem[] {
      return state.checks
    },
  },
  actions: {
    persist() {
      const s: PersistedSettings = {
        wizardDone: this.wizardDone,
        preferredEngineCommand: this.preferredEngineCommand,
        workspaceLabel: this.workspaceLabel,
        workspaceConnected: this.workspaceConnected,
        engineUrl: this.engineUrl,
        engineToken: this.engineToken,
        engineApiKey: this.engineApiKey,
        defaultClassDir: this.defaultClassDir,
        confirmBeforeUpload: this.confirmBeforeUpload,
      }
      localStorage.setItem(LS_KEY, JSON.stringify(s))
    },
    setWorkspace(label: string, connected: boolean) {
      this.workspaceLabel = label
      this.workspaceConnected = connected
      this.persist()
    },
    setEngineUrl(url: string) {
      this.engineUrl = normalizeEngineAddr(url)
      this.persist()
      // 地址变更后立即重新握手（在线 chip 即时反馈）
      void this.pingEngine()
    },
    /** /status 在线检测（在线/离线 chip + 版本显示）。引擎未在线不报错，
     *  只更新 chip 状态（D13 降级观感）。 */
    async pingEngine(): Promise<boolean> {
      const r = await fetchEngineStatus(this.engineUrl, this.engineToken)
      this.engineOnline = r.online
      this.engineVersion = r.status?.version ?? ''
      this.engineStatusError = r.online ? '' : (r.error ?? 'offline')
      return r.online
    },
    /** 环境体检真接入：GET {engineAddr}/doctor 逐项绿黄红。
     *  引擎未在线 → 黄色占位 + lastDoctorError（调用方显示引导文案）。 */
    async runDoctor(): Promise<boolean> {
      this.checkRunAt = new Date().toLocaleTimeString()
      const r = await fetchDoctor(this.engineUrl, this.engineToken)
      if (!r.online) {
        this.lastDoctorError = r.error ?? 'fetch failed'
        this.doctorOk = false
        this.doctorDegraded = true
        for (const c of this.checks) {
          c.status = 'warn'
          c.note = '占位状态：引擎未在线（ assist serve 未启动或地址不对）。'
        }
        this.engineOnline = false
        return false
      }
      this.lastDoctorError = ''
      this.doctorDegraded = false
      this.doctorOk = r.ok
      this.doctorWorkspace = r.engine.workspace
      this.engineOnline = true
      this.engineVersion = r.engine.version
      // 引擎返回的检查项：**优先用稳定 id（A3/D25）**，兼容旧 name 启发式
      const byKey = new Map<string, DoctorCheck>()
      for (const c of r.checks) byKey.set((c as any).id || doctorKey(c), c)
      this.checks.forEach((item) => {
        const hit = byKey.get(item.key)
        if (hit) {
          item.status = statusClass(hit.status)
          item.note = hit.detail || (hit.status === 'green' ? '通过' : hit.status === 'yellow' ? '注意：缺失时引擎可降级' : '缺失')
          ;(item as any).fix = (hit as any).fix ?? {}
        }
      })
      // 引擎多返回的项（未来扩展）追加到表格尾部
      for (const c of r.checks) {
        const k = (c as any).id || doctorKey(c)
        if (!this.checks.some((x) => x.key === k)) {
          this.checks.push({ key: k, label: c.name, status: statusClass(c.status), note: c.detail || '',
            fix: (c as any).fix ?? {} } as any)
        }
      }
      return true
    },
    /** R1.4 修复按钮：POST /install/<item> + SSE 进度；完成后自动重跑体检。 */
    async runInstall(itemId: string): Promise<boolean> {
      if (!this.engineOnline) return false
      this.installLog = ''
      this.installing = itemId
      try {
        const jobId = await startInstall(this.engineUrl, itemId, this.engineToken)
        await new Promise<number>((resolve) => {
          streamInstall(this.engineUrl, jobId, this.engineToken,
            (line) => { this.installLog = (this.installLog + '\n' + line).slice(-4000) },
            (rc) => resolve(rc))
        })
        await this.runDoctor()
        return this.doctorOk
      } catch (e) {
        this.installLog = String((e as Error).message)
        return false
      } finally {
        this.installing = ''
      }
    },

    /** 兼容旧调用名（向导第二步按钮）：体检 = ping + doctor。 */
    async runHealthCheck(): Promise<boolean> {
      const online = await this.pingEngine()
      return (await this.runDoctor()) && online
    },
    /** 水印素材库（阶段4a 水印编辑器）：name → dataURL，仅本浏览器 localStorage；
     *  任务包导出只写 file 相对路径 hint，不内嵌 dataURL（可携带、不含大图）。 */
    persistWmAsset(name: string, dataUrl: string) {
      this.wmAssets[name] = dataUrl
      this.persistWmAssets()
    },
    persistWmAssets() {
      try { localStorage.setItem(LS_WM_ASSETS_KEY, JSON.stringify(this.wmAssets)) } catch { /* 容量/隐私降级 */ }
    },
    finishWizard() {
      this.wizardDone = true
      this.wizard.visible = false
      try { localStorage.setItem(LS_ONBOARDING_KEY, 'done') } catch { /* 隐私模式降级 */ }
      this.persist()
    },
    skipWizard() {
      // 可跳过；跳过时保持横幅提示但不置灰整体界面（D13）
      this.wizardDone = true
      this.wizard.visible = false
      try { localStorage.setItem(LS_ONBOARDING_KEY, 'done') } catch { /* 隐私模式降级 */ }
      this.persist()
    },
    /** 重看向导（设置中心显式入口）。 */
    reopenWizard() {
      this.wizard.visible = true
      this.wizard.step = 1
    },
  },
})

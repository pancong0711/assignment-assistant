import { defineStore } from 'pinia'
import {
  DEFAULT_ENGINE_ADDR, fetchDoctor, fetchEngineStatus, fetchEngineUpdate, fetchPwPkgs,
  normalizeEngineAddr, restartEngine, startInstall, streamInstall,
  statusClass, type DoctorCheck, type EngineUpdateInfo, type PwPkgItem,
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
/** B3/D46-5：题图素材库（kb/fig 相对路径 → dataURL），与水印素材同模式独立键 */
const LS_FIG_ASSETS_KEY = 'assignment-assistant.fig.assets.v1'

function loadFigAssets(): Record<string, string> {
  try { return JSON.parse(localStorage.getItem(LS_FIG_ASSETS_KEY) ?? '{}') as Record<string, string> } catch { return {} }
}

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
merged.engineToken = merged.engineToken ?? ''
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
    /** D67：重启前后实例身份（/status 返回） */
    engineInstanceId: '' as string,
    enginePid: 0 as number,
    engineSupervised: false as boolean,
    enginePort: 0 as number,
    /** 引擎未在线时的体检降级态标记（true=上次体检走的是占位/降级路径）。 */
    doctorDegraded: false as boolean,
    /** 最近一次 /doctor 结果（含未在线降级信息） */
    lastDoctorError: '' as string,
    doctorOk: false as boolean,
    doctorWorkspace: '' as string,
    /** D65-P2：Playwright 内核直下清单（/pw/pkgs） */
    pwPkgs: [] as PwPkgItem[],
    pwPkgsInbox: '' as string,
    pwPkgsError: '' as string,
    pwPkgsLoaded: false as boolean,
    /** D65-P4：引擎更新检测/更新状态 */
    engineUpdateInfo: null as EngineUpdateInfo | null,
    engineUpdateChecking: false as boolean,
    engineUpdating: false as boolean,
    /** 水印素材库（name → dataURL；作业纸仅引用文件路径 hint） */
    wmAssets: loadWmAssets() as Record<string, string>,
    /** B3/D46-5：题图库（basename → dataURL；仅本浏览器，导出 JSON 只写 img_path hint） */
    figAssets: loadFigAssets() as Record<string, string>,
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
      this.engineInstanceId = r.status?.instance_id ?? ''
      this.enginePid = r.status?.pid ?? 0
      this.engineSupervised = Boolean(r.status?.supervised)
      this.enginePort = r.status?.port ?? 0
      this.engineStatusError = r.online ? '' : (r.error ?? 'offline')
      return r.online
    },

    /** D67：调用 /restart 并等待“新实例”回在线；旧进程未退出时不得误报成功。 */
    async restartEngineAndWait(timeoutMs = 15000): Promise<{ ok: boolean; reason: string }> {
      await this.pingEngine()
      const beforeId = this.engineInstanceId
      try {
        await restartEngine(this.engineUrl, this.engineToken)
      } catch (e) {
        return { ok: false, reason: (e as Error).message }
      }
      const deadline = Date.now() + timeoutMs
      let everOnline = false
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 500))
        if (!(await this.pingEngine())) continue
        everOnline = true
        const afterId = this.engineInstanceId
        if (afterId && afterId !== beforeId) return { ok: true, reason: '' }
      }
      if (everOnline) {
        return { ok: false, reason: '旧引擎仍在在线（instance_id 未变化），可能没有真正退出' }
      }
      return { ok: false, reason: '引擎在时限内未重回在线' }
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
      if (!this.engineOnline) {
        // D64 §22.1 修复：不再静默返回——冒出一句，避免"闪一下无提示"
        this.installLog = '⚠ 引擎未在线（installing 前置校验失败）；请先体检确认引擎地址。'
        return false
      }
      this.installLog = ''
      this.installing = itemId
      try {
        const jobId = await startInstall(this.engineUrl, itemId, this.engineToken)
        let rc = -2
        await new Promise<number>((resolve) => {
          streamInstall(this.engineUrl, jobId, this.engineToken,
            (line) => { this.installLog = (this.installLog + '\n' + line).slice(-4000) },
            (rc0) => { rc = rc0; resolve(rc0) })
        })
        await this.runDoctor()
        // rc 非零（尤其 -1 = SSE 中断且无日志）时补一句，不再让 UI 无声回落
        if (!this.installLog)
          this.installLog = `⚠ 安装任务提前中断（code ${rc})，未收到任何输出；请查看引擎服务端日志。`
        else if (rc !== 0)
          this.installLog += `\n⚠ 安装未成功（code ${rc}），上方为过程输出。`
        return this.doctorOk
      } catch (e) {
        this.installLog = String((e as Error).message)
        return false
      } finally {
        this.installing = ''
      }
    },

    /** D65-P2：拉取浏览器内核直下清单（引擎 /pw/pkgs）。 */
    async loadPwPkgs(): Promise<boolean> {
      this.pwPkgsLoaded = true
      const r = await fetchPwPkgs(this.engineUrl, this.engineToken)
      if (!r.online) {
        this.pwPkgsError = r.error ?? '引擎未在线'
        this.pwPkgs = []
        return false
      }
      if (!r.ok) {
        this.pwPkgsError = r.reason ?? '引擎未返回直下清单'
        this.pwPkgs = []
        return false
      }
      this.pwPkgs = r.items
      this.pwPkgsInbox = r.inbox ?? ''
      this.pwPkgsError = ''
      return true
    },

    /** D65-P4：检测引擎更新（GET /engine/version）。 */
    async checkEngineUpdate(): Promise<EngineUpdateInfo | null> {
      this.engineUpdateChecking = true
      try {
        this.engineUpdateInfo = await fetchEngineUpdate(this.engineUrl, this.engineToken)
        return this.engineUpdateInfo
      } finally {
        this.engineUpdateChecking = false
      }
    },

    /** D65-P4：用户确认后更新引擎；更新成功自动 /restart + 轮询 + 重跑版本/体检。 */
    async runEngineUpdate(): Promise<boolean> {
      if (!this.engineOnline) {
        this.installLog = '⚠ 引擎未在线，无法执行在线更新。'
        return false
      }
      this.installLog = ''
      this.engineUpdating = true
      try {
        const jobId = await startInstall(this.engineUrl, 'engine_update', this.engineToken)
        let rc = -2
        await new Promise<number>((resolve) => {
          streamInstall(this.engineUrl, jobId, this.engineToken,
            (line) => { this.installLog = (this.installLog + '\n' + line).slice(-4000) },
            (rc0) => { rc = rc0; resolve(rc0) })
        })
        if (rc !== 0) {
          this.installLog += `\n⚠ 引擎更新失败（code ${rc}），上方为过程输出。`
          return false
        }
        this.installLog += '\n♻ 更新包已暂存，正在请求重启并由 launcher 安装……'
        // D71：更新包暂存后，start.bat/start.sh 需要先安装再启动，可能超过 15s。
        const rr = await this.restartEngineAndWait(180000)
        if (!rr.ok) {
          this.installLog += `\n⚠ 更新包已暂存，但自动重启/安装失败：${rr.reason}；请关闭终端后双击 start.bat。`
          return false
        }
        await this.runDoctor()
        await this.checkEngineUpdate()
        this.installLog += '\n✓ 引擎已由 launcher 安装并重启回在线。'
        return true
      } catch (e) {
        this.installLog = String((e as Error).message)
        return false
      } finally {
        this.engineUpdating = false
      }
    },

    /** 兼容旧调用名（向导第二步按钮）：体检 = ping + doctor。 */
    async runHealthCheck(): Promise<boolean> {
      const online = await this.pingEngine()
      return (await this.runDoctor()) && online
    },
    /** 水印素材库（阶段4a 水印编辑器）：name → dataURL，仅本浏览器 localStorage；
     *  作业纸导出只写 file 相对路径 hint，不内嵌 dataURL（可携带、不含大图）。 */
    persistWmAsset(name: string, dataUrl: string) {
      this.wmAssets[name] = dataUrl
      this.persistWmAssets()
    },
    persistWmAssets() {
      try { localStorage.setItem(LS_WM_ASSETS_KEY, JSON.stringify(this.wmAssets)) } catch { /* 容量/隐私降级 */ }
    },
    /** B3/D46-5：题图入库（name=basename；预览按 kb 行 img_path 的 basename 命中显示真图）。 */
    persistFigAsset(name: string, dataUrl: string) {
      this.figAssets[name] = dataUrl
      this.persistFigAssets()
    },
    removeFigAsset(name: string) {
      delete this.figAssets[name]
      this.persistFigAssets()
    },
    persistFigAssets() {
      try { localStorage.setItem(LS_FIG_ASSETS_KEY, JSON.stringify(this.figAssets)) } catch { /* 容量/隐私降级 */ }
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

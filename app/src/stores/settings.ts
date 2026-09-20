import { defineStore } from 'pinia'

/** 设置中心状态（docs/05-D13：设置中心 + 首次运行向导 + 条件式置灰）。
 *  这些设置只存教师本地浏览器（localStorage），不入库、不外发；
 *  真正落盘的 settings.local.json 由引擎侧管理（阶段4 assist serve）。 */

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

interface PersistedSettings {
  wizardDone: boolean
  preferredEngineCommand: 'sh' | 'ps1'
  workspaceLabel: string
  workspaceConnected: boolean
  engineUrl: string
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
    engineUrl: 'http://127.0.0.1:8765',
    engineApiKey: '',
    defaultClassDir: 'classes/2026S1-大学物理-classA',
    confirmBeforeUpload: true,
  }
}

function loadSettings(): PersistedSettings {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (!raw) return defaultSettings()
    return { ...defaultSettings(), ...(JSON.parse(raw) as Partial<PersistedSettings>) }
  } catch {
    return defaultSettings()
  }
}

function placeholderChecks(): EnvCheckItem[] {
  // 阶段4 接入 assist serve 后改为真实检测（逐项绿黄红，docs/05-D5/D13）
  return [
    { key: 'python', label: 'Python / uv', status: 'pending', note: '占位：阶段4 经 assist serve 检测' },
    { key: 'deps', label: '引擎依赖（.runtime/venv）', status: 'pending', note: '占位：阶段4 接入 assist doctor' },
    { key: 'playwright', label: 'Playwright 内核', status: 'pending', note: '占位：阶段4 接入 assist doctor' },
    { key: 'tex', label: 'TeX（可选，样题渲染）', status: 'pending', note: '占位：缺失时引擎自动降级' },
    { key: 'engine', label: '引擎在线（assist serve）', status: 'pending', note: '占位：阶段4 提供本地 HTTP 握手' },
  ]
}

export const useSettingsStore = defineStore('settings', {
  state: () => ({
    ...loadSettings(),
    checks: placeholderChecks() as EnvCheckItem[],
    /** 是否做过任何一次体检动作（用于横幅/向导第二步文案） */
    checkRunAt: '' as string,
    wizard: { visible: true, step: 1 as 1 | 2 | 3 } as WizardState,
  }),
  getters: {
    /** 向导未完成或跳过 → 引擎类按钮灰 + 黄色横幅（D13：不整体置灰） */
    needsSetup: (s) => !s.wizardDone,
    engineLikelyOnline: (s) => s.checks.some((c) => c.key === 'engine' && c.status === 'ok'),
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
    /** 环境体检（占位实现）：TODO(阶段4)：改为调用 assist serve /api/health + assist doctor */
    runHealthCheck() {
      for (const c of this.checks) {
        c.status = 'warn'
        c.note = c.key === 'engine'
          ? '占位状态：静态部署下无法检测本机引擎。阶段4 接入 assist serve 后自动握手。'
          : '占位状态：阶段4 接入 assist doctor / assist serve 后逐项真实检测（绿=通过 黄=注意 红=缺失）。'
      }
      this.checkRunAt = new Date().toLocaleTimeString()
    },
    finishWizard() {
      this.wizardDone = true
      this.wizard.visible = false
      this.persist()
    },
    skipWizard() {
      // 可跳过；跳过时保持横幅提示但不置灰整体界面（D13）
      this.wizardDone = true
      this.wizard.visible = false
      this.persist()
    },
  },
})

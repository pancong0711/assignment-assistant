/** 引擎（assist serve）HTTP 客户端 —— 阶段4a 体检真接入（docs/05-D2/D5/D13）。
 *
 * 契约（父代理提供，engine 侧并线实现）：
 * - GET {engineAddr}/doctor
 *   → { ok: bool, engine: { version, workspace },
 *       checks: [{ name, status: "green"|"yellow"|"red", detail? }] }
 *   检查项为 `assist doctor` 子集：uv / 依赖 / 字体 / TeX(可选黄) /
 *   kb 存在 / settings.local.json 存在。
 * - GET {engineAddr}/status
 *   → { name: "assist-engine", version, workspace: bool }
 *
 * 引擎未在线（fetch 失败/超时）时调用方显示"引擎未在线"降级态，
 * 不得弹错误横幅阻断静态功能（D13：不整体置灰）。
 */

export const DEFAULT_ENGINE_ADDR = 'http://127.0.0.1:8601'

export type DoctorStatus = 'green' | 'yellow' | 'red'

export interface DoctorCheck {
  name: string
  status: DoctorStatus
  detail?: string
}

export interface DoctorResult {
  ok: boolean
  engine: { version: string; workspace: string }
  checks: DoctorCheck[]
}

export interface EngineStatus {
  name: string
  version: string
  workspace: boolean
}

export interface StatusResult {
  online: boolean
  status?: EngineStatus
  error?: string
}

/** 状态 → 体检表格图标（✓ / ! / ✗）。兼容 store 的 ok/warn/fail 四态。 */
export type AnyCheckStatus = DoctorStatus | 'pending' | 'ok' | 'warn' | 'fail'

export function statusGlyph(s: AnyCheckStatus): string {
  if (s === 'green' || s === 'ok') return '✓'
  if (s === 'yellow' || s === 'warn') return '!'
  if (s === 'red' || s === 'fail') return '✗'
  return '·'
}

/** 状态 → store 的 pending/ok/warn/fail 四态（复用现有 status-* 配色）。 */
export function statusClass(s: DoctorStatus | 'pending'): 'pending' | 'ok' | 'warn' | 'fail' {
  return s === 'green' ? 'ok' : s === 'yellow' ? 'warn' : s === 'red' ? 'fail' : 'pending'
}

/** 归一化引擎地址：去尾部斜杠；空值回落默认地址。 */
export function normalizeEngineAddr(addr: string): string {
  const a = (addr || '').trim()
  if (!a) return DEFAULT_ENGINE_ADDR
  return a.replace(/\/+$/, '')
}

/** 带超时的 GET（默认 4s：本地引擎未起时 connect 会立刻失败，
 *  超时主要兜地址配错指向外网/防火墙丢包的情形）。 */
async function getJson(url: string, timeoutMs = 4000): Promise<unknown> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(url, { signal: ctrl.signal, headers: { Accept: 'application/json' } })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return await res.json()
  } finally {
    clearTimeout(timer)
  }
}

/** GET /status —— 在线检测（在线/离线 chip + 版本显示）。 */
export async function fetchEngineStatus(engineAddr: string): Promise<StatusResult> {
  const base = normalizeEngineAddr(engineAddr)
  try {
    const raw = await getJson(`${base}/status`)
    const o = raw as Record<string, unknown>
    return {
      online: o.name === 'assist-engine',
      status: {
        name: String(o.name ?? ''),
        version: String(o.version ?? ''),
        workspace: Boolean(o.workspace),
      },
    }
  } catch (e) {
    return { online: false, error: (e as Error).message }
  }
}

/** GET /doctor —— 体检真接入。失败返回 { ok:false, checks:[], online:false }，
 *  调用方据 online=false 渲染"引擎未在线"降级态（不抛异常）。 */
export interface DoctorCallResult extends DoctorResult {
  online: boolean
  error?: string
}

export function emptyDoctor(): DoctorCallResult {
  return { ok: false, engine: { version: '', workspace: '' }, checks: [], online: false }
}

export async function fetchDoctor(engineAddr: string): Promise<DoctorCallResult> {
  const base = normalizeEngineAddr(engineAddr)
  try {
    const raw = (await getJson(`${base}/doctor`)) as Record<string, unknown>
    const checks = Array.isArray(raw.checks) ? raw.checks : []
    const engine = (raw.engine ?? {}) as Record<string, unknown>
    return {
      ok: Boolean(raw.ok),
      online: true,
      engine: { version: String(engine.version ?? ''), workspace: String(engine.workspace ?? '') },
      checks: checks.map((c) => {
        const it = c as Record<string, unknown>
        const s = String(it.status ?? 'yellow')
        return {
          name: String(it.name ?? '检查项'),
          status: (s === 'green' || s === 'red' ? s : 'yellow') as DoctorStatus,
          detail: it.detail === undefined || it.detail === null ? undefined : String(it.detail),
        }
      }),
    }
  } catch (e) {
    return { ...emptyDoctor(), error: (e as Error).message }
  }
}

/** 引擎未在线时的引导命令（D13：体检页逐项 + 复制命令按钮）。 */
export const SERVE_HINT_CMD = 'uv run assist serve        # 引擎在线后本页自动识别（默认 http://127.0.0.1:8601）'

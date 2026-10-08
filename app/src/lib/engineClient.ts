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
  id?: string
  name: string
  status: DoctorStatus
  detail?: string
  fix?: { type?: string; install?: string }
}

/** R1.3：POST /install/<item> 发起安装任务（返回 job_id），SSE/轮询 /jobs/<id>。 */
export async function startInstall(engineAddr: string, item: string,
                                   token?: string): Promise<string> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, `/install/${item}`, token),
                          { method: 'POST' })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const o = (await res.json()) as { job_id: string }
  return o.job_id
}

/** D64 §22.1：POST /restart —— 引擎进程自愈重启（旧进程 execv 新代码）。
 *  返回 true=重启请求已受理；随后引擎会有 <1s 的断流，调用方应轮询 /status 等回线。 */
export async function restartEngine(engineAddr: string, token?: string): Promise<boolean> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/restart', token), { method: 'POST' })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const o = (await res.json()) as { ok?: boolean }
  return Boolean(o?.ok)
}

/** B4：把 PWA 内存 KbBook 交引擎 openpyxl 原位写回（保留样式），返回引擎写入路径。 */
export async function writeKbViaEngine(
  engineAddr: string, token: string | undefined, kind: string, chapters: unknown,
): Promise<string> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/kb/write', token), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind, chapters }),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const o = (await res.json()) as { error?: string }
      if (o?.error) detail = o.error
    } catch { /* ignore */ }
    throw new Error(`引擎写回失败：${detail}`)
  }
  const o = (await res.json()) as { ok?: boolean; path?: string }
  if (!o?.ok) throw new Error(`引擎写回失败：${o?.path ?? 'unknown'}`)
  return String(o.path ?? '')
}

/** 订阅安装进度（SSE），返回最后状态 rc（0=成功；负/非0=失败）。onLine 每次 stdout 行回调。 */
export function streamInstall(engineAddr: string, jobId: string, token: string | undefined,
                              onLine: (line: string) => void, onDone: (rc: number) => void): () => void {
  const es = new EventSource(engineUrlWithToken(engineAddr, `/jobs/${jobId}/stream`, token))
  es.addEventListener('message', (ev) => onLine((ev as MessageEvent).data))
  es.addEventListener('done', (ev) => {
    const rc = Number(String((ev as MessageEvent).data).replace(/[^0-9-]/g, '') || '0')
    onDone(rc); es.close()
  })
  es.onerror = () => { es.close(); onDone(-1) }   // D64 §22.1：SSE 中断也 resolve（-1），UI 不永悬"安装中"
  return () => es.close()
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

/** 追加引擎访问令牌（`assist serve --lan` 防蹭网 token，策略见 docs/05-D21/D5）。 */
export function engineUrlWithToken(engineAddr: string, path: string, token?: string): string {
  const base = normalizeEngineAddr(engineAddr)
  const u = new URL(path, base + '/')
  const t = (token || '').trim()
  if (t) u.searchParams.set('token', t)
  return u.toString()
}

/** GET /status —— 在线检测（在线/离线 chip + 版本显示）。 */
export async function fetchEngineStatus(engineAddr: string, token?: string): Promise<StatusResult> {
  const base = normalizeEngineAddr(engineAddr)
  const url = engineUrlWithToken(base, '/status', token)
  try {
    const raw = await getJson(url)
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

export async function fetchDoctor(engineAddr: string, token?: string): Promise<DoctorCallResult> {
  const base = normalizeEngineAddr(engineAddr)
  try {
    const raw = (await getJson(engineUrlWithToken(base, '/doctor', token))) as Record<string, unknown>
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
          // D64 §22.1 修复：id/fix 透传——此前被映射函数丢弃，
          // 导致 store 按 id 定版失效 + 每行 🔧修复 按钮永不出现
          ...(it.id !== undefined && it.id !== null ? { id: String(it.id) } : {}),
          ...(it.fix && typeof it.fix === 'object' ? { fix: it.fix as DoctorCheck['fix'] } : {}),
        }
      }),
    }
  } catch (e) {
    return { ...emptyDoctor(), error: (e as Error).message }
  }
}

/** 引擎未在线时的引导命令（D13：体检页逐项 + 复制命令按钮）。 */
export const SERVE_HINT_CMD = 'uv run assist serve        # 引擎在线后本页自动识别（默认 http://127.0.0.1:8601）'

/* ========== D63 T7/T8：学习通对接端点（engine serve xxt 组） ========== */

export interface XxtSessionStatus {
  verdict: 'alive' | 'dead' | 'unknown' | string
  checked_at?: string
  final_url?: string
  reasons?: string[]
  hint?: string
  storage_exists?: boolean
  storage_refreshed?: string
}

export interface XxtRunRow {
  run_id: string
  ts_start?: string
  ts_end?: string
  failures?: number
  classes?: number
  works?: number
}

/** GET /xxt/status：体检（engine 侧 TTL 缓存）+ 头像 data-URL（alive 时非空）。 */
export async function fetchXxtStatus(engineAddr: string, token?: string)
  : Promise<{ verdict: string; avatar_dataurl?: string | null; info?: XxtSessionStatus }> {
  const base = normalizeEngineAddr(engineAddr)
  const o = (await getJson2(engineUrlWithToken(base, '/xxt/status', token))) as
    { ok: boolean; xxt?: XxtSessionStatus; avatar?: { ok?: boolean; dataurl?: string } }
  const x = (o.xxt || {}) as XxtSessionStatus
  return {
    verdict: x.verdict || 'unknown',
    avatar_dataurl: (o.avatar && o.avatar.ok && o.avatar.dataurl) ? o.avatar.dataurl : null,
    info: x,
  }
}

/** POST /xxt/login/start：后台扫码登录任务（job_id 起步，QR 由 /xxt/qr 轮询）。 */
export async function startXxtLogin(engineAddr: string, token?: string): Promise<string> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/login/start', token), { method: 'POST' })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const o = (await res.json()) as { job_id: string }
  return o.job_id
}

/** GET /xxt/runs：只读提取 run 清单（engine 本仓/工件目录）。 */
export async function fetchXxtRuns(engineAddr: string, token?: string): Promise<XxtRunRow[]>
  {
  const base = normalizeEngineAddr(engineAddr)
  const o = (await getJson2(engineUrlWithToken(base, '/xxt/runs', token))) as
    { ok: boolean; runs?: XxtRunRow[] }
  return o.runs || []
}

/** GET /xxt/run/<id>：单 run 全量 JSON（同源教师端，含姓名=本机隐私域）。 */
export async function fetchXxtRun(engineAddr: string, token: string | undefined, runId: string)
  : Promise<unknown> {
  const base = normalizeEngineAddr(engineAddr)
  return (await getJson2(engineUrlWithToken(base, `/xxt/run/${encodeURIComponent(runId)}`, token)))
}

async function getJson2(url: string): Promise<unknown> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

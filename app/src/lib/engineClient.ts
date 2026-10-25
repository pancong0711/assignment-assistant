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
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const o = (await res.json()) as { error?: string; hint?: string }
      if (o?.error) detail = o.error
      if (o?.hint) detail += `（${o.hint}）`
    } catch { /* 保留 HTTP 状态 */ }
    throw new Error(detail)
  }
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
  /** D77：短 commit；旧引擎可能没有。 */
  commit?: string
  workspace: boolean
  /** D67：同一进程的实例身份；PWA 重启后必须看到它变化。 */
  pid?: number
  instance_id?: string
  started_at?: string
  supervised?: boolean
  port?: number
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
        commit: o.commit === undefined || o.commit === null ? undefined : String(o.commit),
        workspace: Boolean(o.workspace),
        pid: typeof o.pid === 'number' ? o.pid : undefined,
        instance_id: o.instance_id === undefined || o.instance_id === null
          ? undefined : String(o.instance_id),
        started_at: o.started_at === undefined || o.started_at === null
          ? undefined : String(o.started_at),
        supervised: typeof o.supervised === 'boolean' ? o.supervised : undefined,
        port: typeof o.port === 'number' ? o.port : undefined,
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

/* ========== D81：Workspace / kb 管理 ========== */
export interface WorkspaceInfo {
  ok?: boolean
  workspace: string
  defaultWorkspace: string
  isDefault: boolean
  kbPath: string
  kbExists: boolean
  xlsx: string[]
  xlsxCount: number
}
export async function fetchWorkspaceInfo(engineAddr: string, token?: string): Promise<WorkspaceInfo> {
  const base = normalizeEngineAddr(engineAddr)
  return (await getJson2(engineUrlWithToken(base, '/workspace/info', token))) as WorkspaceInfo
}
export async function createDefaultKb(engineAddr: string, token?: string): Promise<WorkspaceInfo> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/workspace/bootstrap', token), { method: 'POST' })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json()) as WorkspaceInfo
}
export async function migrateKb(engineAddr: string, token: string | undefined, srcDir: string): Promise<{ ok?: boolean; copiedCount?: number; errors?: string[]; target?: string }> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/kb/migrate', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ srcDir }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json()) as { ok?: boolean; copiedCount?: number; errors?: string[]; target?: string }
}

/* ========== D65-P4：引擎版本检测（engine /engine/version） ========== */

export interface EngineVersionMeta {
  engine_version?: string
  commit?: string
  _path?: string
  _fallback?: boolean
}

export interface EngineUpdateInfo {
  online: boolean
  ok: boolean
  update_available: boolean | null
  local: EngineVersionMeta
  remote?: EngineVersionMeta | null
  remote_url?: string
  error?: string
}

/** GET /engine/version —— PWA「检测更新」；引擎未在线时 online=false。 */
export async function fetchEngineUpdate(engineAddr: string, token?: string): Promise<EngineUpdateInfo> {
  const base = normalizeEngineAddr(engineAddr)
  try {
    const raw = (await getJson(engineUrlWithToken(base, '/engine/version', token), 15000)) as Record<string, unknown>
    const local = (raw.local && typeof raw.local === 'object' ? raw.local : {}) as Record<string, unknown>
    const remote = raw.remote && typeof raw.remote === 'object' ? raw.remote as Record<string, unknown> : null
    const toMeta = (o: Record<string, unknown>): EngineVersionMeta => ({
      engine_version: o.engine_version === undefined || o.engine_version === null ? undefined : String(o.engine_version),
      commit: o.commit === undefined || o.commit === null ? undefined : String(o.commit),
      _path: o._path === undefined || o._path === null ? undefined : String(o._path),
      _fallback: o._fallback === undefined || o._fallback === null ? undefined : Boolean(o._fallback),
    })
    return {
      online: true,
      ok: Boolean(raw.ok),
      update_available: raw.update_available === null || raw.update_available === undefined
        ? null : Boolean(raw.update_available),
      local: toMeta(local),
      remote: remote ? toMeta(remote) : null,
      remote_url: raw.remote_url === undefined || raw.remote_url === null ? undefined : String(raw.remote_url),
      error: raw.error === undefined || raw.error === null ? undefined : String(raw.error),
    }
  } catch (e) {
    return { online: false, ok: false, update_available: null, local: {}, error: (e as Error).message }
  }
}

/* ========== D65-P2：浏览器内核直下清单（engine /pw/pkgs） ========== */

export interface PwPkgItem {
  name: string
  dir: string
  file: string
  needed: boolean
  installed: boolean
  in_inbox: boolean
  urls: Record<string, string>
}

export interface PwPkgsResult {
  ok: boolean
  online: boolean
  inbox?: string
  items: PwPkgItem[]
  reason?: string
  error?: string
}

/** GET /pw/pkgs —— PWA 展示直下链接、收包路径、目标目录与包状态。
 *  引擎未在线时返回 online=false，调用方保留静态降级 UI。 */
export async function fetchPwPkgs(engineAddr: string, token?: string): Promise<PwPkgsResult> {
  const base = normalizeEngineAddr(engineAddr)
  try {
    const raw = (await getJson(engineUrlWithToken(base, '/pw/pkgs', token), 15000)) as Record<string, unknown>
    const items = Array.isArray(raw.items) ? raw.items : []
    return {
      ok: Boolean(raw.ok),
      online: true,
      inbox: raw.inbox === undefined || raw.inbox === null ? undefined : String(raw.inbox),
      reason: raw.reason === undefined || raw.reason === null ? undefined : String(raw.reason),
      items: items.map((it) => {
        const o = it as Record<string, unknown>
        const urls = (o.urls && typeof o.urls === 'object' ? o.urls : {}) as Record<string, unknown>
        return {
          name: String(o.name ?? ''),
          dir: String(o.dir ?? ''),
          file: String(o.file ?? ''),
          needed: Boolean(o.needed),
          installed: Boolean(o.installed),
          in_inbox: Boolean(o.in_inbox),
          urls: Object.fromEntries(Object.entries(urls).map(([k, v]) => [k, String(v)])),
        }
      }),
    }
  } catch (e) {
    return { ok: false, online: false, items: [], error: (e as Error).message }
  }
}

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

/** 从 CLI job 输出里提取可读错误信息（D83 修复）。
 *
 * 背景：引擎 CLI 失败时先 echo 一份 indent JSON（`{ "ok": false, "error": "步骤…" }`），
 * 最后一行是 `}`；旧实现取末行 → PWA 只显示「}」。
 * 这里优先解析 JSON 的 error 字段（含后端步骤名）；没有则回退到最后一个非空行
 * （未捕获异常时即 traceback 末行的异常消息）。
 */
export function extractJobError(output: string): string {
  const raw = String(output || '')
  // 取**最后**一个 "error" 字段：CLI 末尾的结果 JSON 才是本 job 的结论
  let m: RegExpMatchArray | null = null
  for (const cand of raw.matchAll(/"error"\s*:\s*"((?:[^"\\]|\\.)*)"/g)) m = cand
  if (m) {
    try { return JSON.parse(`"${m[1]}"`) as string } catch { return m[1] }
  }
  const lines = raw.split('\n').map((l) => l.trim()).filter(Boolean)
  return lines.length ? lines[lines.length - 1].slice(-400) : '未知错误（无输出）'
}

/** GET /jobs/<id>：D66 扫码登录任务状态（生成失败时给前端明确原因，而不是破图）。 */
export interface XxtLoginJobStatus {
  status: string
  returncode?: number | null
  lines?: string[]
}

export async function fetchXxtLoginJob(
  engineAddr: string, token: string | undefined, jobId: string,
): Promise<XxtLoginJobStatus> {
  const base = normalizeEngineAddr(engineAddr)
  const o = (await getJson2(engineUrlWithToken(
    base, `/jobs/${encodeURIComponent(jobId)}`, token))) as {
      status?: string; returncode?: number | null; lines?: string[]
    }
  return {
    status: String(o.status ?? 'unknown'),
    returncode: o.returncode ?? null,
    lines: Array.isArray(o.lines) ? o.lines.map(String) : [],
  }
}

/** POST /xxt/extract：D72 PWA 一键提取账户数据（当前仅 mode=all）。 */
export async function startXxtExtract(
  engineAddr: string, token?: string, opts?: { skip_notices?: boolean },
): Promise<string> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/extract', token), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: 'all', skip_notices: opts?.skip_notices ?? false }),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const o = (await res.json()) as { error?: string; hint?: string }
      if (o?.error) detail = o.error
      if (o?.hint) detail += `（${o.hint}）`
    } catch { /* keep status */ }
    throw new Error(detail)
  }
  const o = (await res.json()) as { job_id?: string }
  if (!o?.job_id) throw new Error('引擎未返回 job_id')
  return o.job_id
}

export interface XxtTargetClass { name: string; classId: string; works?: string[] }
export interface XxtTargetCourse { name: string; courseId: string; classes: XxtTargetClass[] }
export interface XxtTargetDiffItem {
  kind?: 'course' | 'class'
  courseId?: string
  courseName?: string
  classId?: string
  name?: string
  old?: string
  new?: string
}
export interface XxtTargetsDiff {
  against_at?: string
  courses_added?: XxtTargetDiffItem[]
  courses_removed?: XxtTargetDiffItem[]
  classes_added?: XxtTargetDiffItem[]
  classes_removed?: XxtTargetDiffItem[]
  renamed?: XxtTargetDiffItem[]
  counts?: Record<string, number>
}
export interface XxtTargets {
  ok?: boolean
  discovered_at?: string
  courses?: XxtTargetCourse[]
  diff?: XxtTargetsDiff | null
  age_seconds?: number | null
  history_count?: number
  keep?: number
}

/** POST /xxt/discover：D72 targets 模式——只读发现「我教的课」课程/班级清单。 */
export async function startXxtDiscover(engineAddr: string, token?: string): Promise<string> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/discover', token), { method: 'POST' })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const o = (await res.json()) as { job_id?: string }
  if (!o?.job_id) throw new Error('引擎未返回 job_id')
  return o.job_id
}

export interface XxtWork {
  name: string
  workId: string
  pending?: number | null
  submitted?: number | null
  unsubmitted?: number | null
  answer_window?: string
}
export interface XxtWorksClass {
  name: string
  classId: string
  cpi?: string
  works: XxtWork[]
  empty_confirmed?: boolean
  error?: string
}
export interface XxtWorksCourse { name: string; courseId: string; cpi?: string; classes: XxtWorksClass[] }
export interface XxtWorks { ok?: boolean; discovered_at?: string; courses?: XxtWorksCourse[] }

/** POST /xxt/works：D74-4 对选中班级惰性发现作业清单（只读，不进 mark）。 */
export async function startXxtDiscoverWorks(
  engineAddr: string, token: string | undefined, targets: XxtTargetCourse[],
): Promise<string> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/works', token), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ targets }),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const o = (await res.json()) as { error?: string }
      if (o?.error) detail = o.error
    } catch { /* keep status */ }
    throw new Error(detail)
  }
  const o = (await res.json()) as { job_id?: string }
  if (!o?.job_id) throw new Error('引擎未返回 job_id')
  return o.job_id
}

/** GET /xxt/works：最近一次作业清单发现结果（无结果返回空）。 */
export async function fetchXxtWorks(engineAddr: string, token?: string): Promise<XxtWorks> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/works', token))
  if (res.status === 404) return { courses: [] }
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json()) as XxtWorks
}

/** GET /xxt/targets：最近一次只读发现结果（无结果时返回空清单而非抛错）。 */
export async function fetchXxtTargets(engineAddr: string, token?: string): Promise<XxtTargets> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/targets', token))
  if (res.status === 404) return { courses: [] }
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json()) as XxtTargets
}

export interface XxtFreshness {
  ok?: boolean
  age_seconds?: number | null
  level?: 'ok' | 'warn' | 'danger' | 'unknown' | string
  stale?: boolean
  hint?: string
}

/** GET /xxt/freshness：D74-8 发现快照新鲜度，供操作前预判。 */
export async function fetchXxtFreshness(
  engineAddr: string, token?: string,
): Promise<XxtFreshness> {
  const base = normalizeEngineAddr(engineAddr)
  return (await getJson2(engineUrlWithToken(base, '/xxt/freshness', token))) as XxtFreshness
}

/** POST /xxt/targets/history/clear：D74-3 清理发现结果历史快照（保留当前快照）。 */
export async function clearXxtTargetsHistory(
  engineAddr: string, token?: string,
): Promise<number> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/targets/history/clear', token),
    { method: 'POST' })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const o = (await res.json()) as { removed?: string[] }
  return Array.isArray(o.removed) ? o.removed.length : 0
}

/** POST /xxt/extract（mode=targets）：只提取勾选的课程/班级。 */
export async function startXxtExtractTargets(
  engineAddr: string, token: string | undefined,
  targets: XxtTargetCourse[], opts?: { skip_notices?: boolean; appendRunId?: string },
): Promise<string> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/extract', token), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: 'targets', targets, skip_notices: opts?.skip_notices ?? false, append_run_id: opts?.appendRunId || '' }),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const o = (await res.json()) as { error?: string; hint?: string }
      if (o?.error) detail = o.error
      if (o?.hint) detail += `（${o.hint}）`
    } catch { /* keep status */ }
    throw new Error(detail)
  }
  const o = (await res.json()) as { job_id?: string }
  if (!o?.job_id) throw new Error('引擎未返回 job_id')
  return o.job_id
}

/** POST /xxt/run/import：D73-9 导入旧 run JSON（文件内容直接上传，仅本机引擎落盘）。 */
export async function importXxtRun(
  engineAddr: string, token: string | undefined, data: unknown, filename?: string,
): Promise<{ run_id?: string; classes?: number; works?: number; courses?: number }> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/run/import', token), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ data, filename }),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const o = (await res.json()) as { error?: string }
      if (o?.error) detail = o.error
    } catch { /* keep status */ }
    throw new Error(detail)
  }
  const o = (await res.json()) as { imported?: { run_id?: string; classes?: number; works?: number; courses?: number } }
  return o.imported || {}
}

/** POST /xxt/run/<id>/delete：D73 删除单条 run JSON + run 级截图。 */
export async function deleteXxtRun(
  engineAddr: string, token: string | undefined, runId: string,
): Promise<number> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(
    base, `/xxt/run/${encodeURIComponent(runId)}/delete`, token), { method: 'POST' })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const o = (await res.json()) as { error?: string }
      if (o?.error) detail = o.error
    } catch { /* keep status */ }
    throw new Error(detail)
  }
  const o = (await res.json()) as { removed?: string[] }
  return Array.isArray(o.removed) ? o.removed.length : 0
}

/** POST /xxt/runs/clear：D73-11 清空全部 run（JSON + run 级截图 + run 级 HTML 存档）。 */
export async function clearXxtRuns(engineAddr: string, token?: string): Promise<number> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/runs/clear', token), { method: 'POST' })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const o = (await res.json()) as { error?: string }
      if (o?.error) detail = o.error
    } catch { /* keep status */ }
    throw new Error(detail)
  }
  const o = (await res.json()) as { removed?: string[] }
  return Array.isArray(o.removed) ? o.removed.length : 0
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

/* ========== D74-9：全局操作记录（journal） ========== */

export interface JournalEvent {
  ts?: string
  kind?: string
  source?: string
  result?: string
  run_id?: string | null
  duration_ms?: number | null
  params?: Record<string, unknown>
  error?: string
}

export interface JournalStats { files?: number; bytes?: number; months?: number }

export async function fetchJournal(
  engineAddr: string, token: string | undefined,
  opts?: { start?: string; end?: string; kind?: string; limit?: number },
): Promise<{ events: JournalEvent[]; stats: JournalStats }> {
  const base = normalizeEngineAddr(engineAddr)
  const qs = new URLSearchParams()
  if (opts?.start) qs.set('start', opts.start)
  if (opts?.end) qs.set('end', opts.end)
  if (opts?.kind) qs.set('kind', opts.kind)
  if (opts?.limit) qs.set('limit', String(opts.limit))
  const path = `/journal${qs.toString() ? `?${qs.toString()}` : ''}`
  const o = (await getJson2(engineUrlWithToken(base, path, token))) as
    { ok?: boolean; events?: JournalEvent[]; stats?: JournalStats }
  return { events: o.events || [], stats: o.stats || {} }
}

export async function clearJournal(engineAddr: string, token?: string): Promise<number> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/journal/clear', token), { method: 'POST' })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const o = (await res.json()) as { removed?: string[] }
  return Array.isArray(o.removed) ? o.removed.length : 0
}

/* ========== D74-9/T：run 工件容量控制 ========== */

export interface XxtStorageStats {
  count?: number
  bytes?: number
  max_bytes?: number
  max_count?: number
}

export async function fetchXxtStorage(engineAddr: string, token?: string): Promise<XxtStorageStats> {
  const base = normalizeEngineAddr(engineAddr)
  const o = (await getJson2(engineUrlWithToken(base, '/xxt/storage', token))) as XxtStorageStats
  return o || {}
}

export async function pruneXxtRuns(
  engineAddr: string, token?: string,
): Promise<{ removed_count?: number; stats?: XxtStorageStats }> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/runs/prune', token), { method: 'POST' })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json()) as { removed_count?: number; stats?: XxtStorageStats }
}

/* ========== D75-1：真实批阅列表预览 ========== */

export interface XxtReviewStudent {
  studentId?: string
  name: string
  score?: string
  status?: string
  graded?: boolean
  review_path?: string
}

export interface XxtReviewStudents {
  ok?: boolean
  count?: number
  scored?: number
  students?: XxtReviewStudent[]
  source?: string
  error?: string
  hint?: string
}

// ---------------- D85 §3：本地人工批阅草稿 + 上传 ----------------

export interface XxtGradeDraft {
  score?: number
  comment?: string
  comment_text?: string
  images?: { name: string; data_b64: string }[]
  updatedAt?: string
}

export interface XxtGradeDrafts {
  ok?: boolean
  count?: number
  drafts?: Record<string, XxtGradeDraft>
  error?: string
}

/** GET /xxt/grade/drafts/<classId>/<workId>：读本地人工批阅草稿。 */
export async function fetchXxtGradeDrafts(
  engineAddr: string, token: string | undefined, classId: string, workId: string,
): Promise<XxtGradeDrafts> {
  const base = normalizeEngineAddr(engineAddr)
  const path = `/xxt/grade/drafts/${encodeURIComponent(classId)}/${encodeURIComponent(workId)}`
  return (await getJson2(engineUrlWithToken(base, path, token))) as XxtGradeDrafts
}

/** POST /xxt/grade/draft：保存单个学生的人工批阅草稿（本地文件，非平台写操作）。 */
export async function saveXxtGradeDraft(
  engineAddr: string, token: string | undefined,
  payload: { classId: string; workId: string; key: string; score?: number | null
    comment?: string; commentText?: string; images?: { name: string; data_b64: string }[]
    student?: string; tag?: string
    ai?: Record<string, unknown>; human?: Record<string, unknown> | null
    human_mode?: string; revision?: Record<string, unknown> | null },
): Promise<{ ok?: boolean; key?: string; error?: string }> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/grade/draft', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const o = (await res.json().catch(() => ({}))) as { ok?: boolean; key?: string; error?: string }
  if (!res.ok && !o?.error) throw new Error(`HTTP ${res.status}`)
  return o
}

/** POST /xxt/grade/delete-draft：删除单个学生草稿。 */
export async function deleteXxtGradeDraft(
  engineAddr: string, token: string | undefined,
  payload: { classId: string; workId: string; key: string },
): Promise<{ ok?: boolean; error?: string }> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/grade/delete-draft', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return (await res.json().catch(() => ({}))) as { ok?: boolean; error?: string }
}

/** POST /xxt/grade/upload：把本地草稿上传到平台（send=false 为 dry-run；返回 job_id）。 */
export async function startXxtGradeUpload(
  engineAddr: string, token: string | undefined,
  payload: { courseId: string; classId: string; cpi: string; workId: string
    student?: string; send?: boolean; force?: boolean },
): Promise<string> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/grade/upload', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const o = (await res.json()) as { error?: string }; if (o?.error) detail = o.error } catch { /* keep */ }
    throw new Error(detail)
  }
  const o = (await res.json()) as { job_id?: string }
  if (!o?.job_id) throw new Error('引擎未返回 job_id')
  return o.job_id
}

// ---------------- D86：AI 辅助批阅（provider 设置 / 班级映射 / AI 运行 / 报告） ----------------

export interface LlmProvider {
  name: string
  base_url: string
  models?: string[]
  batch_support?: boolean
  api_key?: string
  has_key?: boolean
}
export interface LlmStageCfg { provider?: string; model?: string; batch?: boolean }
export interface LlmConfig {
  ok?: boolean
  providers?: LlmProvider[]
  stages?: Record<string, LlmStageCfg>
  default_base_url?: string
  error?: string
}

/** GET /llm/config：provider（**掩码**）+ 两段式配置。 */
export async function fetchLlmConfig(engineAddr: string, token?: string): Promise<LlmConfig> {
  const base = normalizeEngineAddr(engineAddr)
  return (await getJson2(engineUrlWithToken(base, '/llm/config', token))) as LlmConfig
}

/** POST /llm/provider：{action:'set'|'delete'|'stage', ...}。 */
export async function postLlmProvider(
  engineAddr: string, token: string | undefined,
  payload: { action?: 'set' | 'delete' | 'stage'
    name?: string; base_url?: string; api_key?: string | null; batch_support?: boolean
    model?: string; stage?: string; provider?: string; batch?: boolean; forget_model?: string },
): Promise<LlmConfig & { ok?: boolean; error?: string }> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/llm/provider', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return (await res.json().catch(() => ({}))) as LlmConfig & { ok?: boolean; error?: string }
}

export interface XxtClassMap {
  ok?: boolean
  map?: Record<string, string>
  candidates?: { classDir: string; dirName: string; rosters: string[] }[]
  classDir?: string
  source?: string
  error?: string
}

/** GET /xxt/class-map：映射 + 本地候选目录。 */
export async function fetchXxtClassMap(engineAddr: string, token?: string): Promise<XxtClassMap> {
  const base = normalizeEngineAddr(engineAddr)
  return (await getJson2(engineUrlWithToken(base, '/xxt/class-map', token))) as XxtClassMap
}

/** POST /xxt/class-map：{courseId,classId,classDir} 或 {auto:true,name}。 */
export async function postXxtClassMap(
  engineAddr: string, token: string | undefined,
  payload: { courseId: string; classId: string; classDir?: string; auto?: boolean
    name?: string; write?: boolean },
): Promise<XxtClassMap> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/class-map', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return (await res.json().catch(() => ({}))) as XxtClassMap
}

/** POST /xxt/grade/ai-run：把作业包 + 班级/作业交给引擎跑 AI 两段式（返回 job_id）。 */
export async function startXxtGradeAi(
  engineAddr: string, token: string | undefined,
  payload: { courseId: string; classId: string; cpi: string; workId: string
    taskpad: Record<string, unknown>; pads?: Record<string, unknown>[]
    mode?: string; tags?: string[]; limit?: number },
): Promise<string> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/grade/ai-run', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const o = (await res.json()) as { error?: string }; if (o?.error) detail = o.error } catch { /* keep */ }
    throw new Error(detail)
  }
  const o = (await res.json()) as { job_id?: string }
  if (!o?.job_id) throw new Error('引擎未返回 job_id')
  return o.job_id
}

/** POST /xxt/grade/render-drafts：按 task 产物的批阅结果重新生成本地草稿 + 报告 PNG。 */
export async function startXxtGradeRenderDrafts(
  engineAddr: string, token: string | undefined,
  payload: { courseId: string; classId: string; cpi?: string; workId: string
    taskId: string; kind: 'ai' | 'human' },
): Promise<string> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/grade/render-drafts', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const o = (await res.json()) as { error?: string }; if (o?.error) detail = o.error } catch { /* keep */ }
    throw new Error(detail)
  }
  const o = (await res.json()) as { job_id?: string }
  if (!o?.job_id) throw new Error('引擎未返回 job_id')
  return o.job_id
}

/** GET /xxt/preview/students/<classId>/<workId>[?run_id=]：
 *  解析本地 review 列表存档；无存档时引擎会回退到 students.json manifest。 */
export async function fetchXxtReviewStudents(
  engineAddr: string, token: string | undefined,
  classId: string, workId: string, runId?: string,
): Promise<XxtReviewStudents> {
  const base = normalizeEngineAddr(engineAddr)
  const path = `/xxt/preview/students/${encodeURIComponent(classId)}/${encodeURIComponent(workId)}`
    + (runId ? `?run_id=${encodeURIComponent(runId)}` : '')
  return (await getJson2(engineUrlWithToken(base, path, token))) as XxtReviewStudents
}

/* ========== D77：课程通知发布（写操作，engine CLI 套壳） ========== */

export interface XxtNoticeTargetClass { classId: string; name?: string }
export interface XxtNoticeTargetCourse { courseId: string; courseName?: string; classes: XxtNoticeTargetClass[] }
export interface XxtNoticeAttachment { name: string; path: string; rel: string; size: number; mtime: number; generated_at?: string }

/** GET /xxt/notice/attachments：列出 workspace 下 classes/sheets 目录中的 PDF。 */
export async function fetchXxtNoticeAttachments(
  engineAddr: string, token?: string, limit = 200,
): Promise<XxtNoticeAttachment[]> {
  const base = normalizeEngineAddr(engineAddr)
  const raw = await getJson2(engineUrlWithToken(base, `/xxt/notice/attachments?limit=${encodeURIComponent(String(limit))}`, token))
  const o = raw as Record<string, unknown>
  return Array.isArray(o.items) ? (o.items as XxtNoticeAttachment[]) : []
}

/** POST /xxt/notice/send：发起 dry-run 或真正发送 job。 */
export async function startXxtNoticeSend(
  engineAddr: string, token: string | undefined,
  payload: { targets: XxtNoticeTargetCourse[]; title: string; bodyHtml: string; attachments: string[]; send: boolean },
): Promise<{ jobId: string; mode: string }> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/notice/send', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const o = (await res.json()) as { error?: string }; if (o?.error) detail = o.error } catch {}
    throw new Error(detail)
  }
  const o = (await res.json()) as { job_id?: string; mode?: string }
  if (!o?.job_id) throw new Error('引擎未返回 job_id')
  return { jobId: o.job_id, mode: String(o.mode || (payload.send ? 'send' : 'dry-run')) }
}

export async function fetchXxtAttachmentWhitelist(engineAddr: string, token?: string): Promise<string[]> {
  const base = normalizeEngineAddr(engineAddr)
  const o = (await getJson2(engineUrlWithToken(base, '/xxt/notice/attachment-whitelist', token))) as { items?: string[] }
  return o.items || []
}
export async function saveXxtAttachmentWhitelist(engineAddr: string, token: string | undefined, items: string[]): Promise<string[]> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/notice/attachment-whitelist', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ items }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const o = (await res.json()) as { items?: string[] }
  return o.items || []
}

export interface XxtAllowItem { courseId: string; classId: string; name?: string }
export interface XxtWorkFolder { directoryId: string; name: string }

export async function fetchXxtWriteAllowlist(engineAddr: string, token?: string): Promise<XxtAllowItem[]> {
  const base = normalizeEngineAddr(engineAddr)
  const o = (await getJson2(engineUrlWithToken(base, '/xxt/write-allowlist', token))) as { items?: XxtAllowItem[] }
  return o.items || []
}
export async function saveXxtWriteAllowlist(engineAddr: string, token: string | undefined, items: XxtAllowItem[]): Promise<XxtAllowItem[]> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/write-allowlist', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ items }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const o = (await res.json()) as { items?: XxtAllowItem[] }
  return o.items || []
}
export async function fetchXxtWorkFolders(engineAddr: string, token: string | undefined, courseId: string, classId: string, cpi: string): Promise<XxtWorkFolder[]> {
  const base = normalizeEngineAddr(engineAddr)
  const path = `/xxt/work/folders?courseId=${encodeURIComponent(courseId)}&classId=${encodeURIComponent(classId)}&cpi=${encodeURIComponent(cpi)}`
  const o = (await getJson2(engineUrlWithToken(base, path, token))) as { items?: XxtWorkFolder[] }
  return o.items || []
}
export async function fetchXxtWorkDetail(engineAddr: string, token: string | undefined, courseId: string, classId: string, cpi: string, workLibraryId: string): Promise<{ ok?: boolean; title?: string; stemHtml?: string; error?: string }> {
  const base = normalizeEngineAddr(engineAddr)
  const path = `/xxt/work/detail?courseId=${encodeURIComponent(courseId)}&classId=${encodeURIComponent(classId)}&cpi=${encodeURIComponent(cpi)}&workLibraryId=${encodeURIComponent(workLibraryId)}`
  return (await getJson2(engineUrlWithToken(base, path, token))) as { ok?: boolean; title?: string; stemHtml?: string; error?: string }
}
export async function createXxtWorkFolder(engineAddr: string, token: string | undefined, payload: { courseId: string; classId: string; cpi: string; directoryId: string; title: string }): Promise<{ ok?: boolean; error?: string }> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/work/folder-create', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const o = (await res.json()) as { error?: string }; if (o?.error) detail = o.error } catch {}
    throw new Error(detail)
  }
  return (await res.json()) as { ok?: boolean; error?: string }
}
export async function copyXxtWork(engineAddr: string, token: string | undefined, payload: { courseId: string; classId: string; cpi: string; directoryId: string; workLibraryId: string; title: string }): Promise<{ ok?: boolean; newWorkLibraryId?: string; error?: string }> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/work/copy', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const o = (await res.json()) as { error?: string }; if (o?.error) detail = o.error } catch {}
    throw new Error(detail)
  }
  return (await res.json()) as { ok?: boolean; newWorkLibraryId?: string; error?: string }
}

export async function startXxtWorkCreate(engineAddr: string, token: string | undefined, payload: { courseId: string; classId: string; cpi: string; title: string; stemHtml: string; directoryId?: string; attachments?: { name: string; data_b64: string }[] }): Promise<string> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/work/create', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const o = (await res.json()) as { error?: string }; if (o?.error) detail = o.error } catch {}
    throw new Error(detail)
  }
  const o = (await res.json()) as { job_id?: string }
  if (!o?.job_id) throw new Error('引擎未返回 job_id')
  return o.job_id
}

/* ========== D79：发布-学习通（通知上传 / 作业列表与发布） ========== */

export interface XxtWorkLibraryItem { workLibraryId: string; type?: string; text?: string; canEdit?: boolean; publishedClasses?: string[] }

export async function uploadXxtNoticeFiles(
  engineAddr: string, token: string | undefined,
  items: { name: string; data_b64: string }[],
): Promise<XxtNoticeAttachment[]> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/notice/upload', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const o = (await res.json()) as { items?: XxtNoticeAttachment[] }
  return o.items || []
}

/** GET /xxt/work/list：读取作业库条目（含未发布草稿）。 */
export async function fetchXxtWorkList(
  engineAddr: string, token: string | undefined,
  courseId: string, classId: string, cpi: string, directoryId = '0', classIds?: string[],
): Promise<{ ok?: boolean; items?: XxtWorkLibraryItem[]; error?: string }> {
  const base = normalizeEngineAddr(engineAddr)
  const cids = (classIds && classIds.length) ? `&classIds=${encodeURIComponent(classIds.join(','))}` : ''
  const path = `/xxt/work/list?courseId=${encodeURIComponent(courseId)}&classId=${encodeURIComponent(classId)}&cpi=${encodeURIComponent(cpi)}&directoryId=${encodeURIComponent(directoryId)}${cids}`
  return (await getJson2(engineUrlWithToken(base, path, token))) as { ok?: boolean; items?: XxtWorkLibraryItem[]; error?: string }
}

/** POST /xxt/work/publish：dry-run 或发布已有作业。 */
export async function startXxtWorkPublish(
  engineAddr: string, token: string | undefined,
  payload: { courseId: string; classId: string; classIds?: string[]; workLibraryId: string; cpi: string;
    startTime?: string; endTime?: string; allowLate?: boolean; lateDeadline?: string;
    redoTimes?: number; send: boolean },
): Promise<{ jobId: string; mode: string }> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/work/publish', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const o = (await res.json()) as { error?: string }; if (o?.error) detail = o.error } catch {}
    throw new Error(detail)
  }
  const o = (await res.json()) as { job_id?: string; mode?: string }
  if (!o?.job_id) throw new Error('引擎未返回 job_id')
  return { jobId: o.job_id, mode: String(o.mode || (payload.send ? 'send' : 'dry-run')) }
}

/* ========== D75-1c/d：批阅图片 + 两栏批语 ========== */

export interface XxtReviewImageWork {
  classId: string
  workId: string
  courseId?: string
  courseName?: string
  className?: string
  workName?: string
  count?: number
  students?: number
  bytes?: number
  mtime?: number
  generated_at?: string
  images?: string[]
  comment_count?: number
  images_deleted?: boolean
  students_total?: number
  students_with_images?: number
  zero_image_count?: number
  zero_image_students?: string[]
}

export interface XxtReviewIndex {
  works?: XxtReviewImageWork[]
  stats?: { works?: number; images?: number; bytes?: number }
}

export async function startXxtReviewDownload(
  engineAddr: string, token: string | undefined,
  opts: { courseId: string; classId: string; workId: string
    courseName?: string; className?: string; workName?: string; limit?: number
    mode?: 'full' | 'missing' | 'comments-only'
    allowPost?: string[] },
): Promise<string> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/review/download', token), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(opts),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const o = (await res.json()) as { error?: string }
      if (o?.error) detail = o.error
    } catch { /* keep status */ }
    throw new Error(detail)
  }
  const o = (await res.json()) as { job_id?: string }
  if (!o?.job_id) throw new Error('引擎未返回 job_id')
  return o.job_id
}

export async function fetchXxtReviewIndex(
  engineAddr: string, token?: string,
): Promise<XxtReviewIndex> {
  const base = normalizeEngineAddr(engineAddr)
  return (await getJson2(engineUrlWithToken(base, '/xxt/review/index', token))) as XxtReviewIndex
}

export async function pruneXxtReview(engineAddr: string, token?: string): Promise<number> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/review/prune', token), { method: 'POST' })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const o = (await res.json()) as { removed_count?: number }
  return o.removed_count || 0
}

export function xxtReviewFileUrl(
  engineAddr: string, token: string | undefined, classId: string, workId: string, fname: string,
): string {
  const base = normalizeEngineAddr(engineAddr)
  return engineUrlWithToken(
    base, `/xxt/review/file/${encodeURIComponent(classId)}/${encodeURIComponent(workId)}/${encodeURIComponent(fname)}`,
    token)
}

/* ========== D75-1e / D75-4：探针 PWA 化 + 逐生预览 ========== */

export interface XxtReviewProbeDetail {
  name?: string
  workAnswerId?: string
  images?: number
  comment_len?: number
  per_question_comments?: number
  score?: string
  error?: string
}

export interface XxtReviewProbe {
  ok?: boolean
  students?: { name: string; status?: string; workAnswerId: string }[]
  details?: XxtReviewProbeDetail[]
  aborted?: { method?: string; url?: string }[]
  error?: string
  hint?: string
}

export async function startXxtReviewProbe(
  engineAddr: string, token: string | undefined,
  opts: { courseId: string; classId: string; workId: string; sample?: number },
): Promise<string> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/review/probe', token), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(opts),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const o = (await res.json()) as { job_id?: string }
  if (!o?.job_id) throw new Error('引擎未返回 job_id')
  return o.job_id
}

export async function fetchXxtReviewProbeLatest(
  engineAddr: string, token?: string,
): Promise<XxtReviewProbe> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/review/probe/latest', token))
  if (res.status === 404) return { ok: false, error: 'no probe yet' }
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json()) as XxtReviewProbe
}

export interface XxtReviewManifestStudent {
  studentId?: string
  name: string
  workAnswerId?: string
  status?: string
  images?: string[]
  comment?: string
  comment_text?: string
  comment_images?: string[]
  per_question_comments?: string[]
  per_question_comment_texts?: string[]
  per_question_comment_images?: string[][]
  ueditor0?: string
  score?: string
  error?: string
}

export interface XxtReviewManifest {
  ok?: boolean
  classId?: string
  workId?: string
  courseId?: string
  courseName?: string
  className?: string
  workName?: string
  generated_at?: string
  students?: XxtReviewManifestStudent[]
}

export async function fetchXxtReviewWork(
  engineAddr: string, token: string | undefined, classId: string, workId: string,
): Promise<XxtReviewManifest> {
  const base = normalizeEngineAddr(engineAddr)
  return (await getJson2(engineUrlWithToken(
    base, `/xxt/review/work/${encodeURIComponent(classId)}/${encodeURIComponent(workId)}`, token,
  ))) as XxtReviewManifest
}


/** POST /xxt/review/work/<class>/<work>/delete：删除该次作业图片，保留 students.json 清单。 */
export async function deleteXxtReviewWork(
  engineAddr: string, token: string | undefined, classId: string, workId: string,
): Promise<{ deleted_answer?: number; deleted_comment?: number }> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(
    base, `/xxt/review/work/${encodeURIComponent(classId)}/${encodeURIComponent(workId)}/delete`, token),
    { method: 'POST' })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json()) as { deleted_answer?: number; deleted_comment?: number }
}

/** POST /xxt/review/work/<class>/<work>/purge：彻底删除该次作业目录（含 students.json）。 */
export async function purgeXxtReviewWork(
  engineAddr: string, token: string | undefined, classId: string, workId: string,
): Promise<{ purged?: boolean }> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(
    base, `/xxt/review/work/${encodeURIComponent(classId)}/${encodeURIComponent(workId)}/purge`, token),
    { method: 'POST' })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json()) as { purged?: boolean }
}

/* ---------------- D87 §5：水印样式库（serve 端点） ---------------- */

export interface WmStyleItem { image: string; pos?: string; ratio?: number; alpha?: number }
export interface WmStyle {
  name: string; enabled?: boolean; pageText?: boolean; default?: boolean
  items?: WmStyleItem[]; updatedAt?: string
}

/** GET /watermark/styles：命名样式列表（含 default 标记）+ 素材文件清单。 */
export async function fetchWatermarkStyles(
  engineAddr: string, token?: string, assetsDir?: string,
): Promise<{ ok?: boolean; assets_dir?: string; source?: string; styles?: WmStyle[]; files?: string[] }> {
  const base = normalizeEngineAddr(engineAddr)
  const q = assetsDir ? `?assets_dir=${encodeURIComponent(assetsDir)}` : ''
  return (await getJson2(engineUrlWithToken(base, `/watermark/styles${q}`, token))) as
    { ok?: boolean; assets_dir?: string; source?: string; styles?: WmStyle[]; files?: string[] }
}

/** POST /watermark/style：样式 CRUD（action = save|rename|delete|set_default）。 */
export async function saveWatermarkStyle(
  engineAddr: string, token: string | undefined,
  payload: { action?: 'save' | 'rename' | 'delete' | 'set_default'; name: string
    new_name?: string; default?: boolean; style?: Partial<WmStyle>; assets_dir?: string },
): Promise<{ ok?: boolean; error?: string; assets_dir?: string; styles?: WmStyle[]; style?: WmStyle }> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/watermark/style', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const o = (await res.json().catch(() => ({}))) as
    { ok?: boolean; error?: string; assets_dir?: string; styles?: WmStyle[]; style?: WmStyle }
  if (!res.ok && !o?.error) throw new Error(`HTTP ${res.status}`)
  return o
}

/** POST /watermark/upload：水印图片 base64 → 落 <ws>/assets/watermark/，返回相对路径。 */
export async function uploadWatermarkImage(
  engineAddr: string, token: string | undefined,
  payload: { name: string; data: string; assets_dir?: string },
): Promise<{ ok?: boolean; error?: string; name?: string; path?: string; bytes?: number }> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/watermark/upload', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const o = (await res.json().catch(() => ({}))) as
    { ok?: boolean; error?: string; name?: string; path?: string; bytes?: number }
  if (!res.ok && !o?.error) throw new Error(`HTTP ${res.status}`)
  return o
}

/* ---------------- D89-N1：作业包（pack） ---------------- */

export interface PackPadRef { padId: string; tag?: string }
export interface Pack {
  id: string; name?: string; term?: string; class_dir?: string
  pads?: PackPadRef[]; note?: string; updatedAt?: string; schema?: number
}

/** GET /packs：列出 workspace 下的作业包。 */
export async function fetchPacks(
  engineAddr: string, token?: string,
): Promise<{ ok?: boolean; packs?: Pack[] }> {
  const base = normalizeEngineAddr(engineAddr)
  return (await getJson2(engineUrlWithToken(base, '/packs', token))) as { ok?: boolean; packs?: Pack[] }
}

/** GET /pack/<id>：读取单个作业包。 */
export async function fetchPack(
  engineAddr: string, token: string | undefined, id: string,
): Promise<Pack & { ok?: boolean; error?: string }> {
  const base = normalizeEngineAddr(engineAddr)
  return (await getJson2(engineUrlWithToken(base, `/pack/${encodeURIComponent(id)}`, token))) as
    Pack & { ok?: boolean; error?: string }
}

/** POST /pack：保存/删除/重命名作业包（action）。 */
export async function savePack(
  engineAddr: string, token: string | undefined,
  payload: { action?: 'save' | 'delete' | 'rename'; id: string; new_id?: string; pack?: Partial<Pack> },
): Promise<{ ok?: boolean; error?: string; pack?: Pack; packs?: Pack[] }> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/pack', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const o = (await res.json().catch(() => ({}))) as
    { ok?: boolean; error?: string; pack?: Pack; packs?: Pack[] }
  if (!res.ok && !o?.error) throw new Error(`HTTP ${res.status}`)
  return o
}

/* ---------------- D89-N3/N4：题目 solution 多版本 ---------------- */

export interface SolutionVersion {
  id: string; text: string; source?: string; model?: string; at?: string; pinned?: boolean
}
export interface SolutionDoc {
  qid: string; kb?: string; chap?: string; versions?: SolutionVersion[]
  ok?: boolean; error?: string
}

/** GET /kb/solutions/<qid>：读某题全部答案版本。 */
export async function fetchKbSolutions(
  engineAddr: string, token: string | undefined, qid: string,
): Promise<SolutionDoc> {
  const base = normalizeEngineAddr(engineAddr)
  try {
    return (await getJson2(engineUrlWithToken(base, `/kb/solutions/${encodeURIComponent(qid)}`, token))) as SolutionDoc
  } catch {
    return { qid, versions: [] }
  }
}

/** D100-T2：`GET /kb/solutions`（无 qid）→ 全库生效答案索引 {qid: {text,source,version,from,...}}。
 *  引擎离线/未实现时返回空索引（调用方回落 xlsx `solution` 列，行为同 D100 前）。 */
export interface KbSolutionEntry extends SolutionVersion {
  /** 引擎 `effective_map` 额外回填的版本号别名（= version）。 */
  id: string
  version?: string; from?: string; pinned?: boolean
  n_versions?: number; ai_versions?: number
}
export interface KbSolutionIndex {
  ok?: boolean; effective?: Record<string, KbSolutionEntry>
  digest?: number; error?: string
}

export async function fetchKbSolutionIndex(
  engineAddr: string, token?: string,
): Promise<KbSolutionIndex> {
  const base = normalizeEngineAddr(engineAddr)
  try {
    return (await getJson2(engineUrlWithToken(base, '/kb/solutions', token))) as KbSolutionIndex
  } catch {
    return { ok: false, effective: {} }
  }
}

/** POST /kb/solution：追加/置顶/删除某题的某版本（action = add|pin|rm）。 */
export async function mutateKbSolution(
  engineAddr: string, token: string | undefined,
  payload: { action?: 'add' | 'pin' | 'rm'; qid: string; text?: string; source?: string
    model?: string; kb?: string; chap?: string; pin?: boolean; version?: string },
): Promise<{ ok?: boolean; error?: string; solutions?: SolutionDoc; added?: SolutionVersion }> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/kb/solution', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const o = (await res.json().catch(() => ({}))) as
    { ok?: boolean; error?: string; solutions?: SolutionDoc; added?: SolutionVersion }
  if (!res.ok && !o?.error) throw new Error(`HTTP ${res.status}`)
  return o
}

/* ---------------- D89-N5：题库 AI 作答 ---------------- */

/** POST /kb/ai-solve：题库题目 AI 作答（返回 job_id；dry-run 也走 job 流）。 */
export async function startKbAiSolve(
  engineAddr: string, token: string | undefined,
  payload: { kb?: string; chap?: string; ids?: string[]; model?: string; pin?: boolean; apply?: boolean
    /** D104：教师额外作答要求（如「请画出示意图」「输出为 HTML」） */
    requirement?: string },
): Promise<string> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/kb/ai-solve', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const o = (await res.json()) as { error?: string }; if (o?.error) detail = o.error } catch { /* keep */ }
    throw new Error(detail)
  }
  const o = (await res.json()) as { ok?: boolean; job_id?: string; error?: string }
  if (!o?.ok || !o.job_id) throw new Error(o?.error || '未返回 job_id')
  return o.job_id
}

/* ---------------- D90：LLM Playground ---------------- */

export interface PlaygroundRecord {
  id: string; folder?: string; at?: string; provider?: string; model?: string
  temperature?: number | null; mode?: string; batchGroup?: string
  question?: string; attachments?: string[]; answer?: string; notes?: string[]; error?: string
}

/** POST /playground/upload：附件 base64 → workspace 运行目录，返回落盘路径。 */
export async function uploadPlaygroundAttachment(
  engineAddr: string, token: string | undefined,
  payload: { name: string; data: string; group?: string },
): Promise<{ ok?: boolean; error?: string; name?: string; kind?: string; path?: string; bytes?: number }> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/playground/upload', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  })
  const o = (await res.json().catch(() => ({}))) as any
  if (!res.ok && !o?.error) throw new Error(`HTTP ${res.status}`)
  return o
}

/** POST /playground/ask：单次调用（无多轮上下文）；返回 {ok, answer, recordId}。 */
export async function playgroundAsk(
  engineAddr: string, token: string | undefined,
  payload: { question: string; attachments?: string[]; provider?: string; model?: string
    system?: string; temperature?: number | null; maxTokens?: number; folder?: string; save?: boolean },
): Promise<{ ok?: boolean; answer?: string; model?: string; recordId?: string; error?: string; notes?: string[] }> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/playground/ask', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question: payload.question, attachments: payload.attachments,
      provider: payload.provider, model: payload.model, system: payload.system,
      temperature: payload.temperature, max_tokens: payload.maxTokens, folder: payload.folder,
      save: payload.save !== false,
    }),
  })
  const o = (await res.json().catch(() => ({}))) as any
  if (!res.ok && !o?.error) throw new Error(`HTTP ${res.status}`)
  return o
}

/** POST /playground/batch：批量发送（逐条独立调用）。 */
export async function playgroundBatch(
  engineAddr: string, token: string | undefined,
  payload: { questions: string[]; attachments?: string[]; provider?: string; model?: string
    folder?: string; workers?: number; save?: boolean },
): Promise<{ ok?: boolean; groupId?: string; total?: number; succeeded?: number
    results?: { ok?: boolean; question?: string; answer?: string; error?: string; recordId?: string }[]
    error?: string }> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/playground/batch', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  })
  const o = (await res.json().catch(() => ({}))) as any
  if (!res.ok && !o?.error) throw new Error(`HTTP ${res.status}`)
  return o
}

/** GET /playground/records：记录 + 文件夹。 */
export async function fetchPlaygroundRecords(
  engineAddr: string, token?: string,
): Promise<{ ok?: boolean; records?: PlaygroundRecord[]; folders?: string[] }> {
  const base = normalizeEngineAddr(engineAddr)
  return (await getJson2(engineUrlWithToken(base, '/playground/records', token))) as any
}

/** POST /playground/record：删除/移动/保存记录。 */
export async function mutatePlaygroundRecord(
  engineAddr: string, token: string | undefined,
  payload: { action?: 'save' | 'delete' | 'move'; id?: string; ids?: string[]; folder?: string
    record?: Partial<PlaygroundRecord> },
): Promise<{ ok?: boolean; error?: string; records?: PlaygroundRecord[] }> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/playground/record', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  })
  const o = (await res.json().catch(() => ({}))) as any
  if (!res.ok && !o?.error) throw new Error(`HTTP ${res.status}`)
  return o
}

/** POST /playground/folder：新建/删除/重命名文件夹。 */
export async function mutatePlaygroundFolder(
  engineAddr: string, token: string | undefined,
  payload: { action?: 'new' | 'delete' | 'rename'; name: string; new_name?: string },
): Promise<{ ok?: boolean; error?: string; folders?: string[] }> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/playground/folder', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  })
  const o = (await res.json().catch(() => ({}))) as any
  if (!res.ok && !o?.error) throw new Error(`HTTP ${res.status}`)
  return o
}

/* ---------------- D92-R3：题库目录（下拉数据源） ---------------- */

export interface KbCatalogId { id: string; content?: string }
export interface KbCatalogChapter { chap: string; count: number; ids: KbCatalogId[] }
export interface KbCatalogKind { kind: string; chapters: KbCatalogChapter[] }

/** GET /kb/catalog：题库 kind/章节/题号[+内容]。 */
export async function fetchKbCatalog(
  engineAddr: string, token?: string,
): Promise<{ ok?: boolean; kinds?: KbCatalogKind[] }> {
  const base = normalizeEngineAddr(engineAddr)
  try {
    return (await getJson2(engineUrlWithToken(base, '/kb/catalog', token))) as
      { ok?: boolean; kinds?: KbCatalogKind[] }
  } catch {
    return { ok: false, kinds: [] }
  }
}

/* ---------------- D92-R4：按草稿（双套+模式）逐生生成报告 ---------------- */

/** POST /xxt/grade/render-from-drafts：按本地双套草稿逐生生成报告（人工在前+附件AI+修订标红）。 */
export async function renderReportsFromDrafts(
  engineAddr: string, token: string | undefined,
  payload: { classId: string; workId: string; taskId?: string; classDir?: string; withReportPng?: boolean },
): Promise<{ ok?: boolean; error?: string; count?: number; dir?: string
  reports?: { key?: string; student?: string; kind?: string; revised?: boolean; png?: boolean }[] }> {
  const base = normalizeEngineAddr(engineAddr)
  const res = await fetch(engineUrlWithToken(base, '/xxt/grade/render-from-drafts', token), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  })
  const o = (await res.json().catch(() => ({}))) as any
  if (!res.ok && !o?.error) throw new Error(`HTTP ${res.status}`)
  return o
}

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  fetchXxtRun, fetchXxtRuns, fetchXxtStatus, startXxtLogin,
} from '../lib/engineClient'
import { useSettingsStore } from '../stores/settings'

/* 学习通 tab（D63 T7/T8 实装，docs/16 §20）：
 * - 登录卡：QR 框（/xxt/qr）↔ 头像（verdict=alive 时 data-URL）；
 * - 列表：/xxt/runs 最新 run 的 全 course 分组列表，组头 sticky、每列表独立滚动；
 * - 行操作：置顶(≤10 可调)/移出/刷新/从学习通恢复（恢复=仅回放最近 run JSON，零网络）。
 * 写操作（公告发布/批阅回传）维持 D62 冻结——本页不提供任何写按钮。   */

const settings = useSettingsStore()
const engUrl = computed(() => settings.engineUrl)
const tok = computed(() => settings.engineToken)

/* ---------- 登录卡 ---------- */
const verdict = ref<'alive' | 'dead' | 'unknown' | string>('unknown')
const avatar = ref<string | null>(null)
const qrcode = ref<string>('')
const loginHint = ref('')

async function refreshStatus() {
  try {
    const r = await fetchXxtStatus(engUrl.value, tok.value)
    verdict.value = r.verdict
    avatar.value = r.avatar_dataurl || null
    if (r.verdict === 'alive') {
      loginHint.value = `已登录（体检 ${r.info?.checked_at || ''}；storage 已回写续期）`
    } else if (r.verdict === 'dead') {
      loginHint.value = `会话失效${(r.info?.reasons || []).join('，')}——请扫码`
    } else {
      const why = (r.info?.reasons || []).join('，')
      loginHint.value = why.includes('playwright')
        ? '引擎缺 playwright——请到「设置中心 → Playwright（学习通提取）」一键联网安装'
        : '引擎未记录会话（未扫码登录），可点上方「扫码登录」'
    }
  } catch {
    verdict.value = 'unknown'
    loginHint.value = '引擎未在线（设置中心可改 engine 地址）'
  }
}

async function startScan() {
  loginHint.value = '已发起扫码任务：输入学习通手机 App 扫描下方二维码…'
  try {
    await startXxtLogin(engUrl.value, tok.value)
    pollQr()
  } catch (e) {
    loginHint.value = `启动失败：${String(e)}（检查引擎在线/playwright 安装项）`
  }
}

function pollQr() {
  const base = engUrl.value.replace(/\/+$/, '') || ''
  const tokArg = tok.value ? `?token=${encodeURIComponent(tok.value)}` : ''
  qrcode.value = `${base}/xxt/qr${tokArg}` // <img> 直取；生成后每 3s 重载一次直至 alive
  const timer = setInterval(async () => {
    await refreshStatus()
    if (verdict.value === 'alive') { clearInterval(timer) }
  }, 3000)
}

/* ---------- 列表（最新 run） ---------- */
interface WorkRow {
  workId: string; name: string; answer_window?: string
  pending?: number | null; submitted?: number | null; unsubmitted?: number | null
  submitted_names?: { name: string; status?: string }[]
  unsubmitted_names?: string[]; sub_not_in_roster?: string[]
  anchor?: { ok?: boolean; notes?: string[]; roster_delta?: number }
}
interface ClassRow { name: string; classId: string; status: string; works: WorkRow[]; roster?: { total?: number | null } ; notes?: string[] }
interface CourseRow { name: string; courseId: string; classes: ClassRow[] }
const runs = ref<{ run_id: string; ts_end?: string; works?: number; failures?: number }[]>([])
const curRun = ref<string | null>(null)
const courses = ref<CourseRow[]>([])
const loadSteps = ref<{ action: string; detail?: string; title?: string; url?: string; ts?: string; shot?: string }[]>([])
const loadingRun = ref(false)
const runMsg = ref('')
const filterMode = ref<'all' | 'hasWorks' | 'empty' | 'fail'>('all')  // T8
/* ---- §24 通知查看卡（只读；数据=最新 run 的 notices[]） ---- */
interface NoticeItem { text: string; href: string }
const noticeClsFilter = ref<string>('')
function noticeOf(cl: ClassRow): NoticeItem[] { return (cl as unknown as { notices?: NoticeItem[] }).notices || [] }
const noticeClasses = computed(() =>
  courses.value.flatMap(c => c.classes).filter(cl => noticeOf(cl).length > 0))
const noticeRows = computed(() => {
  const pool = noticeClasses.value.filter(cl => !noticeClsFilter.value || cl.classId === noticeClsFilter.value)
  const rows: { cls: string; title: string; when: string; read?: string; ratio?: number }[] = []
  for (const cl of pool) {
    for (const it of noticeOf(cl)) {
      const t = it.text || ''
      const wm = t.match(/(\d{2}-\d{2} \d{2}:\d{2}|\d{4}-\d{2}-\d{2})/)
      const rm = t.match(/已读：(\d+)\/(\d+)/)
      rows.push({ cls: cl.name, title: t.replace(/\s*\d{2}-\d{2} \d{2}:\d{2}.*$/, '').slice(0, 60),
                  when: wm ? wm[1] : '', read: rm ? `${rm[1]}/${rm[2]}` : undefined,
                  ratio: rm ? Number(rm[1]) / Math.max(1, Number(rm[2])) : undefined })
    }
  }
  return rows
})
const shotUrl = (shot?: string): string => {
  if (!shot) { return '' }
  const fname = shot.split('/').pop() || ''
  const tokArg = tok.value ? `?token=${encodeURIComponent(tok.value)}` : ''
  return `${engUrl.value.replace(/\/+$/, '')}/xxt/shot/${curRun.value || ''}/${fname}${tokArg}`
}

/* 列表项可见性（T8） */
const pinned = ref<string[]>(JSON.parse(localStorage.getItem('xxt-pinned') || '[]') as string[])
const pinCap = ref(Number(localStorage.getItem('xxt-pinCap') || 10) || 10)
const removed = ref<string[]>(JSON.parse(localStorage.getItem('xxt-removed') || '[]') as string[])

function key(cl: ClassRow): string { return `${cl.classId}` }
function isPinned(cl: ClassRow): boolean { return pinned.value.includes(cl.classId) }
function isRemoved(cl: ClassRow): boolean { return removed.value.includes(key(cl)) }

function persistLocal() {
  localStorage.setItem('xxt-pinned', JSON.stringify(pinned.value))
  localStorage.setItem('xxt-removed', JSON.stringify(removed.value))
  localStorage.setItem('xxt-pinCap', String(pinCap.value))
}

function togglePin(cl: ClassRow) {
  const k = cl.classId
  if (isPinned(cl)) {
    pinned.value = pinned.value.filter(x => x !== k)
  } else {
    if (pinned.value.length >= pinCap.value) {
      runMsg.value = `置顶已达上限 ${pinCap.value}（上限可在下方调整）`
      return
    }
    pinned.value.push(k)
  }
  persistLocal()
}

function removeRow(cl: ClassRow) {
  if (!isRemoved(cl)) removed.value.push(key(cl))
  persistLocal()
}

function restoreRemoved() {
  removed.value = []          // 「从学习通恢复列表」：按 20.3 决议=仅回放最近 run JSON（零网络）
  runMsg.value = '已恢复全部行（回放最近 run）'
  persistLocal()
}

async function refreshRuns() {
  loadingRun.value = true
  runMsg.value = ''
  try {
    runs.value = await fetchXxtRuns(engUrl.value, tok.value)
    if (!runs.value.length) { runMsg.value = '暂无 run（引擎侧 xxt extract run 未产出）'; return }
    await loadRun(runs.value[0].run_id)
  } catch (e) {
    runMsg.value = `引擎不可达：${String(e)}`
  } finally { loadingRun.value = false }
}

async function loadRun(id: string) {
  loadingRun.value = true
  try {
    const raw = (await fetchXxtRun(engUrl.value, tok.value, id)) as Record<string, unknown>
    curRun.value = String(raw['run_id'] || id)
    courses.value = (raw['courses'] as CourseRow[]) || []
    loadSteps.value = ((raw['steps'] as unknown[]) || []) as typeof loadSteps.value
    runMsg.value = `run ${curRun.value} 已载入（${courses.value.reduce((a, c) => a + c.classes.length, 0)} 班）`
  } catch (e) {
    runMsg.value = `载入失败：${String(e)}`
  } finally { loadingRun.value = false }
}

const grouped = computed(() => courses.value.map(c => {
  const pass = (cl: ClassRow): boolean => {
    if (isRemoved(cl)) { return false }
    if (filterMode.value === 'hasWorks') { return cl.works.length > 0 }
    if (filterMode.value === 'empty') { return cl.status === 'empty_confirmed' }
    if (filterMode.value === 'fail') { return cl.status === 'not_extracted' }
    return true
  }
  const visible = c.classes.filter(pass)
  if (filterMode.value === 'hasWorks') { visible.sort((a, b) => b.works.length - a.works.length) }
  const pinnedRows = visible.filter(cl => isPinned(cl))
  const normal = visible.filter(cl => !isPinned(cl))
  return { course: c, pinnedRows, normal, total: visible.length }
}))


onMounted(() => { refreshStatus(); refreshRuns() })
</script>

<template>
  <section>
    <h2>学习通 <small style="font-weight:400;color:var(--c-muted)">登录 · 只读基本信息（D63 T7/T8；写操作维持 D62 冻结）</small></h2>

    <!-- 登录卡：QR 框 ↔ 头像 -->
    <div class="card">
      <div style="display:flex; gap:24px; align-items:flex-start; flex-wrap:wrap">
        <div style="width:168px; text-align:center">
          <div style="border:1px solid var(--c-border); border-radius:12px; padding:6px; background:#fff; min-height:156px; display:flex; align-items:center; justify-content:center">
            <img v-if="verdict==='alive' && avatar" :src="avatar" alt="登录头像"
                 style="width:140px; height:140px; border-radius:50%; object-fit:cover" />
            <div v-else-if="verdict==='alive'"
                 style="width:140px; height:140px; border-radius:50%; display:flex; align-items:center; justify-content:center; flex-direction:column; background:var(--c-bg,#f7f7f9)">
              <span style="font-size:44px">🎓</span><small>已登录</small>
            </div>
            <img v-else-if="qrcode" :src="qrcode" alt="登录二维码" style="width:150px" />
            <span v-else class="hint" style="color:var(--c-muted)">待扫码</span>
          </div>
          <div style="margin-top:6px">{{ verdict==='alive' ? `● 已登录${verdict?'':''}` : '○ 未登录/失效' }}</div>
        </div>
        <div style="flex:1; min-width:260px">
          <p class="hint">{{ loginHint || '点击「扫码登录」开始（只扫码，无账密路径）' }}</p>
          <p>
            <button class="btn primary" :disabled="verdict==='alive'" @click="startScan">📷 扫码登录（QR）</button>
            <button class="btn" style="margin-left:8px" @click="refreshStatus">🔄 刷新体检</button>
          </p>
          <p class="hint" style="color:var(--c-muted)">
            体检=三信号判活+storage 回写续期（§11）；
            dead 时头像位退回二维码态。
          </p>
        </div>
      </div>
    </div>

    <!-- §24 通知查看卡（只读；数据=最新 run notices[]） -->
    <div class="card" v-if="noticeRows.length">
      <h3>通知 <small style="font-weight:400;color:var(--c-muted)">最新 run 抓取的各班通知（只读；{{ noticeRows.length }} 条）</small></h3>
      <p>
        <label class="field">班级：
          <select v-model="noticeClsFilter" style="width:200px">
            <option value="">全部（{{ noticeClasses.length }} 班有通知）</option>
            <option v-for="cl in noticeClasses" :key="cl.classId" :value="cl.classId">{{ cl.name }}</option>
          </select>
        </label>
      </p>
      <div style="max-height:320px; overflow-y:auto; border:1px solid var(--c-border); border-radius:8px">
        <table style="width:100%; border-collapse:collapse">
          <tbody>
            <tr v-for="(r, i) in noticeRows" :key="i">
              <td style="padding:5px 8px; width:150px">{{ r.cls }}</td>
              <td style="padding:5px 8px">{{ r.title }}</td>
              <td style="padding:5px 8px; width:110px; white-space:nowrap">{{ r.when }}</td>
              <td style="padding:5px 8px; width:90px; white-space:nowrap">
                <span v-if="r.read" :style="r.ratio !== undefined && r.ratio < 0.9 ? 'color:#7a5c00' : ''">已读 {{ r.read }}</span>
                <span v-else class="hint" style="color:var(--c-muted)">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- §23.3 发公告向导卡（占位 disabled；T10 冻结——表单形态预览，无任何提交逻辑） -->
    <div class="card">
      <h3>发公告 <small style="font-weight:400;color:var(--c-muted)">占位（T10 冻结；表单按 §23.3 设计预置，解冻后接引擎写会话）</small>
        <span class="tag" style="background:#fff3cd; color:#7a5c00; padding:2px 8px; border-radius:6px; font-size:12px">🔒 写操作冻结</span></h3>
      <fieldset :disabled="true" style="border:none; opacity:.65">
        <p>
          <label class="field">发布班级（多选，来自已提取班）：
            <select multiple disabled style="width:260px" size="3">
              <option v-for="c in courses" :key="c.courseId" disabled>{{ c.name }}</option>
            </select>
          </label>
        </p>
        <p><label class="field">标题（≤128 字）：
          <input type="text" maxlength="128" disabled placeholder="第X章作业说明（占位）" style="width:320px" />
        </label></p>
        <p><label class="field" style="vertical-align:top">正文：
          <textarea rows="3" disabled placeholder="公告正文（占位；解冻后为富文本/纯文本）" style="width:min(480px,90%); vertical-align:middle"></textarea>
        </label></p>
        <p><label class="btn as-label btn-file" disabled title="占位：选择「输出与交付」生成的作业纸 PDF">附件（作业纸 PDF）选择器…</label>
          <span class="hint" style="margin-left:8px">尚未选择（占位）</span></p>
        <p class="hint">定时发送 / 提醒渠道：占位（缺省关闭，§23.1 侦察对应 .scheduledSend 与四渠道提醒）</p>
        <p>
          <button class="btn" disabled>👁 发送前预览（占位）</button>
          <button class="btn primary" disabled style="margin-left:8px">📢 发布（占位·双确认后启用）</button>
        </p>
      </fieldset>
      <p class="hint" style="color:var(--c-muted)">
        解冻流程（docs/16 §23.2）：教师确认测试班 → 引擎写会话（route 白名单仅公告域+上传 CDN）→
        发送前快照存档 → 二次确认 → 提交；本卡所有控件 disabled，不含任何提交逻辑。
      </p>
    </div>

    <!-- 导航过程展示框（§20.3 方案 A；数据=run steps/shots；页宽横向滚动缩略卡流） -->
    <div class="card" v-if="loadSteps.length">
      <h3>提取过程 <small style="font-weight:400;color:var(--c-muted)">最新 run 的页面导航流（每跳一张缩略图；引擎真会话所拍）</small></h3>
      <div style="display:flex; gap:10px; overflow-x:auto; padding-bottom:6px">
        <div v-for="(st, i) in loadSteps" :key="i"
             style="min-width:190px; border:1px solid var(--c-border); border-radius:8px; overflow:hidden; background:var(--c-surface,#fff)">
          <img v-if="st.shot" :src="shotUrl(st.shot)" :alt="st.action" style="width:190px; height:107px; object-fit:cover; display:block" />
          <div style="padding:6px 8px">
            <div style="font-size:12px"><b>{{ i+1 }}. {{ st.action }}</b></div>
            <div class="hint" style="font-size:11px; color:var(--c-muted); word-break:break-all">
              {{ st.detail || '' }} · {{ st.title || (st.url || '').slice(0, 46) }}<br /><span style="opacity:.7">{{ st.ts }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 列表卡 -->
    <div class="card">
      <h3>读提取结果 <small style="font-weight:400;color:var(--c-muted)">基于最近 run JSON（§19 schema）；点开行看名单</small></h3>
      <p>
        <button class="btn primary" :disabled="loadingRun" @click="refreshRuns">⟳ 刷新/更新列表</button>
        <button class="btn" style="margin-left:8px" @click="restoreRemoved">♻ 从学习通恢复列表（回放最近 run）</button>
        <label class="field" style="margin-left:12px">置顶上限：
          <select v-model.number="pinCap" @change="persistLocal" style="width:80px">
            <option v-for="n in [5,10,15,20]" :key="n" :value="n">{{ n }}</option>
          </select>
        </label>
        <button class="btn" style="margin-left:8px" @click="() => loadRun(curRun || '')" :disabled="!curRun">重载本 run</button>
        <label class="field" style="margin-left:12px">筛选：
          <select v-model="filterMode" style="width:150px">
            <option value="all">全部班级</option>
            <option value="hasWorks">有作业（多→少）</option>
            <option value="empty">确认为 0</option>
            <option value="fail">未提取（失败）</option>
          </select>
        </label>
      </p>
      <p v-if="runMsg" class="hint">{{ runMsg }}</p>
      <p v-if="runs.length" class="hint" style="color:var(--c-muted)">
        可选 run：
        <select v-model="curRun" @change="loadRun(curRun || '')" style="max-width:240px">
          <option v-for="r in runs" :key="r.run_id" :value="r.run_id">
            {{ r.run_id }}（{{ r.works || 0 }} 作业/失败 {{ r.failures || 0 }}）
          </option>
        </select>
      </p>

      <div v-if="grouped.length" style="display:flex; flex-direction:column; gap:16px">
        <div v-for="g in grouped" :key="g.course.courseId" class="course-group">
          <div class="group-head" style="position:sticky; top:0; z-index:5; background:var(--c-bg,#f7f7f9); padding:6px 0; border-bottom:1px solid var(--c-border)">
            <b>{{ g.course.name }}</b>
            <span class="hint" style="margin-left:8px; color:var(--c-muted)">courseId {{ g.course.courseId }} · {{ g.pinnedRows.length + g.normal.length }} 班</span>
          </div>
          <div class="class-scroll" style="max-height:420px; overflow-y:auto; border:1px solid var(--c-border); border-radius:8px">
            <table style="width:100%; border-collapse:collapse">
              <thead>
                <tr style="position:sticky; top:32px; background:var(--c-surface,#fff)">
                  <th style="text-align:left; padding:6px 8px">班级</th>
                  <th style="padding:6px 8px">作业</th>
                  <th style="padding:6px 8px">状态</th>
                  <th style="padding:6px 8px">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="cl in [...g.pinnedRows, ...g.normal]" :key="cl.classId"
                    :style="isPinned(cl) ? 'background:var(--c-pin-bg,#fffbe8)' : ''">
                  <td style="padding:6px 8px">
                    {{ cl.name }}{{ isPinned(cl) ? ' 📌' : '' }}
                  </td>
                  <td style="padding:6px 8px; text-align:center">
                    <span v-if="!cl.works.length">–</span>
                    <details v-else>
                      <summary>{{ cl.works.length }} 份</summary>
                      <table style="border-collapse:collapse; margin-top:4px">
                        <tbody>
                          <tr v-for="w in cl.works" :key="w.workId">
                            <td style="padding:2px 6px">{{ w.name }}</td>
                            <td style="padding:2px 6px">{{ w.pending ?? '-' }}/{{ w.submitted ?? '-' }}/{{ w.unsubmitted ?? '-' }}</td>
                            <td style="padding:2px 6px">
                              <span v-if="w.anchor?.roster_delta != null && Math.abs(w.anchor?.roster_delta||0) > 2" class="hint" style="color:#7a5c00">
                                差值{{ w.anchor?.roster_delta }}（含发布人/未入班，灰注）
                              </span>
                            </td>
                          </tr>
                        </tbody>
                      </table>
                      <div style="margin-top:6px">
                        <details>
                          <summary class="hint">未交名单 / 白名单（仅本机教师端可见）</summary>
                          <div v-for="w in cl.works" :key="'n'+w.workId" style="margin:4px 0; font-size:12px">
                            <b>{{ w.name }}</b>：
                            <span>未交（{{ (w.unsubmitted_names || []).length }}）：</span>
                            <span style="word-break:break-all">{{ (w.unsubmitted_names || []).join('、') || '（无差集或本班无名册基准）' }}</span>
                            <span v-if="(w.sub_not_in_roster || []).length "> ｜ 提交但不在名册（白名单）：</span>
                            <span v-if="(w.sub_not_in_roster || []).length" style="word-break:break-all">{{ (w.sub_not_in_roster || []).join('、') }}</span>
                          </div>
                        </details>
                      </div>
                    </details>
                  </td>
                  <td style="padding:6px 8px; text-align:center">
                    {{ cl.status === 'extracted' ? '✅' : (cl.status === 'empty_confirmed' ? '∅0' : '⚠ 未提取') }}
                  </td>
                  <td style="padding:6px 8px; text-align:center; white-space:nowrap">
                    <button class="btn" @click="togglePin(cl)">{{ isPinned(cl) ? '取消置顶' : '📌 置顶' }}</button>
                    <button class="btn" style="margin-left:4px" @click="removeRow(cl)">✕ 移出</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <p v-else class="hint" style="color:var(--c-muted)">
        暂无列表数据：引擎侧先运行 <code>assist xxt extract --targets …</code> 或在 .scratch 放置 run JSON。
      </p>
    </div>
  </section>
</template>

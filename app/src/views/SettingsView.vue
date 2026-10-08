<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useSettingsStore } from '../stores/settings'
import { pickDirectory, detectCapabilities, fsWriteHint, downloadData } from '../lib/fsAccess'
import { getKbDirHandle } from '../stores/kb'
import { statusGlyph } from '../lib/engineClient'

const settings = useSettingsStore()
const caps = detectCapabilities()

/** 向导（docs/05-D13 首次运行向导）：三步 —— 选/建 workspace（含 kb 预检）→
 *  环境体检（assist serve /doctor 真接入）→ 完成。每步可"上一步"、
 *  步骤指示器可点回；完成/跳过写入 localStorage
 *  （assignment-assistant.onboarding.v1），重开不再弹。 */
const wizardStep = ref<1 | 2 | 3>(1)

function goStep(s: 1 | 2 | 3) {
  // 指示器可点回：只能回到已走过的步骤（不跳过未到达的步骤）
  if (s <= wizardStep.value || s === 1) wizardStep.value = s
}
function prevStep() {
  if (wizardStep.value > 1) wizardStep.value = (wizardStep.value - 1) as 1 | 2
}

const copyHint = ref('')

const checkDone = computed(() => settings.checkRunAt !== '')
const doctorOnline = computed(() => settings.engineOnline)

/* ---------- workspace 步骤：kb 目录存在性预检（纯前端文案） ---------- */
const kbPrecheck = ref<'unknown' | 'exists' | 'missing' | 'noaccess'>('unknown')
const wsPathInput = ref('')

async function precheckKb() {
  const p = wsPathInput.value.trim()
  if (!p) { kbPrecheck.value = 'unknown'; return }
  // File System Access API 仅安全上下文可用；这里只做提示性预检（不真正写盘）。
  // 沙箱外浏览器无法逐级探测任意路径 —— 用目录 picker 时才真正可知。
  if (settings.workspaceConnected && caps.directoryPicker) {
    kbPrecheck.value = 'exists' // 已通过目录句柄连接：将复用
    return
  }
  kbPrecheck.value = 'noaccess'
}

async function chooseWorkspace() {
  if (caps.directoryPicker) {
    const dir = await pickDirectory()
    if (dir) {
      settings.setWorkspace(dir.name, true)
      // D55/H1 根因①修复：设置中心选目录必须同时连接句柄（此前只存名字，导致 KaTeX/写回永远"未连接"）
      const { connectKbDir } = await import('../stores/kb')
      await connectKbDir(dir)
      wsPathInput.value = dir.name
      kbPrecheck.value = 'exists'
    }
    return
  }
  settings.setWorkspace('（未选，浏览器不支持目录选择，降级为说明）', false)
}

const kbPrecheckText = computed(() => {
  switch (kbPrecheck.value) {
    case 'exists': return '已连接/已有 kb 目录：执行 bootstrap 时将复用现有题库（不覆盖）。'
    case 'missing': return '未发现 kb 目录：bootstrap 将新建 workspace 骨架（kb/ classes/ exports/）。'
    case 'noaccess': return '纯网页无法探测本机任意路径：引擎 bootstrap 会自动判断——kb 存在则复用，不存在则新建（体检第 5 项也会显示）。'
    default: return '填写路径或选择目录后给出预检文案。'
  }
})

async function copyText(text: string, label: string) {
  try {
    await navigator.clipboard.writeText(text)
    copyHint.value = `已复制${label}`
  } catch {
    copyHint.value = `复制失败，请手动选择文本：${text}`
  }
  setTimeout(() => { copyHint.value = '' }, 3000)
}

const INSTALL_SH = 'bash install.sh        # Linux / macOS（或 curl -fsSL ... | bash，阶段5 Releases）'
const INSTALL_PS1 = 'powershell -ExecutionPolicy Bypass -File install.ps1   # Windows（含国内镜像源，docs/05-D10）'
const SERVE_CMD = 'uv run assist serve      # 引擎在线后本页自动识别（默认 http://127.0.0.1:8601）'

/* ---------- 体检真接入（阶段4a） ---------- */
const checking = ref(false)

async function runDoctorNow() {
  checking.value = true
  try {
    const online = await settings.runHealthCheck()
    statusHint.value = online
      ? `体检完成（assist-engine ${settings.engineVersion || ''}，workspace=${settings.doctorWorkspace || '未定位'}）。`
      : '引擎未在线——在本机运行 assist serve 后重试。'
  } finally {
    checking.value = false
  }
}

const statusHint = ref('')

/* ---------- KaTeX 自托管资源自检（D43-3：同源 ./katex/ 应可用） ---------- */
const katexChecking = ref(false)
const katexInstalling = ref(false)
const dirHandleConnected = ref(false)
const dirName = ref('')

/** D56-J5：刷新 workspace 句柄状态（会话内 + IndexedDB 恢复）。 */
async function refreshWorkspaceState() {
  try {
    const { restoreKbDir, getKbDirHandle } = await import('../stores/kb')
    await restoreKbDir()
    const h = getKbDirHandle()
    dirHandleConnected.value = !!h
    dirName.value = h?.name ?? ''
  } catch { dirHandleConnected.value = false }
}

/** D53-G3：安装 KaTeX 离线包到 workspace（sheets/katex/**，~608KB，幂等覆盖）。
 *  FSA 可用=递归 writeFileInDir；不可用=打包 zip 浏览器下载 + 解压位置指引。 */
async function installKatexToWorkspace() {
  katexInstalling.value = true
  try {
    // D56-J5：决策前先刷新句柄状态并 ping 引擎（引擎晚启动时不至于误走 zip 兜底）
    await refreshWorkspaceState()
    await settings.pingEngine()
    const { collectKatexFiles } = await import('../lib/sheetHtml')
    const files = await collectKatexFiles()
    // ① 已连接 workspace 句柄（会话内或 IDB 恢复）→ 直接写盘（零解压）
    let dir = getKbDirHandleSafe()
    // ② 未连接但支持目录选择 → 弹一次选择目录 → 连接（持久化）→ 直接写盘（零解压）
    if (!dir && caps.directoryPicker) {
      const picked = await pickDirectory()
      if (picked) {
        const { connectKbDir } = await import('../stores/kb')
        await connectKbDir(picked)
        dir = picked
      }
    }
    if (dir) {
      const { writeFileInDir } = await import('../lib/fsAccess')
      for (const f of files) await writeFileInDir(dir, `sheets/katex/${f.relPath}`, f.blob)
      dirHandleConnected.value = true
      dirName.value = dir?.name ?? dirName.value
      katexStatus.value = `✅ 已直装 ${files.length} 个文件 → <workspace>/sheets/katex/（目录句柄已记住，刷新后仍连接；重复点击=更新）。引擎 CLI 加 --katex local 即离线渲染。`
      return
    }
    // ③ 浏览器不能写盘（Firefox/Safari）但引擎在线 → 引擎服务端直装（零解压、零句柄）
    if (settings.engineOnline) {
      const ok = await settings.runInstall('katex')
      katexStatus.value = ok
        ? `✅ 已由引擎直装到 <workspace>/sheets/katex/（服务端写盘）。引擎日志见安装输出。`
        : `⚠ 引擎直装失败：${settings.installLog.slice(-200) || '见设置中心安装输出'}`
      return
    }
    // ④ 兜底：zip 下载（LAN http / 无引擎 / 无 FSA 的最后一档）
    const JSZip = (await import('jszip')).default
    const zip = new JSZip()
    for (const f of files) zip.file(`katex/${f.relPath}`, f.blob)
    const blob = await zip.generateAsync({ type: 'blob' })
    downloadData(blob, 'katex-offline.zip')
    katexStatus.value = `⚠ 当前无法直装（无目录句柄、无引擎）：已下载 katex-offline.zip——解压到 <workspace>/sheets/ 下（得到 sheets/katex/…）。`
  } catch (e) {
    katexStatus.value = `⚠ 安装失败：${(e as Error).message}`
  } finally {
    katexInstalling.value = false
  }
}
function getKbDirHandleSafe(): FileSystemDirectoryHandle | null {
  try { return getKbDirHandle() ?? null } catch { return null }
}
const katexStatus = ref('尚未检查（预览一般无需检查；资源已随应用打包）')

/* ---------- D58：TinyTeX 可选依赖（设置中心专用栏：检测 + 网络安装） ---------- */
const tinytexChecking = ref(false)
const tinytexInstalling = ref(false)
const tinytexStatus = ref('尚未检测（可选依赖；缺失时 LaTeX 样题自动降级，不影响 HTML/PDF 主通道）')
const tinytexCheck = computed(() => settings.checks.find((c) => c.key === 'tex'))

async function checkTinyTex() {
  tinytexChecking.value = true
  try {
    await settings.pingEngine()
    if (!settings.engineOnline) {
      tinytexStatus.value = '⚠ 引擎未在线——无法检测本机 TeX。请先启动 assist serve，或用 CLI：assist tex status'
      return
    }
    await settings.runDoctor()
    const c = tinytexCheck.value
    if (!c) {
      tinytexStatus.value = '⚠ 体检未返回 TeX 项（引擎版本可能较旧）'
      return
    }
    tinytexStatus.value = `${statusGlyph(c.status)} ${c.note || '未返回详情'}`
  } catch (e) {
    tinytexStatus.value = `⚠ 检测失败：${(e as Error).message}`
  } finally {
    tinytexChecking.value = false
  }
}

async function installTinyTex() {
  tinytexInstalling.value = true
  try {
    await settings.pingEngine()
    if (!settings.engineOnline) {
      tinytexStatus.value = '⚠ 需要引擎在线（assist serve）才能写盘安装；也可在终端运行：assist tex install'
      return
    }
    tinytexStatus.value = '⏳ 正在从网络下载 TinyTeX 并解压到 <workspace>/.runtime/tex（体积较大，请耐心等待）…'
    const ok = await settings.runInstall('tinytex')
    const c = tinytexCheck.value
    if (ok && c?.status === 'ok') {
      tinytexStatus.value = `✅ ${c.note || 'xelatex 已可用'}`
    } else {
      tinytexStatus.value = `⚠ 未检测到可用 xelatex；安装输出末尾：${settings.installLog.slice(-240) || '（空）'}`
    }
  } catch (e) {
    tinytexStatus.value = `⚠ 安装失败：${(e as Error).message}`
  } finally {
    tinytexInstalling.value = false
  }
}

async function checkKatex() {
  katexChecking.value = true
  try {
    const base = new URL('./katex/katex.min.js', document.baseURI).href
    const res = await fetch(base)
    katexStatus.value = res.ok
      ? `✅ 同源 KaTeX 资源可用（${base}，HTTP ${res.status}）——预览/打印/下载均离线渲染公式。`
      : `⚠ 资源不可达（HTTP ${res.status}）：${base} —— 重新部署 Pages 或经引擎同源 serve 打开本页即可恢复。`
  } catch (e) {
    katexStatus.value = `⚠ 检查失败：${(e as Error).message}`
  } finally {
    katexChecking.value = false
  }
}

onMounted(() => {
  // D56-J5：恢复并显示 workspace 句柄状态
  void refreshWorkspaceState()
  // 进页即做 /status 在线检测（chip + 版本显示），不弹错误
  void settings.pingEngine()
  wsPathInput.value = settings.workspaceLabel
  void precheckKb()
})
</script>

<template>
  <section>
    <!-- 首次运行向导：仅当未完成时展示（完成/跳过后重开不再弹） -->
    <div v-if="settings.needsSetup" class="card">
      <h2>首次运行向导（Onboarding）</h2>
      <p class="hint">
        三步：① 选/建 workspace → ② 环境体检 → ③ 完成。可随时跳过；
        跳过或未完成不会整体置灰界面（docs/05-D13），仅引擎依赖功能灰。
      </p>
      <div class="wizard-steps">
        <button class="wizard-step-pill as-btn" :class="{ active: wizardStep === 1, done: wizardStep > 1 }" @click="goStep(1)">① workspace</button>
        <button class="wizard-step-pill as-btn" :class="{ active: wizardStep === 2, done: wizardStep > 2 }" @click="goStep(2)" :disabled="wizardStep < 2">② 环境体检</button>
        <button class="wizard-step-pill as-btn" :class="{ active: wizardStep === 3 }" @click="goStep(3)" :disabled="wizardStep < 3">③ 完成</button>
      </div>

      <!-- 第 1 步：workspace 选/建（说明为主，真正建目录由引擎/安装脚本完成） -->
      <div v-if="wizardStep === 1">
        <p class="hint">
          workspace = 教师管理根目录（多学期多班级长期使用，docs/04 §1）。目录约定:
          <code>kb/</code> 题库在根目录，<code>classes/&lt;学期批号&gt;-&lt;课程简称&gt;-&lt;班级名&gt;/</code>
          为各班目录，<code>.runtime/</code> 是引擎环境（永不打包），<code>settings.local.json</code> 存 apikey 等（不入库）。
        </p>
        <p class="hint">
          两个入口：<b>本机装好引擎</b> 后（阶段4 assist serve 接管），引擎会自动定位/创建 workspace；
          <b>或现在</b>在浏览器里选择未来的 workspace 目录（Chrome/Edge），导入导出时会把
          kb xlsx / 作业纸写进去。
        </p>
        <label class="field">workspace 路径：
          <input type="text" v-model="wsPathInput" style="width: 340px" placeholder="如 ~/.assignment-assistant（默认）" @change="precheckKb(); settings.setWorkspace(wsPathInput, settings.workspaceConnected)" />
        </label>
        <p>
          <button class="btn" :disabled="!caps.directoryPicker" @click="chooseWorkspace"
            :title="caps.insecure ? fsWriteHint() : '需 Chrome/Edge（File System Access API）'">
            {{ caps.directoryPicker ? '选择 workspace 目录…' : (caps.insecure ? '选择 workspace 目录…（LAN 预览下不可用，需本机打开）' : '浏览器不支持目录选择（Firefox/Safari）') }}
          </button>
          <button class="btn" style="margin-left:8px" @click="precheckKb">kb 目录预检</button>
        </p>
        <p class="hint">当前：{{ settings.workspaceConnected ? `已选目录 ${settings.workspaceLabel}` : '未连接（可选，可跳过）' }}</p>
        <p class="hint" :class="{ 'kb-precheck-ok': kbPrecheck === 'exists' }">
          kb 预检：{{ kbPrecheckText }}
        </p>
        <p>
          <button class="btn" @click="wizardStep = 2">
            {{ settings.workspaceConnected || settings.workspaceLabel ? '下一步 →' : '继续（稍后再选）→' }}
          </button>
          <button class="btn" style="margin-left:8px" :disabled="wizardStep <= 1" @click="prevStep">← 上一步</button>
        </p>
      </div>

      <!-- 第 2 步：环境体检（assist serve /doctor 真接入；未在线 → 黄色占位 + 引导） -->
      <div v-else-if="wizardStep === 2">
        <p class="hint">
          体检经 <code>{{ settings.engineUrl }}/doctor</code> 真实检测（逐项绿黄红 ✓/!/✗，
          与 CLI <code>assist doctor</code> 检查项同口径：uv/依赖/字体/TeX(可选黄)/kb/settings.local.json）。
        </p>
        <p>
          <button class="btn primary" :disabled="checking" @click="runDoctorNow">
            {{ checking ? '体检中…' : '运行环境体检' }}
          </button>
          <button class="btn" :disabled="!caps.directoryPicker" style="margin-left:8px" @click="chooseWorkspace">
            重新选择 workspace…
          </button>
          <button class="btn" style="margin-left:8px" :disabled="wizardStep <= 1" @click="prevStep">← 上一步</button>
        </p>
        <!-- 在线 chip：/status 在线检测 -->
        <p class="hint" style="margin-bottom:4px">
          引擎状态：
          <span class="engine-chip" :class="doctorOnline ? 'on' : 'off'">
            <span class="engine-chip-dot"></span>{{ doctorOnline ? '在线' : '离线' }}<template v-if="doctorOnline && settings.engineVersion"> · v{{ settings.engineVersion }}</template>
          </span>
          <button class="btn small clip-btn" style="margin-left:8px" @click="settings.pingEngine(); statusHint = ''">重新检测</button>
        </p>
        <div class="notice" v-if="!doctorOnline">
          <b>引擎未在线——在本机运行 assist serve 后重试。</b>
          下方为黄色占位状态（降级观感，docs/05-D13）；也可先复制安装命令在教师机终端执行：
          <ul style="margin:6px 0 0">
            <li>Linux/macOS：<code>{{ INSTALL_SH }}</code>
              <button class="btn small clip-btn" @click="copyText(INSTALL_SH, 'install.sh 命令')">复制命令</button></li>
            <li>Windows（PowerShell）：<code>{{ INSTALL_PS1 }}</code>
              <button class="btn small clip-btn" @click="copyText(INSTALL_PS1, 'install.ps1 命令')">复制命令</button></li>
            <li>装好后启动引擎：<code>{{ SERVE_CMD }}</code>
              <button class="btn small clip-btn" @click="copyText(SERVE_CMD, 'assist serve 命令')">复制命令</button></li>
          </ul>
        </div>
        <ul class="check-list">
          <li v-for="c in settings.checks" :key="c.key" :class="`status-${c.status}`">
            <span class="status-dot"></span>
            <b>{{ statusGlyph(c.status) }} {{ c.label }}</b> — {{ c.note }}
          </li>
        </ul>
        <p class="hint" v-if="statusHint">{{ statusHint }}</p>
        <p class="hint" v-if="copyHint">{{ copyHint }}</p>
        <div class="notice" v-if="!caps.full && caps.browserHint">
          {{ caps.browserHint }}
        </div>
        <p>
          <button class="btn" :disabled="!checkDone" @click="wizardStep = 3">下一步 →</button>
          <button class="btn" style="margin-left:8px" :disabled="wizardStep <= 1" @click="prevStep">← 上一步</button>
        </p>
      </div>

      <!-- 第 3 步：完成 -->
      <div v-else>
        <p class="hint">
          向导到此为止。后续可在设置中心继续填写引擎地址、apikey（仅存本浏览器）等。
          引擎未就绪前，引擎依赖按钮保持置灰并显示黄色横幅 —— 不影响题库编辑、作业纸设计等静态功能。
        </p>
        <p>
          <button class="btn primary" @click="settings.finishWizard(); wizardStep = 1">完成设定</button>
          <button class="btn" style="margin-left:8px" @click="settings.skipWizard(); wizardStep = 1">跳过，稍后再说</button>
          <button class="btn" style="margin-left:8px" @click="prevStep">← 上一步</button>
        </p>
      </div>
    </div>

    <!-- 常规设置中心 -->
    <div class="card">
      <h2>引擎地址 / 凭据 <span class="engine-chip" :class="settings.engineOnline ? 'on' : 'off'" style="margin-left:8px"><span class="engine-chip-dot"></span>{{ settings.engineOnline ? '在线' : '离线' }}<template v-if="settings.engineOnline && settings.engineVersion"> · v{{ settings.engineVersion }}</template></span></h2>
      <p class="hint">
        引擎（程序）与 workspace（数据）分离（docs/05-D13/D14）。引擎地址存于本浏览器 localStorage，
        与 workspace 落盘的 <code>settings.local.json</code> 的 <code>engine_addr</code> 同名对应（默认
        http://127.0.0.1:8601，PWA 内可改）；apikey 等真正落盘仍由引擎侧管理（阶段4）。
      </p>
      <div class="kv-list">
        <dt>引擎地址</dt>
        <dd>
          <label class="field">
            <input type="text" v-model="settings.engineUrl" style="width:260px" @change="settings.setEngineUrl(settings.engineUrl)" />
            <label class="field" style="margin-left:10px">引擎令牌 token（--lan 模式）：
              <input type="text" v-model="settings.engineToken" @change="settings.engineToken = settings.engineToken.trim()" style="width:160px" placeholder="仅 --lan 部署需填" />
            </label>
          </label>
          <button class="btn small" @click="void settings.pingEngine()">检测在线（/status）</button>
        </dd>
        <dt>LLM apikey</dt>
        <dd>
          <label class="field">
            <input type="password" v-model="settings.engineApiKey" placeholder="仅存本浏览器；调 LLM 建议由引擎代理（docs/02 §5）" style="width:320px" @change="settings.persist()" />
          </label>
        </dd>
        <dt>默认班级目录</dt>
        <dd>
          <label class="field"><input type="text" v-model="settings.defaultClassDir" style="width:320px" @change="settings.persist()" /></label>
        </dd>
        <dt>上传前预览确认</dt>
        <dd>
          <label class="field">
            <input type="checkbox" v-model="settings.confirmBeforeUpload" @change="settings.persist()" />
            可选步骤（docs/05-D7）
          </label>
        </dd>
      </div>

      <h3>一键启动 / 安装（R1.2：教师双击脚本即得 Companion 模式）</h3>
      <p class="hint">
        已是<b>两种路径</b>：① 教师 **下载一键脚本、双击运行**（自动装 uv→建 workspace/.runtime venv→装依赖→起引擎→自动开浏览器，D14 收纳）；② 已装引擎的机器上用下方体检页——红/黄项旁点 🔧修复（走 /install）。
      </p>
      <p>
        <a class="btn primary" href="start.bat" download>⬇ Windows 一键启动 start.bat</a>
        <a class="btn" style="margin-left:8px" href="start.sh" download>⬇ macOS / Linux 一键启动 start.sh</a>
      </p>
      <p class="hint">
        **workspace = start 脚本所在目录**（docs/05-D28）：把下载的 start.bat 移到你常用的资料目录，双击它 = 该目录就是整个 workspace，uv/Python/venv/缓存/日志/一切产物全部收纳在其中的 `.runtime/`（删除目录=整体卸载）；<br/>Windows 双击 `start.bat`：<b>窗口全英文提示是设计取舍——cmd 解析器对 UTF-8 中文注释存在解析歧义</b>（v3/v4 闪退根因，docs/05-D25/D27）；macOS/Linux：`bash start.sh`。<br/>网页（http://127.0.0.1:8601）随脚本顺次打开，体检/【🔧修复】按钮/批阅/学习通占位全可用。<br/>如报错：窗口会停住显示英文提示行；`workspace/start.log`（bat 旁边）有全程记录——把尾部几行发我即可。**：出错窗口会写 `workspace/start.log`（bat 与它所在目录并列），可发我尾部内容。<br />
        模式：本机打开 <code>http://127.0.0.1:8601/</code>（引擎与 PWA 同源，环境体检/修复按钮/批阅均可用）。
      </p>

          <hr />
    <h3>环境体检（assist serve /doctor）</h3>
      <p>
        <button class="btn primary" :disabled="checking" @click="runDoctorNow">{{ checking ? '体检中…' : '体检' }}</button>
        <span class="hint" style="margin-left:8px">{{ statusHint }}</span>
      </p>
      <ul class="check-list">
        <li v-for="c in settings.checks" :key="c.key" :class="`status-${c.status}`">
          <span class="status-dot"></span>
          <b>{{ statusGlyph(c.status) }} {{ c.label }}</b> — {{ c.note }}
          <button v-if="c.status !== 'ok' && (c as any).fix?.type === 'install'" class="btn small" style="margin-left:8px"
            :disabled="settings.installing !== ''" @click="settings.runInstall((c as any).fix.install)">
            {{ settings.installing === (c as any).fix.install ? '安装中…' : '🔧 修复' }}
          </button>
        </li>
      </ul>
      <p v-if="settings.installLog" class="hint"><code>安装输出</code>
        <pre style="max-height:160px; overflow:auto; white-space:pre-wrap">{{ settings.installLog }}</pre>
      </p>

    <!-- D63 T7.1：Playwright（学习通只读提取依赖）联网安装卡（镜像优先，见 docs/16 §22.1） -->
    <h3>Playwright（学习通提取 · 只读引导）</h3>
    <p class="hint">
      用途：assist xxt 会话体检/只读提取（学习通选项卡）需要本机安装 playwright 包与 chromium 内核。
      接到引擎后可**一键联网安装**（未随仓库分发任何安装包）。
    </p>
    <p>
      <button class="btn primary" @click="settings.runInstall('playwright')"
              :disabled="settings.installing !== ''">
        {{ settings.installing === 'playwright' ? '安装中…（pypi→tuna、内核→npmmirror）' : '⚡ 联网安装 Playwright（国内镜像）' }}
      </button>
      <span class="hint" style="margin-left:8px">
        装完请点上方「体检」回看 playwright 项（绿=就绪）；已装本机 chrome 时可设 XXT_CHROME 免内核下载。
      </span>
    </p>

      <div class="notice" v-if="!settings.engineOnline">
        引擎未在线——在本机运行 <code>assist serve</code> 后重试。
        <button class="btn small clip-btn" @click="copyText(SERVE_CMD, 'assist serve 命令')">复制命令</button>
        <span v-if="copyHint" style="margin-left:8px">{{ copyHint }}</span>
      </div>
    </div>

    <!-- ============ KaTeX 公式资源（自托管·同源，D43-3） ============ -->
    <div class="card">
      <h2>KaTeX 公式资源 <small style="font-weight:400;color:var(--c-muted)">自托管·同源（./katex/，0.16.4）· 预览公式免安装</small></h2>
      <p class="hint">
        作业纸预览/打印的公式渲染资源<b>已随 PWA 打包</b>（同源 <code>./katex/</code>：css + js + woff2 字体），
        离线也可正确显示，<b>无需下载安装、无需管理环境</b>；「下载 HTML」导出时自动把资源
        内联成自包含文件（file:// 打开同样渲染）。引擎 CLI（<code>assist sheet html</code>）用
        <code>--katex local</code> 时读取本卡安装的 workspace 离线包。
      </p>
      <p class="hint">
        workspace 目录：<b>{{ dirHandleConnected ? '✅ 已连接（可直接写盘，刷新后自动恢复）' : '⚠ 未连接（点安装时会让你选一次目录；若引擎在线也可由引擎服务端直装）' }}</b>
        <span v-if="dirName">（{{ dirName }}）</span>
      </p>
      <p>
        <button class="btn" :disabled="katexChecking" @click="checkKatex">{{ katexChecking ? '检查中…' : '自检 KaTeX 资源' }}</button>
        <button class="btn primary" style="margin-left:8px" :disabled="katexInstalling" @click="installKatexToWorkspace"
          title="D53-G3：把同源 KaTeX 选择集（css/js/auto-render+woff2×20，~608KB）写入 <workspace>/sheets/katex/——引擎 CLI 产物离线渲染配套；重复点击=更新">📦 {{ katexInstalling ? '安装中…' : '直装到 workspace（零解压）' }}</button>
        <span class="hint" style="margin-left:8px">{{ katexStatus }}</span>
      </p>
      <p class="hint">
        「安装到 workspace」= 引擎通道离线化：装完后 <code>assist sheet html --katex local</code>（或本 PWA「下载 HTML」自包含文件，无需此步）
        生成的 sheets/*.html 引用 ../katex/ 相对路径即可断网渲染公式。未连接 workspace 目录时自动降级为下载 katex-offline.zip（解压到 &lt;workspace&gt;/sheets/ 下）。
      </p>
    </div>

    <!-- ============ D58：TinyTeX 可选依赖（专用检测/安装栏，不入仓库） ============ -->
    <div class="card">
      <h2>TinyTeX（LaTeX 渲染，可选） <small style="font-weight:400;color:var(--c-muted)">网络下载安装 · 仓库不含安装包 · workspace 内卸载</small></h2>
      <p class="hint">
        TinyTeX 只用于 LaTeX 样题渲染/精细排版，<b>不是主依赖</b>；缺失时样题自动降级，HTML 主通道与
        reportlab PDF 不受影响。安装包不会放进远程仓库，本卡只负责检测与从
        <code>tinytex-releases</code> 官方 Release <b>联网下载</b>，解压到
        <code>&lt;workspace&gt;/.runtime/tex</code>（删除 workspace 即整体卸载，无需系统 PATH）。
      </p>
      <p class="hint">
        引擎未在线时无法写盘检测/安装；CLI 备份入口：<code>assist tex status</code> /
        <code>assist tex install</code>。
      </p>
      <p>
        <button class="btn" :disabled="tinytexChecking" @click="checkTinyTex">{{ tinytexChecking ? '检测中…' : '检测 TeX / xelatex' }}</button>
        <button class="btn primary" style="margin-left:8px" :disabled="tinytexInstalling" @click="installTinyTex"
          title="从 tinytex-releases 官方 Release 网络下载并解压到 workspace/.runtime/tex；不入仓库；重复点击可修复/重装">📦 {{ tinytexInstalling ? '安装中…' : '联网安装 TinyTeX' }}</button>
        <span class="hint" style="margin-left:8px">{{ tinytexStatus }}</span>
      </p>
      <p class="hint" v-if="tinytexCheck"><b>当前体检项：</b>{{ tinytexCheck.note || '—' }}</p>
      <p class="hint" v-if="tinytexInstalling && settings.installLog"><code>安装输出（末尾）</code></p>
      <pre v-if="tinytexInstalling && settings.installLog" style="max-height:180px; overflow:auto; white-space:pre-wrap">{{ settings.installLog.slice(-1200) }}</pre>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useSettingsStore } from '../stores/settings'
import { pickDirectory, detectCapabilities, fsWriteHint } from '../lib/fsAccess'
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

onMounted(() => {
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
          kb xlsx / 任务包写进去。
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

      <h3>环境体检（assist serve /doctor）</h3>
      <p>
        <button class="btn primary" :disabled="checking" @click="runDoctorNow">{{ checking ? '体检中…' : '体检' }}</button>
        <span class="hint" style="margin-left:8px">{{ statusHint }}</span>
      </p>
      <ul class="check-list">
        <li v-for="c in settings.checks" :key="c.key" :class="`status-${c.status}`">
          <span class="status-dot"></span>
          <b>{{ statusGlyph(c.status) }} {{ c.label }}</b> — {{ c.note }}
        </li>
      </ul>
      <div class="notice" v-if="!settings.engineOnline">
        引擎未在线——在本机运行 <code>assist serve</code> 后重试。
        <button class="btn small clip-btn" @click="copyText(SERVE_CMD, 'assist serve 命令')">复制命令</button>
        <span v-if="copyHint" style="margin-left:8px">{{ copyHint }}</span>
      </div>
    </div>
  </section>
</template>

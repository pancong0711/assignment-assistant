<script setup lang="ts">
import { computed, ref } from 'vue'
import { useSettingsStore } from '../stores/settings'
import { pickDirectory, detectCapabilities, fsWriteHint } from '../lib/fsAccess'

const settings = useSettingsStore()
const caps = detectCapabilities()

/** 向导（docs/05-D13 首次运行向导雏形）：三步 —— 选/建 workspace 说明 → 环境体检 → 完成 */
const wizardStep = ref<1 | 2 | 3>(1)

const copyHint = ref('')

const checkDone = computed(() => settings.checkRunAt !== '')

async function chooseWorkspace() {
  if (caps.directoryPicker) {
    const dir = await pickDirectory()
    if (dir) {
      settings.setWorkspace(dir.name, true)
    }
    return
  }
  settings.setWorkspace('（未选，浏览器不支持目录选择，降级为说明）', false)
}

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
const SERVE_CMD = 'uv run assist serve      # 阶段4 提供本地 HTTP API + SSE 日志，端口与引擎地址见文档 05-D2'
</script>

<template>
  <section>
    <!-- 首次运行向导：仅当未完成时展示 -->
    <div v-if="settings.needsSetup" class="card">
      <h2>首次运行向导（Onboarding雏形）</h2>
      <p class="hint">
        三步：① 选/建 workspace → ② 环境体检 → ③ 完成。可随时跳过；
        跳过或未完成不会整体置灰界面（docs/05-D13），仅引擎依赖功能灰。
      </p>
      <div class="wizard-steps">
        <span class="wizard-step-pill" :class="{ active: wizardStep === 1, done: wizardStep > 1 }">① workspace</span>
        <span class="wizard-step-pill" :class="{ active: wizardStep === 2, done: wizardStep > 2 }">② 环境体检</span>
        <span class="wizard-step-pill" :class="{ active: wizardStep === 3 }">③ 完成</span>
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
        <label class="field">workspace 名称 / 路径（示例）：
          <input type="text" v-model="settings.workspaceLabel" style="width: 340px" placeholder="如 ~/.assignment-assistant（默认）" @change="settings.persist()" />
        </label>
        <p>
          <button class="btn" :disabled="!caps.directoryPicker" @click="chooseWorkspace"
            :title="caps.insecure ? fsWriteHint() : '需 Chrome/Edge（File System Access API）'">
            {{ caps.directoryPicker ? '选择 workspace 目录…' : (caps.insecure ? '选择 workspace 目录…（LAN 预览下不可用，需本机打开）' : '浏览器不支持目录选择（Firefox/Safari）') }}
          </button>
        </p>
        <p class="hint">当前：{{ settings.workspaceConnected ? `已选目录 ${settings.workspaceLabel}` : '未连接（可选，可跳过）' }}</p>
      </div>

      <!-- 第 2 步：环境体检（当前为占位说明 + 引导文案 + 复制命令） -->
      <div v-else-if="wizardStep === 2">
        <p class="hint">
          体检目前是<b>占位状态</b>：纯静态部署无法直接探测本机执行环境，阶段4 将接入
          <code>assist serve</code> 本地体检接口（逐项绿黄红 + 复制命令，docs/05-D5）。
          现在可先复制安装命令，在教师机终端里执行后再回来。
        </p>
        <p>
          <button class="btn primary" @click="settings.runHealthCheck()">运行环境体检（占位）</button>
          <button class="btn" :disabled="!caps.directoryPicker" style="margin-left:8px" @click="chooseWorkspace">
            重新选择 workspace…
          </button>
        </p>
        <ul class="check-list">
          <li v-for="c in settings.checks" :key="c.key" class="status-warn" :class="`status-${c.status}`">
            <span class="status-dot"></span>
            <b>{{ c.label }}</b> — {{ c.note }}
          </li>
        </ul>
        <div class="notice" v-if="!caps.full && caps.browserHint">
          {{ caps.browserHint }}
        </div>
        <div class="notice">
          若体检显示 <b>需装引擎</b>（当前默认占位提示），在教师机终端执行：
          <ul style="margin:6px 0 0">
            <li>Linux/macOS：<code>{{ INSTALL_SH }}</code>
              <button class="btn small clip-btn" @click="copyText(INSTALL_SH, 'install.sh 命令')">复制命令</button></li>
            <li>Windows（PowerShell）：<code>{{ INSTALL_PS1 }}</code>
              <button class="btn small clip-btn" @click="copyText(INSTALL_PS1, 'install.ps1 命令')">复制命令</button></li>
            <li>装好后启动引擎（阶段4 起 PWA 自动识别）：<code>{{ SERVE_CMD }}</code>
              <button class="btn small clip-btn" @click="copyText(SERVE_CMD, 'assist serve 命令')">复制命令</button></li>
          </ul>
        </div>
        <p class="hint" v-if="copyHint">{{ copyHint }}</p>
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
        </p>
      </div>

        <p>
          <button v-if="wizardStep === 1" class="btn" @click="wizardStep = 2">
            {{ settings.workspaceConnected || settings.workspaceLabel ? '下一步 →' : '继续（稍后再选）→' }}
          </button>
          <button v-else-if="wizardStep === 2" class="btn" :disabled="!checkDone" @click="wizardStep = 3">下一步 →</button>
        </p>
    </div>

    <!-- 常规设置中心 -->
    <div class="card">
      <h2>引擎地址 / 凭据</h2>
      <p class="hint">
        引擎（程序）与 workspace（数据）分离（docs/05-D13/D14）。这些值只保存在本浏览器 localStorage；
        引擎真正落盘的 <code>settings.local.json</code> 由引擎侧管理（阶段4），这里仅是前端镜像配置。
      </p>
      <div class="kv-list">
        <dt>引擎地址</dt>
        <dd>
          <label class="field"><input type="text" v-model="settings.engineUrl" style="width:260px" @change="settings.persist()" /></label>
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
    </div>
  </section>
</template>

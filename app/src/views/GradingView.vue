<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useSettingsStore } from '../stores/settings'
import { parseTaskpad, type Taskpad } from '../lib/taskpad'

/** 批阅工作台（阶段4a 静态可用版，docs/05-D2/D13）。
 *  职责：选任务包 + 选本地学生图片 → 显示每个学生分组的 转录/评阅/报告 占位。
 *  API 联调（serve 触发）在后续阶段接入；当前以"用 CLI 跑"的指引为主：
 *  assist grade --task <json> --images <dir>（复制按钮）。
 *  输入目录仅列出选中文件，不做任何上传（数据全程本地）。
 *  D13：引擎未在线时联调按钮灰 + 文案引导去体检页。 */

const settings = useSettingsStore()
const status = ref('')

/* ---------- 任务包选择 ---------- */
const parsed = ref<Taskpad | null>(null)
const padError = ref('')
const padFileName = ref('')

async function onPadFile(e: Event) {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0]
  if (!f) return
  padFileName.value = f.name
  try {
    parsed.value = parseTaskpad(JSON.parse(await f.text()))
    padError.value = ''
    status.value = `已载入任务包 ${parsed.value.id}（${parsed.value.items.length} 组选题）。`
  } catch (err) {
    parsed.value = null
    padError.value = (err as Error).message
    status.value = `任务包解析失败：${padError.value}`
  }
}

/* ---------- 学生图片（本地多选，仅列出，不上传） ---------- */
interface ImgEntry { name: string; size: number; student: string }
const images = ref<ImgEntry[]>([])

function guessStudent(name: string): string {
  // 约定（engine grade 同口径）：文件名=学生名 或 学号-题号 → 取前缀作为学生分组键
  const base = name.replace(/\.[^.]+$/, '')
  const m = base.match(/^(.+?)[-_－]/)
  return m ? m[1] : base
}

function onImages(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  images.value = files.map((f) => ({ name: f.name, size: f.size, student: guessStudent(f.name) }))
  status.value = images.value.length
    ? `已选择 ${images.value.length} 个图片文件（仅本地列出，不上传）。`
    : ''
}

const groups = computed<Array<{ student: string; files: ImgEntry[] }>>(() => {
  const map = new Map<string, ImgEntry[]>()
  for (const it of images.value) {
    const arr = map.get(it.student) ?? []
    arr.push(it)
    map.set(it.student, arr)
  }
  return [...map.entries()]
    .map(([student, files]) => ({ student, files }))
    .sort((a, b) => a.student.localeCompare(b.student, 'zh-CN'))
})

const GRADE_CMD = computed(() =>
  `assist grade --task <任务包.json> --images <学生图片目录>`)

const padSummary = computed(() => {  if (!parsed.value) return null
  const p = parsed.value
  return {
    id: p.id,
    classDir: p.class_dir || '（空，默认 classes/）',
    items: p.items.length,
    questions: p.items.reduce((n, i) => n + i.ids.length, 0),
    hasGrade: Boolean(p.grade && (p.grade.steps?.length || p.grade.models)),
  }
})

let copyTimer = 0
function copyGradeCmd() {
  void navigator.clipboard?.writeText(GRADE_CMD.value).then(() => {
    status.value = '已复制批阅命令：' + GRADE_CMD.value
    clearTimeout(copyTimer)
    copyTimer = window.setTimeout(() => { if (status.value.startsWith('已复制批阅命令')) status.value = '' }, 4000)
  })
}

onMounted(() => { void settings.pingEngine() })
</script>

<template>
  <section>
    <div class="card">
      <h2>批阅工作台 <small style="font-weight:400;color:var(--c-muted)">任务包 + 学生图片 → 转录 / 评阅 / 报告（阶段4a 静态版）</small></h2>
      <p class="hint">
        三步：① 选任务包 JSON（作业纸设计页导出的 .taskpad.json）→ ② 选本地学生作业图片（可多选）
        → ③ 按学生分组查看 转录/评阅/报告 占位。本页<b>只列出本地文件，不做任何上传</b>；
        真正执行批阅由引擎完成（serve 触发联调在后续阶段接入，当前用 CLI 跑，docs/05-D1 CLI 超集）。
      </p>
      <div class="notice" v-if="!settings.engineOnline">
        引擎未在线——在本机运行 <code>assist serve</code> 后重试；先去
        <a href="#/settings" style="cursor:pointer;text-decoration:underline">设置中心 → 环境体检</a>
        完成体检。批阅执行当前请直接用下方 CLI 命令（复制到教师机终端）。
      </div>
      <div class="notice info" v-else>
        引擎在线（assist-engine {{ settings.engineVersion }}）。阶段4a 本页仍以 CLI 指引为主，serve 触发按钮在 API 联调后启用。
      </div>
    </div>

    <div class="card">
      <h2>① 选择任务包</h2>
      <p>
        <label class="btn as-label" for="grade-pad-file">导入任务包 JSON…</label>
        <input type="file" accept=".json,application/json" hidden id="grade-pad-file" @change="onPadFile" />
        <span class="hint" style="margin-left:8px">{{ padFileName || '尚未选择' }}</span>
      </p>
      <table class="grid" v-if="padSummary" style="max-width:560px">
        <tbody>
          <tr><th style="width:110px">任务包 id</th><td>{{ padSummary.id }}</td></tr>
          <tr><th>班级目录</th><td>{{ padSummary.classDir }}</td></tr>
          <tr><th>选题</th><td>{{ padSummary.items }} 组 / {{ padSummary.questions }} 题</td></tr>
          <tr><th>grade 配置</th><td>{{ padSummary.hasGrade ? '任务包内含 grade 节' : '空（仅出作业纸；批阅参数交给引擎默认值）' }}</td></tr>
        </tbody>
      </table>
      <p class="hint" v-if="padError" style="color:var(--c-danger)">解析失败：{{ padError }}</p>
      <p class="hint" v-else-if="!parsed">任务包 = CLI 完整参数（docs/05-D2/D8）：同一份 JSON 也可直接
        <code>assist sheet make --task &lt;file&gt;</code> 出作业纸 PDF。</p>
    </div>

    <div class="card">
      <h2>② 学生作业图片（本地多选，不上传）</h2>
      <p>
        <label class="btn as-label" for="grade-imgs">选择图片文件…（可多选）</label>
        <input type="file" accept="image/*" multiple hidden id="grade-imgs" @change="onImages" />
        <span class="hint" style="margin-left:8px">{{ images.length ? `已选 ${images.length} 个` : '尚未选择' }}</span>
      </p>
      <p class="hint">
        命名约定（与引擎同口径）：文件名 = 学生名 或 学号-题号（如 <code>学生A-1.jpg</code>），
        自动按前缀分组；也可直接整目录交给 CLI 的 <code>--images &lt;dir&gt;</code>。
      </p>
      <table class="grid" v-if="groups.length" style="max-width:860px">
        <thead>
          <tr><th>学生分组</th><th>文件数</th><th>文件（仅列出本地路径名，不上传）</th></tr>
        </thead>
        <tbody>
          <tr v-for="g in groups" :key="g.student">
            <td>{{ g.student }}</td>
            <td style="text-align:center">{{ g.files.length }}</td>
            <td style="font-size:12px; word-break:break-all">{{ g.files.map((f) => f.name).join('、') }}</td>
          </tr>
        </tbody>
      </table>
      <p class="hint" v-else>尚未选择图片。</p>
    </div>

    <div class="card">
      <h2>③ 转录 / 评阅 / 报告（按学生分组占位）</h2>
      <p class="hint" v-if="!groups.length">选择任务包与图片后，这里按学生分组显示三步产物占位；阶段4a API 联调（serve 触发）后逐步点亮。</p>
      <table class="grid" v-else style="max-width:860px">
        <thead>
          <tr><th>学生</th><th>转录</th><th>评阅</th><th>报告</th></tr>
        </thead>
        <tbody>
          <tr v-for="g in groups" :key="g.student">
            <td>{{ g.student }}</td>
            <td><span class="dot-pending status-dot"></span>待引擎执行（占位）</td>
            <td><span class="dot-pending status-dot"></span>待引擎执行（占位）</td>
            <td><span class="dot-pending status-dot"></span>待引擎执行（占位）</td>
          </tr>
        </tbody>
      </table>

      <h3>用 CLI 跑（当前阶段推荐，docs/05-D1）</h3>
      <p class="hint">把任务包 JSON 与图片放入 workspace 后，在教师机终端执行：</p>
      <p>
        <code>{{ GRADE_CMD }}</code>
        <button class="btn small clip-btn" style="margin-left:8px" @click="copyGradeCmd">复制命令</button>
      </p>
      <p class="hint">
        批阅产物落在 <code>classes/&lt;班级&gt;/grading/</code>（转录/评阅/报告/汇总表，docs/04 §1）；
        引擎未在线时本页联调按钮保持置灰（D13 条件式置灰）。
      </p>
      <p>
        <button class="btn primary" disabled
          title="阶段4a API 联调（serve 触发）后启用；当前请用上方 CLI 命令">
          ⚙ 通过引擎执行批阅（联调后启用）
        </button>
        <button class="btn" style="margin-left:8px" disabled
          :title="settings.engineOnline ? '联调后启用' : '引擎未在线：运行 assist serve 后重试'">
          ⬇ 导出批阅报告（联调后启用）
        </button>
      </p>
      <p class="hint" v-if="status">{{ status }}</p>
    </div>
  </section>
</template>

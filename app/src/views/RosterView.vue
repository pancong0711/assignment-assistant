<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { STUDENT_TAGS, STUDENT_TAG_LABELS } from '../lib/kb'
import {
  SCORE_FAMILY_PRESETS, isFixedFamily, scoreFamilyDesc, scoreFamilyLabel,
  type ScoreFamily,
} from '../lib/roster'
import { useRosterStore } from '../stores/roster'
import { getKbDirHandle } from '../stores/kb'
import { detectCapabilities, fsWriteHint, pickReadFileFsa } from '../lib/fsAccess'

/** 班级与成绩（M5 成绩管理，docs/05-D18）：名单/成绩导入 + 综合得分 + 自动打 tag + 导出。
 *  成绩源格式预设（docs/05-D19）：固定四类（教务点名册/教务期末/学习通作业统计/
 *  学习通章节测验/雨课堂汇总）按列名 family 语义自动定位分数列，无需用户选列；
 *  custom 保留手动选列。纯前端闭环（不依赖学习通/引擎）。 */

const roster = useRosterStore()
const caps = detectCapabilities()
const status = ref('')
/** 成绩源添加时的格式预设选择（默认 custom = 旧行为） */
const presetFamily = ref<ScoreFamily>('custom')
const presetDesc = computed(() => scoreFamilyDesc(presetFamily.value))
const presetIsFixed = computed(() => isFixedFamily(presetFamily.value))

onMounted(() => {
  if (roster.students.length) roster.touch()
})

function pickXlsx(): Promise<File | null> {
  // LAN（http://IP）/Firefox/Safari 下静默降级为 file input（fsAccess 内部处理）
  return pickReadFileFsa('.xlsx')
}

async function importRoster() {
  const file = await pickXlsx()
  if (!file) return
  try {
    status.value = await roster.loadRosterFile(file)
  } catch (e) {
    status.value = `名单读入失败：${(e as Error).message}`
  }
}

async function addSource() {
  const file = await pickXlsx()
  if (!file) return
  try {
    status.value = await roster.addScoreSource(file, presetFamily.value)
  } catch (e) {
    status.value = `成绩源读入失败：${(e as Error).message}`
  }
}

/** 源内切换格式预设：需要原始 xlsx 重新解析（固定四类按 family 语义重新定位） */
async function reparseSource(idx: number) {
  const file = await pickXlsx()
  if (!file) return
  try {
    const family = roster.sources[idx]?.family ?? 'custom'
    await roster.rescoreWithFamily(idx, file, family)
    status.value = `已按 ${scoreFamilyLabel(family)} 重新解析成绩源「${roster.sources[idx]?.name ?? ''}」。`
  } catch (e) {
    status.value = `成绩源重新解析失败：${(e as Error).message}`
  }
}

function recompute() {
  if (!roster.students.length) {
    status.value = '请先导入/手动建立名单。'
    return
  }
  roster.recompute()
  status.value = `已按比例切分打 tag（共 ${roster.students.length} 人；比例合计 ${(roster.ratioSum * 100).toFixed(1)}%）。`
}

const warnRatio = computed(() => roster.ratioSum > 1.0001)
const warnRatioOff = computed(() => Math.abs(roster.ratioSum - 1) > 0.0001 && roster.ratioSum <= 1.0001)

function setTag(stuIdx: number, ev: Event) {
  const val = (ev.target as HTMLSelectElement).value
  roster.setManualTag(roster.students[stuIdx], val)
}

const batchNames = ref('')
const batchTag = ref('copy')
const batchCreateIfAbsent = ref(true)
const batchMsg = ref('')

function applyBatchTag() {
  const names = batchNames.value.split(/[，,、/；;]+/).map((s2: string) => s2.trim()).filter(Boolean)
  if (!names.length || !batchTag.value) return
  let hit = 0; let added = 0
  for (const nm of names) {
    let idx = roster.students.findIndex((s) => s.name === nm)
    if (idx < 0 && batchCreateIfAbsent.value) {
      roster.addStudent()
      idx = roster.students.length - 1
      roster.students[idx].name = nm
      added++
    }
    if (idx >= 0) { roster.students[idx].tag = batchTag.value; hit++ }
  }
  roster.touch()
  batchMsg.value = `已给 ${hit} 人打上 ${batchTag.value}（新增 ${added} 人）`
}

function setPunish(stuIdx: number, ev: Event) {
  const stu = roster.students[stuIdx]
  if ((ev.target as HTMLInputElement).checked) roster.setManualTag(stu, 'punish')
  else roster.setManualTag(stu, '')
}

// punish 快捷勾选：见下面名单表操作说明（tag 选择即覆盖，punish 在下拉中）

function downloadRosterJsonAndXlsx() {
  roster.downloadRosterXlsx()
  roster.downloadRosterJson()
}

async function downloadTaskPackage() {
  try {
    status.value = await roster.downloadTaskPackage()
  } catch (e) {
    status.value = `任务包导出失败：${(e as Error).message}`
  }
}

/** 与 kb 编辑器共用已连接的 workspace 目录句柄（原地写回 roster/；TODO(阶段4) 换 roster 自己的句柄） */
const dirHandle = computed(() => getKbDirHandle())
const writeHint = fsWriteHint()

async function saveToWorkspace() {
  if (!dirHandle.value) {
    status.value = '未连接 workspace 目录（在「题库编辑器」连接后可原地写回；当前用下载导出即可）。'
    return
  }
  try {
    status.value = await roster.saveToDir(dirHandle.value)
  } catch (e) {
    status.value = `写回失败：${(e as Error).message}`
  }
}

const exportDisabled = computed(() => roster.students.length === 0)

/** 导出前统计（显示在按钮下的提示） */
const summaryText = computed(() => {
  if (!roster.students.length) return '名单为空。'
  const parts: string[] = []
  for (const [tag, cnt] of Object.entries(roster.tagCounts)) {
    parts.push(`${STUDENT_TAG_LABELS[tag] ?? tag}：${cnt}`)
  }
  return `共 ${roster.students.length} 人。${parts.join('；')}`
})

const fixedSourceCount = computed(() => roster.sources.filter((s) => isFixedFamily(s.family)).length)
</script>

<template>
  <section>
    <p class="hint" style="margin-top:0">
      名单列自适应（姓名|name、学号|number、班级|class、tag|tag）；成绩源支持<b>格式预设</b>
      （docs/05-D19：固定四类教务/学习通/雨课堂 + custom）；综合得分 = 多源加权归一均值；
      分组比例自动切分 tag；「特殊标签」栏随时人工覆盖（special_tag_cfg）。
    </p>
    <div class="notice" v-if="!caps.full && caps.browserHint">{{ caps.browserHint }}</div>
    <div class="notice info" v-if="caps.insecure" style="margin-top:6px">
      当前为局域网预览（http://IP，非安全上下文）：导入名单/成绩/题库均可用（文件选择方式）；
      "写回 workspace 目录"不可用——请用下方导出按钮下载文件，教师手动放回 workspace。
      {{ writeHint }}
    </div>
    <div class="card">
      <h2>成绩源（格式预设 + 任意 xlsx，docs/05-D19）</h2>
      <p class="hint">
        先选<b>格式预设</b>再选文件：固定四类无需选列（自动按该格式的列名语义定位）；
        custom（自定义）需手动指定"分数来源列" + 权重（雨课堂签到次数、作业完成度、考试分数等均可）。
        列值在其源内按最大值归一到 0~100；综合得分 = weighted mean。
      </p>
      <p>
        <label class="field">格式预设：
          <select v-model="presetFamily" style="min-width:230px">
            <option v-for="p in SCORE_FAMILY_PRESETS" :key="p.value" :value="p.value">{{ p.label }}</option>
          </select>
        </label>
        <button class="btn primary" style="margin-left:8px" @click="addSource">＋添加成绩源（选 xlsx）</button>
      </p>
      <p class="hint" :class="{ notice: presetIsFixed }" style="margin-top:2px">
        <template v-if="presetIsFixed">这是固定格式（来自{{ presetFamily === 'rainclass' ? '雨课堂' : presetFamily.startsWith('xuexitong') ? '学习通' : '教务' }}导出）——无需选列，自动按列名语义解析。说明：{{ presetDesc }}</template>
        <template v-else>{{ presetDesc }}</template>
      </p>
      <div v-if="!roster.sources.length" class="notice">尚无成绩源：可只导名单不打 tag（tag 列留空），或添加若干成绩源后「重算并打 tag」。</div>
      <p v-for="(s, i) in roster.sources" :key="i" class="hint" style="border-bottom:1px dashed var(--c-border);padding:6px 0">
        <label class="field">源名：<input type="text" v-model="s.name" style="width:150px" @change="roster.touch()" /></label>
        <label class="field" :title="scoreFamilyDesc(s.family)">格式预设：
          <select :value="s.family" @change="roster.setSourceFamily(i, (($event.target as HTMLSelectElement).value) as ScoreFamily, null)" style="max-width:190px">
            <option v-for="p in SCORE_FAMILY_PRESETS" :key="p.value" :value="p.value">{{ p.label }}</option>
          </select>
        </label>
        <template v-if="isFixedFamily(s.family)">
          <span class="hint" style="color:var(--c-ok)">
            固定格式（来自{{ s.family === 'rainclass' ? '雨课堂' : s.family.startsWith('xuexitong') ? '学习通' : '教务' }}导出）·
            {{ s.family === 'roster' ? '仅接表，不计分' : `分数列：${s.scoreColumn}` }}
            <button class="btn small" style="margin-left:4px" title="固定四类按原始表重新按 family 语义解析" @click="reparseSource(i)">重选文件解析</button>
          </span>
        </template>
        <template v-else>
          <label class="field">分数来源列：
            <select v-model="s.scoreColumn" @change="roster.touch()">
              <option v-for="h in Object.keys(s.rows[0] ?? {})" :key="h" :value="h">{{ h }}</option>
            </select>
          </label>
          <label class="field">姓名列：
            <select v-model="s.nameColumn" @change="roster.touch()">
              <option v-for="h in Object.keys(s.rows[0] ?? {})" :key="h" :value="h">{{ h }}</option>
            </select>
          </label>
        </template>
        <label class="field" v-if="s.family !== 'roster'">权重：<input type="number" v-model.number="s.weight" min="0.1" step="0.1" style="width:70px" @change="roster.touch()" /></label>
        <span class="hint">{{ s.rows.length }} 行 · {{ s.fileName }}</span>
        <button class="btn small" @click="roster.removeSource(i)">移除</button>
      </p>
      <p class="hint" v-if="fixedSourceCount">已按固定格式解析的成绩源 ×{{ fixedSourceCount }}（score_sources[].family 将随任务包导出，与 engine CLI <code>--score family:file[:col[:weight]]</code> 同口径）。</p>
    </div>

    <div class="card">
      <h2>分组比例 + 自动切分打 tag</h2>
      <p class="hint">
        2603 默认比例模板可改（punish 不参与比例，仅手动勾选覆盖；docs/05-D17/D18）。
        切分：按综合得分降序 → 自上而下逐比例切档次（int(人数×比例)，余数补到最后一个非 translation 项）；
        translation 沿用 _legacy 的"随机散布"语义。已手动覆盖的学生不参与切分且不被覆盖。
      </p>
      <p>
        <label class="field" v-for="g in roster.ratios" :key="g.tag">
          {{ STUDENT_TAG_LABELS[g.tag] ?? g.tag }}
          <input type="number" :value="Math.round(g.ratio * 100)" min="0" max="100" step="1" style="width:60px"
            @change="(e) => { g.ratio = Number((e.target as HTMLInputElement).value) / 100 || 0; roster.touch(); }" />%
        </label>
        <span class="hint" :class="{ notice: warnRatio }">
          合计 {{ (roster.ratioSum * 100).toFixed(1) }}%
          <template v-if="warnRatio">（&gt;100%：余数为负时按名单实际人数封顶切分）</template>
          <template v-else-if="warnRatioOff">（&lt;100%：剩余学生补到最后一个非 translation 档）</template>
        </span>
      </p>
      <p>
        <button class="btn primary" @click="recompute">重算综合得分并自动切分打 tag</button>
        <button class="btn" style="margin-left:8px" :disabled="exportDisabled" @click="saveToWorkspace" v-if="dirHandle">写回 workspace roster/</button>
      </p>
      <p class="hint" v-if="dirHandle && writeHint">{{ writeHint }}</p>
      <p class="hint">{{ summaryText }}</p>
    </div>

    <div class="card">
      <h2>特殊标签（手动覆盖 special_tag_cfg，批量打 tag）</h2>
      <p>
        <button class="btn primary" @click="importRoster">导入名单 xlsx…</button>
        <button class="btn" style="margin-left:8px" @click="roster.addStudent()">＋手动添加学生</button>
        <button class="btn" style="margin-left:8px" @click="roster.clearAll()" v-if="roster.students.length">清空全部</button>
      </p>
      <p class="hint" v-if="!roster.students.length">尚无学生：先"导入名单 xlsx"（教务导出固定格式，列自动识别）或手动添加，再配分组比例/成绩源即可自动分层；也可直接手动点选本表的 tag（=special_tag_cfg 覆盖）。</p>
      <p>
        <label class="field">批量打 tag：姓名（逗号/顿号分隔多个学生）
          <input type="text" v-model="batchNames" placeholder="学生A, 学生B, 学生C" style="width:min(420px, 60%)" />
        </label>
        <label class="field">tag：
          <select v-model="batchTag">
            <option v-for="t2 in STUDENT_TAGS" :key="t2" :value="t2">{{ STUDENT_TAG_LABELS[t2] }}</option>
          </select>
        </label>
        <label class="field" style="white-space:nowrap"><input type="checkbox" v-model="batchCreateIfAbsent" /> 缺失者自动新增</label>
        <button class="btn" style="margin-left:8px" @click="applyBatchTag" :disabled="!batchNames.trim()">应用到多个学生</button>
        <span class="hint" v-if="batchMsg"> {{ batchMsg }}</span>
      </p>
      <table class="grid">
        <thead>
          <tr><th style="width:120px">姓名</th><th style="width:150px">学号</th><th style="width:150px">班级</th><th style="width:180px">tag</th><th style="width:60px">punish</th><th style="width:40px"></th></tr>
        </thead>
        <tbody>
          <tr v-for="(s, i) in roster.students" :key="i">
            <td><input v-model="s.name" @change="roster.touch()" /></td>
            <td><input v-model="s.number" @change="roster.touch()" /></td>
            <td><input v-model="s.class" @change="roster.touch()" /></td>
            <td>
              <select :value="s.tag" @change="setTag(i, $event)">
                <option value="">（未打）</option>
                <option v-for="t in STUDENT_TAGS" :key="t" :value="t">{{ STUDENT_TAG_LABELS[t] }}</option>
              </select>
            </td>
            <td style="text-align:center"><input type="checkbox" :checked="s.punish" @change="setPunish(i, $event)" title="punish：期末补作业统一题集（不参与比例）" /></td>
            <td><button class="btn small" @click="roster.removeStudent(i)">✕</button></td>
          </tr>
        </tbody>
      </table>
      <p class="hint" style="margin-top:8px">
        手动改 tag = special_tag 覆盖（等价 _legacy special_tag_cfg）；重算自动切分时手动覆盖不被冲掉。
      </p>
    </div>

    <div class="card">
      <h2>产出（名单带 tag → 引擎可直接用）</h2>
      <p class="hint">
        roster.xlsx 列 = name/number/class/tag（恒英文值），<code>uv run assist sheet make &lt;task&gt; --roster roster.xlsx</code> 直接可用；
        roster.json 供 CLI/AI；任务包 zip 内含 roster.xlsx + roster.json + task-package.json
        （group_cfg + special_tag_cfg + punish + score_sources[].family，docs/05-D19）+ 附带切分规则说明 md。
      </p>
      <p>
        <button class="btn primary" :disabled="exportDisabled" @click="downloadRosterJsonAndXlsx">导出 tag 名单（xlsx + JSON）</button>
        <button class="btn" style="margin-left:8px" :disabled="exportDisabled" @click="downloadTaskPackage">下载任务包（zip，附带说明）</button>
      </p>
      <p class="hint" :style="{ marginTop: '4px' }">
        punish 名单（期末补交统一题集，不按层）：
        <template v-if="roster.tagCounts.punish">
          <code>{{ roster.students.filter((s) => s.tag === 'punish').map((s) => s.name).join('、') }}</code>
        </template>
        <template v-else>（未勾选）</template>
      </p>
      <p class="hint" v-if="caps.insecure">LAN 预览提示：导出为浏览器下载，教师手动放回 workspace 的 <code>classes/&lt;班级&gt;/roster/</code> 即可（写回目录能力需本机 localhost/https 打开）。</p>
    </div>
  </section>
</template>

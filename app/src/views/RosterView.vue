<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { STUDENT_TAGS, STUDENT_TAG_LABELS } from '../lib/kb'
import { useRosterStore } from '../stores/roster'
import { getKbDirHandle } from '../stores/kb'
import { detectCapabilities, pickReadFileFsa } from '../lib/fsAccess'

/** 班级与成绩（M5 成绩管理，docs/05-D18）：名单/成绩导入 + 综合得分 + 自动打 tag + 导出。
 *  纯前端闭环（不依赖学习通/引擎）；数据仅存本浏览器 localStorage 与本地导出文件。 */

const roster = useRosterStore()
const caps = detectCapabilities()
const status = ref('')

onMounted(() => {
  if (roster.students.length) roster.touch()
})

function pickXlsx(): Promise<File | null> {
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
    status.value = await roster.addScoreSource(file)
  } catch (e) {
    status.value = `成绩源读入失败：${(e as Error).message}`
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
</script>

<template>
  <section>
    <div class="card">
      <h2>班级与成绩 <small style="font-weight:400;color:var(--c-muted)">M5 成绩管理（阶段3.5，docs/05-D18）· 纯前端闭环，不依赖学习通/引擎</small></h2>
      <p class="hint">
        名单列自适应（姓名|name、学号|number、班级|class、tag|tag，引擎 files/roster.py 同款宽松映射）；
        成绩源任意 xlsx，手动指定"分数来源列"+ 权重（宽松策略：雨课堂签到次数/总次数、作业提交/完成度、
        考试分数 常见列均可）。综合得分 = 源内按最大值归一 × 权重加权；自上而下按比例切分档次打 tag。
      </p>
      <p>
        <button class="btn primary" @click="importRoster">导入名单 xlsx…</button>
        <button class="btn" style="margin-left:8px" @click="roster.addStudent()">＋手动添加学生</button>
        <button class="btn" style="margin-left:8px" @click="roster.clearAll()" v-if="roster.students.length">清空全部（名单+成绩源+比例复位）</button>
      </p>
      <div class="notice" v-if="!caps.full">{{ caps.browserHint }}</div>
      <p class="hint" v-if="status">{{ status }}</p>
    </div>

    <div class="card" v-if="roster.students.length">
      <h2>名单表（可手动增删改）</h2>
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
      <h2>成绩源（列表式添加，任意 xlsx）</h2>
      <p class="hint">
        每个成绩源：起名 + 权重（加权平均用）+ 选一位"分数来源列"（雨课堂签到次数、作业完成度、考试分数等均可）。
        列值在其源内按最大值归一到 0~100；综合得分 = weighted mean。
      </p>
      <p><button class="btn primary" @click="addSource">＋添加成绩源（选 xlsx）</button></p>
      <div v-if="!roster.sources.length" class="notice">尚无成绩源：可只导名单不打 tag（tag 列留空），或添加若干成绩源后「重算并打 tag」。</div>
      <p v-for="(s, i) in roster.sources" :key="i" class="hint" style="border-bottom:1px dashed var(--c-border);padding:6px 0">
        <label class="field">源名：<input type="text" v-model="s.name" style="width:160px" @change="roster.touch()" /></label>
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
        <label class="field">权重：<input type="number" v-model.number="s.weight" min="0.1" step="0.1" style="width:70px" @change="roster.touch()" /></label>
        <span class="hint">{{ s.rows.length }} 行 · {{ s.fileName }}</span>
        <button class="btn small" @click="roster.removeSource(i)">移除</button>
      </p>
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
      <p class="hint">{{ summaryText }}</p>
    </div>

    <div class="card">
      <h2>产出（名单带 tag → 引擎可直接用）</h2>
      <p class="hint">
        roster.xlsx 列 = name/number/class/tag（恒英文值），<code>uv run assist sheet make &lt;task&gt; --roster roster.xlsx</code> 直接可用；
        roster.json 供 CLI/AI；任务包 zip 内含 roster.xlsx + task-package.json（group_cfg + special_tag_cfg + punish）+ 附带切分规则说明 md。
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
    </div>
  </section>
</template>

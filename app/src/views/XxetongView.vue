<script setup lang="ts">
import { ref } from 'vue'

/** 学习通（M-A S1，docs/05-D25 / 13-taskboard R2.2；docs/05-D43-D43-5 修订）：
 *  纯学习通域 = 发公告（作业纸附件）占位 + 批阅任务列表占位 + 登录状态 chip，
 *  阶段6 实装前全部 disabled + 黄色引导。
 *  批阅工作台已**独立为「批阅」选项卡**（D43-5：原迁入件撤出，GradingView 复活，
 *  #/grading hash 直达真 tab）——本页不再混占批阅逻辑。 */

const status = ref('')

/* ---------- 占位卡（阶段6 实装前全部 disabled，D25） ---------- */
const noticeTitle = ref('')
const noticeBody = ref('')
const noticePadFile = ref('')
const noticeCls = ref('')

function pickNoticePadName(e: Event) {
  const input = e.target as HTMLInputElement
  noticePadFile.value = input.files?.[0]?.name ?? ''
  status.value = noticePadFile.value ? '已选择附件（本地占位；发布功能阶段6 实装）。' : ''
}
</script>

<template>
  <section>
    <!-- ================= 占位卡（阶段6 实装，D25） ================= -->
    <div class="card">
      <h2>学习通 <small style="font-weight:400;color:var(--c-muted)">发公告（作业纸附件）· 批阅下载/上传/打分 —— 阶段6 提供实功能，当前占位（D25）</small></h2>
      <div class="notice" style="border-color:#c9a227;color:#7a5c00">
        ⚠ 阶段6 提供实功能，当前占位（D25）：下方所有按钮均置灰，仅展示目标交互形态；
        实装内容 = 登录（浏览器 profile）、公告+附件发布、批阅下载/上传/打分（docs/13 M-F）。
      </div>

      <p>
        <span class="hint" style="margin-right:8px">登录状态：</span>
        <span class="hint" style="display:inline-block; padding:2px 10px; border:1px solid var(--c-border); border-radius:999px; background:var(--c-bg,#f7f7f9)">
          ● 未登录（占位 · 阶段6 浏览器 profile 登录后显示课程/账号）
        </span>
      </p>

      <h3>发公告（主用途 = 发布作业纸 PDF 附件，docs/05-D27）</h3>
      <p>
        <label class="field">标题：<input type="text" v-model="noticeTitle" placeholder="第1章作业（占位）" style="width:280px" /></label>
        <label class="field">发布班级：
          <select v-model="noticeCls" disabled title="占位：阶段6 从学习通拉取课程/班级列表">
            <option value="">（占位：阶段6 从学习通拉取班级）</option>
          </select>
        </label>
      </p>
      <p>
        <label class="field" style="vertical-align:top">正文：
          <textarea v-model="noticeBody" rows="3" placeholder="公告正文占位（阶段6 实装）" style="width:min(480px, 90%); vertical-align:middle" />
        </label>
      </p>
      <p>
        <label class="btn as-label btn-file" for="notice-pad-file" title="占位：选择「输出与交付」卡生成的打印级 PDF（模板）作为附件">附件（作业纸 PDF）选择器…</label>
        <input type="file" accept=".pdf,application/pdf" hidden id="notice-pad-file" @change="pickNoticePadName" />
        <span class="hint" style="margin-left:8px">{{ noticePadFile || '尚未选择（占位）' }}</span>
        <button class="btn primary" style="margin-left:12px" disabled title="阶段6 提供实功能，当前占位（D25）">📢 发布公告（带附件）</button>
      </p>
      <p class="hint" v-if="status">{{ status }}</p>
      <p class="hint">
        建议链路（阶段6）：「作业纸设计」→ 输出与交付「打印级 PDF（模板）」→ 本页发公告带附件（docs/05-D27）；
        整班分层作业纸走「作业纸内容」的 batch 交付包，不经学习通公告。
      </p>

      <h3>批阅任务列表（下载 / 上传 / 打分）</h3>
      <table class="grid" style="max-width:720px; font-size:12px">
        <thead>
          <tr><th>学习通作业</th><th>班级</th><th>提交/已收</th><th>下载作业</th><th>上传评语+打分</th></tr>
        </thead>
        <tbody>
          <tr>
            <td>（占位：阶段6 拉取课程作业列表）</td>
            <td>—</td><td>— / —</td>
            <td><button class="btn small" disabled title="阶段6 提供实功能，当前占位（D25）">⬇ 下载</button></td>
            <td><button class="btn small" disabled title="阶段6 提供实功能，当前占位（D25）">⬆ 上传/打分</button></td>
          </tr>
        </tbody>
      </table>
      <p class="hint">
        占位说明：批阅的"本地闭环"（作业纸 + 学生图片 → 引擎转录/评阅/报告）已独立为
        <a href="#/grading" style="cursor:pointer;text-decoration:underline"><b>「批阅」选项卡</b></a>
        （docs/13 D43-5；#/grading hash 直达）；学习通侧的下载/上传/打分在阶段6 接入（M-F）。
      </p>
    </div>
  </section>
</template>

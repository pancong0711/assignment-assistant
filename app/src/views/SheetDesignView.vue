<script setup lang="ts">
/**
 * SheetDesignView.vue — docs/05-D39 合并视图 + docs/05-D45 段序重排：
 *   ① 版式与头部（工具栏/版式/页眉页脚/头部/水印）→ ② 内容（选题/变体绑定）
 *   → ③ 预览与清单（AMD iframe 实时 + 开关）→ ④ 输出与交付。
 * 一次编辑会话 = 自然工序顺序（用户拍板 2026-09-29）：先选定版式/水印等，
 * 再选题目，然后预览作业纸，最后交付。
 * 子组件复用：两侧/四段共享同一 pinia taskpad store（状态天然同步）。
 * 开关（includeAnswers/showSamples）挂本视图（③/④段共享，默认均不勾，D43-6）。
 * hash 兼容：/layout /content /designer /sheet 全部 redirect 到本视图（App.vue HASH_ALIASES）。
 */
import { onMounted, ref } from 'vue'
import SheetLayoutView from './SheetLayoutView.vue'
import SheetContentView from './SheetContentView.vue'
import SheetPreviewSection from '../components/SheetPreviewSection.vue'
import SheetOutputSection from '../components/SheetOutputSection.vue'
import { useKbStore } from '../stores/kb'
import { useTaskpadStore } from '../stores/taskpad'
import { useSettingsStore } from '../stores/settings'
import { expandPadItems, type SheetHtmlPadInput } from '../lib/sheetHtml'
import type { KbKind } from '../lib/kb'

const kb = useKbStore()
const pad = useTaskpadStore()
const settings = useSettingsStore()

/** D43-6 内容开关（默认不勾；③/④段共享） */
const includeAnswers = ref(false)
const showSamples = ref(false)

const pageStatus = ref('')

/** ④段用回调：当前作业纸 PadInput + 模板学生清单 + 题库 xlsx 导出 */
function currentInput(): SheetHtmlPadInput {
  return {
    pad: JSON.parse(JSON.stringify(pad.current)),
    items: expandPadItems(pad.current, (kind) => kb.book(kind as KbKind)),
  }
}
function templateStudents(): NonNullable<SheetHtmlPadInput['students']> {
  return showSamples.value
    ? [
        { name: '学生A', number: '2026xxxx01', class: 'classA', tag: '' },
        { name: '学生B', number: '2026xxxx02', class: 'classB', tag: '' },
      ]
    : [{ name: '', number: '', class: '', tag: '' }]
}
function getKbBinaries(): Record<string, ArrayBuffer | undefined> {
  return kb.exportBinaries()
}

onMounted(() => { /* 通知中心占位（各段经 notify 上抛 pageStatus） */ })
</script>

<template>
  <section class="design-view">
    <p class="design-anchors">
      <a href="#form">① 版式</a>
      · <a href="#items">② 内容/变体绑定</a>
      · <a href="#preview">③ 预览/清单</a>
      · <a href="#output">④ 输出与交付</a>
      · <b>工艺顺序 = 版式 → 选题 → 预览 → 交付（docs/05-D45）</b>
    </p>
    <p class="hint" style="margin:6px 12px" v-if="pageStatus">{{ pageStatus }}</p>

    <div class="design-block" id="form">
      <SheetLayoutView @notify="(m) => { pageStatus = String(m) }" />
    </div>

    <div class="design-block" id="items">
      <SheetContentView />
    </div>

    <div class="design-block" id="preview-block">
      <SheetPreviewSection
        :include-answers="includeAnswers"
        :show-samples="showSamples"
        @update:include-answers="includeAnswers = $event"
        @update:show-samples="showSamples = $event"
        @notify="(m) => { pageStatus = String(m) }"
      />
    </div>

    <div class="design-block" id="output-block">
      <SheetOutputSection
        :current-input="currentInput"
        :template-students="templateStudents"
        :include-answers="includeAnswers"
        :show-samples="showSamples"
        :get-kb-binaries="getKbBinaries"
        :engine-buttons-disabled="settings.needsSetup"
        @notify="(m) => { pageStatus = String(m) }"
      />
    </div>
  </section>
</template>

<style scoped>
.design-anchors {
  position: sticky;
  top: 0;
  z-index: 3;
  background: var(--c-bg, #fff);
  padding: 6px 12px;
  border-bottom: 1px solid var(--c-border);
  font-size: 14px;
}
.design-item { margin-bottom: 12px; }
.design-block { padding: 10px 0; }
.design-block + .design-block { border-top: 2px dashed #ddd; padding-top: 16px; margin-top: 6px; }
</style>

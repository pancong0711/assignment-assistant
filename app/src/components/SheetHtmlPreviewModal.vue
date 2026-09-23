<script setup lang="ts">
import { ref } from 'vue'
import { downloadBlob } from '../lib/fsAccess'

/** SheetHtmlPreviewModal.vue — VC-1/VC-2「浏览器打印版（HTML overlay）」弹层
 *  （docs/14 §VC-1/2 / §VB-4，05-D30）。
 *
 *  自包含组件：backdrop + 大弹窗 + iframe(srcdoc) —— 用同一份 HTML 模板
 *  （engine/templates/assignment.html.j2 的 TS 同构，app/src/lib/sheetHtml.ts）
 *  在弹窗里预览/打印/下载，**不依赖引擎在线**：
 *  - iframe 内联渲染：版式/分页/水印/KaTeX 与打印输出一致；
 *  - KaTeX CDN 不可达 → renderMathInElement 不存在 → 公式按 $..$ 源码降级显示；
 *  - 「打印」调用 iframe.contentWindow.print()（打印作业纸文档本身）；
 *  - 「下载 HTML」供教师把整班 HTML 存到本地再打印/存 PDF（VB-4）。
 */
const props = defineProps<{ html: string; title: string }>()
defineEmits<{ (e: 'close'): void }>()

const iframeRef = ref<HTMLIFrameElement | null>(null)

function printFrame(): void {
  const w = iframeRef.value?.contentWindow
  if (!w) return
  try {
    w.focus()
    w.print()
  } catch { /* 浏览器拒绝时教师可用「下载 HTML」后再打印 */ }
}

function download(): void {
  downloadBlob(new Blob([props.html], { type: 'text/html;charset=utf-8' }),
    `${props.title.replace(/[\\/:*?"<>|\s]+/g, '-')}.html`)
}
</script>

<template>
  <div class="backdrop" @click.self="$emit('close')">
    <div class="modal sheet-html-modal" role="dialog" aria-modal="true" :aria-label="title">
      <div class="sm-head">
        <h2 style="margin:0; font-size:15px">{{ title }} <small style="font-weight:400;color:var(--c-muted)">浏览器打印版（同一 HTML 模板 · docs/14 §VC-1/2）</small></h2>
        <span style="flex:1"></span>
        <button class="btn small" title="下载自包含 HTML（浏览器打开 → Ctrl/Cmd+P → 另存为 PDF）" @click="download">⬇ 下载 HTML</button>
        <button class="btn small" title="打印对话框：A4 / 边距=无 / 页眉页脚=关 / 背景图形=开" @click="printFrame">🖨 打印</button>
        <button class="btn small" @click="$emit('close')">关闭</button>
      </div>
      <iframe
        ref="iframeRef"
        class="sm-frame"
        :srcdoc="html"
        title="作业纸 HTML 打印预览（每生分页 · A4 · 水印 · KaTeX）"
      ></iframe>
      <p class="hint" style="margin:6px 0 0">
        预览=打印一致（每生分页块 · @page A4 横/竖 · 水印层 · 题图占位框）；
        题图/水印真实图片由引擎 CLI 通道（<code>assist sheet html</code>）base64 内嵌；
        KaTeX 走 CDN —— 离线时公式按 $..$ 源码降级显示。
      </p>
    </div>
  </div>
</template>

<style scoped>
.sheet-html-modal {
  width: 94vw; max-width: 1180px; height: 92vh;
  display: flex; flex-direction: column; gap: 8px; padding: 12px;
}
.sm-head { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.sm-frame {
  flex: 1; width: 100%; border: 1px solid var(--c-border);
  border-radius: 8px; background: #e8ecf3;
}
</style>

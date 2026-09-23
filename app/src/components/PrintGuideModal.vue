<script setup lang="ts">
/** PrintGuideModal.vue — VB-6「教程」弹层（docs/14 §VB-6 / 05-D30）。
 *
 *  自包含组件：backdrop + 内容，不引全局状态。版式页打印卡/帮助卡只需：
 *    import PrintGuideModal from '../components/PrintGuideModal.vue'
 *    const showGuide = ref(false)
 *    <button class="btn" @click="showGuide = true">📖 打印教程</button>
 *    <PrintGuideModal v-if="showGuide" @close="showGuide = false" />
 *  （wiring 由版式页侧完成，本任务不动 SheetLayoutView —— docs/13 §S2c。）
 */
import { PRINT_GUIDE } from '../lib/printGuide'

defineEmits<{ (e: 'close'): void }>()
</script>

<template>
  <div class="backdrop" @click.self="$emit('close')">
    <div class="modal" role="dialog" aria-modal="true" aria-label="浏览器打印教程">
      <h2>📖 浏览器打印教程（HTML 主通道 · docs/14 §VB-6）</h2>
      <p class="hint">作业纸/整班 HTML 打开浏览器打印对话框时，请按下面四项核对；<b>背景图形关闭会导致水印层缺失</b>。</p>

      <h3>打印对话框四项设置</h3>
      <ol style="margin:0; padding-left:22px">
        <li v-for="s in PRINT_GUIDE.settings" :key="s.title" style="margin-bottom:8px">
          <b>{{ s.title }}</b> —— {{ s.detail }}
        </li>
      </ol>

      <h3>浏览器差异</h3>
      <ul style="margin:0; padding-left:22px">
        <li><b>Chrome（首选）：</b>{{ PRINT_GUIDE.browsers.chrome }}</li>
        <li><b>Edge：</b>{{ PRINT_GUIDE.browsers.edge }}</li>
        <li><b>Firefox：</b>{{ PRINT_GUIDE.browsers.firefox }}</li>
        <li><b>Safari：</b>{{ PRINT_GUIDE.browsers.safari }}</li>
      </ul>

      <h3>相关文档</h3>
      <p style="margin:0">
        <template v-for="(r, i) in PRINT_GUIDE.docRefs" :key="r">
          <code style="font-size:12px">{{ r }}</code><span v-if="i < PRINT_GUIDE.docRefs.length - 1"> · </span>
        </template>
      </p>

      <p style="margin-top:16px; text-align:right">
        <button class="btn" @click="$emit('close')">我知道了</button>
      </p>
    </div>
  </div>
</template>

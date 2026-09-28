<script setup lang="ts">
/**
 * SheetDesignView.vue — docs/05-D39：作业纸设计合并视图（版式 + 内容 + 预览导出）。
 * 实现方式：子组件复用（SheetLayoutView + SheetContentView）——两侧本来共享同一 pinia
 * taskpad store（pad.current/pad.savedJsons 全量共享），合并视图下的状态天然同步。
 * 页内锚点锚座（快速跳转）：#form → SheetLayoutView；#items → SheetContentView；
 * 预览锚：#preview → 版式页预览段（内含 HTML overlay/print）。
 * hash 兼容：/layout /content /designer 全部 redirect 到本视图（App.vue HASH_ALIASES）。
 */
import SheetLayoutView from './SheetLayoutView.vue'
import SheetContentView from './SheetContentView.vue'
</script>

<template>
  <section class="design-view">
    <p class="design-anchors">
      <a href="#form">① 版式</a>
      · <a href="#items">② 内容</a>
      · <a href="#preview">③ 预览/导出</a>
      · <b>同一 store，同屏编辑</b>
    </p>

    <div class="design-block" id="form">
      <SheetLayoutView />
    </div>

    <div class="design-block" id="items">
      <SheetContentView />
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

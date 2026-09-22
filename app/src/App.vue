<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useSettingsStore } from './stores/settings'
import SettingsView from './views/SettingsView.vue'
import KbEditorView from './views/KbEditorView.vue'
import SheetLayoutView from './views/SheetLayoutView.vue'
import SheetContentView from './views/SheetContentView.vue'
import RosterView from './views/RosterView.vue'
import XxetongView from './views/XxetongView.vue'
import TransferView from './views/TransferView.vue'

const settings = useSettingsStore()

/** 7 项顶层导航（M-A S1 选项卡重组，docs/05-D25；docs/13 M-A） */
const TABS = [
  { key: 'settings', label: '设置中心', component: SettingsView },
  { key: 'kb', label: '题库编辑器', component: KbEditorView },
  { key: 'layout', label: '作业纸版式', component: SheetLayoutView },
  { key: 'content', label: '作业纸内容', component: SheetContentView },
  { key: 'roster', label: '班级与标签', component: RosterView },
  { key: 'xxetong', label: '学习通', component: XxetongView },
  { key: 'transfer', label: '导入导出', component: TransferView },
] as const

/** 旧 hash 兼容（R2.4）：#/designer → #/layout（版式页）；#/grading → #/xxetong
 *  （批阅工作台并入学习通）；#/sheet → #/content；#/roster 保持不变。 */
const HASH_ALIASES: Record<string, string> = {
  designer: 'layout',
  grading: 'xxetong',
  sheet: 'content',
}

const activeKey = ref<string>('settings')

function readHash(): string {
  const h = window.location.hash.replace(/^#\/?/, '')
  if (h in HASH_ALIASES) {
    // 原地改写地址，保证旧链接/收藏跳到新页签
    const target = HASH_ALIASES[h]!
    window.location.hash = `/${target}`
    return target
  }
  return TABS.some((t) => t.key === h) ? h : 'settings'
}

activeKey.value = readHash()
const onHash = () => { activeKey.value = readHash() }
onMounted(() => window.addEventListener('hashchange', onHash))
onUnmounted(() => window.removeEventListener('hashchange', onHash))

function go(key: string) {
  window.location.hash = `/${key}`
}

const activeTab = computed(() => TABS.find((t) => t.key === activeKey.value) ?? TABS[0])

/** 各视图可触发页面级横幅（如"上传到学习通需引擎 online"，docs/05-D13） */
const bannerText = ref('')
const bannerDismissed = ref(false)
const showBanner = computed(() => bannerText.value !== '' && !bannerDismissed.value)

function showEngineBanner(msg: string) {
  bannerText.value = msg
  bannerDismissed.value = false
}
</script>

<template>
  <header class="app-header">
    <p class="app-title">
      作业助手 <small>大学物理作业纸设计 + AI 批阅（阶段2 PWA 骨架，数据全程本地）</small>
    </p>
    <nav class="tabs" aria-label="主导航">
      <button
        v-for="t in TABS"
        :key="t.key"
        class="tab"
        :class="{ active: t.key === activeKey }"
        @click="go(t.key)"
      >{{ t.label }}</button>
    </nav>
  </header>

  <div v-if="settings.needsSetup && !bannerDismissed" class="app-banner" role="status">
    <b>⚠️</b>
    <span>
      设置向导未完成：上传到学习通、打印级 PDF 等需引擎在线的功能暂时置灰，请去
      <a @click.prevent="go('settings')">设置中心 → 环境体检</a>
      完成向导（静态可用的题库编辑 / 作业纸版式与内容不受影响 —— docs/05-D13）。
    </span>
    <button class="btn small" style="margin-left:auto" @click="bannerDismissed = true">知道了</button>
  </div>
  <div v-else-if="showBanner" class="app-banner" role="status">
    <b>⚠️</b><span>{{ bannerText }}</span>
    <button class="btn small" style="margin-left:auto" @click="bannerDismissed = true">知道了</button>
  </div>

  <main class="app-main">
    <component :is="activeTab.component" @engine-banner="showEngineBanner" />
  </main>

  <footer class="app-footer">
    assignment-assistant app · 纯静态 PWA（Vue3 + Vite + TS + Pinia）· 数据仅存教师本地浏览器 / 本地目录，不入库不上传
  </footer>
</template>

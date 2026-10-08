<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useSettingsStore } from './stores/settings'
import SettingsView from './views/SettingsView.vue'
import KbEditorView from './views/KbEditorView.vue'
import SheetDesignView from './views/SheetDesignView.vue'
import RosterView from './views/RosterView.vue'
import GradingView from './views/GradingView.vue'
import XxetongView from './views/XxetongView.vue'
import TransferView from './views/TransferView.vue'
import HelpView from './views/HelpView.vue'

const settings = useSettingsStore()

/** 8 项顶层导航（docs/05-D43-D43-5：批阅独立选项卡，位置=班级与标签 与 学习通 之间；
 *  S1"批阅并入学习通"的实施选择按用户拍板反转，GradingView 复活）。 */
const TABS = [
  { key: 'settings', label: '设置中心', component: SettingsView },
  { key: 'kb', label: '题库编辑器', component: KbEditorView },
  { key: 'design', label: '作业纸设计', component: SheetDesignView },
  { key: 'roster', label: '班级与标签', component: RosterView },
  { key: 'xxetong', label: '学习通', component: XxetongView },
  { key: 'grading', label: '批阅', component: GradingView },
  { key: 'transfer', label: '导入导出', component: TransferView },
  { key: 'help', label: '使用说明', component: HelpView },
] as const

/** hash 兼容（R2.4 / D43-5 修订）：#/designer #/layout #/sheet → #/design； D64-N2=D63 tab 后置 xxetong→grading（key 不变，无 hash 迁移）；
 *  「批阅」自 D43-5 起为真选项卡（#/grading 直达，不再并入学习通）。 */
const HASH_ALIASES: Record<string, string> = {
  designer: 'design',
  layout: 'design',
  content: 'design',
  sheet: 'design',
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
onMounted(() => {
  onScroll()
  window.addEventListener('scroll', onScroll, { passive: true })
})
// D55/H1：启动时恢复 workspace 目录句柄（IndexedDB 持久化 + 权限恢复）
onMounted(async () => {
  try {
    const { restoreKbDir } = await import('./stores/kb')
    await restoreKbDir()
  } catch { /* noop */ }
})
onUnmounted(() => {
  window.removeEventListener('hashchange', onHash)
  window.removeEventListener('scroll', onScroll)
})

function go(key: string) {
  window.location.hash = `/${key}`
}

const activeTab = computed(() => TABS.find((t) => t.key === activeKey.value) ?? TABS[0])

/** D58：所有选项卡共用的「返回顶部」按钮（滚动超过一屏后出现）。 */
const showBackTop = ref(false)
function onScroll() {
  showBackTop.value = window.scrollY > 360
}
function scrollToTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

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

  <button
    v-if="showBackTop"
    class="back-top"
    type="button"
    aria-label="返回页面顶部"
    title="返回页面顶部"
    @click="scrollToTop"
  >↑ 顶部</button>

  <footer class="app-footer">
    assignment-assistant app · 纯静态 PWA（Vue3 + Vite + TS + Pinia）· 数据仅存教师本地浏览器 / 本地目录，不入库不上传
  </footer>
</template>

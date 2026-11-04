/** D137：挂载真实组件（资料页 / Atopia 面板 / provider 配置区）验证 PWA 对齐。 */
import { createApp, h, ref } from 'vue'
import { createPinia } from 'pinia'
import MaterialsView from './.d137-materials.ts'
import AtopiaPanel from './.d137-atopia.ts'
import { useSettingsStore } from '../src/stores/settings'

const addr = (window as any).__ENGINE_ADDR__ || ''
const which = (window as any).__WHICH__ || 'materials'
const app = createApp({
  setup() {
    const key = ref(0)
    return () => h('div', [
      which === 'materials'
        ? h(MaterialsView, { key: key.value })
        : h(AtopiaPanel, { engineAddr: addr, token: '' }),
    ])
  },
})
const pinia = createPinia()
app.use(pinia)
useSettingsStore(pinia).engineUrl = addr
app.mount('#app')
;(window as any).__ready = true

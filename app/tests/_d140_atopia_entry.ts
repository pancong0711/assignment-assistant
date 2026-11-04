/** D140：挂载真实 AtopiaView（对话 + 工具两个页签），连真实引擎。 */
import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import AtopiaView from './.d140-atopia.ts'
import { useSettingsStore } from '../src/stores/settings'

const addr = (window as any).__ENGINE_ADDR__ || ''
const app = createApp({ render: () => h(AtopiaView) })
const pinia = createPinia()
app.use(pinia)
useSettingsStore(pinia).engineUrl = addr
app.mount('#app')
;(window as any).__ready = true

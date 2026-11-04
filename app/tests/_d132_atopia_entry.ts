/** D132 浏览器回归入口：挂载**真实的** AtopiaPanel。 */
import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import AtopiaPanel from './.d132-atopia.ts'
import { useSettingsStore } from '../src/stores/settings'

const addr = (window as any).__ENGINE_ADDR__ || ''
const app = createApp({ render: () => h(AtopiaPanel, { engineAddr: addr, token: '' }) })
const pinia = createPinia()
app.use(pinia)
useSettingsStore(pinia).engineUrl = addr
app.mount('#app')
;(window as any).__ready = true
